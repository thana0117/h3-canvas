"""Full loop against the mock ComfyUI: create card -> generate -> files land on the laptop."""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from h3canvas.main import create_app
from h3canvas.mock_comfy import create_mock


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("server did not start")


@pytest.fixture()
def stack(tmp_path):
    comfy_port, app_port = free_port(), free_port()
    mock = create_mock(render_seconds=0.2)
    s1 = serve(mock, comfy_port)
    app = create_app(data_dir=tmp_path, comfy_url=f"http://127.0.0.1:{comfy_port}", poll_interval=0.1,
                     frontend_dist=tmp_path / "no-dist")
    s2 = serve(app, app_port)
    with httpx.Client(base_url=f"http://127.0.0.1:{app_port}", timeout=10) as c:
        yield c, mock, tmp_path
    s2.should_exit = s1.should_exit = True


def wait_for(c, pid, pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        board = c.get(f"/api/projects/{pid}/board").json()
        if pred(board):
            return board
        time.sleep(0.1)
    raise AssertionError(f"timed out: {board}")


def test_generate_downloads_to_laptop(stack):
    c, mock, data = stack
    assert c.get("/api/engine").json()["online"] is True
    p = c.post("/api/projects", json={"name": "Qin Xiao"}).json()
    c.patch(f"/api/projects/{p['id']}", json={"style": "Photoreal Chinese costume drama"})
    card = c.post(f"/api/projects/{p['id']}/cards", json={"kind": "character", "title": "Su Wanning",
                                                           "description": "young noblewoman in pale silk"}).json()
    jobs = c.post(f"/api/cards/{card['id']}/generate", json={"count": 2}).json()
    assert len(jobs) == 2

    board = wait_for(c, p["id"], lambda b: len(b["assets"]) == 2 and not b["jobs"])
    a = board["assets"][0]
    assert a["media"] == "image" and a["thumb"]
    assert "Su Wanning" in a["prompt"] and "Photoreal" in a["prompt"]
    assert (data / "projects" / p["id"] / a["file"]).is_file()
    assert c.get(f"/files/{p['id']}/{a['file']}").status_code == 200
    hero = [x for x in board["cards"] if x["id"] == card["id"]][0]["hero_asset_id"]
    assert hero in {x["id"] for x in board["assets"]}

    # keep_pc_clean: results went to temp/ and history was forgotten on the PC
    st = mock.state.mock
    assert all(kind == "temp" for kind, _ in st["files"])
    assert st["history"] == {}

    # sent graph used the composed negative + PreviewImage
    c.delete(f"/api/assets/{hero}")
    board = c.get(f"/api/projects/{p['id']}/board").json()
    assert len(board["assets"]) == 1
    assert [x for x in board["cards"] if x["id"] == card["id"]][0]["hero_asset_id"] is None


def test_execution_error_is_reported(stack):
    c, _, _ = stack
    p = c.post("/api/projects", json={"name": "x"}).json()
    card = c.post(f"/api/projects/{p['id']}/cards", json={"kind": "prop", "description": "FAIL"}).json()
    c.post(f"/api/cards/{card['id']}/generate", json={"count": 1})
    board = wait_for(c, p["id"], lambda b: b["jobs"] and b["jobs"][0]["status"] == "error")
    assert "mock failure" in board["jobs"][0]["error"]


def test_waits_while_gpu_busy(stack):
    c, mock, _ = stack
    st = mock.state.mock
    st["queue"].append(("someone-else", {}))  # e.g. a Studio video clip
    st["running"] = "studio-clip"  # pretend the worker is busy
    p = c.post("/api/projects", json={"name": "x"}).json()
    card = c.post(f"/api/projects/{p['id']}/cards", json={"kind": "scene", "description": "city gate"}).json()
    c.post(f"/api/cards/{card['id']}/generate", json={"count": 1})
    time.sleep(0.6)
    board = c.get(f"/api/projects/{p['id']}/board").json()
    assert board["jobs"][0]["status"] == "pending"
    assert board["engine"]["busy"] >= 1
    st["queue"].clear()
    st["running"] = None
    wait_for(c, p["id"], lambda b: len(b["assets"]) == 1)


def test_engine_offline_keeps_jobs_pending(tmp_path):
    port = free_port()
    app = create_app(data_dir=tmp_path, comfy_url=f"http://127.0.0.1:{free_port()}", poll_interval=0.1,
                     frontend_dist=tmp_path / "no-dist")
    s = serve(app, port)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
        assert c.get("/api/engine").json()["online"] is False
        p = c.post("/api/projects", json={"name": "x"}).json()
        card = c.post(f"/api/projects/{p['id']}/cards", json={"kind": "prop", "description": "a lantern"}).json()
        c.post(f"/api/cards/{card['id']}/generate", json={"count": 1})
        time.sleep(0.5)
        board = c.get(f"/api/projects/{p['id']}/board").json()
        assert board["jobs"][0]["status"] == "pending"
        assert board["engine"]["online"] is False
    s.should_exit = True
