# Circle to Search

**Android-style freehand screen capture for Omarchy / Hyprland**

[![AUR](https://img.shields.io/aur/version/omarchy-circle-to-search)](https://aur.archlinux.org/packages/omarchy-circle-to-search)
[![License](https://img.shields.io/github/license/eightscrow/omarchy-circle-to-search)](LICENSE)

Draw around anything on screen. Search it, read it, translate it.

<p>
  <img src="pic/screenshot-2026-04-21_09-42-02.png" width="49%" alt="Animated glow selection with warm gradient">
  <img src="pic/capture-preview.png" width="49%" alt="Capture result dialog">
</p>

<details>
<summary>More screenshots</summary>
<br>

<p>
  <img src="pic/screenshot-2026-04-21_09-42-32.png" width="49%" alt="Animated glow selection in blue theme">
  <img src="pic/capture-preview-blue.png" width="49%" alt="Capture dialog in blue theme">
</p>

<p>
  <img src="pic/ocr-result.png" width="49%" alt="OCR result dialog">
  <img src="pic/selection-ocr.png" width="49%" alt="OCR selection flow">
</p>

<p>
  <img src="pic/overlay-full.png" width="49%" alt="Full overlay on desktop">
  <img src="pic/overlay-help.png" width="49%" alt="Overlay with help card">
</p>

<p>
  <img src="pic/drawing-selection.png" width="49%" alt="Drawing a selection">
  <img src="pic/help-card.png" width="49%" alt="Help card">
</p>

</details>

---

## Features

- **Animated glow selection** — draw a freehand region with a theme-aware gradient glow
- **Google Lens search** — send your selection to Google Lens instantly
- **OCR text extraction** — pull text from any region with Tesseract
- **Translate** — Google Translate or local Ollama model, your choice
- **Multi-monitor** — supports mixed-DPI and fractional scaling
- **Smart theming** — auto-uses Omarchy theme if present, with simple user overrides for any Hyprland setup

## Install

### AUR (recommended)

```bash
yay -S omarchy-circle-to-search
```

Then add keybinds to `~/.config/hypr/bindings.conf`:

```
bind = SUPER ALT, C, exec, circle-to-search
bind = SUPER ALT, T, exec, circle-to-search --translate
```

Works on any Hyprland setup. On Omarchy, current theme colors are used automatically.

### Manual

```bash
./install.sh                # base install
./install.sh --with-ollama  # with local translation
```

The installer handles packages, keybinds, and reload.

## Usage

| Key | Action |
|-----|--------|
| Draw + release | Capture selected region |
| `Enter` | Capture full screen |
| `M` | Toggle Instant Search |
| `T` | Toggle Select & Translate |
| `Esc` | Exit |

### Translate mode

| Key | Action |
|-----|--------|
| Draw box | Add translation region |
| Scroll on region | Change font size |
| `C` | Clear all regions |
| `Z` | Undo last region |
| `Esc` | Exit translate mode |

### Dialogs

| Key | Action |
|-----|--------|
| `1` / `Enter` | Primary action |
| `2` | Secondary action |
| `3` | Third action |
| `Esc` | Cancel |

## Ollama (optional)

Local translation with no cloud dependency. Not included in the AUR package — install separately:

```bash
sudo pacman -S ollama
ollama serve
ollama pull qwen2.5:7b
```

Any Ollama model works — just pull the one you prefer and set it in the config.

Then press `T` in the menu overlay to use Select & Translate.

Configure in `~/.config/circle-to-search/config.toml`:

```toml
ollama_model = "qwen2.5:7b"       # any Ollama model
translation_target = "English"     # any language
```

## Theming

### Theming for non-Omarchy setups is still under development, and might not work on every system. 
I have plans to test it on some preconfigured dotfiles like Jakoolit and ML4W

### How it works

On every launch, colors are loaded in this priority order (highest to lowest):

1. `~/.config/circle-to-search/colors.css` — your manual overrides (only keys you set)
2. `~/.config/circle-to-search/theme.toml` — your manual overrides (only keys you set)
3. Omarchy `~/.config/omarchy/current/theme/colors.toml` — active Omarchy theme
4. pywal `~/.cache/wal/colors.json` — if no Omarchy theme is present
5. Built-in fallback palette (Tokyo Night)

All three user config files are created automatically on first run if they do not exist.

### Color roles

| Key | What it affects |
|-----|-----------------|
| `background` | Overlay and dialog background |
| `foreground` | Primary text color |
| `accent` | Glow stroke, selection ring, button highlights |
| `accent_alt` | Secondary glow layer, alternate highlights |
| `muted` | Dimmed text, inactive elements |
| `surface` | Card and panel backgrounds |
| `success` | Confirmation indicators |
| `warning` | Warning indicators |
| `danger` | Error indicators, delete actions |
| `interactive` | Focused button, active control — auto-picked for best contrast |
| `interactive_hover` | Hover state of interactive elements |
| `highlight` | Text selection highlight |
| `font_ui` | Font family for all dialog text |

### Omarchy (automatic)

Nothing to do. If Omarchy is installed and a theme is active, Circle to Search picks up
`~/.config/omarchy/current/theme/colors.toml` automatically. Switching Omarchy themes
updates the overlay on next launch.

This is the default path for Omarchy users.

### Manual color override

Edit `~/.config/circle-to-search/colors.css` — only set the values you want to change.
Unset keys continue to come from Omarchy or pywal.

```css
:root {
  --cts-accent: #ff6e6e;
  --cts-background: #1a1b26;
  --cts-foreground: #a9b1d6;
}
```

All available CSS variables follow the `--cts-<key>` pattern, where `<key>` matches
the color role names in the table above (e.g. `--cts-accent-alt`, `--cts-surface`).

Alternatively, edit `~/.config/circle-to-search/theme.toml` — TOML format, same keys:

```toml
accent = "#ff6e6e"
background = "#1a1b26"
```

`colors.css` and `theme.toml` both override Omarchy and pywal. Changes are picked up on
the next Circle to Search launch.

### GTK widget style

For advanced GTK overrides (fonts, button sizes, dialog borders), edit:

`~/.config/circle-to-search/custom.css`

This is standard GTK 3 CSS applied on top of the built-in stylesheet. Leave empty to use defaults.

### pywal (non-Omarchy setups)

Run pywal normally:

```bash
wal -i /path/to/wallpaper
```

When no Omarchy theme is present, Circle to Search reads pywal's default JSON export
at `~/.cache/wal/colors.json` automatically. No extra configuration needed.

If you use a non-default pywal cache location, use `theme.toml` or `colors.css`
instead, because Circle to Search currently reads only that default pywal path.

### matugen (non-Omarchy setups)

matugen can generate `theme.toml` from a template. One simple setup is:

Create `~/.config/matugen/templates/circle-to-search.toml`:

```toml
background = "{{colors.background.default.hex}}"
foreground = "{{colors.on_background.default.hex}}"
accent = "{{colors.primary.default.hex}}"
accent_alt = "{{colors.secondary.default.hex}}"
muted = "{{colors.surface_variant.default.hex}}"
surface = "{{colors.surface.default.hex}}"
success = "{{colors.tertiary.default.hex}}"
warning = "{{colors.secondary.default.hex}}"
danger = "{{colors.error.default.hex}}"
interactive = "{{colors.primary.default.hex}}"
interactive_hover = "{{colors.tertiary.default.hex}}"
font_ui = "JetBrains Mono NF"
```

Register the template in `~/.config/matugen/config.toml`:

```toml
[templates.circle_to_search]
input_path = "~/.config/matugen/templates/circle-to-search.toml"
output_path = "~/.config/circle-to-search/theme.toml"
```

After you run matugen, for example:

```bash
matugen image /path/to/wallpaper
```

the generated `theme.toml` is picked up automatically on the next launch.

## Uninstall

```bash
# AUR
sudo pacman -R omarchy-circle-to-search

# Manual
./uninstall.sh
./uninstall.sh --remove-packages  # also remove dependencies
```

## Tech

Python -- GTK 3 / PyGObject -- GTK Layer Shell -- Pillow -- grim -- Tesseract OCR

## Security / Privacy

- OCR runs locally with Tesseract
- Ollama translation runs locally over `localhost`
- Google Lens and Google Translate send data to external services
- Installer and uninstaller only touch recorded app state and packages

## Requirements

- Hyprland

Supported architectures: `x86_64`, `aarch64`

Installed by default:

- `python`
- `python-cairo`
- `python-gobject`
- `python-pillow`
- `gtk3`
- `gtk-layer-shell`
- `grim`
- `wl-clipboard`
- `tesseract`
- `tesseract-data-eng`
- `python-pytesseract`

Optional:

- `ollama`


Started from the original idea and early codebase in [jaslrobinson/circle-to-search](https://github.com/jaslrobinson/circle-to-search).

This version has since been extensively rewritten with a different product focus on mind.

## License

MIT -- see [LICENSE](LICENSE)

