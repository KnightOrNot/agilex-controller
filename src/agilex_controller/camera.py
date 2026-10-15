"""Application-owned camera lifecycle and asynchronous, lossless raw RGB-D files."""

from __future__ import annotations

import json
import multiprocessing
import os
import queue
import shutil
import signal
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from .configuration import CameraConfig
from .recording import RecordingError


def _preview_main(images: Any, stop: Any) -> None:
    from camera_realsense.preview import Preview

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    preview = Preview()
    try:
        while not stop.is_set() and preview.pump():
            try:
                image = images.get(timeout=0.02)
            except queue.Empty:
                continue
            preview.show([image])
    finally:
        preview.destroy()


def _save_png(image: np.ndarray, stream: BinaryIO, compress_level: int) -> None:
    """Encode RGB8/native Z16 without Pillow's per-row adaptive filter search."""
    if image.dtype == np.uint8 and image.ndim == 3 and image.shape[2] == 3:
        bits, color, pixels = 8, 2, image
    elif image.dtype == np.uint16 and image.ndim == 2:
        # PNG stores 16-bit samples in network byte order, including 0 and 65535.
        bits, color, pixels = 16, 0, image.astype(">u2", copy=False)
    else:
        raise ValueError("raw PNG requires RGB uint8 or depth uint16")
    height, width = image.shape[:2]
    pixels = np.ascontiguousarray(pixels).view(np.uint8).reshape(height, -1)
    rows = np.empty((height, pixels.shape[1] + 1), dtype=np.uint8)
    rows[:, 0] = 0  # PNG filter None: avoid CPU-heavy adaptive filtering.
    rows[:, 1:] = pixels

    def chunk(kind: bytes, data: bytes) -> None:
        stream.write(struct.pack(">I", len(data)))
        stream.write(kind)
        stream.write(data)
        stream.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(kind))))

    stream.write(b"\x89PNG\r\n\x1a\n")
    chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bits, color, 0, 0, 0))
    chunk(b"IDAT", zlib.compress(rows.tobytes(), level=compress_level))
    chunk(b"IEND", b"")


class ImageEpisodeWriter:
    def __init__(
        self, path: Path, queue_size: int, *, png_compress_level: int = 0
    ) -> None:
        self.path = path
        self._png_compress_level = png_compress_level
        self._written = 0
        self._write_seconds = 0.0
        (path / "frames").mkdir(parents=True, exist_ok=False)
        self._queue: queue.Queue[Any] = queue.Queue(queue_size)
        self._done = threading.Event()
        self._error: Exception | None = None
        self._previous: int | None = None
        self._thread = threading.Thread(target=self._write, daemon=False)
        self._thread.start()

    def check(self) -> None:
        if self._error is not None:
            raise RecordingError(
                f"camera image writer failed: {self._error}"
            ) from self._error

    def add(self, frame: Any) -> None:
        self.check()
        if self._previous == frame.timestamp_ns:
            return
        if self._previous is not None and frame.timestamp_ns < self._previous:
            raise RecordingError("camera timestamps moved backwards")
        try:
            self._queue.put_nowait(frame)
        except queue.Full as exc:
            rate = self._written / self._write_seconds if self._write_seconds else 0
            self._error = RecordingError(
                "camera image queue is full; episode is incomplete; "
                f"path={self.path}, capacity={self._queue.maxsize}, "
                f"written={self._written}, writer_fps={rate:.1f}; "
                "image encoding/storage cannot keep up with capture"
            )
            raise self._error from exc
        self._previous = frame.timestamp_ns

    def finish(self) -> Path:
        while not self._done.is_set():
            try:
                self._queue.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self._done.wait()
        self._thread.join()
        self.check()
        return self.path

    def _write(self) -> None:
        try:
            with (self.path / "frames.jsonl").open("x", encoding="utf-8") as index:
                number = 0
                while True:
                    frame = self._queue.get()
                    if frame is None:
                        break
                    started = time.monotonic()
                    relative = f"frames/{number:06d}.png"
                    with (self.path / relative).open("xb") as stream:
                        _save_png(frame.image, stream, self._png_compress_level)
                        stream.flush()
                        os.fsync(stream.fileno())
                    metadata = {
                        key: value
                        for key, value in vars(frame).items()
                        if key != "image"
                    }
                    metadata.update(file=relative, frame_index=number)
                    index.write(json.dumps(metadata, allow_nan=False) + "\n")
                    number += 1
                    self._written = number
                    self._write_seconds += time.monotonic() - started
                index.flush()
                os.fsync(index.fileno())
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()


class CameraSession:
    """Capture independently of robot commands; save every frame while recording."""

    def __init__(self, config: CameraConfig, *, source_factory: Any = None) -> None:
        from camera_realsense.stream import ColorStream

        self.config = config
        self._source: Any = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._latest: Any = None
        self._error: Exception | None = None
        self._active: dict[str, ImageEpisodeWriter] = {}
        self._finished: dict[str, ImageEpisodeWriter] = {}
        self._frames: dict[str, Any] = {}
        self._preview: Any = None
        self._preview_queue: Any = None
        self._preview_stop: Any = None
        self._closed = False
        try:
            self._source = (source_factory or ColorStream)(
                serial=config.serial,
                width=config.width,
                height=config.height,
                fps=config.fps,
                warmup_frames=config.warmup_frames,
                depth_enabled=config.depth_enabled,
                depth_width=config.depth_width,
                depth_height=config.depth_height,
                depth_fps=config.depth_fps,
            )
            self._source.start()
            self._reader = threading.Thread(
                target=self._capture, daemon=True, name="camera-capture"
            )
            self._reader.start()
            if not self._ready.wait(config.startup_timeout_s):
                status = getattr(self._source, "startup_status", "unavailable")
                raise RuntimeError(
                    "camera did not produce all aligned RGB/depth frames "
                    f"before startup timeout; {status}"
                )
            self.check_health()
            if config.preview:
                context = multiprocessing.get_context("spawn")
                self._preview_queue = context.Queue(maxsize=1)
                self._preview_stop = context.Event()
                self._preview = context.Process(
                    target=_preview_main,
                    args=(self._preview_queue, self._preview_stop),
                    daemon=True,
                )
                self._preview.start()
        except BaseException as exc:
            try:
                self.close()
            except Exception as cleanup_error:
                exc.add_note(f"camera cleanup also failed: {cleanup_error}")
            raise

    @property
    def manifest(self) -> dict[str, Any]:
        metadata = dict(self._source.metadata)
        depth = metadata.pop("depth", None)
        result = {
            self.config.name: {
                **metadata,
                "kind": "color",
                "max_skew_ms": self.config.max_skew_ms,
                "storage": "rgb8_png",
                "index": "cameras/{name}/{episode}/frames.jsonl",
            }
        }
        if self.config.depth_enabled:
            if depth is None:
                raise RuntimeError("camera source did not declare depth metadata")
            result[self.config.name + "_depth"] = {
                **metadata,
                **depth,
                "kind": "depth",
                "storage": "z16_png",
                "max_skew_ms": self.config.max_skew_ms,
                "index": "cameras/{name}/{episode}/frames.jsonl",
            }
        return result

    def _capture(self) -> None:
        try:
            while not self._stop.is_set():
                frame = self._source.read(timeout_s=0.2)
                if frame is None:
                    if self._ready.is_set():
                        self.check_health()
                    continue
                expected = (
                    {"color", "depth"} if self.config.depth_enabled else {"color"}
                )
                if frame.stream not in expected:
                    raise RuntimeError(f"unexpected camera stream: {frame.stream}")
                with self._lock:
                    self._frames[frame.stream] = frame
                    if frame.stream == "color":
                        self._latest = frame
                    if frame.stream in self._active:
                        self._active[frame.stream].add(frame)
                    if "color" in self._frames and (
                        not self.config.depth_enabled or "depth" in self._frames
                    ):
                        self._ready.set()
                if frame.stream == "color" and self._preview_queue is not None:
                    try:
                        self._preview_queue.put_nowait(frame.image)
                    except queue.Full:
                        pass  # Preview may skip; the recording writer never does.
        except Exception as exc:
            self._error = exc
            self._ready.set()

    def check_health(self) -> None:
        if self._error is not None:
            raise RuntimeError(f"camera capture failed: {self._error}") from self._error
        with self._lock:
            for stream in (
                ["color", "depth"] if self.config.depth_enabled else ["color"]
            ):
                frame = self._frames.get(stream)
                if frame is None:
                    raise RuntimeError(f"camera has no aligned {stream} frame")
                age = (time.monotonic_ns() - frame.received_time_ns) / 1e9
                if age > self.config.frame_timeout_s:
                    raise RuntimeError(
                        f"camera {stream} stopped producing frames ({age:.3f}s)"
                    )
            for writer in self._active.values():
                writer.check()
        if self._preview is not None and self._preview.exitcode not in (None, 0):
            raise RuntimeError(
                "camera preview failed; disable --camera-preview on headless hosts"
            )

    def start_episode(self, joint_partial: Path) -> None:
        with self._lock:
            self.check_health()
            if self._active:
                raise RecordingError("camera episode is already recording")
            episode = joint_partial.name.removesuffix(".jsonl.partial")
            self._finished = {}
            for stream, frame in self._frames.items():
                name = self.config.name + ("_depth" if stream == "depth" else "")
                path = (
                    joint_partial.parent.parent
                    / "cameras"
                    / name
                    / f"{episode}.partial"
                )
                writer = ImageEpisodeWriter(
                    path,
                    self.config.queue_size,
                    png_compress_level=self.config.png_compress_level,
                )
                self._active[stream] = writer
                writer.add(frame)  # Keep pre-roll for the first target timestamp.

    def finish_episode(self) -> list[Path]:
        with self._lock:
            if self._active:
                self._finished, self._active = self._active, {}
            writers = list(self._finished.values())
        paths, errors = [], []
        for writer in writers:
            try:
                paths.append(writer.finish())
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RecordingError(f"camera episode flush failed: {errors}") from errors[
                0
            ]
        if self._error is not None:
            raise RecordingError(
                f"camera episode capture failed: {self._error}"
            ) from self._error
        return paths

    def commit_episode(self) -> None:
        for partial in self.finish_episode():
            if partial.exists():
                final = partial.with_suffix("")
                if final.exists():
                    raise RecordingError(f"camera output already exists: {final}")
                os.replace(partial, final)

    def discard_episode(self) -> None:
        for partial in self.finish_episode():
            shutil.rmtree(partial, ignore_errors=False)
        self._finished = {}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        try:
            if self._reader is not None and self._reader.ident is not None:
                self._reader.join(timeout=2)
            if self._source is not None:
                self._source.close()
            if self._reader is not None and self._reader.is_alive():
                self._reader.join(timeout=1)
                if self._reader.is_alive():
                    raise RuntimeError("camera capture thread did not stop")
        finally:
            if self._preview is not None:
                self._preview_stop.set()
                if self._preview.pid is not None:
                    self._preview.join(timeout=2)
                    if self._preview.is_alive():
                        self._preview.terminate()
                        self._preview.join(timeout=2)
                self._preview_queue.cancel_join_thread()
                self._preview_queue.close()
            self.finish_episode()
