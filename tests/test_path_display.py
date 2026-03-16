from pathlib import Path

from filmstudio.services.path_display import format_local_display_path


def test_format_local_display_path_normalizes_windows_drive_prefixes() -> None:
    assert format_local_display_path("/E:/sanyo4ever-filmstudio/runtime/final.mp4") == (
        "E:/sanyo4ever-filmstudio/runtime/final.mp4"
    )
    assert format_local_display_path(r"E:\sanyo4ever-filmstudio\runtime\final.mp4") == (
        "E:/sanyo4ever-filmstudio/runtime/final.mp4"
    )
    assert format_local_display_path(Path(r"E:\sanyo4ever-filmstudio\runtime\poster.png")) == (
        "E:/sanyo4ever-filmstudio/runtime/poster.png"
    )


def test_format_local_display_path_keeps_non_windows_paths_unchanged() -> None:
    assert format_local_display_path("/api/v1/projects/proj_123/deliverables/final_video/download") == (
        "/api/v1/projects/proj_123/deliverables/final_video/download"
    )
    assert format_local_display_path(None) is None
    assert format_local_display_path("") == ""
