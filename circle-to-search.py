#!/usr/bin/env python3
"""Circle to Search — Omarchy live-only edition."""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.parse
import uuid

# Allow imports from /usr/lib/circle-to-search when installed via AUR.
_LIB_DIR = "/usr/lib/circle-to-search"
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from PIL import Image, ImageFilter

import cts
from cts import Gtk, GLib
from cts import LAYER_SHELL_AVAILABLE
import cts.config as config
import cts.lock as lock
from cts.capture import copy_to_clipboard_image, copy_to_clipboard_text
from cts.capture import get_hyprland_cursor_monitor
from cts.dialogs import ImagePreviewDialog, TextResultDialog
from cts.overlay_live import LiveOverlay


IMGUR_CLIENT_ID = "546c25a59c58ad7"


def _notify(summary, body=None, icon=None, timeout=None):
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send"]
    if timeout is not None:
        cmd.extend(["-t", str(timeout)])
    if icon:
        cmd.extend(["-i", icon])
    cmd.append(summary)
    if body:
        cmd.append(body)
    subprocess.run(cmd, check=False)


def _open_url(url):
    for launcher in ("omarchy-launch-browser", "xdg-open"):
        if shutil.which(launcher):
            subprocess.Popen(
                [launcher, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
    _notify("Browser Error", "No browser launcher found", icon="dialog-error")
    return False


def _persistent_output_path(fmt):
    suffix = {'png': 'png', 'jpg': 'jpg', 'webp': 'webp'}.get(fmt, 'png')
    return os.path.join(
        tempfile.gettempdir(),
        f"circle_search_upload_{uuid.uuid4().hex[:8]}.{suffix}",
    )


def _apply_output_settings(crop_path, output_settings):
    """Apply feather / format conversion and return a persistent output path."""
    feather = int(output_settings.get('feather', 0))
    fmt = output_settings.get('format', 'png')
    out = _persistent_output_path(fmt)

    try:
        if feather == 0 and fmt == 'png':
            shutil.copyfile(crop_path, out)
            copy_to_clipboard_image(out)
            return out

        img = Image.open(crop_path)
    except (OSError, IOError) as exc:
        _notify("Image Error", str(exc), icon="dialog-error")
        return None

    if feather > 0 and img.mode == 'RGBA':
        alpha = img.getchannel('A')
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
        img.putalpha(alpha)

    if fmt == 'jpg':
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert('RGB')
        img.save(out, "JPEG", quality=90)
    elif fmt == 'webp':
        img.save(out, "WEBP", quality=90)
    else:
        img.save(out, "PNG", optimize=True)

    copy_to_clipboard_image(out)
    return out


def _upload_and_search(persistent_path):
    """Upload to imgur and open Google Lens in a detached process."""
    # Look for upload.py relative to cts package, not the entry script.
    upload_script = os.path.join(
        os.path.dirname(os.path.realpath(cts.__file__)), "upload.py"
    )
    subprocess.Popen(
        ["python3", upload_script, persistent_path, IMGUR_CLIENT_ID],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _handle_ocr(crop_path, hypr_mon):
    """OCR the cropped image, show text dialog, dispatch action."""
    try:
        img = Image.open(crop_path)
        text = cts.pytesseract.image_to_string(img).strip()
    except Exception as exc:
        _notify("OCR Error", str(exc), icon="dialog-error")
        return

    if not text:
        _notify("No Text Found", "OCR could not detect any text", icon="dialog-warning")
        return

    copy_to_clipboard_text(text)

    text_dialog = TextResultDialog(text, target_monitor=hypr_mon)
    text_dialog.show_all()
    Gtk.main()

    text_result = text_dialog.result
    final_text = text_dialog.final_text
    text_dialog.destroy()

    if text_result == "search":
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(final_text)}"
        _open_url(url)

    elif text_result == "translate":
        url = (f"https://translate.google.com/?sl=auto&tl=en"
               f"&text={urllib.parse.quote_plus(final_text)}")
        _open_url(url)

    elif text_result == "copy":
        copy_to_clipboard_text(final_text)


def main():
    parser = argparse.ArgumentParser(
        description="Circle to Search — Omarchy live overlay",
    )
    parser.add_argument(
        '--translate',
        action='store_true',
        help='Start in Select & Translate mode (requires OCR and Ollama)',
    )
    args = parser.parse_args()

    config.init()

    if not LAYER_SHELL_AVAILABLE:
        _notify(
            "Live Overlay Unavailable",
            "gtk-layer-shell is required on Omarchy.",
            icon="dialog-error",
        )
        sys.exit(1)

    hyprland = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    xdg_session = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if not hyprland and 'hyprland' not in xdg_session:
        _notify(
            "Hyprland Required",
            f"This build targets Omarchy / Hyprland only. Detected: {xdg_session or 'unknown'}",
            icon="dialog-error",
        )
        sys.exit(1)

    start_translate = args.translate
    crop_path = [None]

    def on_selection(path):
        crop_path[0] = path

    hypr_mon = get_hyprland_cursor_monitor()
    overlay = LiveOverlay(on_selection, target_monitor=hypr_mon)
    overlay.show_all()
    if start_translate:
        GLib.timeout_add(100, overlay.start_live_translate)
    Gtk.main()

    if not crop_path[0]:
        sys.exit(0)

    img = Image.open(crop_path[0])
    has_transparency = (img.mode == 'RGBA'
                        and img.getchannel('A').getextrema()[0] < 255)

    if cts.USER_CONFIG['instant_search']:
        persistent_path = _apply_output_settings(
            crop_path[0], {'format': 'png', 'feather': 0},
        )
        if persistent_path:
            _upload_and_search(persistent_path)
    else:
        dialog = ImagePreviewDialog(
            crop_path[0],
            has_transparency=has_transparency,
            target_monitor=hypr_mon,
        )
        dialog.show_all()
        Gtk.main()
        choice = dialog.result
        output_settings = dialog.get_output_settings()
        dialog.destroy()

        if choice == "google_lens":
            persistent_path = _apply_output_settings(crop_path[0], output_settings)
            if persistent_path:
                _upload_and_search(persistent_path)
        elif choice == "manual_paste":
            persistent_path = _apply_output_settings(crop_path[0], output_settings)
            if persistent_path:
                copy_to_clipboard_image(persistent_path)
                _open_url("https://lens.google.com/")
        elif choice == "ocr":
            _handle_ocr(crop_path[0], hypr_mon)

    try:
        os.remove(crop_path[0])
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    if not lock.acquire():
        sys.exit(0)

    def _signal_handler(signum, frame):
        lock.release()
        sys.exit(1)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        main()
    finally:
        lock.release()
