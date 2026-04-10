"""
Launch the student viewer in a separate process when Qt is available.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from gui.student_viewer import open_viewer as open_tk_viewer

BASE_DIR = Path(__file__).resolve().parent.parent
VIEWER_SCRIPT = Path(__file__).resolve().parent / "viewer_app_qt.py"
VIEWER_MODULE = "gui.viewer_app_qt"

_viewer_process: subprocess.Popen | None = None


def _can_launch_qt_viewer() -> bool:
    return importlib.util.find_spec("PySide6") is not None and VIEWER_SCRIPT.exists()


def _launch_qt_viewer() -> bool:
    global _viewer_process

    if _viewer_process and _viewer_process.poll() is None:
        try:
            _viewer_process.terminate()
            _viewer_process.wait(timeout=3)
        except Exception:
            try:
                _viewer_process.kill()
            except Exception:
                pass
        finally:
            _viewer_process = None

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        _viewer_process = subprocess.Popen(
            [sys.executable, "-m", VIEWER_MODULE],
            cwd=str(BASE_DIR),
            creationflags=creationflags,
        )
        return True
    except Exception:
        return False


def open_student_viewer(master=None):
    if _can_launch_qt_viewer() and _launch_qt_viewer():
        return None
    return open_tk_viewer(master)
