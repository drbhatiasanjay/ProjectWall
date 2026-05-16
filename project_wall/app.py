from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts import EmailAlerter
from .config import Project, WallConfig, load_config
from .health import probe_many
from .manager import ProcessManager
from .monitor import HealthMonitor
from .version import version_payload

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent
DEFAULT_CONFIG = ROOT_DIR / "projects.yml"
DEFAULT_LOG_DIR = ROOT_DIR / "logs"


def _project_public(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "color": p.color,
        "icon": p.icon,
        "stack": p.stack,
        "port": p.port,
        "live_url": p.live_url,
        "obsidian": p.obsidian,
        "health_url": p.rendered_health(),
        "local_url": f"http://127.0.0.1:{p.port}" if p.port else None,
    }


def _state_public(state) -> dict:
    return {
        "pid": state.pid,
        "started_at": state.started_at,
        "last_activity_at": state.last_activity_at,
        "exit_code": state.exit_code,
        "error": state.error,
        "running": state.pid is not None,
        "crash_tail": state.crash_tail,
    }


def _make_wall_logger(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "wall.log"

    def _log(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    return _log


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg_path = Path(os.environ.get("WALL_CONFIG", DEFAULT_CONFIG))
    log_dir = Path(os.environ.get("WALL_LOGS", DEFAULT_LOG_DIR))
    cfg = load_config(cfg_path)
    mgr = ProcessManager(cfg, log_dir)
    wall_log = _make_wall_logger(log_dir)
    alerter = EmailAlerter(log=wall_log)
    monitor = HealthMonitor(mgr, cfg, alerter, log=wall_log)
    monitor.start()
    app.state.cfg = cfg
    app.state.mgr = mgr
    app.state.alerter = alerter
    app.state.monitor = monitor
    app.state.log_dir = log_dir
    try:
        yield
    finally:
        monitor.shutdown()
        mgr.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="ProjectWall", lifespan=lifespan)

    templates = Jinja2Templates(directory=str(PKG_DIR / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(PKG_DIR / "static")),
        name="static",
    )

    @app.get("/")
    async def index(request: Request):
        cfg: WallConfig = request.app.state.cfg
        return templates.TemplateResponse(
            request,
            "index.html",
            {"projects": [_project_public(p) for p in cfg.projects]},
        )

    @app.get("/api/projects")
    async def list_projects(request: Request):
        cfg: WallConfig = request.app.state.cfg
        mgr: ProcessManager = request.app.state.mgr
        states = mgr.all_states()
        payload = []
        for p in cfg.projects:
            entry = _project_public(p)
            entry["state"] = _state_public(states[p.id])
            payload.append(entry)
        return {"projects": payload}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str, request: Request):
        cfg: WallConfig = request.app.state.cfg
        mgr: ProcessManager = request.app.state.mgr
        p = cfg.get(project_id)
        if p is None:
            raise HTTPException(404, f"Unknown project: {project_id}")
        entry = _project_public(p)
        entry["state"] = _state_public(mgr.state(project_id))
        return entry

    @app.post("/api/projects/{project_id}/start")
    async def start_project(project_id: str, request: Request):
        mgr: ProcessManager = request.app.state.mgr
        try:
            state = mgr.start(project_id)
        except KeyError:
            raise HTTPException(404, f"Unknown project: {project_id}")
        return JSONResponse(_state_public(state))

    @app.post("/api/projects/{project_id}/stop")
    async def stop_project(project_id: str, request: Request):
        mgr: ProcessManager = request.app.state.mgr
        try:
            state = mgr.stop(project_id)
        except KeyError:
            raise HTTPException(404, f"Unknown project: {project_id}")
        return JSONResponse(_state_public(state))

    @app.get("/api/version")
    async def version(request: Request):
        log_dir = request.app.state.log_dir
        return version_payload(log_dir)

    @app.get("/api/monitor")
    async def monitor_events(request: Request):
        mon: HealthMonitor = request.app.state.monitor
        return {"events": mon.events()}

    @app.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(
            PKG_DIR / "static" / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    async def service_worker():
        # Served from root so its scope is the whole app, not just /static.
        return FileResponse(
            PKG_DIR / "static" / "sw.js",
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    @app.get("/api/projects/{project_id}/logs")
    async def project_logs(project_id: str, request: Request, n: int = 100):
        mgr: ProcessManager = request.app.state.mgr
        try:
            return {"lines": mgr.tail(project_id, n=n)}
        except KeyError:
            raise HTTPException(404, f"Unknown project: {project_id}")

    @app.websocket("/api/projects/{project_id}/logs/ws")
    async def log_stream_ws(websocket: WebSocket, project_id: str):
        mgr: ProcessManager = websocket.app.state.mgr
        if project_id not in mgr._logs:
            await websocket.close(code=4004)
            return
        await websocket.accept()
        log = mgr._logs[project_id]
        loop = asyncio.get_running_loop()
        sid, q = log.subscribe(loop)
        try:
            for line in log.tail(100):
                await websocket.send_text(line)
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    # Keepalive ping — JS filters empty strings
                    try:
                        await websocket.send_text("")
                    except Exception:
                        break
                    continue
                try:
                    await websocket.send_text(line)
                except Exception:
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            log.unsubscribe(sid)

    @app.get("/api/health")
    async def health(request: Request):
        cfg: WallConfig = request.app.state.cfg
        urls = {
            p.id: p.rendered_health()
            for p in cfg.projects
            if p.rendered_health()
        }
        if not urls:
            return {"results": {}}
        results = await probe_many(urls, timeout_s=float(cfg.defaults.health_timeout_s))
        return {
            "results": {
                k: {
                    "ok": v.ok,
                    "status": v.status,
                    "latency_ms": v.latency_ms,
                    "error": v.error,
                }
                for k, v in results.items()
            }
        }

    return app


app = create_app()
