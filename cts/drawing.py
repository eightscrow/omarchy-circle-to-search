"""Cairo drawing helpers for the live overlay."""

import math

import cts
from cts.config import set_ui_font


def catmull_rom_path(cr, points):
    """Draw smooth Catmull-Rom spline through *points* using Cairo beziers."""
    n = len(points)
    if n < 2:
        return
    cr.move_to(points[0][0], points[0][1])
    if n == 2:
        cr.line_to(points[1][0], points[1][1])
        return
    last = n - 1
    for i in range(n - 1):
        p0 = points[max(0, i - 1)]
        p1 = points[i]
        p2 = points[min(last, i + 1)]
        p3 = points[min(last, i + 2)]
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        cr.curve_to(c1x, c1y, c2x, c2y, p2[0], p2[1])


def draw_glow_stroke(cr, path_func, line_width, accent_rgb, accent2_rgb, muted_rgb):
    """Build path once via *path_func*, then replay with crisp strokes."""
    path_func()
    saved = cr.copy_path()
    cr.new_path()

    mr, mg, mb = muted_rgb
    cr.set_line_width(line_width + 4)
    cr.set_source_rgba(mr, mg, mb, 0.18)
    cr.append_path(saved)
    cr.stroke()

    ar, ag, ab = accent_rgb
    cr.set_line_width(line_width + 1.5)
    cr.set_source_rgba(ar, ag, ab, 0.55)
    cr.append_path(saved)
    cr.stroke()

    a2r, a2g, a2b = accent2_rgb
    cr.set_line_width(line_width)
    cr.set_source_rgba(a2r, a2g, a2b, 0.95)
    cr.append_path(saved)
    cr.stroke()


def draw_instant_indicator(cr, sw, sh):
    """Draw status indicator showing Instant Search is active."""
    t = cts.APP_THEME
    inter_r, inter_g, inter_b = t['interactive_rgb']
    fg_r, fg_g, fg_b = t['foreground_rgb']
    bg_r, bg_g, bg_b = t['background_rgb']

    pad = 18
    panel_h = 36
    panel_w = 180
    px = sw - panel_w - pad
    py = sh - panel_h - pad - 38

    set_ui_font(cr, bold=True)
    draw_rounded_rect(cr, px, py, panel_w, panel_h, 4)
    cr.set_source_rgba(bg_r, bg_g, bg_b, 0.96)
    cr.fill_preserve()
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.35)
    cr.set_line_width(1)
    cr.stroke()

    bar_h = panel_h - 14
    cr.rectangle(px + 10, py + 7, 3, bar_h)
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
    cr.fill()

    cr.set_font_size(10)
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
    cr.move_to(px + 22, py + 14)
    cr.show_text("MODE")

    cr.set_font_size(11)
    cr.set_source_rgba(fg_r, fg_g, fg_b, 0.95)
    cr.move_to(px + 22, py + 27)
    cr.show_text("INSTANT SEARCH ON")


def draw_rounded_rect(cr, x, y, width, height, radius):
    """Draw a rounded rectangle path (no fill/stroke)."""
    cr.new_path()
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.arc(x + width - radius, y + radius, radius, 1.5 * math.pi, 2 * math.pi)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 0.5 * math.pi)
    cr.arc(x + radius, y + height - radius, radius, 0.5 * math.pi, math.pi)
    cr.close_path()


def draw_help_overlay(cr, sw, sh, title, subtitle):
    """Draw centered command panel overlay."""
    t = cts.APP_THEME
    bg_r, bg_g, bg_b = t['background_rgb']
    fg_r, fg_g, fg_b = t['foreground_rgb']
    inter_r, inter_g, inter_b = t['interactive_rgb']
    muted_r, muted_g, muted_b = t['muted_rgb']

    set_ui_font(cr, bold=True)
    cr.set_font_size(10)
    kicker = "CIRCLE TO SEARCH"
    k_ext = cr.text_extents(kicker)

    cr.set_font_size(16)
    t_ext = cr.text_extents(title)
    cr.set_font_size(10)
    s_ext = cr.text_extents(subtitle)

    card_w = max(k_ext.width, t_ext.width, s_ext.width) + 48
    card_h = 78
    card_x = (sw - card_w) / 2
    card_y = sh / 2 - 56
    radius = 4

    draw_rounded_rect(cr, card_x, card_y, card_w, card_h, radius)
    cr.set_source_rgba(bg_r, bg_g, bg_b, 0.96)
    cr.fill_preserve()
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.35)
    cr.set_line_width(1)
    cr.stroke()

    bar_h = card_h - 20
    cr.rectangle(card_x + 12, card_y + 10, 3, bar_h)
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
    cr.fill()

    set_ui_font(cr, bold=True)
    cr.set_font_size(10)
    cr.set_source_rgba(inter_r, inter_g, inter_b, 0.7)
    cr.move_to(card_x + 24, card_y + 21)
    cr.show_text(kicker)

    cr.set_font_size(16)
    tx = (sw - t_ext.width) / 2
    ty = card_y + 42
    cr.set_source_rgba(fg_r, fg_g, fg_b, 0.95)
    cr.move_to(tx, ty)
    cr.show_text(title)

    cr.set_font_size(10)
    sx = (sw - s_ext.width) / 2
    sy = card_y + 60
    cr.set_source_rgba(fg_r, fg_g, fg_b, 0.5)
    cr.move_to(sx, sy)
    cr.show_text(subtitle)


