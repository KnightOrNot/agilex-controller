"""Python 3.12 web runtime, with an unchanged pinned LeLab installation."""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from pydantic import BaseModel

from .config import AppConfig
from .preview import point_cloud, preview_image
from .session import Session

LOGGER = logging.getLogger("uvicorn.error")


class StartRequest(BaseModel):
    task: str = "PiPER-X GELLO teleoperation"
    motion_confirmed: bool = False


class DeleteDatasetRequest(BaseModel):
    dataset_repo_id: str
    delete_from_hub: bool = False


def create_app(project: Path, config_path: Path, simulate: bool = False) -> FastAPI:
    config = AppConfig.load(config_path)
    root = (project / config.data_root).resolve()
    # LeLab's media browser reads this at call time; collection uses the same root.
    os.environ["HF_LEROBOT_HOME"] = str(root)
    # LeRobot freezes HF_LEROBOT_HOME when imported. The adapters may import it
    # before this app's root is known, so rebind the constant used for local
    # LeRobotDataset(repo_id) lookups (upload/dataset-info) to the same root.
    from lerobot.datasets import dataset_metadata

    dataset_metadata.HF_LEROBOT_HOME = root
    session = Session(project, config_path, config, simulate)
    preview_cache: dict = {}
    preview_lock = threading.Lock()
    preview_clients = 0

    def encode_preview(mode: str):
        snapshot = session.preview_snapshot()
        frames, camera = snapshot["frames"], snapshot["camera"]
        if not camera or "color" not in frames:
            return None
        if mode != "rgb" and "depth" not in frames:
            raise ValueError("当前会话未启用深度预览")
        with preview_lock:
            cache_key = (snapshot["generation"], snapshot["sequence"])
            cached = preview_cache.get(mode)
            if cached and cached[0] == cache_key:
                return cached[1]
            depth = camera.get("depth") or {}
            selection = camera.get("profile_selection", {})
            measured = selection.get("measured_fps") or {}
            color_width, color_height = camera["width"], camera["height"]
            has_depth = "depth" in frames
            depth_width = depth.get("width", color_width)
            depth_height = depth.get("height", color_height)
            # Report the dimensions actually delivered for the selected mode;
            # color and depth profiles may differ.
            width, height = {
                "rgb": (color_width, color_height),
                "depth": (depth_width, depth_height),
                "rgbd": (color_width + depth_width, color_height),
                "cloud": (depth_width, depth_height),
            }[mode if has_depth else "rgb"]
            info = {
                "type": "frame",
                "mode": mode,
                "sequence": snapshot["sequence"],
                "width": width,
                "height": height,
                "color_width": color_width,
                "color_height": color_height,
                "depth_width": depth_width if has_depth else None,
                "depth_height": depth_height if has_depth else None,
                "capture_fps": camera.get("fps"),
                "depth_fps": depth.get("fps") if has_depth else None,
                # Measured transport rates from startup probing, when available.
                "measured_capture_fps": measured,
                "profile_mode": selection.get("requested_mode"),
                "sample_fps": snapshot["sample_fps"],
                "dataset_fps": config.dataset_fps,
                "has_depth": has_depth,
            }
            if mode == "cloud":
                xyz = point_cloud(
                    frames["depth"]["image"],
                    camera["depth"],
                    config.preview_cloud_stride,
                    config.preview_depth_max_m,
                )
                payload = xyz.tobytes()
                info.update(points=len(xyz), depth_max_m=config.preview_depth_max_m)
            else:
                from PIL import Image

                image = preview_image(frames, camera, mode, config.preview_depth_max_m)
                stream = io.BytesIO()
                Image.fromarray(image).save(stream, format="JPEG", quality=80)
                payload = stream.getvalue()
            packet = (info, payload)
            preview_cache[mode] = (cache_key, packet)
            return packet

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        session.stop(wait=True)

    app = FastAPI(title="AgileX Data Collection", lifespan=lifespan)
    app.state.session = session

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        # Browsers from other sites must not be able to arm a local robot.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return Response("cross-origin control denied", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return Response("cross-site control denied", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/dataset-browser", response_class=HTMLResponse)
    def dataset_browser_shell():
        return BROWSER_PAGE

    @app.get("/collection-assets/pointcloud.js")
    def pointcloud_script():
        return FileResponse(Path(__file__).with_name("pointcloud.js"))

    @app.websocket("/api/preview/ws")
    async def preview_stream(socket: WebSocket, mode: str = "rgb"):
        nonlocal preview_clients
        origin = socket.headers.get("origin")
        if origin and urlsplit(origin).netloc != socket.headers.get("host"):
            await socket.close(code=1008)
            return
        # Claim the slot before the first await so concurrent handshakes cannot
        # both pass the limit check.
        if preview_clients >= 2:
            await socket.close(code=1013)
            return
        preview_clients += 1
        last_sequence = None
        period = 1 / config.dataset_fps
        next_delivery = time.monotonic()
        try:
            await socket.accept()
            if mode not in {"rgb", "depth", "rgbd", "cloud"}:
                await socket.send_json({"type": "error", "detail": "未知预览模式"})
                await socket.close(code=1003)
                return
            while session.status()["phase"] in {
                "following",
                "recording",
                "saving",
                "discarding",
                "pending",
                "creating_dataset",
            }:
                await asyncio.sleep(max(0, next_delivery - time.monotonic()))
                packet = await asyncio.to_thread(encode_preview, mode)
                if packet and packet[0]["sequence"] != last_sequence:
                    await socket.send_json(packet[0])
                    await socket.send_bytes(packet[1])
                    last_sequence = packet[0]["sequence"]
                    next_delivery += period
                    # Drop overdue display work instead of bursting old frames.
                    if next_delivery < time.monotonic() - period:
                        next_delivery = time.monotonic()
                else:
                    # A source frame can arrive just after the display deadline.
                    await asyncio.sleep(min(0.005, period / 4))
            await socket.close()
        except WebSocketDisconnect:
            pass
        except (ValueError, KeyError) as exc:
            await socket.send_json({"type": "error", "detail": str(exc)})
            await socket.close(code=1003)
        finally:
            preview_clients -= 1

    @app.get("/api/status")
    def status():
        return session.status()

    @app.get("/robots")
    def robots():
        return {"status": "success", "robots": []}

    @app.get("/datasets")
    def datasets():
        from lelab.datasets import list_local_datasets_with_source

        return list_local_datasets_with_source()

    @app.post("/api/start")
    def start(body: StartRequest):
        try:
            session.start(confirmed=body.motion_confirmed, task=body.task)
        except (RuntimeError, ValueError) as exc:
            LOGGER.warning("启动跟随被拒绝：%s", exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session.status()

    @app.post("/api/control/{action}")
    def control(action: str):
        try:
            if action == "stop":
                session.stop()
            else:
                session.command(action)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session.status()

    @app.get("/api/preview")
    def preview():
        from PIL import Image

        image = session.preview()
        if image is None:
            return Response(status_code=204)
        stream = io.BytesIO()
        Image.fromarray(image).save(stream, format="JPEG", quality=80)
        return Response(
            stream.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    # Reuse official dataset endpoints and its built React browser. Browsing,
    # merge, upload and authentication are exposed; motion, calibration,
    # training, inference, installers and deletion stay unavailable.
    from lelab.server import FRONTEND_DIST
    from lelab.server import app as official_app

    @app.get("/edit-dataset")
    def dataset_browser(request: Request):
        # Upstream defaults to localhost:8000, even when served on another
        # origin. Carry its supported ?api= override without patching the UI.
        origin = str(request.base_url).rstrip("/")
        if request.query_params.get("api") != origin:
            return RedirectResponse(str(request.url.include_query_params(api=origin)))
        return FileResponse(FRONTEND_DIST / "index.html")

    from lelab import episode_media
    from lelab.record import handle_delete_dataset

    @app.post("/delete-dataset")
    def delete_dataset(body: DeleteDatasetRequest):
        """Delete one local dataset; Hub deletion stays out of this app."""
        if body.delete_from_hub:
            return JSONResponse(
                {
                    "success": False,
                    "message": "仅支持删除本地副本；如需删除 Hub 仓库请使用 HF CLI。",
                },
                status_code=400,
            )
        try:
            target = episode_media.resolve_dataset_dir(body.dataset_repo_id).resolve()
        except episode_media.DatasetNotFoundError as exc:
            return JSONResponse(
                {"success": False, "message": str(exc)}, status_code=404
            )
        active = session.status()
        if (
            active.get("dataset")
            and active["phase"] not in {"idle", "completed", "error"}
            and Path(active["dataset"]).resolve() == target
        ):
            return JSONResponse(
                {
                    "success": False,
                    "message": "当前会话正在使用该数据集，请先停止跟随并等待清理完成。",
                },
                status_code=409,
            )
        return handle_delete_dataset(body)

    # Keep direct navigation to unimplemented LeLab pages from rendering the
    # official workflow. Client-side links are disabled by the browser wrapper.
    def unsupported_page():
        return RedirectResponse("/dataset-browser")

    for path in (
        "/recording",
        "/teleoperation",
        "/training",
        "/training/{job_id}",
        "/inference",
        "/calibration",
    ):
        app.add_api_route(
            path, unsupported_page, methods=["GET"], include_in_schema=False
        )

    allowed_get = {
        "/dataset-episodes",
        "/dataset-episode",
        "/dataset-motion",
        "/dataset-thumbnails",
        "/dataset-frame",
        "/dataset-video",
        "/hf-auth-status",
        "/health",
    }
    # Merge/upload handlers are official LeLab implementations. Dataset info
    # is read-only but uses POST; HF login supports the upload flow.
    allowed_post = {
        "/dataset-info",
        "/datasets/merge",
        "/upload-dataset",
        "/hf-auth/login",
    }
    for route in official_app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        if (path in allowed_get and methods == {"GET"}) or (
            path in allowed_post and methods == {"POST"}
        ):
            app.router.routes.append(route)
        elif getattr(route, "name", None) == "frontend":
            app.router.routes.append(route)
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    path = (args.config or project / "config/default.toml").resolve()
    uvicorn.run(
        create_app(project, path, args.simulate), host="127.0.0.1", port=args.port
    )


BROWSER_PAGE = """<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>LeLab 数据集</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;font:14px system-ui}
header{height:48px;display:flex;align-items:center;gap:24px;padding:0 20px;
border-bottom:1px solid #dfe5ef;background:white}a{color:#2459bb;text-decoration:none}
header .note{color:#718096;font-size:12px}
iframe{display:block;width:100%;height:calc(100dvh - 48px);border:0}
</style><header><a href="/">← 返回数据采集</a><strong>LeLab 数据集浏览</strong>
<span class="note">仅开放浏览、合并、上传与删除；其余功能已禁用</span></header>
<iframe id="lelab-frame" src="/edit-dataset" title="LeLab 官方数据集浏览器"></iframe>
<script>
(() => {
  const frame = document.getElementById('lelab-frame');
  const unsupportedRoutes = new Set([
    '/', '/recording', '/teleoperation', '/training', '/inference', '/calibration']);
  const unsupportedAria = new Set(['Start the guided tour']);
  const unsupportedText = text =>
    text === 'Back' || text === 'Back to Home' || text === 'Skip Upload' ||
    text === 'Record more' || text.startsWith('Create new dataset') ||
    text.startsWith('Take the tour');
  const disable = element => {
    if (element.dataset.lelabDisabled) return;
    element.dataset.lelabDisabled = '1';
    if (element.tagName === 'BUTTON') element.disabled = true;
    element.setAttribute('aria-disabled', 'true');
    element.title = '当前数采应用未启用此功能';
    element.style.pointerEvents = 'none';
    element.style.opacity = '.45';
    element.style.cursor = 'not-allowed';
  };
  const apply = () => {
    const doc = frame.contentDocument;
    if (!doc || !doc.body) return;
    for (const link of doc.querySelectorAll('a[href]')) {
      try {
        const url = new URL(link.getAttribute('href'), doc.baseURI);
        if (url.origin === location.origin && unsupportedRoutes.has(url.pathname))
          disable(link);
      } catch (error) {}
    }
    for (const button of doc.querySelectorAll('button')) {
      const text = (button.innerText || button.textContent || '').trim();
      if (unsupportedText(text) ||
          unsupportedAria.has(button.getAttribute('aria-label'))) disable(button);
    }
    // Local deletion only: never offer/allow Hub repository deletion here.
    for (const box of doc.querySelectorAll('#delete-from-hub')) disable(box);
    // Upload/merge internals are not useful while operating the collection.
    const textOf = node => (node.innerText || node.textContent || '').trim();
    const hide = node => {
      if (!node || node.dataset.lelabHidden) return;
      node.dataset.lelabHidden = '1';
      node.style.display = 'none';
    };
    for (const label of doc.querySelectorAll('span')) {
      if (textOf(label) === 'Repository ID:') hide(label.parentElement);
    }
    for (const heading of doc.querySelectorAll('h3')) {
      if (textOf(heading) !== 'About HuggingFace Hub Upload') continue;
      let card = heading.parentElement;
      while (card && card !== doc.body &&
             !(card.className || '').includes('rounded-lg')) {
        card = card.parentElement;
      }
      hide(card && card !== doc.body ? card : heading.parentElement);
    }
    for (const note of doc.querySelectorAll('p')) {
      if (textOf(note).startsWith('Saved locally as ')) hide(note);
    }
  };
  const rewriteHistory = win => {
    if (!win || win.__lelabHistoryPatched) return;
    win.__lelabHistoryPatched = true;
    for (const method of ['pushState', 'replaceState']) {
      const original = win.history[method];
      win.history[method] = function (state, title, url) {
        try {
          const target = new URL(url || win.location.href, win.location.href);
          if (unsupportedRoutes.has(target.pathname)) url = '/edit-dataset';
        } catch (error) {}
        return original.call(this, state, title, url);
      };
    }
  };
  // The official picker keeps its dataset list in React state. A successful
  // delete leaves the removed name visible until a full reload refetches it.
  const reloadAfterDelete = win => {
    if (!win || win.__lelabDeletePatched) return;
    win.__lelabDeletePatched = true;
    const original = win.fetch;
    win.fetch = async function (...args) {
      const response = await original.apply(this, args);
      try {
        const url = (typeof args[0] === 'string' ? args[0] : args[0]?.url) || '';
        if (url.includes('/delete-dataset') && response.ok) {
          const data = await response.clone().json();
          if (data && data.success && !win.__lelabDeleteReloading) {
            win.__lelabDeleteReloading = true;
            setTimeout(() => {win.location.href = '/edit-dataset';}, 500);
          }
        }
      } catch (error) {}
      return response;
    };
  };
  let observer = null;
  const attach = () => {
    apply();
    rewriteHistory(frame.contentWindow);
    reloadAfterDelete(frame.contentWindow);
    if (observer) observer.disconnect();
    const doc = frame.contentDocument;
    if (doc && doc.body) {
      observer = new MutationObserver(apply);
      observer.observe(doc.body, {childList: true, subtree: true});
    }
  };
  frame.addEventListener('load', attach);
})();
</script></html>"""


PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>AgileX Data Collection</title>
<style>
*{box-sizing:border-box}body{font:14px system-ui;margin:24px auto;padding:0 20px;
max-width:1100px;background:#f4f6fa;color:#223049}header{display:flex;
justify-content:space-between;align-items:center;margin-bottom:18px;gap:16px}
h1{font-size:21px;letter-spacing:-.5px;margin:0 0 4px}h2{font-size:14px;margin:0 0 12px}
p{margin:8px 0}header p,.muted{color:#718096;font-size:12px}
.badge{display:inline-block;margin-left:10px;border-radius:12px;background:#e9effa;
padding:3px 9px;color:#52709c;font-size:11px;font-weight:400;letter-spacing:0}
.card{background:white;border:1px solid #e1e7f0;border-radius:12px;padding:18px;
margin-bottom:14px;box-shadow:0 3px 14px #22304905}
button,input,select{font:inherit;border-radius:7px;border:1px solid #d6deea}
button,a.nav{padding:8px 14px;text-decoration:none;cursor:pointer;
background:#fff;color:#344661}button:hover,a.nav:hover{background:#edf3ff}
button:disabled{opacity:.4;cursor:default}#start{background:#2563eb;color:#fff;
border-color:#2563eb}#stop{color:#bc3a43;border-color:#eed5d7;margin-left:auto}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 8px}
input[type=text]{display:block;width:100%;max-width:600px;padding:9px 11px;
margin-top:6px}input[type=checkbox]{accent-color:#2563eb;margin:0 7px 0 0}
.confirm{display:flex;align-items:center;margin-top:12px;color:#59677c;font-size:12px}
#start-help{font-size:12px;color:#718096;min-height:18px}#error{color:#b83243}
.preview-wrap{background:#edf1f6;border-radius:8px;min-height:160px;
display:flex;align-items:center;justify-content:center;overflow:hidden}
#preview{display:block;max-width:100%;max-height:440px;object-fit:contain}
#cloud{width:100%;height:440px;display:none;touch-action:none}
.preview-head{display:flex;justify-content:space-between;align-items:center;
gap:12px;margin-bottom:12px}.preview-head h2{margin:0}
select{padding:6px 10px;background:#fff}#preview-stats{margin-top:10px;
font:12px ui-monospace,monospace;color:#718096;min-height:18px}
a{color:#2563eb}
@media(max-width:640px){body{padding:0 12px;margin:16px auto}.card{padding:14px}
header{align-items:flex-start}#stop{margin-left:0}}
</style><header><div><h1>AgileX Data Collection
<span id="phase-label" class="badge">连接中</span></h1>
<p>GELLO → PiPER-X · RGB-D 采集</p></div>
<a class="nav" href="/dataset-browser">LeLab 数据集 ↗</a></header>
<section class="card"><label>任务描述 <input id="task" type="text"
value="PiPER-X GELLO teleoperation"></label>
<label class="confirm"><input id="confirmed" type="checkbox">
我已确认启动、对齐和退出回零的运动范围安全</label>
<div class="actions">
<button id="start" disabled aria-describedby="start-help">启动跟随</button>
<button id="record" disabled>开始采样</button>
<button id="save" disabled>保存本段</button>
<button id="discard" disabled>丢弃本段</button>
<button id="stop" disabled>停止跟随</button>
</div><p id="start-help" aria-live="polite">正在读取会话状态…</p>
<p id="error" role="alert"></p></section>
<section class="card"><div class="preview-head"><h2>实时预览</h2>
<select id="preview-mode" aria-label="预览模式">
<option value="rgb">RGB</option><option value="depth">深度</option>
<option value="rgbd">RGB + 深度</option><option value="cloud">3D 点云</option>
</select></div><div class="preview-wrap">
<img id="preview" alt="启动跟随后显示相机预览">
<canvas id="cloud" aria-label="三维点云：拖动旋转，滚轮缩放"></canvas></div>
<p id="preview-stats">等待相机 · 点云支持拖动旋转 / 滚轮缩放 / 双击复位</p></section>
<script src="/collection-assets/pointcloud.js"></script><script>
const $=id=>document.getElementById(id);
let currentStatus=null,startPending=false;
let previewSocket=null,previewMode=null,previewInfo=null,cloudViewer=null;
let decoding=false,previewFrames=0,previewTime=0,previewFps=0,previewGeneration=0;
const activePhases=['following','recording','saving','discarding',
'pending','creating_dataset'];
function previewStats(){
if(!previewInfo)return;
const s=previewInfo;
const depth=s.mode==='depth'||s.mode==='cloud';
const size=s.mode==='rgbd'
?`RGB ${s.color_width}×${s.color_height} + 深度 ${s.depth_width}×${s.depth_height}`
:`${s.width}×${s.height}`;
const measured=s.measured_capture_fps||{};
const shown=value=>value==null?'—':Number(value).toFixed(1);
const colorFps=shown(measured.color??s.capture_fps);
const depthFps=shown(measured.depth??s.depth_fps);
const rate=s.mode==='rgbd'
?`捕获 RGB ${colorFps} / 深度 ${depthFps} FPS`
:`捕获 ${depth?depthFps:colorFps} FPS`;
$('preview-stats').textContent=`预览 ${previewFps.toFixed(1)} FPS · `+
`采样 ${s.sample_fps.toFixed(1)} / ${s.dataset_fps} FPS · `+
`${size} · ${rate} · ${s.profile_mode||'manual'}`+
(s.mode==='cloud'?` · ${s.points} 点（深度坐标系，按距离着色）`:'');
}
function maintainPreview(){
const active=currentStatus&&activePhases.includes(currentStatus.phase);
const mode=$('preview-mode').value||'rgb';
if(!active){if(previewSocket)previewSocket.close();previewSocket=null;
previewMode=null;previewGeneration++;
$('preview-stats').textContent=currentStatus?.phase==='preparing'?
'正在初始化相机与机械臂…':'预览未运行';return;}
if(previewSocket&&previewMode===mode)return;
if(previewSocket)previewSocket.close();
const generation=++previewGeneration;
previewMode=mode;previewInfo=null;previewFrames=0;previewFps=0;
previewTime=performance.now();decoding=false;
$('preview').style.display=mode==='cloud'?'none':'block';
$('cloud').style.display=mode==='cloud'?'block':'none';
const scheme=location.protocol==='https:'?'wss':'ws';
const ws=new WebSocket(`${scheme}://${location.host}/api/preview/ws?mode=${mode}`);
previewSocket=ws;ws.binaryType='arraybuffer';
ws.onmessage=async event=>{
if(generation!==previewGeneration)return;
if(typeof event.data==='string'){
const data=JSON.parse(event.data);
if(data.type==='error'){$('preview-stats').textContent=data.detail;return;}
previewInfo=data;return;}
if(decoding||!previewInfo)return;
decoding=true;
try{
if(mode==='cloud'){
if(!cloudViewer)cloudViewer=new PointCloudViewer($('cloud'));
cloudViewer.setPoints(new Float32Array(event.data),previewInfo.depth_max_m);
}else{
const blob=new Blob([event.data],{type:'image/jpeg'});
const url=URL.createObjectURL(blob);
await new Promise(resolve=>{
const image=$('preview');
image.onload=image.onerror=()=>{URL.revokeObjectURL(url);resolve();};image.src=url;});
}
if(generation!==previewGeneration)return;
// Start timing after the first decode; WebGL/shader setup can block for
// seconds and would otherwise depress the first reported FPS.
if(!previewFrames)previewTime=performance.now();
previewFrames++;
const elapsed=(performance.now()-previewTime)/1000;
if(elapsed>=1){previewFps=previewFrames/elapsed;previewFrames=0;
previewTime=performance.now();}previewStats();
}catch(error){$('preview-stats').textContent=error.message;}
finally{if(generation===previewGeneration)decoding=false;}
};
ws.onclose=()=>{if(generation===previewGeneration)previewSocket=null;};
ws.onerror=()=>{if(generation===previewGeneration)
$('preview-stats').textContent='预览连接中断，请检查会话状态。';};
}
$('preview-mode').onchange=maintainPreview;
function controls(){
const ready=currentStatus&&['idle','completed','error'].includes(currentStatus.phase);
const phases={idle:'待启动',preparing:'准备中',following:'跟随中',recording:'采样中',
saving:'保存中',discarding:'丢弃中',stopping:'停止中',completed:'已结束',
error:'故障',pending:'处理中',creating_dataset:'创建数据集'};
if(currentStatus)$('phase-label').textContent=
`${phases[currentStatus.phase]||currentStatus.phase} · `+
`已保存 ${currentStatus.saved_episodes||0} 段`;
const taskReady=$('task').value.trim().length>0;
const confirmed=currentStatus&&(currentStatus.simulated||$('confirmed').checked);
$('start').disabled=startPending||!ready||!taskReady||!confirmed;
$('record').disabled=!currentStatus||currentStatus.phase!=='following';
$('save').disabled=$('discard').disabled=
!currentStatus||currentStatus.phase!=='recording';
$('stop').disabled=!currentStatus||['idle','completed','error'].includes(currentStatus.phase);
$('start-help').textContent=!currentStatus?'正在读取会话状态…':
startPending?'正在提交启动请求，请勿重复点击。':
!ready?(currentStatus.phase==='following'?'跟随中，可开始采样。':
currentStatus.phase==='recording'?'采样中，完成后保存本段。':'正在处理，请稍候。'):
!taskReady?'请填写任务描述。':
!confirmed?'请先勾选上方的运动范围安全确认，再启动跟随。':
currentStatus.simulated?'模拟模式：不会访问真实硬件。':'已确认，可以启动跟随。';
}
$('confirmed').onchange=controls;
$('task').oninput=controls;
async function post(path,body={}){try{const r=await fetch(path,{method:'POST',
headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const data=await r.json();if(!r.ok)throw Error(data.detail||'请求失败');
$('error').textContent='';await update();}catch(e){$('error').textContent=e.message}}
$('start').onclick=async()=>{
controls();if($('start').disabled)return;
startPending=true;controls();
try{await post('/api/start',{task:$('task').value,
motion_confirmed:$('confirmed').checked});}
finally{startPending=false;controls();}};
for(const action of ['record','save','discard','stop'])
$(action).onclick=()=>post('/api/control/'+action);
async function update(){try{const r=await fetch('/api/status');
if(!r.ok)throw Error('状态读取失败');
const s=await r.json();
if(s.error)$('error').textContent=s.error;
else if(currentStatus?.error)$('error').textContent='';
currentStatus=s;controls();
maintainPreview();
}catch(e){$('error').textContent=e.message}}
update();setInterval(update,1000);
</script></html>"""


if __name__ == "__main__":
    main()
