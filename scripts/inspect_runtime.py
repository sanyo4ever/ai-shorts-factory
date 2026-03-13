from __future__ import annotations

from filmstudio.core.settings import get_settings
from filmstudio.services.adapter_registry import build_runtime_probe


def main() -> int:
    probe = build_runtime_probe(get_settings())
    import json

    print(json.dumps(probe, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
