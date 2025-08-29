"""Lightweight bridge to interact with AppWindow from prefs without circular imports."""
from __future__ import annotations

from typing import Any, Optional

_app_window: Optional[Any] = None


def set_app_window(app: Any) -> None:
    global _app_window
    _app_window = app


def get_app_window() -> Optional[Any]:
    return _app_window


def detach_plugin(plugin: Any) -> None:
    if _app_window is None:
        return
    try:
        _app_window.detach_plugin_to_new_window(plugin)
    except Exception:
        pass


def move_plugin_to_window(plugin: Any, window_index: int) -> None:
    if _app_window is None:
        return
    try:
        windows = getattr(_app_window, '_plugin_windows', [])
        if 0 <= window_index < len(windows):
            _app_window.move_plugin_to_window(plugin, windows[window_index])
    except Exception:
        pass


def return_plugin_to_main(plugin: Any) -> None:
    if _app_window is None:
        return
    try:
        _app_window.return_plugin_to_main(plugin)
    except Exception:
        pass


def get_plugin_windows_count() -> int:
    if _app_window is None:
        return 0
    try:
        return len(getattr(_app_window, '_plugin_windows', []))
    except Exception:
        return 0


def has_plugin_ui(plugin: Any) -> bool:
    if _app_window is None:
        return False
    try:
        rows = getattr(_app_window, '_plugin_rows', {})
        return plugin in rows
    except Exception:
        return False


