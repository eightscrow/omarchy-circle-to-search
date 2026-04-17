"""Screenshot capture (grim), monitor detection, clipboard helpers.

Only grim is supported — this project targets Hyprland / Omarchy.
"""

import json
import mimetypes
import os
import subprocess

from cts import Gdk


# ---------------------------------------------------------------------------
# Monitor detection
# ---------------------------------------------------------------------------

def get_active_monitor_geometry():
    """(x, y, w, h) of the monitor containing the pointer (GDK fallback)."""
    display = Gdk.Display.get_default()
    try:
        seat = display.get_default_seat()
        pointer = seat.get_pointer()
        _screen, px, py = pointer.get_position()
        monitor = display.get_monitor_at_point(px, py)
    except Exception:
        monitor = None
    if monitor is None:
        monitor = display.get_primary_monitor() or display.get_monitor(0)
    geo = monitor.get_geometry()
    return geo.x, geo.y, geo.width, geo.height


def get_hyprland_cursor_monitor():
    """Return Hyprland monitor dict under the cursor, or None."""
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return None
    try:
        cp = subprocess.run(
            ["hyprctl", "-j", "cursorpos"],
            capture_output=True, text=True, timeout=2,
        )
        mr = subprocess.run(
            ["hyprctl", "-j", "monitors"],
            capture_output=True, text=True, timeout=2,
        )
        if cp.returncode != 0 or mr.returncode != 0:
            return None

        cursor = json.loads(cp.stdout)
        monitors = json.loads(mr.stdout)
        px = float(cursor.get("x", 0))
        py = float(cursor.get("y", 0))

        for mon in monitors:
            x = int(mon.get("x", 0))
            y = int(mon.get("y", 0))
            w = int(mon.get("width", 0))
            h = int(mon.get("height", 0))
            scale = float(mon.get("scale", 1.0) or 1.0)
            lw, lh = w / scale, h / scale
            if w > 0 and x <= px < x + lw and y <= py < y + lh:
                return mon

        for mon in monitors:
            if mon.get("focused") and int(mon.get("width", 0)) > 0:
                return mon

        return monitors[0] if monitors else None
    except Exception:
        return None


def get_capture_monitor_geometry():
    """(x, y, w_logical, h_logical) for ``grim -g``."""
    mon = get_hyprland_cursor_monitor()
    if mon is not None:
        x = int(mon.get("x", 0))
        y = int(mon.get("y", 0))
        w = int(mon.get("width", 0))
        h = int(mon.get("height", 0))
        scale = float(mon.get("scale", 1.0) or 1.0)
        return x, y, int(round(w / scale)), int(round(h / scale))
    return get_active_monitor_geometry()


# ---------------------------------------------------------------------------
# Screenshot (grim only)
# ---------------------------------------------------------------------------

def take_screenshot_with_tool(output_path, geometry=None, output_name=None):
    """Capture screenshot using grim.

    Args:
        output_path: destination file
        geometry: optional (x, y, w, h) for region capture
        output_name: optional Wayland output name for ``grim -o``
    """
    if output_name:
        result = subprocess.run(["grim", "-o", output_name, output_path],
                                capture_output=True)
    elif geometry:
        x, y, w, h = geometry
        geom_str = f"{int(x)},{int(y)} {int(w)}x{int(h)}"
        result = subprocess.run(["grim", "-g", geom_str, output_path],
                                capture_output=True)
    else:
        result = subprocess.run(["grim", output_path], capture_output=True)
    return result.returncode == 0

# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def copy_to_clipboard_image(path):
    mime_type = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, 'rb') as f:
        subprocess.run(["wl-copy", "-t", mime_type], stdin=f, check=False)


def copy_to_clipboard_text(text):
    proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
    proc.communicate(input=text)
