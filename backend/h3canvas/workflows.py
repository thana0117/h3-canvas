"""Load ComfyUI API-format workflows and inject prompt/seed/size/reference images.

A workflow is a file exported from ComfyUI with "Export (API)". The app never
hardcodes node ids: it either reads an optional `<name>.map.json` sidecar or
detects the important inputs by walking the graph from the sampler.

Sidecar format (every value is a [node_id, input_name] pair, or a list of them):
    {
      "prompt":   ["6", "text"],
      "negative": ["7", "text"],
      "seed":     ["3", "seed"],
      "width":    ["58", "width"],
      "height":   ["58", "height"],
      "images":   [["10", "image"], ["11", "image"]]
    }
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("prompt", "negative", "seed", "width", "height", "images")
SEED_KEYS = ("seed", "noise_seed")
TEXT_KEYS = ("text", "prompt", "text_g")
NEGATIVE_KEYS = ("negative_prompt", "negative")
VIDEO_HINTS = ("video", "vhs_", "animated", "webm", "mp4")

Target = tuple[str, str]


class WorkflowError(Exception):
    pass


@dataclass
class Workflow:
    name: str
    path: Path
    graph: dict
    mapping: dict[str, list[Target]] = field(default_factory=dict)
    mapping_source: str = "auto"  # "auto" | "file"
    output: str = "image"  # "image" | "video"

    def summary(self) -> dict:
        return {
            "name": self.name,
            "file": str(self.path),
            "output": self.output,
            "mapping_source": self.mapping_source,
            "mapping": {role: [list(t) for t in targets] for role, targets in self.mapping.items()},
            "missing": [r for r in ("prompt", "seed") if not self.mapping.get(r)],
        }


def list_workflow_files(dirs: list[Path]) -> dict[str, Path]:
    """Later directories override earlier ones (user dir beats built-in)."""
    found: dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if p.name.endswith(".map.json"):
                continue
            found[p.stem] = p
    return found


def load_workflow(name: str, dirs: list[Path]) -> Workflow:
    files = list_workflow_files(dirs)
    if name not in files:
        raise WorkflowError(f"Workflow '{name}' not found")
    path = files[name]
    try:
        graph = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise WorkflowError(f"{path.name} is not valid JSON: {e}") from e
    if not isinstance(graph, dict):
        raise WorkflowError(f"{path.name} is not a workflow object")
    if "nodes" in graph and "links" in graph:
        raise WorkflowError(
            f"{path.name} is in ComfyUI's UI format. Re-export it with Workflow > Export (API)."
        )
    graph = {k: v for k, v in graph.items() if isinstance(v, dict) and "class_type" in v}
    if not graph:
        raise WorkflowError(f"{path.name} has no nodes")

    wf = Workflow(name=name, path=path, graph=graph, output=detect_output(graph))
    map_path = path.with_name(f"{name}.map.json")
    if map_path.exists():
        wf.mapping = _normalize_mapping(json.loads(map_path.read_text()), graph, map_path.name)
        wf.mapping_source = "file"
    else:
        wf.mapping = detect_mapping(graph)
    return wf


def _normalize_mapping(raw: dict, graph: dict, label: str) -> dict[str, list[Target]]:
    out: dict[str, list[Target]] = {}
    for role, value in raw.items():
        if role not in ROLES:
            continue
        pairs = [value] if value and isinstance(value[0], str) else value
        targets = []
        for pair in pairs:
            nid, key = str(pair[0]), str(pair[1])
            if nid not in graph:
                raise WorkflowError(f"{label}: node '{nid}' for '{role}' is not in the workflow")
            targets.append((nid, key))
        out[role] = targets
    return out


def _is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def _sorted_ids(graph: dict) -> list[str]:
    return sorted(graph, key=lambda k: (0, int(k)) if k.isdigit() else (1, k))


def _title(node: dict) -> str:
    return str(node.get("_meta", {}).get("title", "")).lower()


def _find_text_upstream(graph: dict, start: str, max_depth: int = 8) -> Target | None:
    """Breadth-first walk up the links until a node with a string prompt input."""
    seen, frontier = set(), [start]
    for _ in range(max_depth):
        nxt = []
        for nid in frontier:
            if nid in seen or nid not in graph:
                continue
            seen.add(nid)
            inputs = graph[nid].get("inputs", {})
            for key in TEXT_KEYS:
                if isinstance(inputs.get(key), str):
                    return (nid, key)
            nxt.extend(v[0] for v in inputs.values() if _is_link(v))
        frontier = nxt
    return None


def detect_mapping(graph: dict) -> dict[str, list[Target]]:
    ids = _sorted_ids(graph)
    mapping: dict[str, list[Target]] = {}

    # Seed: first node that has an integer seed input (KSampler, RandomNoise, ...).
    for nid in ids:
        inputs = graph[nid].get("inputs", {})
        key = next((k for k in SEED_KEYS if isinstance(inputs.get(k), int)), None)
        if key:
            mapping["seed"] = [(nid, key)]
            break

    # Prompts: follow the conditioning links of whatever node has positive/negative.
    for nid in ids:
        inputs = graph[nid].get("inputs", {})
        if _is_link(inputs.get("positive")) and "prompt" not in mapping:
            hit = _find_text_upstream(graph, inputs["positive"][0])
            if hit:
                mapping["prompt"] = [hit]
                # Encoders like TextEncodeQwenImage21 take both prompts in one node.
                enc = graph[hit[0]].get("inputs", {})
                key = next((k for k in NEGATIVE_KEYS if isinstance(enc.get(k), str)), None)
                if key:
                    mapping["negative"] = [(hit[0], key)]
            if _is_link(inputs.get("negative")):
                neg = _find_text_upstream(graph, inputs["negative"][0])
                if neg and neg != hit and "negative" not in mapping:
                    mapping["negative"] = [neg]

    # Fallback: text nodes by title, then first text node.
    if "prompt" not in mapping:
        text_nodes = [
            (nid, k)
            for nid in ids
            for k in TEXT_KEYS
            if isinstance(graph[nid].get("inputs", {}).get(k), str)
        ]
        negs = [t for t in text_nodes if "negative" in _title(graph[t[0]])]
        pos = [t for t in text_nodes if t not in negs]
        if pos:
            mapping["prompt"] = [pos[0]]
        if negs and "negative" not in mapping:
            mapping["negative"] = [negs[0]]

    # Size: prefer an empty-latent style node (has batch_size), else any width/height pair.
    sized = [
        nid
        for nid in ids
        if isinstance(graph[nid].get("inputs", {}).get("width"), int)
        and isinstance(graph[nid].get("inputs", {}).get("height"), int)
    ]
    sized.sort(key=lambda n: "batch_size" not in graph[n]["inputs"])
    if sized:
        mapping["width"] = [(sized[0], "width")]
        mapping["height"] = [(sized[0], "height")]

    images = [
        (nid, "image")
        for nid in ids
        if graph[nid]["class_type"].startswith("LoadImage")
        and isinstance(graph[nid].get("inputs", {}).get("image"), str)
    ]
    if images:
        mapping["images"] = images
    return mapping


def detect_output(graph: dict) -> str:
    for node in graph.values():
        ct = node["class_type"].lower()
        if ("save" in ct or "combine" in ct or "preview" in ct) and any(h in ct for h in VIDEO_HINTS):
            return "video"
    return "image"


def apply_params(
    wf: Workflow,
    *,
    prompt: str | None = None,
    negative: str | None = None,
    seed: int | None = None,
    width: int | None = None,
    height: int | None = None,
    images: list[str] | None = None,
    keep_pc_clean: bool = True,
) -> dict:
    g = copy.deepcopy(wf.graph)

    def put(role: str, value):
        for nid, key in wf.mapping.get(role, []):
            g[nid]["inputs"][key] = value

    if prompt is not None:
        if not wf.mapping.get("prompt"):
            raise WorkflowError(f"Workflow '{wf.name}' has no prompt input mapped")
        put("prompt", prompt)
    if negative is not None:
        put("negative", negative)
    if seed is not None:
        put("seed", seed)
    if width is not None and height is not None:
        put("width", width)
        put("height", height)
    if images:
        slots = wf.mapping.get("images", [])
        if len(images) > len(slots):
            raise WorkflowError(
                f"Workflow '{wf.name}' has {len(slots)} image input(s), got {len(images)} references"
            )
        for (nid, key), name in zip(slots, images):
            g[nid]["inputs"][key] = name

    for node in g.values():
        if node["class_type"] == "SaveImage":
            if keep_pc_clean:
                # PreviewImage writes to ComfyUI's temp/ folder, which is wiped on restart.
                node["class_type"] = "PreviewImage"
                node["inputs"].pop("filename_prefix", None)
            else:
                node["inputs"]["filename_prefix"] = "h3canvas/img"
    return g
