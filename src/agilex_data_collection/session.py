"""App-owned control loop, bounded recording queue and LeRobot persistence."""

from __future__ import annotations

import importlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from agilex_adapters import Gello, GelloConfig, PiperX, PiperXConfig
from agilex_adapters.devices import JOINTS
from agilex_adapters.transport import BridgeClient

from .config import AppConfig


def aligned_frames(frames: dict, target_ns: int, max_skew_ms: float) -> dict:
    """Reject stale samples; timestamps share the host monotonic clock."""
    for name, frame in frames.items():
        skew = abs(frame["timestamp_ns"] - target_ns) / 1e6
        if skew > max_skew_ms:
            raise RuntimeError(f"{name} timestamp skew {skew:.1f} ms exceeds limit")
        uncertainty = frame.get("clock_uncertainty_ns", 0) / 1e6
        if uncertainty > max_skew_ms:
            raise RuntimeError(f"{name} clock uncertainty exceeds timestamp tolerance")
    times = [frame["timestamp_ns"] for frame in frames.values()]
    if times and (max(times) - min(times)) / 1e6 > max_skew_ms:
        raise RuntimeError("RGB/depth timestamp skew exceeds limit")
    return frames


class Session:
    def __init__(
        self, project: Path, config_path: Path, config: AppConfig, simulate: bool
    ) -> None:
        self.project, self.config_path, self.config = project, config_path, config
        self.simulate = simulate
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._recording = threading.Event()
        self._samples: queue.Queue = queue.Queue(config.queue_size)
        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._epoch = 0
        self._status: dict = {"phase": "idle", "saved_episodes": 0, "error": None}
        self._preview: np.ndarray | None = None
        self._control_error: Exception | None = None

    def status(self) -> dict:
        with self._lock:
            return {**self._status, "simulated": self.simulate}

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self._status.update(fields)

    def preview(self) -> np.ndarray | None:
        with self._lock:
            return self._preview

    def start(self, *, confirmed: bool, task: str) -> None:
        if not task.strip():
            raise ValueError("task must not be empty")
        if not self.simulate and not confirmed:
            raise ValueError("confirm JS zeroing, GELLO alignment and exit zeroing")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("a session is already running")
            self._stop.clear()
            self._recording.clear()
            self._control_error = None
            self._samples = queue.Queue(self.config.queue_size)
            self._commands = queue.Queue()
            self._status = {
                "phase": "preparing",
                "saved_episodes": 0,
                "error": None,
                "task": task,
                "frames": 0,
            }
            self._thread = threading.Thread(target=self._run, daemon=False)
            self._thread.start()

    def command(self, action: str) -> None:
        with self._lock:
            phase = self._status["phase"]
            allowed = {
                "record": {"following"},
                "save": {"recording"},
                "discard": {"recording"},
            }
            if action not in allowed or phase not in allowed[action]:
                raise ValueError(f"cannot {action} while {phase}")
            self._status["phase"] = "pending"
            self._recording.clear()
            self._commands.put(action)

    def stop(self, wait: bool = False) -> None:
        self._recording.clear()
        self._stop.set()
        if wait and self._thread:
            self._thread.join(timeout=60)
            if self._thread.is_alive():
                raise RuntimeError("session cleanup has not finished")

    def _control(self, endpoint: str) -> None:
        robot = leader = client = None
        try:
            robot = PiperX(PiperXConfig(endpoint=endpoint))
            leader = Gello(GelloConfig(endpoint=endpoint))
            client = BridgeClient(endpoint)
            robot.connect()
            leader.connect()
            tick = time.monotonic()
            sample_at = tick
            while not self._stop.is_set():
                requested = leader.get_action()
                command_started = time.monotonic_ns()
                action = robot.send_action(requested)
                command_finished = time.monotonic_ns()
                now = time.monotonic()
                if now >= sample_at:
                    epoch = self._epoch
                    recording = self._recording.is_set()
                    observation = client.call("observation")
                    observation.update(
                        action_timestamp_ns=leader.last_timestamp_ns,
                        command_started_ns=command_started,
                        command_finished_ns=command_finished,
                    )
                    frames = aligned_frames(
                        client.call("frames"),
                        observation["timestamp_ns"],
                        self.config.max_skew_ms,
                    )
                    required = {"color"} if self.config.camera_enabled else set()
                    if required and self.config.depth_enabled:
                        required.add("depth")
                    if set(frames) != required:
                        raise RuntimeError("missing configured RGB-D streams")
                    if "color" in frames:
                        with self._lock:
                            self._preview = frames["color"]["image"]
                    if recording:
                        with self._lock:
                            if self._recording.is_set() and epoch == self._epoch:
                                self._samples.put_nowait(
                                    (epoch, observation, action, frames)
                                )
                    sample_at += 1 / self.config.dataset_fps
                    # Refuse to silently fill a large gap with duplicated samples.
                    if now - sample_at > 2 / self.config.dataset_fps:
                        raise RuntimeError("sampling fell behind the configured FPS")
                tick += 1 / self.config.control_hz
                self._stop.wait(max(0, tick - time.monotonic()))
        except Exception as exc:
            self._control_error = (
                RuntimeError("recording queue is full; disk cannot keep up")
                if isinstance(exc, queue.Full)
                else exc
            )
            self._stop.set()
        finally:
            if leader:
                leader.disconnect()
            if robot:
                robot.disconnect()
            if client:
                client.close()

    def _dataset(self, root: Path, metadata: dict) -> Any:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        features: dict = {
            "observation.state": {
                "dtype": "float32",
                "shape": (7,),
                "names": list(JOINTS),
            },
            "action": {"dtype": "float32", "shape": (7,), "names": list(JOINTS)},
            "observation.host_time": {
                "dtype": "float64",
                "shape": (1,),
                "names": ["monotonic_s"],
            },
        }
        camera = metadata["camera"]
        if camera:
            features["observation.images.front"] = {
                "dtype": "video",
                "shape": (camera["height"], camera["width"], 3),
                "names": ["height", "width", "channels"],
            }
            if self.config.depth_enabled:
                depth = camera["depth"]
                features["observation.images.front_depth"] = {
                    "dtype": "image",
                    "shape": (depth["height"], depth["width"], 1),
                    "names": ["height", "width", "channels"],
                    "info": {"is_depth_map": True, "depth_unit": "m"},
                }
        return LeRobotDataset.create(
            repo_id=f"local/{root.name}",
            root=root,
            fps=self.config.dataset_fps,
            features=features,
            robot_type="agilex_piperx",
            use_videos=True,
            image_writer_threads=2,
        )

    def _run(self) -> None:
        dataset = None
        process = None
        control = None
        temporary = tempfile.TemporaryDirectory(prefix="agilex-collection-")
        endpoint = f"ipc://{temporary.name}/devices.sock"
        failure: Exception | None = None
        audit = None
        try:
            session_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
            output = (self.project / self.config.data_root / session_id).resolve()
            raw = self.project / "data/raw/app" / session_id
            self._update(dataset=str(output), raw=str(raw))
            python = self.project / ".venv/bin/python"
            if not python.is_file():
                raise RuntimeError("run the existing scripts/setup.sh first")
            # Importing torch/Arrow/codecs may hold the GIL for seconds. Finish
            # lazy dataset imports before hardware/control/watchdog are started.
            importlib.import_module("lerobot.datasets.lerobot_dataset")
            command = [
                str(python),
                "-m",
                "agilex_data_collection.worker",
                "--project",
                str(self.project),
                "--config",
                str(self.config_path),
                "--endpoint",
                endpoint,
                "--simulate" if self.simulate else "--motion-confirmed",
            ]
            log_dir = self.project / "data/logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log = log_dir / f"{session_id}.log"
            self._update(log=str(log))
            with log.open("wb") as stream:
                process = subprocess.Popen(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONPATH": str(self.project / "src")},
                )
            self._update(worker_pid=process.pid)
            deadline = time.monotonic() + 120
            metadata = None
            while time.monotonic() < deadline and not self._stop.is_set():
                if process.poll() is not None:
                    raise RuntimeError(f"hardware worker exited; see {log}")
                probe = BridgeClient(endpoint, timeout_s=0.1)
                try:
                    metadata = probe.call("status")
                    break
                except TimeoutError:
                    pass
                finally:
                    probe.close()
            if metadata is None:
                if self._stop.is_set():
                    return
                raise TimeoutError("hardware startup timed out")
            control = threading.Thread(target=self._control, args=(endpoint,))
            control.start()
            raw.mkdir(parents=True, exist_ok=False)
            (raw / "manifest.json").write_text(
                json.dumps(
                    {"version": 1, "devices": metadata, "config": vars(self.config)},
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._update(phase="following")
            frames_written = 0
            episode = 0
            while not self._stop.is_set():
                if process.poll() is not None:
                    raise RuntimeError(f"hardware worker exited; see {log}")
                try:
                    action = self._commands.get_nowait()
                except queue.Empty:
                    action = None
                if action == "record":
                    if dataset is None:
                        self._update(phase="creating_dataset")
                        dataset = self._dataset(output, metadata)
                    self._epoch += 1
                    episode_dir = raw / f"take_{self._epoch:06d}"
                    episode_dir.mkdir(exist_ok=False)
                    audit = (episode_dir / "samples.jsonl").open("x", encoding="utf-8")
                    frames_written = 0
                    self._recording.set()
                    self._update(phase="recording", frames=0)
                elif action in ("save", "discard"):
                    self._update(phase="saving" if action == "save" else "discarding")
                    # Drain only this take after capture has been disabled.
                    while True:
                        try:
                            item = self._samples.get_nowait()
                        except queue.Empty:
                            break
                        if item[0] == self._epoch:
                            self._append(
                                dataset,
                                audit,
                                episode_dir,
                                frames_written,
                                metadata,
                                item,
                            )
                            frames_written += 1
                    if action == "save" and frames_written:
                        dataset.save_episode()
                        episode += 1
                    else:
                        dataset.clear_episode_buffer()
                    (episode_dir / "result.json").write_text(
                        json.dumps(
                            {
                                "result": action,
                                "frames": frames_written,
                                "dataset_episode": episode - 1
                                if action == "save" and frames_written
                                else None,
                            }
                        ),
                        encoding="utf-8",
                    )
                    audit.close()
                    audit = None
                    self._update(phase="following", saved_episodes=episode)
                    continue
                if self._recording.is_set():
                    try:
                        item = self._samples.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if item[0] == self._epoch:
                        self._append(
                            dataset, audit, episode_dir, frames_written, metadata, item
                        )
                        frames_written += 1
                        self._update(frames=frames_written)
                else:
                    self._stop.wait(0.02)
            if self._control_error:
                raise self._control_error
        except Exception as exc:
            failure = exc
        finally:
            self._recording.clear()
            self._stop.set()
            self._update(phase="stopping")
            if control:
                control.join(timeout=5)
                if control.is_alive():
                    failure = failure or RuntimeError("control thread did not stop")
            # Hardware cleanup and zeroing precede potentially slow encoding.
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    failure = failure or RuntimeError("hardware cleanup timed out")
            if process and process.returncode:
                failure = failure or RuntimeError(
                    f"hardware worker failed ({process.returncode}); "
                    "inspect session log"
                )
            if audit:
                try:
                    (episode_dir / "result.json").write_text(
                        json.dumps({"result": "interrupted", "frames": frames_written}),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    failure = failure or exc
                finally:
                    try:
                        audit.close()
                    except Exception as exc:
                        failure = failure or exc
            if dataset is not None:
                try:
                    # Stop/disconnect never silently commits an incomplete take.
                    dataset.clear_episode_buffer()
                    dataset.finalize()
                except Exception as exc:
                    failure = failure or exc
            temporary.cleanup()
            self._update(
                phase="error" if failure else "completed",
                error=str(failure) if failure else None,
            )

    def _append(
        self,
        dataset: Any,
        audit: Any,
        directory: Path,
        index: int,
        metadata: dict,
        item: tuple,
    ) -> None:
        _, observation, action, frames = item
        frame = {
            "observation.state": np.asarray(observation["positions"], np.float32),
            "action": np.asarray([action[key] for key in JOINTS], np.float32),
            "observation.host_time": np.array(
                [observation["timestamp_ns"] / 1e9], np.float64
            ),
            "task": self.status()["task"],
        }
        provenance = {
            "index": index,
            "robot": {
                key: value for key, value in observation.items() if key != "positions"
            },
            "cameras": {},
        }
        for stream, sample in frames.items():
            image = sample["image"]
            # Native input remains immutable, including discarded/failed takes.
            path = directory / f"{stream}_{index:06d}.npy"
            with path.open("xb") as file:
                np.save(file, image, allow_pickle=False)
            provenance["cameras"][stream] = {
                key: value for key, value in sample.items() if key != "image"
            }
            if stream == "depth":
                units = metadata["camera"]["depth"]["depth_units_m"]
                frame["observation.images.front_depth"] = image.astype(np.float32)[
                    ..., None
                ] * np.float32(units)
            else:
                frame["observation.images.front"] = image
        provenance["positions"] = np.asarray(observation["positions"]).tolist()
        provenance["action"] = [action[key] for key in JOINTS]
        audit.write(json.dumps(provenance, allow_nan=False) + "\n")
        audit.flush()
        dataset.add_frame(frame)
