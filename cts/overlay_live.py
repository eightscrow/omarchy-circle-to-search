"""LiveOverlay — transparent layer-shell overlay for live screen selection."""

import math
import os
import subprocess
import tempfile
import threading
import time
import uuid

from PIL import Image, ImageDraw, ImageFilter

import cts
from cts import Gtk, Gdk, GLib
from cts import GtkLayerShell, OCR_AVAILABLE
from cts.config import set_ui_font, save_user_config
from cts.drawing import (catmull_rom_path, draw_glow_stroke,
                         draw_instant_indicator, draw_help_overlay,
                         draw_rounded_rect, reset_anim_timer)
from cts.capture import (get_active_monitor_geometry, get_capture_monitor_geometry,
                         take_screenshot_with_tool)
from cts.ocr import TranslationCache, OllamaTranslator


class LiveOverlay(Gtk.Window):
    """Layer-shell based overlay for live screen selection (Hyprland)."""

    def __init__(self, callback, target_monitor=None):
        super().__init__(title="Circle to Search")

        self.callback = callback
        self.points = []
        self.drawing = False
        self.selection_made = False
        # Live translate mode
        self.live_translate_mode = False
        self.translation_cache = TranslationCache()
        self.translator = None
        self.translation_regions = []
        self.translate_lock = threading.Lock()
        self.translate_drawing = False
        self.translate_start = None
        self.translate_current = None
        self.translate_hover_idx = None

        # Screen dimensions
        # Hyprland reports pixel dimensions; grim uses layout coordinates.
        # GDK may report different sizes than Hyprland logical (fractional
        # scaling: GDK3 only supports integer scale factors).  Use GDK
        # geometry for overlay size and compute scale to grim layout coords.
        if target_monitor is not None:
            _scale = float(target_monitor.get("scale", 1.0) or 1.0)
            cap_x = int(target_monitor.get("x", 0))
            cap_y = int(target_monitor.get("y", 0))
            # grim layout size
            cap_w = int(round(int(target_monitor.get("width", 0)) / _scale))
            cap_h = int(round(int(target_monitor.get("height", 0)) / _scale))
        else:
            _mon_x, _mon_y, _mon_w, _mon_h = get_active_monitor_geometry()
            cap_x, cap_y, cap_w, cap_h = get_capture_monitor_geometry()

        display = Gdk.Display.get_default()
        target_model = (target_monitor or {}).get("model", "")
        gdk_monitor = None
        if target_model and display:
            for i in range(display.get_n_monitors()):
                m = display.get_monitor(i)
                if m.get_model() == target_model:
                    gdk_monitor = m
                    break
        if gdk_monitor is None and display:
            gdk_monitor = display.get_primary_monitor() or display.get_monitor(0)
        self.scale_factor = gdk_monitor.get_scale_factor() if gdk_monitor else 1

        # Overlay size = GDK geometry (what GTK actually renders at)
        if gdk_monitor:
            gdk_geo = gdk_monitor.get_geometry()
            mon_w = gdk_geo.width
            mon_h = gdk_geo.height
        else:
            mon_w = cap_w
            mon_h = cap_h

        self.screen_width = mon_w
        self.screen_height = mon_h
        self.capture_monitor_x = cap_x
        self.capture_monitor_y = cap_y
        self.capture_monitor_width = cap_w
        self.capture_monitor_height = cap_h

        # Layer shell
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        if gdk_monitor:
            GtkLayerShell.set_monitor(self, gdk_monitor)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.set_decorated(False)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.drawing_area = Gtk.DrawingArea()
        self.add(self.drawing_area)

        self.drawing_area.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("key-press-event", self.on_key_press)
        self.connect("scroll-event", self.on_scroll)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.KEY_PRESS_MASK |
            Gdk.EventMask.SCROLL_MASK
        )

        self._glow_anim_id = None

    # ------------------------------------------------------------------
    # Glow animation timer
    # ------------------------------------------------------------------

    def _start_glow_animation(self):
        if self._glow_anim_id is None:
            self._glow_anim_id = GLib.timeout_add(16, self._glow_tick)

    def _stop_glow_animation(self):
        if self._glow_anim_id is not None:
            GLib.source_remove(self._glow_anim_id)
            self._glow_anim_id = None

    def _glow_tick(self):
        if self.drawing and len(self.points) > 1:
            self.drawing_area.queue_draw()
            return True
        self._glow_anim_id = None
        return False

    # ------------------------------------------------------------------
    # Scroll (font size in translate mode)
    # ------------------------------------------------------------------

    def on_scroll(self, widget, event):
        if not self.live_translate_mode:
            return False
        if self.translate_hover_idx is not None:
            with self.translate_lock:
                if self.translate_hover_idx < len(self.translation_regions):
                    region = self.translation_regions[self.translate_hover_idx]
                    if event.direction == Gdk.ScrollDirection.UP:
                        region['font_size'] = min(region['font_size'] + 2, 36)
                    elif event.direction == Gdk.ScrollDirection.DOWN:
                        region['font_size'] = max(region['font_size'] - 2, 8)
                    elif event.direction == Gdk.ScrollDirection.SMOOTH:
                        if event.delta_y < 0:
                            region['font_size'] = min(region['font_size'] + 1, 36)
                        elif event.delta_y > 0:
                            region['font_size'] = max(region['font_size'] - 1, 8)
            self.drawing_area.queue_draw()
            return True
        return False

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def on_draw(self, widget, cr):
        t = cts.APP_THEME
        bg_r, bg_g, bg_b = t['background_rgb']
        fg_r, fg_g, fg_b = t['foreground_rgb']
        inter_r, inter_g, inter_b = t['interactive_rgb']
        inter_h_r, inter_h_g, inter_h_b = t['interactive_hover_rgb']
        alloc = widget.get_allocation()
        if alloc.width > 1 and alloc.height > 1:
            self.screen_width = alloc.width
            self.screen_height = alloc.height

        if getattr(self, '_capture_mode', False):
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            return False

        if getattr(self, '_translate_capture_mode', False):
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            return False

        if self.live_translate_mode:
            self._draw_translations(cr)
            return False

        cr.set_source_rgba(bg_r, bg_g, bg_b, 0.28)
        cr.paint()

        def glow(path_func, line_width=4, pts=None):
            draw_glow_stroke(cr, path_func, line_width, points=pts)

        # Freehand path
        if len(self.points) > 1:
            def draw_smooth_live():
                catmull_rom_path(cr, self.points)
            glow(draw_smooth_live, line_width=4, pts=self.points)

            tip_x, tip_y = self.points[-1]
            cr.select_font_face("omarchy", 0, 0)
            cr.set_font_size(18)
            icon = "\ue900"
            icon_ext = cr.text_extents(icon)
            cr.set_source_rgba(inter_r, inter_g, inter_b, 0.85)
            cr.move_to(tip_x - icon_ext.width / 2, tip_y + icon_ext.height / 2)
            cr.show_text(icon)
            set_ui_font(cr, bold=True)

        elif not self.drawing:
            draw_help_overlay(cr, self.screen_width, self.screen_height,
                              "Draw around target",
                              "DRAW SELECTION | ENTER FULL IMAGE | M INSTANT | T TRANSLATE | ESC CLOSE")

        if cts.USER_CONFIG['instant_search']:
            draw_instant_indicator(cr, self.screen_width, self.screen_height)

        return False

    # ==================================================================
    # Select & Translate
    # ==================================================================

    def start_live_translate(self):
        if not OCR_AVAILABLE:
            subprocess.run(["notify-send", "OCR Not Available",
                            "Install pytesseract for translation"])
            return False
        if self.translator is None:
            self.translator = OllamaTranslator()
        if not self.translator.available:
            subprocess.run(["notify-send", "Ollama Not Available",
                            "Start Ollama with: ollama serve"])
            return False
        self.live_translate_mode = True
        self.translate_drawing = False
        self.translate_start = None
        self.translate_current = None
        self.drawing_area.queue_draw()
        return True

    def stop_live_translate(self):
        self.live_translate_mode = False
        self.translate_drawing = False
        self.translate_start = None
        self.translate_current = None
        self.drawing_area.queue_draw()

    def clear_translations(self):
        with self.translate_lock:
            self.translation_regions = []
        self.drawing_area.queue_draw()

    def undo_last_translation(self):
        with self.translate_lock:
            if self.translation_regions:
                self.translation_regions.pop()
        self.drawing_area.queue_draw()

    def _translate_mouse_press(self, x, y):
        self.translate_drawing = True
        self.translate_start = (x, y)
        self.translate_current = (x, y)
        self.drawing_area.queue_draw()

    def _translate_mouse_motion(self, x, y):
        if self.translate_drawing:
            self.translate_current = (x, y)
            self.drawing_area.queue_draw()
        else:
            old_hover = self.translate_hover_idx
            self.translate_hover_idx = None
            with self.translate_lock:
                for i, region in enumerate(self.translation_regions):
                    bx, by, bw, bh = region['box']
                    if bx <= x <= bx + bw and by <= y <= by + bh:
                        self.translate_hover_idx = i
                        break
            if old_hover != self.translate_hover_idx:
                self.drawing_area.queue_draw()

    def _translate_mouse_release(self, x, y):
        if not self.translate_drawing or not self.translate_start:
            return
        self.translate_drawing = False
        sx, sy = self.translate_start
        ex, ey = x, y
        box_x = min(sx, ex)
        box_y = min(sy, ey)
        box_w = abs(ex - sx)
        box_h = abs(ey - sy)

        if box_w < 20 or box_h < 10:
            self.translate_start = None
            self.translate_current = None
            self.drawing_area.queue_draw()
            return

        self.translate_start = None
        self.translate_current = None

        self._capture_mode = True
        self.drawing_area.queue_draw()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.05)

        fd, temp_path = tempfile.mkstemp(suffix='.png', prefix='cts_translate_')
        os.close(fd)
        sw = self.screen_width or 1
        sh = self.screen_height or 1
        scale_x = self.capture_monitor_width / sw
        scale_y = self.capture_monitor_height / sh
        capture_x = int(self.capture_monitor_x + box_x * scale_x)
        capture_y = int(self.capture_monitor_y + box_y * scale_y)
        capture_w = max(1, int(box_w * scale_x))
        capture_h = max(1, int(box_h * scale_y))
        capture_ok = take_screenshot_with_tool(
            temp_path,
            geometry=(capture_x, capture_y, capture_w, capture_h),
        )

        self._capture_mode = False
        self.drawing_area.queue_draw()

        if not capture_ok:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return

        region_idx = len(self.translation_regions)
        with self.translate_lock:
            self.translation_regions.append({
                'box': (box_x, box_y, box_w, box_h),
                'text': '',
                'translation': 'Translating...',
                'pending': True,
                'font_size': 14,
            })
        self.drawing_area.queue_draw()

        threading.Thread(
            target=self._process_region_translation,
            args=(region_idx, box_x, box_y, box_w, box_h, temp_path),
            daemon=True,
        ).start()

    def _process_region_translation(self, region_idx, box_x, box_y, box_w, box_h, temp_path):
        try:
            text = cts.pytesseract.image_to_string(
                Image.open(temp_path), config='--oem 1 --psm 6',
            ).strip()
            text = ' '.join(text.split())

            if not text:
                self._update_region(region_idx, '', 'No text detected', False)
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                return

            cached = self.translation_cache.get(text)
            if cached:
                self._update_region(region_idx, text, cached, False)
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                return

            self._update_region(region_idx, text, 'Translating...', True)
            translator = self.translator
            if translator is None:
                self._update_region(region_idx, text, 'Translator unavailable', False)
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                return

            translation = translator.translate(text)
            if translation:
                self.translation_cache.set(text, translation)
                self._update_region(region_idx, text, translation, False)
            else:
                self._update_region(region_idx, text, 'Translation failed', False)

            try:
                os.remove(temp_path)
            except OSError:
                pass
        except Exception as e:
            self._update_region(region_idx, '', f'Error: {e}', False)
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _update_region(self, idx, text, translation, pending):
        with self.translate_lock:
            if idx < len(self.translation_regions):
                self.translation_regions[idx]['text'] = text
                self.translation_regions[idx]['translation'] = translation
                self.translation_regions[idx]['pending'] = pending
        GLib.idle_add(self.drawing_area.queue_draw)

    def _draw_translations(self, cr):
        t = cts.APP_THEME
        bg_r, bg_g, bg_b = t['background_rgb']
        fg_r, fg_g, fg_b = t['foreground_rgb']
        inter_r, inter_g, inter_b = t['interactive_rgb']
        inter_h_r, inter_h_g, inter_h_b = t['interactive_hover_rgb']
        muted_r, muted_g, muted_b = t['muted_rgb']
        surface_r, surface_g, surface_b = t['surface_rgb']
        warning_r, warning_g, warning_b = t['warning_rgb']

        cr.set_source_rgba(bg_r, bg_g, bg_b, 0.08)
        cr.paint()

        with self.translate_lock:
            regions = list(enumerate(self.translation_regions))

        padding = 5
        for idx, region in regions:
            box_x, box_y, box_w, box_h = region['box']
            translation = region['translation']
            pending = region['pending']
            font_size = region.get('font_size', 14)
            line_height = font_size + 4
            is_hovered = (idx == self.translate_hover_idx)

            set_ui_font(cr, bold=False)
            cr.set_font_size(font_size)
            max_width = box_w - padding * 2

            words = translation.split()
            lines = []
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word])
                if cr.text_extents(test_line).width > max_width and current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    current_line.append(word)
            if current_line:
                lines.append(' '.join(current_line))

            max_lines = max(1, int((box_h - padding) / line_height))
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                if lines[-1]:
                    while cr.text_extents(lines[-1] + "...").width > max_width and len(lines[-1]) > 10:
                        lines[-1] = lines[-1][:-1]
                    lines[-1] = lines[-1].rstrip() + "..."

            total_text_height = len(lines) * line_height
            text_start_y = box_y + (box_h - total_text_height) / 2

            draw_rounded_rect(cr, box_x, box_y, box_w, box_h, 3)
            if pending:
                cr.set_source_rgba(surface_r, surface_g, surface_b, 0.95)
            else:
                cr.set_source_rgba(bg_r, bg_g, bg_b, 0.96)
            cr.fill_preserve()

            if is_hovered:
                cr.set_source_rgba(inter_h_r, inter_h_g, inter_h_b, 0.9)
                cr.set_line_width(2)
            elif pending:
                cr.set_source_rgba(warning_r, warning_g, warning_b, 0.7)
                cr.set_line_width(1.5)
            else:
                cr.set_source_rgba(inter_r, inter_g, inter_b, 0.4)
                cr.set_line_width(1)
            cr.stroke()

            cr.rectangle(box_x + 8, box_y + 8, 3, box_h - 16)
            if pending:
                cr.set_source_rgba(warning_r, warning_g, warning_b, 0.7)
            else:
                cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
            cr.fill()

            cr.set_source_rgba(fg_r, fg_g, fg_b, 1.0)
            for i, line in enumerate(lines):
                ly = text_start_y + (i + 1) * line_height - 3
                cr.move_to(box_x + padding + 12, ly)
                cr.show_text(line)

            if is_hovered:
                size_text = f"FONT {font_size}px | SCROLL TO ADJUST"
                cr.set_font_size(10)
                cr.set_source_rgba(fg_r, fg_g, fg_b, 0.4)
                cr.move_to(box_x + 18, box_y + box_h - 6)
                cr.show_text(size_text)

        # Current selection being drawn
        if self.translate_drawing and self.translate_start and self.translate_current:
            sx, sy = self.translate_start
            cx, cy = self.translate_current
            x = min(sx, cx)
            y = min(sy, cy)
            w = abs(cx - sx)
            h = abs(cy - sy)
            draw_rounded_rect(cr, x, y, w, h, 3)
            cr.set_source_rgba(inter_r, inter_g, inter_b, 0.1)
            cr.fill()
            cr.set_source_rgba(inter_h_r, inter_h_g, inter_h_b, 0.7)
            cr.set_line_width(1.5)
            cr.set_dash([10, 4])
            draw_rounded_rect(cr, x, y, w, h, 3)
            cr.stroke()
            cr.set_dash([])

        self._draw_translate_status(cr)

    def _draw_translate_status(self, cr):
        t = cts.APP_THEME
        bg_r, bg_g, bg_b = t['background_rgb']
        inter_r, inter_g, inter_b = t['interactive_rgb']
        inter_h_r, inter_h_g, inter_h_b = t['interactive_hover_rgb']

        region_count = len(self.translation_regions)
        status = (f"SELECT & TRANSLATE | DRAW BOXES | C CLEAR | Z UNDO | "
              f"ESC EXIT | REGIONS {region_count}")

        set_ui_font(cr, bold=True)
        cr.set_font_size(13)
        ext = cr.text_extents(status)
        x = (self.screen_width - ext.width) / 2
        y = 40

        draw_rounded_rect(cr, x - 18, y - 23, ext.width + 36, 34, 4)
        cr.set_source_rgba(bg_r, bg_g, bg_b, 0.96)
        cr.fill_preserve()
        cr.set_source_rgba(inter_r, inter_g, inter_b, 0.35)
        cr.set_line_width(1)
        cr.stroke()

        cr.rectangle(x - 8, y - 15, 3, 18)
        cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
        cr.fill()

        set_ui_font(cr, bold=True)
        fg_r, fg_g, fg_b = t['foreground_rgb']
        cr.set_font_size(13)
        cr.set_source_rgba(fg_r, fg_g, fg_b, 0.85)
        cr.move_to(x, y)
        cr.show_text(status)

    # ==================================================================
    # Event handlers
    # ==================================================================

    def on_button_press(self, widget, event):
        if self.live_translate_mode and event.button == 1:
            self._translate_mouse_press(event.x, event.y)
            return True

        if event.button == 1:
            self.drawing = True
            self.points = [(event.x, event.y)]
            reset_anim_timer()
            self._start_glow_animation()
        return True

    def on_motion(self, widget, event):
        if self.live_translate_mode:
            self._translate_mouse_motion(event.x, event.y)
            return True

        if self.drawing:
            if not self.points or (
                (event.x - self.points[-1][0]) ** 2 +
                (event.y - self.points[-1][1]) ** 2
            ) >= 16:
                self.points.append((event.x, event.y))
                self.drawing_area.queue_draw()
        return True

    def on_button_release(self, widget, event):
        if self.live_translate_mode and event.button == 1:
            self._translate_mouse_release(event.x, event.y)
            return True

        if event.button == 1 and self.drawing:
            self.drawing = False
            self._stop_glow_animation()
            if len(self.points) > 10:
                self.process_selection()
            else:
                self.points = []
                self.drawing_area.queue_draw()
        return True

    def on_key_press(self, widget, event):
        if event.keyval in (Gdk.KEY_t, Gdk.KEY_T):
            if not self.drawing:
                if self.live_translate_mode:
                    self.stop_live_translate()
                else:
                    self.start_live_translate()
                return True

        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C):
            if self.live_translate_mode:
                self.clear_translations()
                return True

        if event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            if self.live_translate_mode:
                self.undo_last_translation()
                return True

        if event.keyval == Gdk.KEY_Escape:
            if self.live_translate_mode:
                self.stop_live_translate()
                return True
            self.callback(None)
            self.destroy()
            Gtk.main_quit()
        elif event.keyval == Gdk.KEY_Return:
            if not self.drawing and len(self.points) == 0:
                self.send_entire_image()
                return True
        elif event.keyval in (Gdk.KEY_m, Gdk.KEY_M):
            if not self.drawing:
                cts.USER_CONFIG['instant_search'] = not cts.USER_CONFIG['instant_search']
                save_user_config()
                self.drawing_area.queue_draw()
        return True

    # ==================================================================
    # Selection processing
    # ==================================================================

    def send_entire_image(self):
        if self.selection_made:
            return
        self.selection_made = True

        self._capture_mode = True
        self.drawing_area.queue_draw()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        self.hide()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.1)

        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"circle_search_full_{uuid.uuid4().hex[:8]}.png")

        if take_screenshot_with_tool(
            output_path,
            geometry=(
                self.capture_monitor_x,
                self.capture_monitor_y,
                self.capture_monitor_width,
                self.capture_monitor_height,
            ),
        ):
            self.callback(output_path)
        else:
            self.callback(None)
        self.destroy()
        Gtk.main_quit()

    def get_bounding_box(self):
        if not self.points:
            return None
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        padding = 10
        x1 = max(0, min(xs) - padding)
        y1 = max(0, min(ys) - padding)
        x2 = min(self.screen_width, max(xs) + padding)
        y2 = min(self.screen_height, max(ys) + padding)
        return (int(x1), int(y1), int(x2), int(y2))

    def process_selection(self):
        if self.selection_made:
            return
        self.selection_made = True

        bbox = self.get_bounding_box()
        if not bbox:
            self.callback(None)
            self.destroy()
            Gtk.main_quit()
            return

        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        if width < 20 or height < 20:
            self.callback(None)
            self.destroy()
            Gtk.main_quit()
            return

        self._capture_points = self.points.copy() if self.points else []
        self.points = []
        self._capture_mode = True
        self.drawing_area.queue_draw()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        self._capture_params = (x1, y1, width, height)
        self._callback = self.callback
        GLib.timeout_add(50, self._do_capture)

    def _do_capture(self):
        x, y, width, height = self._capture_params
        self.hide()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.1)

        temp_dir = tempfile.gettempdir()
        cropped_path = os.path.join(temp_dir, f"circle_search_crop_{uuid.uuid4().hex[:8]}.png")

        # Convert overlay pixel coords → grim logical coords on-the-fly.
        # screen_width/height = actual overlay dimensions (from GTK allocation).
        # capture_monitor_width/height = Hyprland logical (width/scale).
        sw = self.screen_width or 1
        sh = self.screen_height or 1
        scale_x = self.capture_monitor_width / sw
        scale_y = self.capture_monitor_height / sh

        capture_x = int(self.capture_monitor_x + x * scale_x)
        capture_y = int(self.capture_monitor_y + y * scale_y)
        capture_w = max(1, int(width * scale_x))
        capture_h = max(1, int(height * scale_y))

        success = take_screenshot_with_tool(
            cropped_path,
            geometry=(capture_x, capture_y, capture_w, capture_h),
        )

        if success:
            if len(self._capture_points) >= 3:
                img = Image.open(cropped_path).convert('RGBA')
                img_w, img_h = img.size
                mask = Image.new('L', img.size, 0)
                draw = ImageDraw.Draw(mask)

                # Map overlay points → image pixels using actual image size.
                # This works regardless of grim output resolution.
                scaled_points = []
                for px, py in self._capture_points:
                    sx = int((px - x) / width * img_w)
                    sy = int((py - y) / height * img_h)
                    scaled_points.append((sx, sy))

                if len(scaled_points) > 2:
                    draw.polygon(scaled_points, fill=255)

                mask = mask.filter(ImageFilter.GaussianBlur(3))
                mask = mask.point(lambda v: 255 if v > 80 else 0)
                img.putalpha(mask)
                img.save(cropped_path, "PNG", optimize=True)

            self._callback(cropped_path)
        else:
            self._callback(None)

        self.destroy()
        Gtk.main_quit()
        return False
