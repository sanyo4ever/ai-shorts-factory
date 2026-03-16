from __future__ import annotations

import re
from pathlib import Path


_WINDOWS_DRIVE_PREFIX = re.compile(r"^/([A-Za-z]:[/\\].*)$")
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[/\\]")


def format_local_display_path(path: str | Path | None) -> str | None:
    """Normalize user-facing local paths for Windows-friendly display.

    Internal artifact storage should keep native filesystem paths. This helper is
    only for payloads and manifests that are shown to operators. In particular, it:
    - strips the accidental leading slash from `/E:/...`
    - normalizes Windows separators to forward slashes for easier copy/open usage
    """

    if path is None:
        return None
    value = str(path).strip()
    if not value:
        return value
    if value.startswith("\\\\?\\"):
        value = value[4:]
    windows_prefixed = _WINDOWS_DRIVE_PREFIX.match(value)
    if windows_prefixed:
        value = windows_prefixed.group(1)
    if _WINDOWS_DRIVE_PATH.match(value):
        return value.replace("\\", "/")
    return value
