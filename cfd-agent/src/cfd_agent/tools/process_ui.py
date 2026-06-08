from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes


def foreground_enabled() -> bool:
    return os.getenv("CFD_AGENT_FOREGROUND", "true").strip().lower() not in {"0", "false", "no", "off"}


def bring_process_to_foreground(process_id: int, timeout: float = 10.0) -> bool:
    if os.name != "nt" or not foreground_enabled():
        return False

    user32 = ctypes.windll.user32
    found: list[int] = []

    def collect_window(hwnd: int, _lparam: int) -> bool:
        window_process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_process_id))
        if window_process_id.value == process_id and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(collect_window)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found.clear()
        user32.EnumWindows(callback, 0)
        if found:
            user32.ShowWindow(found[0], 9)
            user32.SetForegroundWindow(found[0])
            return True
        time.sleep(0.25)
    return False
