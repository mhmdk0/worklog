"""Fonts bundled in fonts/, so the PDFs look the same on Linux, macOS and Windows."""

import os

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def font_path(filename):
    """Path of a bundled font file, or None if it's missing."""
    path = os.path.join(FONT_DIR, filename)
    return path if os.path.exists(path) else None
