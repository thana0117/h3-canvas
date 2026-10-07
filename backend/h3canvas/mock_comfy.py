"""A fake ComfyUI server for tests and for trying the UI without the PC.

    python -m h3canvas.mock_comfy --port 8189

Implements the endpoints H3 Canvas uses. Each queued prompt "renders" for a
couple of seconds and produces a placeholder PNG showing its prompt and seed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import textwrap
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageDraw


def create_mock(render_seconds: float = 2.0) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(worker())
        yield
        task.cancel()

    app = FastAPI(title="Mock ComfyUI", lifespan=lifespan)
    state = {"queue": [], "running": None, "history": {}, "files": {}, "counter": 0, "uploads": {}}
    app.state.mock = state

    def placeholder(prompt_graph: dict) -> bytes:
        text, seed, w, h = "", 0, 768, 768
        for node in prompt_graph.values():
            inp = node.get("inputs", {})
            if isinstance(inp.get("prompt"), str) and not text:
                text = inp["prompt"]
            if isinstance(inp.get("text"), str) and not text:
                text = inp["text"]
            if isinstance(inp.get("seed"), int):
                seed = inp["seed"]
            if isinstance(inp.get("width"), int):
                w, h = inp["width"], inp["height"]
        scale = 512 / max(w, h)
        w, h = int(w * scale), int(h * scale)
        hue = hashlib.md5(str(seed).encode()).digest()
        im = Image.new("RGB", (w, h), (40 + hue[0] // 3, 40 + hue[1] // 3, 60 + hue[2] // 3))
        d = ImageDraw.Draw(im)
        d.rectangle([8, 8, w - 9, h - 9], outline=(255, 255, 255))
        lines = textwrap.wrap(text, 48)[:18] + ["", f"seed {seed}"]
        d.multiline_text((20, 20), "\n".join(lines), fill=(235, 235, 235))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    async def worker():
        while True:
            if state["queue"] and state["running"] is None:
                pid, graph = state["queue"].pop(0)
                state["running"] = pid
                await asyncio.sleep(render_seconds)
                outputs = {}
                for nid, node in graph.items():
                    if node["class_type"] in ("SaveImage", "PreviewImage"):
                        kind = "temp" if node["class_type"] == "PreviewImage" else "output"
                        state["counter"] += 1
                        name = f"mock_{state['counter']:05d}_.png"
                        state["files"][(kind, name)] = placeholder(graph)
                        outputs[nid] = {"images": [{"filename": name, "subfolder": "", "type": kind}]}
                failed = any("FAIL" in str(n.get("inputs", {}).get("prompt", "")) for n in graph.values())
                status = (
                    {"status_str": "error", "completed": False, "messages": [
                        ["execution_error", {"node_type": "KSampler", "exception_message": "mock failure"}]]}
                    if failed
                    else {"status_str": "success", "completed": True, "messages": []}
                )
                state["history"][pid] = {"prompt": [0, pid, graph], "outputs": {} if failed else outputs, "status": status}
                state["running"] = None
            await asyncio.sleep(0.05)

    @app.get("/system_stats")
    def system_stats():
        return {
            "system": {"os": "mock", "comfyui_version": "mock"},
            "devices": [{"name": "Mock GPU", "vram_total": 24 * 2**30, "vram_free": 20 * 2**30}],
        }

    @app.post("/prompt")
    async def prompt(req: Request):
        body = await req.json()
        graph = body.get("prompt") or {}
        for nid, node in graph.items():
            if node.get("class_type") == "LoadImage":
                name = node["inputs"].get("image", "")
                if name.endswith(" [temp]") and name[:-7] not in state["uploads"]:
                    raise HTTPException(400, {"error": {"message": "Prompt outputs failed validation"},
                                              "node_errors": {nid: {"class_type": "LoadImage", "errors": [
                                                  {"message": "Invalid image file", "details": name}]}}})
        pid = str(uuid.uuid4())
        state["queue"].append((pid, graph))
        return {"prompt_id": pid, "number": len(state["queue"])}

    @app.get("/queue")
    def queue():
        running = [[0, state["running"], {}, {}, []]] if state["running"] else []
        return {"queue_running": running, "queue_pending": [[i, pid, {}, {}, []] for i, (pid, _) in enumerate(state["queue"])]}

    @app.post("/queue")
    async def queue_edit(req: Request):
        body = await req.json()
        drop = set(body.get("delete", []))
        state["queue"] = [q for q in state["queue"] if q[0] not in drop]
        return {}

    @app.post("/interrupt")
    def interrupt():
        return {}

    @app.get("/history/{pid}")
    def history(pid: str):
        return {pid: state["history"][pid]} if pid in state["history"] else {}

    @app.post("/history")
    async def history_edit(req: Request):
        body = await req.json()
        for pid in body.get("delete", []):
            state["history"].pop(pid, None)
        return {}

    @app.get("/view")
    def view(filename: str, type: str = "output", subfolder: str = ""):
        data = state["files"].get((type, filename))
        if data is None:
            raise HTTPException(404)
        return Response(data, media_type="image/png")

    @app.post("/upload/image")
    async def upload(image: UploadFile = File(...), type: str = Form("input"), overwrite: str = Form("false")):
        state["uploads"][image.filename] = await image.read()
        return {"name": image.filename, "subfolder": "", "type": type}

    return app


def main():
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8189)
    ap.add_argument("--render-seconds", type=float, default=3.0)
    args = ap.parse_args()
    uvicorn.run(create_mock(args.render_seconds), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
