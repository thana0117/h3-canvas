"""Asset files on the laptop: <data>/projects/<project_id>/{assets,thumbs}/."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

from PIL import Image

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".gif", ".mkv"}
THUMB_SIZE = 512


def media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return "file"


class AssetStore:
    def __init__(self, root: Path):
        self.root = root

    def project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def path(self, project_id: str, rel: str) -> Path:
        base = self.project_dir(project_id).resolve()
        p = (base / rel).resolve()
        if base not in p.parents:
            raise ValueError("path escapes project folder")
        return p

    def save(self, project_id: str, asset_id: str, source_name: str, data: bytes) -> dict:
        ext = Path(source_name).suffix.lower() or ".bin"
        rel = f"assets/{asset_id}{ext}"
        dest = self.path(project_id, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        info = {"file": rel, "thumb": None, "width": None, "height": None, "media": media_type(source_name)}
        if info["media"] == "image":
            with Image.open(io.BytesIO(data)) as im:
                info["width"], info["height"] = im.size
                thumb = im.convert("RGB")
                thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
                thumb_rel = f"thumbs/{asset_id}.webp"
                thumb_path = self.path(project_id, thumb_rel)
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                thumb.save(thumb_path, "WEBP", quality=82)
                info["thumb"] = thumb_rel
        return info

    def delete_files(self, project_id: str, *rels: str | None) -> None:
        for rel in rels:
            if rel:
                self.path(project_id, rel).unlink(missing_ok=True)

    def delete_project(self, project_id: str) -> None:
        shutil.rmtree(self.project_dir(project_id), ignore_errors=True)
