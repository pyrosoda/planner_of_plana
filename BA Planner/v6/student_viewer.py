"""
Standalone launcher for the student information viewer.

Run:
    python student_viewer.py
"""

from __future__ import annotations

import importlib.util
import sys
import tkinter as tk

from core.config import activate_profile, get_active_profile_name, list_profiles
from gui.profile_dialog import choose_profile


def _ensure_profile_context() -> bool:
    profile_name = get_active_profile_name()
    if profile_name:
        activate_profile(profile_name)
        return True

    chooser_root = tk.Tk()
    chooser_root.withdraw()
    try:
        selected_profile = choose_profile(chooser_root, list_profiles(), last_profile=None)
    finally:
        chooser_root.destroy()

    if not selected_profile:
        return False

    activate_profile(selected_profile)
    return True


def _has_qt() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def main() -> int:
    if not _ensure_profile_context():
        return 0

    if _has_qt():
        from gui.viewer_app_qt import main as qt_main

        return qt_main()

    from gui.student_viewer import StudentViewer

    viewer = StudentViewer()
    viewer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
