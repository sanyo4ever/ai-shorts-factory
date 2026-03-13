from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_patch_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "patch_musetalk_preprocessing.py"
    spec = importlib.util.spec_from_file_location("patch_musetalk_preprocessing", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_musetalk_preprocessing_is_idempotent(tmp_path) -> None:
    module = _load_patch_module()
    service_root = tmp_path / "MuseTalk"
    preprocessing_path = service_root / "musetalk" / "utils" / "preprocessing.py"
    preprocessing_path.parent.mkdir(parents=True, exist_ok=True)
    preprocessing_path.write_text("coord_placeholder = (0.0,0.0,0.0,0.0)\n", encoding="utf-8")

    changed = module.apply_patch(service_root)
    assert changed is True

    patched_text = preprocessing_path.read_text(encoding="utf-8")
    assert "_safe_average" in patched_text
    assert "_landmark_bbox_and_ranges" in patched_text
    assert "if f is None:" in patched_text
    assert "coords_list += [f_landmark]" in patched_text

    changed_again = module.apply_patch(service_root)
    assert changed_again is False
    assert preprocessing_path.read_text(encoding="utf-8") == patched_text
