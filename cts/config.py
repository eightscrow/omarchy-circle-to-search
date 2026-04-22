"""Theme loading, user configuration, CSS generation."""

import json
import re
import sys
from pathlib import Path

import cts

try:
    import tomllib
except ImportError:
    tomllib = None


_DEFAULT_THEME = {
    'background': '#1a1b26',
    'foreground': '#a9b1d6',
    'accent': '#7aa2f7',
    'accent_alt': '#7da6ff',
    'muted': '#444b6a',
    'surface': '#32344a',
    'success': '#9ece6a',
    'warning': '#e0af68',
    'danger': '#f7768e',
}

_HEX_COLOR_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


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


def _normalize_hex_color(value, fallback, key_name=None, source=None, invalid_entries=None):
    """Return a normalized #RRGGBB value or fallback when invalid."""
    raw_value = '' if value is None else str(value)
    text = raw_value.strip().strip('"').strip("'")
    if not _HEX_COLOR_RE.fullmatch(text):
        if invalid_entries is not None and key_name:
            invalid_entries.append({
                'key': key_name,
                'source': source or 'unknown',
                'value': raw_value,
                'fallback': fallback,
            })
        return fallback
    if len(text) == 4:
        text = '#' + ''.join(ch * 2 for ch in text[1:])
    return text.lower()


# ---------------------------------------------------------------------------
# Theme loading
# ---------------------------------------------------------------------------

def _read_toml(path):
    """Read TOML file safely. Returns empty dict on error."""
    if not tomllib or not path.exists():
        return {}
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _read_json(path):
    """Read JSON file safely. Returns empty dict on error."""
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _read_css_vars(path):
    """Read CSS custom properties from file into {name: value}."""
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return {}

    # Drop /* ... */ comments so example lines do not become active overrides.
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    vars_map = {}
    for name, value in re.findall(r'--cts-([a-z0-9-]+)\s*:\s*([^;]+);', content, re.IGNORECASE):
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            vars_map[name.lower()] = cleaned
    return vars_map


def load_theme():
    """Load theme with priority: css/toml override -> Omarchy -> Matugen -> pywal -> built-in defaults."""
    theme: dict[str, object] = dict(_DEFAULT_THEME)
    theme['font_ui'] = 'JetBrains Mono NF'
    invalid_theme_colors = []

    # 1) Omarchy colors (if available)
    omarchy_raw = _read_toml(Path.home() / '.config' / 'omarchy' / 'current' / 'theme' / 'colors.toml')
    if omarchy_raw:
        theme['background'] = omarchy_raw.get('background', theme['background'])
        theme['foreground'] = omarchy_raw.get('foreground', theme['foreground'])
        theme['accent'] = omarchy_raw.get('accent', omarchy_raw.get('color4', theme['accent']))
        theme['accent_alt'] = omarchy_raw.get('color12', theme['accent_alt'])
        theme['muted'] = omarchy_raw.get('color8', theme['muted'])
        theme['surface'] = omarchy_raw.get('color0', theme['surface'])
        theme['success'] = omarchy_raw.get('color2', theme['success'])
        theme['warning'] = omarchy_raw.get('color3', theme['warning'])
        theme['danger'] = omarchy_raw.get('color1', theme['danger'])

    # 2) Matugen colors (ML4W and other Matugen-based setups)
    matugen_raw = _read_json(Path.home() / '.config' / 'ml4w' / 'colors' / 'colors.json')
    if not matugen_raw:
        matugen_raw = _read_json(Path.home() / '.local' / 'share' / 'ml4w-dotfiles-settings' / 'colors' / 'colors.json')

    if (not omarchy_raw) and matugen_raw:
        theme['background'] = matugen_raw.get('background', theme['background'])
        theme['foreground'] = matugen_raw.get('on_background', matugen_raw.get('on_surface', theme['foreground']))
        theme['accent'] = matugen_raw.get('primary', theme['accent'])
        theme['accent_alt'] = matugen_raw.get('secondary', theme['accent_alt'])
        theme['muted'] = matugen_raw.get('surface_variant', matugen_raw.get('outline', theme['muted']))
        theme['surface'] = matugen_raw.get('surface', theme['surface'])
        theme['success'] = matugen_raw.get('tertiary', theme['success'])
        theme['warning'] = matugen_raw.get('secondary_container', theme['warning'])
        theme['danger'] = matugen_raw.get('error', theme['danger'])

    # 3) pywal colors (if Omarchy/Matugen theme is not available)
    pywal_raw = _read_json(Path.home() / '.cache' / 'wal' / 'colors.json')
    pywal_special = pywal_raw.get('special', {}) if isinstance(pywal_raw, dict) else {}
    pywal_colors = pywal_raw.get('colors', {}) if isinstance(pywal_raw, dict) else {}
    if (not omarchy_raw) and (not matugen_raw) and pywal_colors:
        theme['background'] = pywal_special.get('background', theme['background'])
        theme['foreground'] = pywal_special.get('foreground', theme['foreground'])
        theme['accent'] = pywal_colors.get('color4', theme['accent'])
        theme['accent_alt'] = pywal_colors.get('color12', theme['accent_alt'])
        theme['muted'] = pywal_colors.get('color8', theme['muted'])
        theme['surface'] = pywal_colors.get('color0', theme['surface'])
        theme['success'] = pywal_colors.get('color2', theme['success'])
        theme['warning'] = pywal_colors.get('color3', theme['warning'])
        theme['danger'] = pywal_colors.get('color1', theme['danger'])

    # 4) User overrides for any Hyprland setup (theme.toml + colors.css)
    user_theme = _read_toml(_THEME_CONFIG_PATH)
    css_vars = _read_css_vars(_COLORS_CSS_PATH)
    css_to_theme = {
        'background': 'background',
        'foreground': 'foreground',
        'accent': 'accent',
        'accent-alt': 'accent_alt',
        'muted': 'muted',
        'surface': 'surface',
        'success': 'success',
        'warning': 'warning',
        'danger': 'danger',
        'interactive': 'interactive',
        'interactive-hover': 'interactive_hover',
        'highlight': 'highlight',
        'font-ui': 'font_ui',
    }

    overrides = {}
    for key in ('background', 'foreground', 'accent', 'accent_alt',
                'muted', 'surface', 'success', 'warning', 'danger',
                'interactive', 'interactive_hover', 'highlight', 'font_ui'):
        if key in user_theme:
            overrides[key] = str(user_theme[key])

    for css_name, raw_value in css_vars.items():
        theme_key = css_to_theme.get(css_name)
        if theme_key:
            overrides[theme_key] = raw_value

    for key in ('background', 'foreground', 'accent', 'accent_alt',
                'muted', 'surface', 'success', 'warning', 'danger', 'font_ui'):
        if key in overrides:
            theme[key] = overrides[key]

    for key in ('background', 'foreground', 'accent', 'accent_alt',
                'muted', 'surface', 'success', 'warning', 'danger'):
        theme[key] = _normalize_hex_color(
            theme.get(key),
            _DEFAULT_THEME[key],
            key_name=key,
            source='resolved_theme',
            invalid_entries=invalid_theme_colors,
        )

    # Derive interactive colors — need a color that's visible AND vibrant
    # against the background. Pick the brightest, most saturated option
    # from the palette to use as UI interactive color.
    color4 = _normalize_hex_color(
        omarchy_raw.get('color4', pywal_colors.get('color4', theme['accent'])),
        theme['accent'],
        key_name='color4',
        source='palette_candidate',
        invalid_entries=invalid_theme_colors,
    )
    color5 = _normalize_hex_color(
        omarchy_raw.get('color5', omarchy_raw.get('color13', pywal_colors.get('color5', theme['accent_alt']))),
        theme['accent_alt'],
        key_name='color5',
        source='palette_candidate',
        invalid_entries=invalid_theme_colors,
    )
    color13 = _normalize_hex_color(
        omarchy_raw.get('color13', pywal_colors.get('color13', color5)),
        color5,
        key_name='color13',
        source='palette_candidate',
        invalid_entries=invalid_theme_colors,
    )
    cursor_color = _normalize_hex_color(
        omarchy_raw.get('cursor', pywal_special.get('cursor', theme['accent'])),
        theme['accent'],
        key_name='cursor',
        source='palette_candidate',
        invalid_entries=invalid_theme_colors,
    )

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

    interactive_override = ''
    if 'interactive' in overrides:
        interactive_override = _normalize_hex_color(
            overrides.get('interactive'),
            '',
            key_name='interactive',
            source='user_override',
            invalid_entries=invalid_theme_colors,
        )

    hover_override = ''
    if 'interactive_hover' in overrides:
        hover_override = _normalize_hex_color(
            overrides.get('interactive_hover'),
            '',
            key_name='interactive_hover',
            source='user_override',
            invalid_entries=invalid_theme_colors,
        )

    theme['interactive'] = interactive_override if interactive_override else best
    if hover_override:
        theme['interactive_hover'] = hover_override
    else:
        theme['interactive_hover'] = lighten_hex(theme['interactive'], 0.2) if best == second else second
    theme['highlight'] = _normalize_hex_color(
        overrides.get('highlight', omarchy_raw.get('selection_background', pywal_colors.get('color4', best))),
        best,
        key_name='highlight',
        source='resolved_theme',
        invalid_entries=invalid_theme_colors,
    )
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
        for part in str(theme['font_ui']).split(',')
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
        theme[f'{key}_rgb'] = hex_to_rgb_f(str(theme[key]))

    if invalid_theme_colors:
        print(
            '[circle-to-search] Warning: invalid color values detected; using safe fallbacks.',
            file=sys.stderr,
        )
        seen = set()
        for entry in invalid_theme_colors:
            signature = (entry['source'], entry['key'], entry['value'], entry['fallback'])
            if signature in seen:
                continue
            seen.add(signature)
            print(
                f"[circle-to-search]   {entry['source']}.{entry['key']}: {entry['value']!r} -> {entry['fallback']}",
                file=sys.stderr,
            )

    return theme


def load_omarchy_theme():
    """Backward compatible alias for older imports."""
    return load_theme()


# ---------------------------------------------------------------------------
# User config (~/.config/circle-to-search/config.toml)
# ---------------------------------------------------------------------------

_USER_CONFIG_PATH = Path.home() / '.config' / 'circle-to-search' / 'config.toml'
_THEME_CONFIG_PATH = Path.home() / '.config' / 'circle-to-search' / 'theme.toml'
_COLORS_CSS_PATH = Path.home() / '.config' / 'circle-to-search' / 'colors.css'
_CUSTOM_CSS_PATH = Path.home() / '.config' / 'circle-to-search' / 'custom.css'
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


def ensure_theme_templates():
    """Create editable theme files if missing."""
    _THEME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not _THEME_CONFIG_PATH.exists():
        _THEME_CONFIG_PATH.write_text(
            """# Circle to Search theme override
# Leave empty to follow active system theme (Omarchy colors.toml when available).
# Uncomment only keys you want to force.

# accent = "#7aa2f7"
# background = "#1a1b26"
# foreground = "#a9b1d6"
# font_ui = "JetBrains Mono NF"
""",
            encoding='utf-8',
        )

    if not _CUSTOM_CSS_PATH.exists():
        _CUSTOM_CSS_PATH.write_text(
            """/* Circle to Search custom CSS */
/* Leave rules commented until you want to test one. */
/* This file is loaded on top of the built-in GTK 3 stylesheet. */

/* Quick test ideas:
 * 1. Uncomment one block.
 * 2. Launch circle-to-search again.
 * 3. If you do not like result, comment it back out.
 */

/* Slightly rounder panels */
/*
.panel-shell {
    border-radius: 14px;
}
*/

/* Stronger panel border */
/*
.panel-shell {
    border: 2px solid rgba(122, 162, 247, 0.35);
}
*/

/* Bigger title text */
/*
label.window-title {
    font-size: 16px;
}
*/

/* Brighter buttons */
/*
button {
    border-radius: 10px;
    padding: 8px 12px;
}

button:hover {
    background: rgba(122, 162, 247, 0.18);
}
*/

/* Monospace tweak example */
/*
label,
button,
entry,
combobox {
    font-family: "JetBrains Mono NF", monospace;
}
*/
""",
            encoding='utf-8',
        )

    if not _COLORS_CSS_PATH.exists():
        _COLORS_CSS_PATH.write_text(
            """/* Circle to Search color overrides (optional) */
/* Uncomment any values you want to force. */

:root {
    /* --cts-background: #1a1b26; */
    /* --cts-foreground: #a9b1d6; */
    /* --cts-accent: #7aa2f7; */
    /* --cts-accent-alt: #7da6ff; */
    /* --cts-muted: #444b6a; */
    /* --cts-surface: #32344a; */
    /* --cts-success: #9ece6a; */
    /* --cts-warning: #e0af68; */
    /* --cts-danger: #f7768e; */
    /* --cts-interactive: #7aa2f7; */
    /* --cts-interactive-hover: #bb9af7; */
    /* --cts-highlight: #7aa2f7; */
    /* --cts-font-ui: JetBrains Mono NF; */
}
""",
            encoding='utf-8',
        )


# ---------------------------------------------------------------------------
# Cairo font helper
# ---------------------------------------------------------------------------

def set_ui_font(cr, bold=False):
    """Select active UI font for Cairo text drawing."""
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
# GTK CSS from active palette
# ---------------------------------------------------------------------------

def build_gtk_css():
    """Generate GTK 3.0 CSS using active palette plus optional custom.css."""
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
    if _CUSTOM_CSS_PATH.exists():
        try:
            css += "\n\n/* user custom.css */\n" + _CUSTOM_CSS_PATH.read_text(encoding='utf-8')
        except Exception:
            pass

    return css.encode('utf-8')


def build_omarchy_gtk_css():
    """Backward compatible alias for older imports."""
    return build_gtk_css()


# ---------------------------------------------------------------------------
# init() — call once at startup
# ---------------------------------------------------------------------------

def init():
    """Load theme + user config into cts.APP_THEME / cts.USER_CONFIG."""
    cts.APP_THEME = load_theme()
    load_user_config()
    ensure_user_config()
    ensure_theme_templates()
