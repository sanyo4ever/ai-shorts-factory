from __future__ import annotations

import sys
from pathlib import Path


TARGET_SNIPPETS = {
    "from .speech2video import WanS2V": """try:
    from .speech2video import WanS2V
    _speech2video_import_error = None
except Exception as exc:  # pragma: no cover - vendor runtime import guard
    WanS2V = None
    _speech2video_import_error = str(exc)
""",
    "from .animate import WanAnimate": """try:
    from .animate import WanAnimate
    _animate_import_error = None
except Exception as exc:  # pragma: no cover - vendor runtime import guard
    WanAnimate = None
    _animate_import_error = str(exc)
""",
}


def patch_init_file(service_root: Path) -> bool:
    init_path = service_root / "wan" / "__init__.py"
    if not init_path.exists():
        raise FileNotFoundError(f"Wan2.2 __init__.py not found: {init_path}")

    source = init_path.read_text(encoding="utf-8")
    updated = source
    changed = False
    for target, replacement in TARGET_SNIPPETS.items():
        alias = "WanS2V = None" if "WanS2V" in target else "WanAnimate = None"
        if alias in updated:
            continue
        if target not in updated:
            raise RuntimeError(f"Expected Wan2.2 import snippet was not found: {target.strip()}")
        updated = updated.replace(target, replacement)
        changed = True

    if changed:
        init_path.write_text(updated, encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: patch_wan22_optional_imports.py <wan22_repo_root>")
    service_root = Path(argv[1]).resolve()
    changed = patch_init_file(service_root)
    status = "patched" if changed else "already patched"
    print(f"Wan2.2 optional import guard {status}: {service_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
