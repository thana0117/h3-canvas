import json
from pathlib import Path

import pytest

from h3canvas.workflows import WorkflowError, apply_params, detect_mapping, load_workflow

REPO = Path(__file__).resolve().parents[2]
DIRS = [REPO / "workflows"]


def test_builtin_qwen21_mapping():
    wf = load_workflow("qwen_image_21_t2i", DIRS)
    assert wf.mapping["prompt"] == [("4", "prompt")]
    assert wf.mapping["negative"] == [("4", "negative_prompt")]
    assert wf.mapping["seed"] == [("6", "seed")]
    assert wf.mapping["width"] == [("5", "width")]
    assert wf.output == "image"


def test_apply_params_and_keep_pc_clean():
    wf = load_workflow("qwen_image_21_t2i", DIRS)
    g = apply_params(wf, prompt="a gate", negative="text", seed=42, width=1664, height=928)
    assert g["4"]["inputs"]["prompt"] == "a gate"
    assert g["4"]["inputs"]["negative_prompt"] == "text"
    assert g["6"]["inputs"]["seed"] == 42
    assert (g["5"]["inputs"]["width"], g["5"]["inputs"]["height"]) == (1664, 928)
    assert g["8"]["class_type"] == "PreviewImage"
    assert "filename_prefix" not in g["8"]["inputs"]
    # the loaded workflow itself is untouched
    assert wf.graph["8"]["class_type"] == "SaveImage"


def test_keep_pc_clean_off_keeps_save_node():
    wf = load_workflow("qwen_image_21_t2i", DIRS)
    g = apply_params(wf, prompt="x", keep_pc_clean=False)
    assert g["8"]["class_type"] == "SaveImage"


def test_classic_two_encoder_graph():
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1, "height": 1, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["9", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["9", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "11": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
    }
    m = detect_mapping(graph)
    assert m["prompt"] == [("6", "text")]
    assert m["negative"] == [("7", "text")]
    assert m["images"] == [("10", "image"), ("11", "image")]


def test_ui_format_is_rejected(tmp_path):
    (tmp_path / "ui.json").write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(WorkflowError, match="Export \\(API\\)"):
        load_workflow("ui", [tmp_path])


def test_map_file_overrides_detection(tmp_path):
    src = REPO / "workflows" / "qwen_image_21_t2i.json"
    (tmp_path / "w.json").write_text(src.read_text())
    (tmp_path / "w.map.json").write_text(json.dumps({"prompt": ["4", "prompt"], "seed": ["6", "seed"]}))
    wf = load_workflow("w", [tmp_path])
    assert wf.mapping_source == "file"
    assert "negative" not in wf.mapping


def test_too_many_refs():
    wf = load_workflow("qwen_image_21_t2i", DIRS)
    with pytest.raises(WorkflowError):
        apply_params(wf, prompt="x", images=["a [temp]"])
