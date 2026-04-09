"""
Standalone launcher for the student information viewer.

Run:
    python student_viewer.py
"""

from __future__ import annotations

import importlib.util
import sys


def _has_qt() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def main() -> int:
    if _has_qt():
        from gui.viewer_app_qt import main as qt_main

        return qt_main()

    from gui.student_viewer import StudentViewer

    viewer = StudentViewer()
    viewer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
