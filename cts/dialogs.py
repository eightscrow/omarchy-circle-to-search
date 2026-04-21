"""ImagePreviewDialog and TextResultDialog — GTK windows for results display."""

from PIL import Image, ImageFilter

import cts
from cts import Gtk, Gdk, GdkPixbuf
from cts import LAYER_SHELL_AVAILABLE, GtkLayerShell, OCR_AVAILABLE
from cts.config import build_gtk_css


class OmarchyPanelWindow(Gtk.Window):
    """Undecorated panel window — draggable anywhere."""

    def __init__(self, title, target_monitor=None, default_size=(540, 600), resizable=False):
        super().__init__(title=title)
        self._target_monitor = target_monitor or {}
        self._default_size = default_size
        self._gdk_monitor = None
        self._use_layer_shell_panel = False
        self._panel_positioned = False
        self._panel_x = 24
        self._panel_y = 24
        self._drag_active = False
        self._drag_root = None
        self._drag_panel = None

        self.set_default_size(*default_size)
        self.set_keep_above(True)
        self.set_resizable(resizable)
        self.set_decorated(False)
        self.get_style_context().add_class("panel-shell")

        self._setup_window_target()
        self._apply_theme()
        self.connect("size-allocate", self._on_size_allocate)

        # Drag from anywhere on the window
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("button-press-event", self._on_window_press)
        self.connect("button-release-event", self._on_window_release)
        self.connect("motion-notify-event", self._on_window_motion)

    def _apply_theme(self):
        css = build_gtk_css()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_window_target(self):
        display = Gdk.Display.get_default()
        target_model = self._target_monitor.get("model", "")
        if target_model and display:
            for i in range(display.get_n_monitors()):
                monitor = display.get_monitor(i)
                if monitor.get_model() == target_model:
                    self._gdk_monitor = monitor
                    break
        if self._gdk_monitor is None and display:
            self._gdk_monitor = display.get_primary_monitor() or display.get_monitor(0)

        if LAYER_SHELL_AVAILABLE:
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
            if self._gdk_monitor:
                GtkLayerShell.set_monitor(self, self._gdk_monitor)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self._panel_y)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, self._panel_x)
            self._use_layer_shell_panel = True
        else:
            self.set_position(Gtk.WindowPosition.CENTER)

    def _monitor_size(self):
        if self._target_monitor:
            scale = float(self._target_monitor.get("scale", 1.0) or 1.0)
            width = int(round(int(self._target_monitor.get("width", 0)) / scale))
            height = int(round(int(self._target_monitor.get("height", 0)) / scale))
            if width > 0 and height > 0:
                return width, height
        if self._gdk_monitor is not None:
            geometry = self._gdk_monitor.get_geometry()
            return geometry.width, geometry.height
        return self._default_size

    def _apply_panel_position(self, x, y):
        monitor_w, monitor_h = self._monitor_size()
        panel_w = self.get_allocated_width() or self._default_size[0]
        panel_h = self.get_allocated_height() or self._default_size[1]
        max_x = max(0, monitor_w - panel_w - 24)
        max_y = max(0, monitor_h - panel_h - 24)
        self._panel_x = max(12, min(int(x), max_x))
        self._panel_y = max(12, min(int(y), max_y))
        if self._use_layer_shell_panel:
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, self._panel_x)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self._panel_y)

    def _on_size_allocate(self, widget, allocation):
        if not self._use_layer_shell_panel or self._panel_positioned:
            return
        if allocation.width < 2 or allocation.height < 2:
            return
        monitor_w, monitor_h = self._monitor_size()
        centered_x = (monitor_w - allocation.width) // 2
        top_y = max(24, int((monitor_h - allocation.height) * 0.22))
        self._apply_panel_position(centered_x, top_y)
        self._panel_positioned = True

    def _build_panel_header(self, kicker, title, subtitle=None):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_margin_top(12)
        header.set_margin_bottom(8)
        header.set_margin_start(16)
        header.set_margin_end(16)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        kicker_label = Gtk.Label(label=kicker)
        kicker_label.set_halign(Gtk.Align.START)
        kicker_label.get_style_context().add_class("window-kicker")
        left.pack_start(kicker_label, False, False, 0)

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.get_style_context().add_class("window-title")
        left.pack_start(title_label, False, False, 0)

        header.pack_start(left, True, True, 0)

        close_btn = Gtk.Button(label="ESC")
        close_btn.get_style_context().add_class("close-button")
        close_btn.set_valign(Gtk.Align.START)
        close_btn.connect("clicked", lambda _button: self._close_panel())
        header.pack_end(close_btn, False, False, 0)

        return header

    def _on_window_press(self, widget, event):
        if event.button != 1:
            return False
        # Don't drag when clicking interactive widgets
        target = event.window
        child = self.get_child()
        if child and hasattr(event, 'x') and hasattr(event, 'y'):
            widget_at = self._find_interactive_widget(event.x, event.y)
            if widget_at:
                return False
        if self._use_layer_shell_panel:
            self._drag_active = True
            self._drag_root = (event.x_root, event.y_root)
            self._drag_panel = (self._panel_x, self._panel_y)
            return True
        self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def _find_interactive_widget(self, x, y):
        """Check if click hits a button, combo, scale, or textview."""
        interactive_types = (Gtk.Button, Gtk.ComboBox, Gtk.ComboBoxText,
                             Gtk.Scale, Gtk.Entry, Gtk.TextView, Gtk.ScrolledWindow)
        def check(widget):
            if isinstance(widget, interactive_types):
                alloc = widget.get_allocation()
                if widget.get_mapped():
                    wx, wy = widget.translate_coordinates(self, 0, 0)
                    if wx is not None and (wx <= x <= wx + alloc.width and
                                            wy <= y <= wy + alloc.height):
                        return widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    result = check(child)
                    if result:
                        return result
            return None
        return check(self)

    def _on_window_motion(self, widget, event):
        if not self._drag_active or not self._drag_root or not self._drag_panel:
            return False
        delta_x = event.x_root - self._drag_root[0]
        delta_y = event.y_root - self._drag_root[1]
        self._apply_panel_position(self._drag_panel[0] + delta_x, self._drag_panel[1] + delta_y)
        return True

    def _on_window_release(self, widget, event):
        self._drag_active = False
        self._drag_root = None
        self._drag_panel = None
        return False

    def _close_panel(self):
        self.set_result(None)


class ImagePreviewDialog(OmarchyPanelWindow):
    """Preview with format/feather options and action buttons."""

    def __init__(self, image_path, has_transparency=False, target_monitor=None):
        super().__init__(
            title="Circle to Search",
            target_monitor=target_monitor,
            default_size=(560, 620),
            resizable=False,
        )
        self.image_path = image_path
        self.result = None
        self.has_transparency = has_transparency
        self.output_format = 'png'
        self.feather_amount = 4

        self.original_image = Image.open(image_path)
        self.preview_image = None
        self.max_preview_size = 448
        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.get_style_context().add_class("panel-root")
        self.add(main_box)

        main_box.pack_start(
            self._build_panel_header(
                "CAPTURE RESULT",
                "Circle to Search",
                "google lens / ocr / clipboard",
            ),
            False,
            False,
            0,
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(14)
        vbox.set_margin_bottom(14)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        main_box.pack_start(vbox, True, True, 0)

        hint = Gtk.Label(label="1 LENS  |  2 PASTE  |  3 OCR  |  ESC CLOSE")
        hint.set_halign(Gtk.Align.START)
        hint.get_style_context().add_class("hint-label")
        vbox.pack_start(hint, False, False, 0)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.get_style_context().add_class("image-frame")

        pixbuf = self._get_preview_pixbuf()
        self.preview_image = Gtk.Image.new_from_pixbuf(pixbuf)
        self.preview_image.set_margin_top(10)
        self.preview_image.set_margin_bottom(10)
        self.preview_image.set_margin_start(10)
        self.preview_image.set_margin_end(10)

        image_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        image_box.set_halign(Gtk.Align.CENTER)
        image_box.set_valign(Gtk.Align.CENTER)
        image_box.get_style_context().add_class("preview-area")
        image_box.pack_start(self.preview_image, False, False, 0)
        image_box.set_size_request(470, 296)
        frame.add(image_box)
        vbox.pack_start(frame, True, True, 0)

        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        strip.get_style_context().add_class("control-strip")

        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        strip.pack_start(options_box, True, True, 0)

        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        format_label = Gtk.Label(label="FORMAT")
        format_label.get_style_context().add_class("option-label")
        format_box.pack_start(format_label, False, False, 0)

        self.format_combo = Gtk.ComboBoxText()
        self.format_combo.append('png', 'PNG (transparent)')
        self.format_combo.append('jpg', 'JPG (smaller)')
        self.format_combo.append('webp', 'WebP (best)')
        self.format_combo.set_active_id('png')
        self.format_combo.connect('changed', self._on_format_changed)
        self.format_combo.get_style_context().add_class("format-combo")
        format_box.pack_start(self.format_combo, False, False, 0)
        options_box.pack_start(format_box, False, False, 0)

        feather_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        feather_label = Gtk.Label(label="EDGE")
        feather_label.get_style_context().add_class("option-label")
        feather_box.pack_start(feather_label, False, False, 0)

        self.feather_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 20, 1,
        )
        self.feather_scale.set_value(4)
        self.feather_scale.set_size_request(120, -1)
        self.feather_scale.set_draw_value(False)
        self.feather_scale.connect('value-changed', self._on_feather_changed)
        self.feather_scale.get_style_context().add_class("feather-scale")
        feather_box.pack_start(self.feather_scale, True, True, 0)

        self.feather_value_label = Gtk.Label(label="4px")
        self.feather_value_label.get_style_context().add_class("option-label")
        self.feather_value_label.set_size_request(35, -1)
        feather_box.pack_start(self.feather_value_label, False, False, 0)
        options_box.pack_end(feather_box, True, True, 0)
        vbox.pack_start(strip, False, False, 0)

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.pack_start(buttons_box, False, False, 0)

        btn_direct = Gtk.Button(label="1  GOOGLE LENS")
        btn_direct.get_style_context().add_class("command-button")
        btn_direct.get_style_context().add_class("command-primary")
        btn_direct.connect("clicked", lambda b: self.set_result("google_lens"))
        btn_direct.set_tooltip_text("Upload to imgur and open Google Lens automatically")
        buttons_box.pack_start(btn_direct, False, False, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox.set_homogeneous(True)
        buttons_box.pack_start(hbox, False, False, 0)

        btn_lens = Gtk.Button(label="2  PASTE")
        btn_lens.get_style_context().add_class("command-button")
        btn_lens.connect("clicked", lambda b: self.set_result("manual_paste"))
        btn_lens.set_tooltip_text("Open Google Lens (paste image manually)")
        hbox.pack_start(btn_lens, True, True, 0)

        btn_ocr = Gtk.Button(label="3  OCR")
        btn_ocr.get_style_context().add_class("command-button")
        btn_ocr.connect("clicked", lambda b: self.set_result("ocr"))
        if not OCR_AVAILABLE:
            btn_ocr.set_sensitive(False)
            btn_ocr.set_tooltip_text(
                "Install OCR support with ./install.sh --with-ocr"
            )
        else:
            btn_ocr.set_tooltip_text("Extract text using OCR")
        hbox.pack_start(btn_ocr, True, True, 0)

        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", lambda w, e: self.set_result(None) or False)

    def _on_format_changed(self, combo):
        self.output_format = combo.get_active_id()
        if self.output_format == 'jpg' and self.has_transparency:
            self.format_combo.set_tooltip_text(
                "JPG doesn't support transparency - edges will have white background"
            )
        else:
            self.format_combo.set_tooltip_text("")

    def _on_feather_changed(self, scale):
        self.feather_amount = int(scale.get_value())
        self.feather_value_label.set_text(f"{self.feather_amount}px")
        self._update_preview()

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.set_result(None)
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_1, Gdk.KEY_KP_1):
            self.set_result("google_lens")
        elif event.keyval in (Gdk.KEY_2, Gdk.KEY_KP_2):
            self.set_result("manual_paste")
        elif event.keyval in (Gdk.KEY_3, Gdk.KEY_KP_3) and OCR_AVAILABLE:
            self.set_result("ocr")
        return False

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------

    def _get_preview_pixbuf(self):
        img = self.original_image.copy()

        if self.feather_amount > 0 and img.mode == 'RGBA':
            alpha = img.getchannel('A')
            alpha = alpha.filter(ImageFilter.GaussianBlur(self.feather_amount))
            img.putalpha(alpha)

        if img.mode == 'RGBA':
            data = img.tobytes()
            pixbuf = GdkPixbuf.Pixbuf.new_from_data(
                data, GdkPixbuf.Colorspace.RGB, True, 8,
                img.width, img.height, img.width * 4,
            )
        else:
            img_rgb = img.convert('RGB')
            data = img_rgb.tobytes()
            pixbuf = GdkPixbuf.Pixbuf.new_from_data(
                data, GdkPixbuf.Colorspace.RGB, False, 8,
                img_rgb.width, img_rgb.height, img_rgb.width * 3,
            )

        width = pixbuf.get_width()
        height = pixbuf.get_height()
        if width > self.max_preview_size or height > self.max_preview_size:
            scale = min(self.max_preview_size / width,
                        self.max_preview_size / height)
            pixbuf = pixbuf.scale_simple(
                int(width * scale), int(height * scale),
                GdkPixbuf.InterpType.BILINEAR,
            )
        return pixbuf

    def _update_preview(self):
        if self.preview_image:
            self.preview_image.set_from_pixbuf(self._get_preview_pixbuf())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_output_settings(self):
        return {'format': self.output_format, 'feather': self.feather_amount}

    def set_result(self, result):
        self.result = result
        Gtk.main_quit()


# ======================================================================
# TextResultDialog
# ======================================================================

class TextResultDialog(OmarchyPanelWindow):
    """OCR results with search / translate / copy actions."""

    def __init__(self, text, target_monitor=None):
        super().__init__(
            title="Extracted Text",
            target_monitor=target_monitor,
            default_size=(560, 460),
            resizable=False,
        )
        self.text = text
        self.result = None
        self.final_text = text
        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.get_style_context().add_class("panel-root")
        self.add(main_box)

        main_box.pack_start(
            self._build_panel_header(
                "OCR RESULT",
                "Extracted Text",
                "search / translate / copy",
            ),
            False,
            False,
            0,
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(14)
        vbox.set_margin_bottom(14)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        main_box.pack_start(vbox, True, True, 0)

        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        kicker = Gtk.Label(label="COPIED TO CLIPBOARD")
        kicker.set_halign(Gtk.Align.START)
        kicker.get_style_context().add_class("section-kicker")
        heading_box.pack_start(kicker, False, False, 0)

        hint = Gtk.Label(label="1 SEARCH  |  2 TRANSLATE  |  3 COPY  |  ESC CLOSE")
        hint.set_halign(Gtk.Align.START)
        hint.get_style_context().add_class("hint-label")
        heading_box.pack_start(hint, False, False, 0)
        vbox.pack_start(heading_box, False, False, 0)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.get_style_context().add_class("panel-frame")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(220)

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.set_editable(True)
        self.textview.set_left_margin(12)
        self.textview.set_right_margin(12)
        self.textview.set_top_margin(12)
        self.textview.set_bottom_margin(12)
        self.textview.get_buffer().set_text(self.text)
        scrolled.add(self.textview)
        frame.add(scrolled)
        vbox.pack_start(frame, True, True, 0)

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.pack_start(buttons_box, False, False, 0)

        btn_search = Gtk.Button(label="1  SEARCH")
        btn_search.get_style_context().add_class("command-button")
        btn_search.get_style_context().add_class("command-primary")
        btn_search.connect("clicked", lambda b: self.set_result("search"))
        btn_search.set_tooltip_text("Search text in browser")
        buttons_box.pack_start(btn_search, False, False, 0)

        hbox1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox1.set_homogeneous(True)
        buttons_box.pack_start(hbox1, False, False, 0)

        btn_translate = Gtk.Button(label="2  TRANSLATE")

        btn_translate.get_style_context().add_class("command-button")
        btn_translate.connect("clicked", lambda b: self.set_result("translate"))
        btn_translate.set_tooltip_text("Open Google Translate")
        hbox1.pack_start(btn_translate, True, True, 0)

        btn_copy = Gtk.Button(label="3  COPY")
        btn_copy.get_style_context().add_class("command-button")
        btn_copy.connect("clicked", lambda b: self.set_result("copy"))
        btn_copy.set_tooltip_text("Copy text to clipboard")
        hbox1.pack_start(btn_copy, True, True, 0)



        self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.set_result(None)
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_1, Gdk.KEY_KP_1):
            self.set_result("search")
        elif event.keyval in (Gdk.KEY_2, Gdk.KEY_KP_2):
            self.set_result("translate")
        elif event.keyval in (Gdk.KEY_3, Gdk.KEY_KP_3):
            self.set_result("copy")
        return False

    def get_text(self):
        buf = self.textview.get_buffer()
        start, end = buf.get_bounds()
        return buf.get_text(start, end, False)

    def set_result(self, result):
        self.final_text = self.get_text()
        self.result = result
        Gtk.main_quit()
