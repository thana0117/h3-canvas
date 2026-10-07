"""Background loop: send pending jobs to ComfyUI, watch them, pull results to the laptop.

Everything is driven from the database, so it survives the laptop sleeping or
losing its connection: jobs already queued on the PC keep running there, and the
next tick after reconnecting collects whatever finished in the meantime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable

from .comfy import ComfyClient, EngineOffline, EngineRejected, history_error, output_files
from .db import DB, new_id
from .store import AssetStore
from .workflows import WorkflowError, apply_params, load_workflow

log = logging.getLogger("h3canvas.jobs")

# A prompt missing from both queue and history this many ticks in a row is lost
# (usually ComfyUI was restarted while it was queued).
LOST_AFTER_MISSES = 5


class JobRunner:
    def __init__(
        self,
        db: DB,
        store: AssetStore,
        client: Callable[[], ComfyClient],
        workflow_dirs: Callable[[], list[Path]],
        interval: float = 2.0,
    ):
        self.db = db
        self.store = store
        self.client = client
        self.workflow_dirs = workflow_dirs
        self.interval = interval
        self.online: bool | None = None
        self.last_error: str | None = None
        # Number of prompts in ComfyUI's queue that this app did not send (e.g. Studio video clips).
        self.busy: int = 0
        self._misses: dict[str, int] = {}
        self._wake = asyncio.Event()

    def wake(self):
        self._wake.set()

    async def run_forever(self):
        while True:
            try:
                await self.tick()
            except Exception:  # keep the loop alive no matter what
                log.exception("job tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def tick(self):
        jobs = self.db.active_jobs()
        if not jobs:
            return
        client = self.client()
        try:
            running, pending = await client.queue_state()
        except EngineOffline as e:
            self._mark_offline(str(e))
            return
        self.online, self.last_error = True, None
        ours = {j["prompt_id"] for j in jobs if j["prompt_id"]}
        self.busy = len((running | pending) - ours)
        # Don't interleave stills with someone else's queue (model swaps thrash VRAM).
        hold = self.busy > 0 and self.db.get_setting("wait_for_idle", True)

        for job in jobs:
            try:
                if job["status"] == "pending":
                    if not hold:
                        await self._submit(client, job)
                else:
                    await self._check(client, job, running, pending)
            except EngineOffline as e:
                self._mark_offline(str(e))
                return

    def _mark_offline(self, err: str):
        if self.online is not False:
            log.warning("engine offline: %s", err)
        self.online, self.last_error = False, err

    async def _submit(self, client: ComfyClient, job: dict):
        params = json.loads(job["params"])
        try:
            wf = load_workflow(job["workflow"], self.workflow_dirs())
            refs = [await self._upload_ref(client, job["project_id"], aid) for aid in params.get("refs", [])]
            graph = apply_params(
                wf,
                prompt=params.get("prompt"),
                negative=params.get("negative"),
                seed=params.get("seed"),
                width=params.get("width"),
                height=params.get("height"),
                images=refs,
                keep_pc_clean=self.db.get_setting("keep_pc_clean", True),
            )
            prompt_id = await client.queue_prompt(graph)
        except (WorkflowError, EngineRejected, ValueError) as e:
            self.db.set_job(job["id"], status="error", error=str(e))
            return
        self.db.set_job(job["id"], status="queued", prompt_id=prompt_id)

    async def _upload_ref(self, client: ComfyClient, project_id: str, asset_id: str) -> str:
        asset = self.db.one("SELECT * FROM assets WHERE id = ?", asset_id)
        if not asset:
            raise ValueError(f"reference asset {asset_id} no longer exists")
        data = self.store.path(project_id, asset["file"]).read_bytes()
        return await client.upload_image(data, f"h3_{asset_id}{Path(asset['file']).suffix}")

    async def _check(self, client: ComfyClient, job: dict, running: set[str], pending: set[str]):
        pid = job["prompt_id"]
        if pid in running or pid in pending:
            self._misses.pop(pid, None)
            status = "running" if pid in running else "queued"
            if job["status"] != status:
                self.db.set_job(job["id"], status=status)
            return

        entry = await client.history(pid)
        if entry is None:
            self._misses[pid] = self._misses.get(pid, 0) + 1
            if self._misses[pid] >= LOST_AFTER_MISSES:
                self._misses.pop(pid, None)
                self.db.set_job(job["id"], status="error", error="Job vanished from ComfyUI (was it restarted?)")
            return
        self._misses.pop(pid, None)

        if not (entry.get("status") or {}).get("completed", True) and not history_error(entry):
            return  # still being written
        err = history_error(entry)
        if err:
            self.db.set_job(job["id"], status="error", error=err)
        else:
            await self._collect(client, job, entry)
        try:
            await client.forget(pid)
        except EngineRejected:
            pass

    async def _collect(self, client: ComfyClient, job: dict, entry: dict):
        files = output_files(entry)
        if not files:
            self.db.set_job(job["id"], status="error", error="Workflow finished but produced no output files")
            return
        params = json.loads(job["params"])
        card = self.db.one("SELECT * FROM cards WHERE id = ?", job["card_id"]) if job["card_id"] else None
        first_id = None
        for f in files:
            data = await client.download(f["filename"], f["subfolder"], f["type"])
            asset_id = new_id()
            info = self.store.save(job["project_id"], asset_id, f["filename"], data)
            self.db.insert(
                "assets",
                {
                    "id": asset_id,
                    "project_id": job["project_id"],
                    "card_id": card["id"] if card else None,
                    "job_id": job["id"],
                    "media": info["media"],
                    "file": info["file"],
                    "thumb": info["thumb"],
                    "width": info["width"],
                    "height": info["height"],
                    "prompt": params.get("prompt", ""),
                    "seed": params.get("seed"),
                    "workflow": job["workflow"],
                    "created_at": time.time(),
                },
            )
            first_id = first_id or asset_id
        if card and not card["hero_asset_id"]:
            self.db.update("cards", card["id"], {"hero_asset_id": first_id})
        self.db.set_job(job["id"], status="done", error=None)
