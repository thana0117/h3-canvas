"""Thin async client for the ComfyUI HTTP API running on the engine PC."""

from __future__ import annotations

import uuid

import httpx


class EngineOffline(Exception):
    """The ComfyUI server could not be reached."""


class EngineRejected(Exception):
    """ComfyUI answered but refused the request (bad workflow, missing model, ...)."""


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    err = body.get("error")
    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err or body)
    details = []
    for nid, ne in (body.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            details.append(f"node {nid} ({ne.get('class_type', '?')}): {e.get('message')} {e.get('details', '')}".strip())
    return "; ".join([msg, *details]) if details else msg


class ComfyClient:
    def __init__(self, base_url: str, client_id: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or uuid.uuid4().hex
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def aclose(self):
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = await self._http.request(method, path, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            raise EngineOffline(f"{self.base_url} unreachable ({type(e).__name__})") from e
        if resp.status_code >= 400:
            raise EngineRejected(_error_message(resp))
        return resp

    async def system_stats(self, timeout: float = 3.0) -> dict:
        return (await self._request("GET", "/system_stats", timeout=timeout)).json()

    async def queue_prompt(self, graph: dict) -> str:
        resp = await self._request("POST", "/prompt", json={"prompt": graph, "client_id": self.client_id})
        return resp.json()["prompt_id"]

    async def queue_state(self) -> tuple[set[str], set[str]]:
        body = (await self._request("GET", "/queue")).json()
        running = {item[1] for item in body.get("queue_running", [])}
        pending = {item[1] for item in body.get("queue_pending", [])}
        return running, pending

    async def history(self, prompt_id: str) -> dict | None:
        body = (await self._request("GET", f"/history/{prompt_id}")).json()
        return body.get(prompt_id)

    async def forget(self, prompt_id: str) -> None:
        """Drop a finished prompt from ComfyUI's in-memory history."""
        await self._request("POST", "/history", json={"delete": [prompt_id]})

    async def cancel(self, prompt_id: str, running: bool) -> None:
        if running:
            await self._request("POST", "/interrupt", json={"prompt_id": prompt_id})
        else:
            await self._request("POST", "/queue", json={"delete": [prompt_id]})

    async def download(self, filename: str, subfolder: str, kind: str) -> bytes:
        resp = await self._request(
            "GET", "/view", params={"filename": filename, "subfolder": subfolder, "type": kind}, timeout=300
        )
        return resp.content

    async def upload_image(self, data: bytes, name: str, kind: str = "temp") -> str:
        """Upload a reference image; returns the value to put in a LoadImage node."""
        resp = await self._request(
            "POST",
            "/upload/image",
            files={"image": (name, data, "image/png")},
            data={"type": kind, "overwrite": "true"},
        )
        body = resp.json()
        ref = f"{body['subfolder']}/{body['name']}" if body.get("subfolder") else body["name"]
        return ref if kind == "input" else f"{ref} [{kind}]"


def output_files(history_entry: dict) -> list[dict]:
    """Every file ComfyUI reported for a finished prompt, across all output nodes."""
    files = []
    for node_out in history_entry.get("outputs", {}).values():
        for value in node_out.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and "filename" in item:
                    files.append(
                        {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        }
                    )
    return files


def history_error(history_entry: dict) -> str | None:
    status = history_entry.get("status") or {}
    if status.get("status_str") != "error":
        return None
    for kind, data in status.get("messages", []):
        if kind == "execution_error":
            return f"{data.get('node_type', 'node')}: {data.get('exception_message', 'execution error')}".strip()
    return "ComfyUI reported an execution error"
