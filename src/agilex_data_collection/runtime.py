"""Python 3.12 web runtime, with an unchanged pinned LeLab installation."""

from __future__ import annotations

import argparse
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from .config import AppConfig
from .session import Session


class StartRequest(BaseModel):
    task: str = "PiPER-X GELLO teleoperation"
    motion_confirmed: bool = False


def create_app(project: Path, config_path: Path, simulate: bool = False) -> FastAPI:
    config = AppConfig.load(config_path)
    # LeLab's media browser reads this at call time; collection uses the same root.
    os.environ["HF_LEROBOT_HOME"] = str((project / config.data_root).resolve())
    session = Session(project, config_path, config, simulate)

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

    # Reuse official read-only dataset endpoints and its built React browser.
    # Do not expose SO101 motion/calibration, installers, or deletion endpoints.
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

    allowed = {
        "/dataset-episodes",
        "/dataset-episode",
        "/dataset-motion",
        "/dataset-thumbnails",
        "/dataset-frame",
        "/dataset-video",
        "/hf-auth-status",
        "/health",
    }
    for route in official_app.routes:
        if getattr(route, "path", None) in allowed:
            if getattr(route, "methods", set()) == {"GET"}:
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
    path = (args.config or project / "config/data_collection.toml").resolve()
    uvicorn.run(
        create_app(project, path, args.simulate), host="127.0.0.1", port=args.port
    )


PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>AgileX Data Collection</title>
<style>
body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1000px;
background:#101925;color:#eef3fa}h1{font-size:28px}button,input{font:inherit;
padding:12px;border-radius:8px;border:1px solid #7591ad;margin:6px}
button{cursor:pointer;background:#d5e9ff;color:#102439}button:disabled{opacity:.4;
cursor:default}input[type=text]{width:70%}#preview{max-width:100%;max-height:440px}
#stop{background:#ffb6b6}pre{white-space:pre-wrap;background:#1b2c40;padding:20px}
a{color:#b7d7ff}.warning{color:#ffd99e}label{display:block;margin:16px 0}
</style><h1>AgileX Data Collection</h1>
<p>GELLO → PiPER-X · LeRobot RGB-D · LeLab 数据浏览</p>
<p class="warning">真机启动和停止都会执行 JS 回零；启动时还会对齐 GELLO。
请先确认工作空间、供电、急停与 CAN。关闭网页不会自动停止设备，请点击停止。</p>
<label>任务描述 <input id="task" type="text"
value="PiPER-X GELLO teleoperation"></label>
<label><input id="confirmed" type="checkbox">
我已确认启动、对齐和退出回零的运动范围安全</label>
<button id="start">启动跟随</button><button id="record">开始采样</button>
<button id="save">保存本段</button><button id="discard">丢弃本段</button>
<button id="stop">停止跟随</button>
<p>停止会丢弃尚未保存的本段；已保存的 episode 保留。
原始 RGB / Z16 与时间戳始终保留。</p>
<img id="preview" alt="启动跟随后显示 RGB 预览"><pre id="status">连接中…</pre>
<p><a href="/edit-dataset">打开 LeLab 数据集浏览器</a> ·
<a href="/datasets?scope=local">本地数据集列表</a></p><p id="error" role="alert"></p>
<script>
const $=id=>document.getElementById(id);
async function post(path,body={}){try{const r=await fetch(path,{method:'POST',
headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const data=await r.json();if(!r.ok)throw Error(data.detail||'请求失败');
$('error').textContent='';await update();}catch(e){$('error').textContent=e.message}}
$('start').onclick=()=>post('/api/start',{task:$('task').value,
motion_confirmed:$('confirmed').checked});
for(const action of ['record','save','discard','stop'])
$(action).onclick=()=>post('/api/control/'+action);
async function update(){try{const r=await fetch('/api/status');
if(!r.ok)throw Error('状态读取失败');
const s=await r.json();$('status').textContent=JSON.stringify(s,null,2);
$('start').disabled=!['idle','completed','error'].includes(s.phase);
$('record').disabled=s.phase!=='following';
$('save').disabled=$('discard').disabled=s.phase!=='recording';
$('stop').disabled=['idle','completed','error'].includes(s.phase);
if(['following','recording','saving','creating_dataset'].includes(s.phase))
$('preview').src='/api/preview?t='+Date.now();
}catch(e){$('error').textContent=e.message}}
update();setInterval(update,1000);
</script></html>"""


if __name__ == "__main__":
    main()
