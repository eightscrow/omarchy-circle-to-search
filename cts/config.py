"""Omarchy theme loading, user configuration, CSS generation."""

import re
from pathlib import Path

import cts

try:
    import tomllib
except ImportError:
    tomllib = None


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def hex_to_rgb_f(hex_color):
    """#RRGGBB → (r, g, b) floats 0..1 for Cairo."""
    value = hex_color.strip().lstrip('#')
    if len(value) != 6:
        return (1.0, 1.0, 1.0)
    return (int(value[0:2], 16) / 255.0,
            int(value[2:4], 16) / 255.0,
            int(value[4:6], 16) / 255.0)


def hex_to_rgb_i(hex_color):
    """#RRGGBB → (r, g, b) ints 0..255 for CSS."""
    value = hex_color.strip().lstrip('#')
    if len(value) != 6:
        return (255, 255, 255)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def css_rgba(hex_color, alpha):
    r, g, b = hex_to_rgb_i(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def darken_hex(hex_color, factor=0.75):
    """Darken a #RRGGBB color by factor (0..1, lower = darker)."""
    r, g, b = hex_to_rgb_i(hex_color)
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def lighten_hex(hex_color, factor=0.25):
    """Lighten a #RRGGBB color by blending toward white."""
    r, g, b = hex_to_rgb_i(hex_color)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _luminance(hex_color):
    """Relative luminance (0..1) for contrast checking."""
    r, g, b = hex_to_rgb_f(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(lum_a, lum_b):
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Omarchy theme
# ---------------------------------------------------------------------------

def load_omarchy_theme():
    """Load active Omarchy theme colours, fallback to sane defaults."""
    theme = {
        'background': '#101913',
        'foreground': '#a1af9c',
        'accent': '#4a9a68',
        'accent_alt': '#5aae7a',
        'muted': '#4a684a',
        'surface': '#101913',
        'success': '#6aae52',
        'warning': '#c4a64e',
        'danger': '#c87a5c',
        'font_ui': 'JetBrains Mono NF',
    }

    raw_data = {}
    theme_path = Path.home() / '.config' / 'omarchy' / 'current' / 'theme' / 'colors.toml'
    if tomllib and theme_path.exists():
        try:
            with open(theme_path, 'rb') as f:
                raw_data = tomllib.load(f)
            theme['background'] = raw_data.get('background', theme['background'])
            theme['foreground'] = raw_data.get('foreground', theme['foreground'])
            theme['accent'] = raw_data.get('accent', raw_data.get('color4', theme['accent']))
            theme['accent_alt'] = raw_data.get('color12', theme['accent_alt'])
            theme['muted'] = raw_data.get('color8', theme['muted'])
            theme['surface'] = raw_data.get('color0', theme['surface'])
            theme['success'] = raw_data.get('color2', theme['success'])
            theme['warning'] = raw_data.get('color3', theme['warning'])
            theme['danger'] = raw_data.get('color1', theme['danger'])
        except Exception:
            pass

    # Derive interactive colors — need a color that's visible AND vibrant
    # against the background. Pick the brightest, most saturated option
    # from the palette to use as UI interactive color.
    color4 = raw_data.get('color4', theme['accent'])
    color5 = raw_data.get('color5', raw_data.get('color13', theme['accent_alt']))
    color13 = raw_data.get('color13', color5)
    cursor_color = raw_data.get('cursor', theme['accent'])

    # Collect candidate colors and pick the one with best visibility
    candidates = [
        (theme['accent'], 'accent'),
        (color4, 'color4'),
        (color5, 'color5'),
        (color13, 'color13'),
        (cursor_color, 'cursor'),
    ]

    bg_lum = _luminance(theme['background'])

    def _score(hex_color):
        """Score a color for UI use: needs contrast AND saturation."""
        lum = _luminance(hex_color)
        ratio = _contrast_ratio(lum, bg_lum)
        r, g, b = hex_to_rgb_f(hex_color)
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        sat = (max_c - min_c) / max_c if max_c > 0 else 0
        # Penalize near-white (sat < 0.1) and near-black (max < 0.1)
        if sat < 0.1 or max_c < 0.1:
            return 0
        return ratio * (0.5 + sat)

    candidates.sort(key=lambda c: _score(c[0]), reverse=True)
    best = candidates[0][0]
    second = candidates[1][0] if len(candidates) > 1 else best

    theme['interactive'] = best
    theme['interactive_hover'] = lighten_hex(best, 0.2) if best == second else second
    theme['highlight'] = raw_data.get('selection_background', best)
    theme['surface_elevated'] = lighten_hex(theme['background'], 0.12)
    theme['border'] = theme['foreground']

    # Read font-family from active Omarchy theme CSS.
    font_sources = [
        Path.home() / '.config' / 'omarchy' / 'current' / 'theme' / 'hyprland-preview-share-picker.css',
        Path.home() / '.config' / 'omarchy' / 'current' / 'theme' / 'walker.css',
        Path.home() / '.config' / 'omarchy' / 'current' / 'theme' / 'waybar.css',
    ]
    font_re = re.compile(r'font-family\s*:\s*([^;]+);', re.IGNORECASE)
    for font_path in font_sources:
        if not font_path.exists():
            continue
        try:
            content = font_path.read_text(encoding='utf-8', errors='ignore')
            match = font_re.search(content)
            if match:
                font_decl = match.group(1).strip().replace('!important', '').strip()
                if font_decl:
                    theme['font_ui'] = font_decl
                    break
        except Exception:
            continue

    raw_families = [
        part.strip().strip('"').strip("'")
        for part in theme['font_ui'].split(',')
        if part.strip()
    ]
    fallback_families = ['JetBrains Mono NF', 'monospace', 'Sans']
    chain = []
    for family in raw_families + fallback_families:
        if family and family not in chain:
            chain.append(family)
    theme['font_cairo_chain'] = chain
    theme['font_cairo'] = chain[0] if chain else 'Sans'

    for key in ('background', 'foreground', 'accent', 'accent_alt',
                'muted', 'surface', 'success', 'warning', 'danger',
                'interactive', 'interactive_hover', 'highlight',
                'surface_elevated', 'border'):
        theme[f'{key}_rgb'] = hex_to_rgb_f(theme[key])

    return theme


# ---------------------------------------------------------------------------
# User config (~/.config/circle-to-search/config.toml)
# ---------------------------------------------------------------------------

_USER_CONFIG_PATH = Path.home() / '.config' / 'circle-to-search' / 'config.toml'
_REQUIRED_USER_CONFIG_KEYS = (
    'instant_search',
    'ollama_model',
    'translation_target',
)


def load_user_config():
    if tomllib and _USER_CONFIG_PATH.exists():
        try:
            with open(_USER_CONFIG_PATH, 'rb') as f:
                data = tomllib.load(f)
            cts.USER_CONFIG['instant_search'] = bool(data.get('instant_search', False))
            cts.USER_CONFIG['ollama_model'] = str(
                data.get('ollama_model', cts.USER_CONFIG['ollama_model'])
            )
            cts.USER_CONFIG['translation_target'] = str(
                data.get('translation_target', cts.USER_CONFIG['translation_target'])
            )
        except Exception:
            pass


def save_user_config():
    try:
        _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(f'instant_search = {str(cts.USER_CONFIG["instant_search"]).lower()}\n')
            f.write(f'ollama_model = "{cts.USER_CONFIG["ollama_model"]}"\n')
            f.write(f'translation_target = "{cts.USER_CONFIG["translation_target"]}"\n')
    except Exception:
        pass


def ensure_user_config():
    if not _USER_CONFIG_PATH.exists():
        save_user_config()
        return

    if not tomllib:
        return

    try:
        with open(_USER_CONFIG_PATH, 'rb') as f:
            data = tomllib.load(f)
    except Exception:
        return

    if any(key not in data for key in _REQUIRED_USER_CONFIG_KEYS):
        save_user_config()


# ---------------------------------------------------------------------------
# Cairo font helper
# ---------------------------------------------------------------------------

def set_ui_font(cr, bold=False):
    """Select active Omarchy UI font for Cairo text drawing."""
    weight = 1 if bold else 0
    chain = cts.APP_THEME.get(
        'font_cairo_chain',
        [cts.APP_THEME.get('font_cairo', 'Sans'), 'monospace', 'Sans']
    )
    for family in chain:
        try:
            cr.select_font_face(family, 0, weight)
            return
        except Exception:
            continue
    cr.select_font_face('Sans', 0, weight)


# ---------------------------------------------------------------------------
# GTK CSS from Omarchy palette
# ---------------------------------------------------------------------------

def build_omarchy_gtk_css():
    """Generate GTK 3.0 CSS using active Omarchy palette."""
    t = cts.APP_THEME
    inter = t['interactive']
    inter_hover = t['interactive_hover']
    bg = t['background']
    fg = t['foreground']
    surf = t['surface']
    css = f"""
    * {{
        border: none;
        box-shadow: none;
        outline: none;
        -gtk-outline-radius: 0;
    }}
    window {{
        background: transparent;
    }}
    .panel-shell {{
        background: {css_rgba(bg, 0.96)};
        border: 1px solid {css_rgba(fg, 0.12)};
        border-radius: 6px;
    }}
    .panel-root {{
        background: transparent;
    }}
    .panel-header {{
        background: transparent;
    }}
    label {{
        color: {css_rgba(fg, 0.7)};
        font-family: "{t['font_ui']}", monospace;
        font-size: 11px;
    }}
    label.window-kicker {{
        color: {inter};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    label.window-title {{
        color: {fg};
        font-size: 14px;
        font-weight: 700;
    }}
    label.window-subtitle {{
        color: {css_rgba(fg, 0.45)};
        font-size: 9px;
        font-weight: 400;
        letter-spacing: 0.5px;
    }}
    label.section-kicker {{
        color: {inter};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1.5px;
    }}
    label.hint-label {{
        color: {css_rgba(fg, 0.4)};
        font-size: 9px;
        font-weight: 400;
        letter-spacing: 0.3px;
    }}
    label.option-label {{
        color: {css_rgba(fg, 0.5)};
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.8px;
    }}
    .control-strip {{
        background: transparent;
        padding: 4px 0;
    }}
    combobox, .format-combo {{
        background: {css_rgba(surf, 0.5)};
        color: {css_rgba(fg, 0.7)};
        border: 1px solid {css_rgba(fg, 0.08)};
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 10px;
        font-family: "{t['font_ui']}", monospace;
    }}
    scale {{ padding: 0; }}
    scale trough {{
        background: {css_rgba(surf, 0.6)};
        border-radius: 3px;
        min-height: 4px;
    }}
    scale highlight {{
        background: {css_rgba(inter, 0.5)};
        border-radius: 3px;
    }}
    scale slider {{
        background: {inter};
        border-radius: 50%;
        min-width: 12px;
        min-height: 12px;
    }}
    .close-button {{
        background: transparent;
        color: {css_rgba(fg, 0.3)};
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        padding: 4px 8px;
    }}
    .close-button:hover {{
        color: {css_rgba(t['danger'], 0.8)};
    }}
    button {{
        background: {css_rgba(surf, 0.4)};
        color: {css_rgba(fg, 0.7)};
        border: 1px solid {css_rgba(fg, 0.06)};
        padding: 10px 14px;
        border-radius: 4px;
        font-weight: 500;
        font-size: 11px;
        font-family: "{t['font_ui']}", monospace;
    }}
    button:hover {{
        background: {css_rgba(inter, 0.1)};
        color: {fg};
    }}
    button:active {{
        background: {css_rgba(inter, 0.18)};
    }}
    button.command-button {{
        padding: 10px 14px;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.5px;
    }}
    button.command-primary {{
        background: {css_rgba(inter, 0.12)};
        color: {inter_hover};
        border: 1px solid {css_rgba(inter, 0.2)};
        padding: 11px 16px;
        font-weight: 600;
    }}
    button.command-primary:hover {{
        background: {css_rgba(inter, 0.22)};
        color: {fg};
    }}
    button.command-primary:active {{
        background: {css_rgba(inter, 0.3)};
    }}
    box {{
        background-color: transparent;
    }}
    .preview-area {{
        background: {css_rgba(bg, 0.8)};
        border-radius: 4px;
    }}
    .image-frame {{
        background: transparent;
        border-radius: 4px;
    }}
    .panel-frame {{
        background: transparent;
    }}
    frame {{
        background: transparent;
        border-radius: 4px;
    }}
    scrolledwindow {{
        background: {css_rgba(surf, 0.3)};
        border-radius: 4px;
    }}
    textview {{
        background: {css_rgba(surf, 0.3)};
        color: {fg};
        font-family: "{t['font_ui']}", monospace;
        font-size: 12px;
    }}
    textview text {{
        background: transparent;
        color: {fg};
    }}
    menu {{
        background: {bg};
        border: 1px solid {css_rgba(fg, 0.08)};
        border-radius: 4px;
        padding: 4px;
    }}
    menuitem {{
        color: {css_rgba(fg, 0.7)};
        border-radius: 3px;
        padding: 6px 12px;
    }}
    menuitem:hover {{
        background: {css_rgba(inter, 0.1)};
        color: {fg};
    }}
    menuitem label {{ color: inherit; }}
    popover, popover.background {{
        background: {bg};
        border: 1px solid {css_rgba(fg, 0.08)};
        border-radius: 4px;
    }}
    entry {{
        background: {css_rgba(surf, 0.4)};
        color: {fg};
        border: 1px solid {css_rgba(fg, 0.06)};
        border-radius: 4px;
        padding: 4px 8px;
        caret-color: {inter};
    }}
    entry:focus {{
        border-color: {css_rgba(inter, 0.3)};
    }}
    separator {{
        background: {css_rgba(fg, 0.06)};
        min-height: 1px;
    }}
    tooltip {{
        background: {bg};
        border: 1px solid {css_rgba(fg, 0.08)};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    tooltip label {{
        color: {css_rgba(fg, 0.7)};
        font-size: 10px;
    }}
    """
    return css.encode('utf-8')


# ---------------------------------------------------------------------------
# init() — call once at startup
# ---------------------------------------------------------------------------

def init():
    """Load theme + user config into cts.APP_THEME / cts.USER_CONFIG."""
    cts.APP_THEME = load_omarchy_theme()
    load_user_config()
    ensure_user_config()
