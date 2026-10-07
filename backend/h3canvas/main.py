"""FastAPI app: REST API for the canvas UI + serves the built frontend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .comfy import ComfyClient, EngineOffline, EngineRejected
from .db import ACTIVE_STATUSES, DB, new_id
from .jobs import JobRunner
from .prompts import ASPECTS, DEFAULT_ASPECT, DEFAULT_NEGATIVE, DEFAULT_TEMPLATES, KINDS, compose, compose_negative
from .store import AssetStore
from .workflows import WorkflowError, list_workflow_files, load_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW = "qwen_image_21_t2i"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectPatch(BaseModel):
    name: str | None = None
    style: str | None = None
    negative: str | None = None
    templates: dict[str, str] | None = None
    image_workflow: str | None = None


class CardIn(BaseModel):
    kind: str
    title: str = ""
    description: str = ""
    x: float = 0
    y: float = 0


class CardPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    aspect: str | None = None
    x: float | None = None
    y: float | None = None
    hero_asset_id: str | None = None


class GenerateIn(BaseModel):
    count: int = Field(default=1, ge=1, le=8)
    seed: int | None = None
    refs: list[str] = []


class SettingsIn(BaseModel):
    comfy_url: str | None = None
    keep_pc_clean: bool | None = None
    wait_for_idle: bool | None = None


def create_app(
    data_dir: Path | None = None,
    comfy_url: str | None = None,
    frontend_dist: Path | None = None,
    poll_interval: float = 2.0,
) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("H3_DATA_DIR") or Path.home() / "H3Canvas").expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "workflows").mkdir(exist_ok=True)
    frontend_dist = frontend_dist or REPO_ROOT / "frontend" / "dist"

    db = DB(data_dir / "h3canvas.db")
    store = AssetStore(data_dir)
    if comfy_url or os.environ.get("H3_COMFY_URL"):
        db.set_setting("comfy_url", comfy_url or os.environ["H3_COMFY_URL"])

    def workflow_dirs() -> list[Path]:
        return [REPO_ROOT / "workflows", data_dir / "workflows"]

    clients: dict[str, ComfyClient] = {}

    def client() -> ComfyClient:
        url = db.get_setting("comfy_url", "http://127.0.0.1:8188")
        if url not in clients:
            clients[url] = ComfyClient(url)
        return clients[url]

    runner = JobRunner(db, store, client, workflow_dirs, interval=poll_interval)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(runner.run_forever())
        yield
        task.cancel()
        for c in clients.values():
            await c.aclose()
        db.close()

    app = FastAPI(title="H3 Canvas", lifespan=lifespan)
    app.state.db, app.state.runner, app.state.data_dir = db, runner, data_dir

    def get_or_404(table: str, row_id: str) -> dict:
        row = db.one(f"SELECT * FROM {table} WHERE id = ?", row_id)
        if not row:
            raise HTTPException(404, f"{table[:-1]} not found")
        return row

    def project_out(p: dict) -> dict:
        return {**p, "templates": {**DEFAULT_TEMPLATES, **json.loads(p["templates"] or "{}")}}

    def job_out(j: dict) -> dict:
        params = json.loads(j["params"])
        return {k: v for k, v in j.items() if k != "params"} | {"seed": params.get("seed")}

    def delete_asset_rows(rows: list[dict]):
        for a in rows:
            store.delete_files(a["project_id"], a["file"], a["thumb"])
            db.run("DELETE FROM assets WHERE id = ?", a["id"])

    # ---------- settings & engine ----------

    @app.get("/api/settings")
    def get_settings():
        return {
            "comfy_url": db.get_setting("comfy_url", "http://127.0.0.1:8188"),
            "keep_pc_clean": db.get_setting("keep_pc_clean", True),
            "wait_for_idle": db.get_setting("wait_for_idle", True),
            "data_dir": str(data_dir),
            "workflow_dir": str(data_dir / "workflows"),
            "aspects": {k: list(v) for k, v in ASPECTS.items()},
            "kinds": list(KINDS),
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        if body.comfy_url is not None:
            url = body.comfy_url.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            db.set_setting("comfy_url", url)
        if body.keep_pc_clean is not None:
            db.set_setting("keep_pc_clean", body.keep_pc_clean)
        if body.wait_for_idle is not None:
            db.set_setting("wait_for_idle", body.wait_for_idle)
        runner.wake()
        return get_settings()

    @app.get("/api/engine")
    async def engine_status():
        c = client()
        try:
            stats = await c.system_stats()
        except (EngineOffline, EngineRejected) as e:
            runner.online = False
            return {"online": False, "url": c.base_url, "error": str(e)}
        runner.online = True
        try:
            running, pending = await c.queue_state()
        except (EngineOffline, EngineRejected):
            running, pending = set(), set()
        devices = [
            {
                "name": d.get("name"),
                "vram_total": d.get("vram_total"),
                "vram_free": d.get("vram_free"),
            }
            for d in stats.get("devices", [])
        ]
        return {
            "online": True,
            "url": c.base_url,
            "comfyui_version": stats.get("system", {}).get("comfyui_version"),
            "queue_running": len(running),
            "queue_pending": len(pending),
            "devices": devices,
        }

    @app.get("/api/workflows")
    def workflows():
        out = []
        for name in list_workflow_files(workflow_dirs()):
            try:
                out.append(load_workflow(name, workflow_dirs()).summary())
            except WorkflowError as e:
                out.append({"name": name, "error": str(e)})
        return out

    # ---------- projects ----------

    @app.get("/api/projects")
    def list_projects():
        return [
            project_out(p)
            | {"card_count": db.one("SELECT COUNT(*) n FROM cards WHERE project_id = ?", p["id"])["n"]}
            for p in db.all("SELECT * FROM projects ORDER BY updated_at DESC")
        ]

    @app.post("/api/projects")
    def create_project(body: ProjectIn):
        now = time.time()
        p = db.insert(
            "projects",
            {
                "id": new_id(),
                "name": body.name.strip(),
                "style": "",
                "negative": DEFAULT_NEGATIVE,
                "templates": "{}",
                "image_workflow": DEFAULT_WORKFLOW,
                "created_at": now,
                "updated_at": now,
            },
        )
        return project_out(p)

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: str, body: ProjectPatch):
        get_or_404("projects", pid)
        fields = body.model_dump(exclude_none=True)
        if "templates" in fields:
            fields["templates"] = json.dumps(
                {k: v for k, v in fields["templates"].items() if v != DEFAULT_TEMPLATES.get(k)}
            )
        db.update("projects", pid, {**fields, "updated_at": time.time()})
        return project_out(get_or_404("projects", pid))

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str):
        get_or_404("projects", pid)
        db.run("DELETE FROM projects WHERE id = ?", pid)
        store.delete_project(pid)
        return {"ok": True}

    @app.get("/api/projects/{pid}/board")
    def board(pid: str):
        p = get_or_404("projects", pid)
        marks = ", ".join("?" for _ in ACTIVE_STATUSES)
        jobs = db.all(
            f"SELECT * FROM jobs WHERE project_id = ? AND (status IN ({marks}) OR status = 'error') "
            "ORDER BY created_at",
            pid,
            *ACTIVE_STATUSES,
        )
        return {
            "project": project_out(p),
            "cards": db.all("SELECT * FROM cards WHERE project_id = ? ORDER BY created_at", pid),
            "assets": db.all("SELECT * FROM assets WHERE project_id = ? ORDER BY created_at DESC", pid),
            "jobs": [job_out(j) for j in jobs],
            "engine": {"online": runner.online, "error": runner.last_error, "busy": runner.busy},
        }

    # ---------- cards ----------

    @app.post("/api/projects/{pid}/cards")
    def create_card(pid: str, body: CardIn):
        get_or_404("projects", pid)
        if body.kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        card = db.insert(
            "cards",
            {
                "id": new_id(),
                "project_id": pid,
                "kind": body.kind,
                "title": body.title,
                "description": body.description,
                "aspect": DEFAULT_ASPECT[body.kind],
                "x": body.x,
                "y": body.y,
                "hero_asset_id": None,
                "created_at": time.time(),
            },
        )
        db.update("projects", pid, {"updated_at": time.time()})
        return card

    @app.patch("/api/cards/{cid}")
    def patch_card(cid: str, body: CardPatch):
        get_or_404("cards", cid)
        fields = body.model_dump(exclude_unset=True)
        if fields.get("aspect") and fields["aspect"] not in ASPECTS:
            raise HTTPException(400, "unknown aspect")
        db.update("cards", cid, fields)
        return get_or_404("cards", cid)

    @app.delete("/api/cards/{cid}")
    def delete_card(cid: str):
        get_or_404("cards", cid)
        delete_asset_rows(db.all("SELECT * FROM assets WHERE card_id = ?", cid))
        db.run("DELETE FROM cards WHERE id = ?", cid)
        return {"ok": True}

    @app.get("/api/cards/{cid}/prompt")
    def preview_prompt(cid: str):
        card = get_or_404("cards", cid)
        p = get_or_404("projects", card["project_id"])
        return {"prompt": compose(card["kind"], card["title"], card["description"], p["style"], json.loads(p["templates"]))}

    @app.post("/api/cards/{cid}/generate")
    def generate(cid: str, body: GenerateIn):
        card = get_or_404("cards", cid)
        if not card["description"].strip() and not card["title"].strip():
            raise HTTPException(400, "Describe the card first")
        p = get_or_404("projects", card["project_id"])
        workflow = p["image_workflow"] or DEFAULT_WORKFLOW
        try:
            load_workflow(workflow, workflow_dirs())
        except WorkflowError as e:
            raise HTTPException(400, str(e))
        prompt = compose(card["kind"], card["title"], card["description"], p["style"], json.loads(p["templates"]))
        width, height = ASPECTS.get(card["aspect"], ASPECTS["1:1"])
        now = time.time()
        jobs = []
        for i in range(body.count):
            seed = body.seed + i if body.seed is not None else random.randint(0, 2**50)
            params = {
                "prompt": prompt,
                "negative": compose_negative(card["kind"], p["negative"]),
                "seed": seed,
                "width": width,
                "height": height,
                "refs": body.refs,
            }
            jobs.append(
                db.insert(
                    "jobs",
                    {
                        "id": new_id(),
                        "project_id": p["id"],
                        "card_id": cid,
                        "workflow": workflow,
                        "params": json.dumps(params),
                        "status": "pending",
                        "prompt_id": None,
                        "error": None,
                        "created_at": now + i * 1e-3,
                        "updated_at": now,
                    },
                )
            )
        runner.wake()
        return [job_out(j) for j in jobs]

    # ---------- jobs & assets ----------

    @app.delete("/api/jobs/{jid}")
    async def cancel_job(jid: str):
        job = get_or_404("jobs", jid)
        if job["status"] in ("queued", "running") and job["prompt_id"]:
            try:
                await client().cancel(job["prompt_id"], running=job["status"] == "running")
            except (EngineOffline, EngineRejected):
                pass
        db.run("DELETE FROM jobs WHERE id = ?", jid)
        return {"ok": True}

    @app.delete("/api/assets/{aid}")
    def delete_asset(aid: str):
        asset = get_or_404("assets", aid)
        db.run("UPDATE cards SET hero_asset_id = NULL WHERE hero_asset_id = ?", aid)
        delete_asset_rows([asset])
        return {"ok": True}

    @app.get("/files/{pid}/{kind}/{name}")
    def files(pid: str, kind: str, name: str):
        if kind not in ("assets", "thumbs"):
            raise HTTPException(404)
        try:
            path = store.path(pid, f"{kind}/{name}")
        except ValueError:
            raise HTTPException(404)
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # ---------- frontend ----------

    if frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="static")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = frontend_dist / path
            if path and f.is_file() and frontend_dist.resolve() in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(frontend_dist / "index.html")

    return app
