"""Circle to Search — Hyprland Edition

Package initialisation: sets GDK backend, imports GTK, and exposes shared
state that every sub-module needs.
"""

import os

# Force Wayland backend before any GTK/GDK import.
os.environ['GDK_BACKEND'] = 'wayland'

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib  # noqa: E402

# Layer-shell (live overlay + dialog placement)
LAYER_SHELL_AVAILABLE = False
GtkLayerShell = None
try:
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import GtkLayerShell as _GLS
    GtkLayerShell = _GLS
    LAYER_SHELL_AVAILABLE = True
except (ValueError, ImportError):
    pass

# OCR (pytesseract + tesseract)
OCR_AVAILABLE = False
pytesseract = None
try:
    import pytesseract as _pt
    pytesseract = _pt
    OCR_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Shared mutable state — populated by cts.config.init()
# ---------------------------------------------------------------------------
APP_THEME: dict = {}
USER_CONFIG: dict = {
    'instant_search': False,
    'ollama_model': 'qwen2.5:7b',
    'translation_target': 'English',
}
