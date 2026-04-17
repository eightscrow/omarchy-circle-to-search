#!/bin/bash
# Circle to Search - Installer
# Omarchy / Hyprland / Arch Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="$HOME/.local/share/circle-to-search"
MANIFEST_FILE="$MANIFEST_DIR/install.manifest"
APP_ENTRY="$SCRIPT_DIR/circle-to-search.py"
HYPR_BINDINGS="$HOME/.config/hypr/bindings.conf"
HYPR_MARKER_START="# >>> circle-to-search >>>"
HYPR_MARKER_END="# <<< circle-to-search <<<"
LEGACY_MARKER_START="# >>> circle-to-search-autobind >>>"
LEGACY_MARKER_END="# <<< circle-to-search-autobind <<<"

DEFAULT_KEY="C"
DEFAULT_MODS="SUPER ALT"
KEYBIND_DISPLAY="${DEFAULT_MODS// /+}+${DEFAULT_KEY}"

WITH_OCR=1
WITH_OLLAMA=0
SKIP_HYPR=0
ASSUME_YES=0
DRY_RUN=0
VERBOSE=0

TMP_FILES=()
LOG_FILE=""
HYPR_CONFIGURED=0
HYPR_BACKUP_FILE=""

CORE_PKGS=(python python-gobject python-pillow gtk3 gtk-layer-shell grim wl-clipboard tesseract tesseract-data-eng python-pytesseract)
OLLAMA_PKGS=(ollama)

_tty() { [[ -t 1 ]]; }
_c() { _tty && printf '%s' "$1" || true; }
BOLD=$(_c $'\033[1m');   RESET=$(_c $'\033[0m')
GREEN=$(_c $'\033[32m'); YELLOW=$(_c $'\033[33m')
RED=$(_c $'\033[31m');   CYAN=$(_c $'\033[36m')
DIM=$(_c $'\033[2m')

ok()   { printf '  %s[OK]%s   %s\n' "$GREEN"  "$RESET" "$*"; }
fail() { printf '  %s[FAIL]%s %s\n' "$RED"    "$RESET" "$*" >&2; }
warn() { printf '  %s[WARN]%s %s\n' "$YELLOW" "$RESET" "$*"; }
info() { printf '  %s[INFO]%s %s\n' "$CYAN"   "$RESET" "$*"; }
skip() { printf '  %s[SKIP]%s %s\n' "$DIM"    "$RESET" "$*"; }
hr()   { printf '%s%s%s\n' "$DIM" "$(printf '%.0s─' {1..72})" "$RESET"; }
section() { printf '\n%s%s%s\n' "$BOLD" "$*" "$RESET"; hr; }
die()  { fail "$*"; exit 1; }

cleanup() {
    local path
    for path in "${TMP_FILES[@]:-}"; do
        [[ -n "$path" && -e "$path" ]] && rm -f "$path"
    done
    [[ -n "$LOG_FILE" && -f "$LOG_FILE" ]] && rm -f "$LOG_FILE"
    return 0
}
trap cleanup EXIT

usage() {
    cat <<EOF
${BOLD}Circle to Search  —  Installer${RESET}

${BOLD}Usage:${RESET} ./install.sh [options]

${BOLD}Options:${RESET}
  --with-ollama     Install Ollama translation support
  --skip-hypr-bind  Skip Hyprland keybinding setup
  --yes             Skip confirmation prompts
  --dry-run         Show plan without making changes
  --verbose         Show full pacman output
  -h, --help        Show this help

${BOLD}Default keybinding:${RESET}
  ${KEYBIND_DISPLAY}

${BOLD}Change it later:${RESET}
  ${HYPR_BINDINGS}

${BOLD}Examples:${RESET}
  ./install.sh
  ./install.sh --with-ollama
  ./install.sh --dry-run

${BOLD}Package safety:${RESET}
    install.sh only installs missing packages
    uninstall.sh only considers packages recorded by install.sh
EOF
}

confirm() {
    local prompt="$1"
    if [[ $ASSUME_YES -eq 1 ]]; then
        return 0
    fi
    printf '\n  %s [Y/n] ' "$prompt"
    read -r reply
    [[ -z "$reply" || "$reply" =~ ^[Yy]$ ]]
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "$1 not found in PATH."
}

new_tempfile() {
    local file
    file=$(mktemp)
    TMP_FILES+=("$file")
    printf '%s\n' "$file"
}

backup_path_for() {
    local path="$1"
    printf '%s.circle-to-search.bak.%s\n' "$path" "$(date +%Y%m%d-%H%M%S)"
}

strip_marker_blocks() {
    local input_file="$1"
    local output_file="$2"
    awk \
        -v s1="$HYPR_MARKER_START" \
        -v e1="$HYPR_MARKER_END" \
        -v s2="$LEGACY_MARKER_START" \
        -v e2="$LEGACY_MARKER_END" '
        $0==s1 {skip=1; next}
        $0==e1 {skip=0; next}
        $0==s2 {skip=1; next}
        $0==e2 {skip=0; next}
        !skip {print}
    ' "$input_file" > "$output_file"
}

read_manifest_value() {
    local key="$1"
    local file="$2"
    [[ -f "$file" ]] || return 0
    awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, "", $0); print; exit}' "$file"
}

merge_recorded_packages() {
    local existing_raw="$1"
    shift
    local merged=()
    local seen=""
    local pkg
    local existing_pkgs=()
    [[ -n "${existing_raw// /}" ]] && read -ra existing_pkgs <<< "$existing_raw"

    for pkg in "${existing_pkgs[@]}" "$@"; do
        [[ -z "$pkg" ]] && continue
        if [[ " $seen " != *" $pkg "* ]]; then
            merged+=("$pkg")
            seen+=" $pkg"
        fi
    done

    printf '%s\n' "${merged[*]:-}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-ollama)    WITH_OLLAMA=1 ;;
        --skip-hypr-bind) SKIP_HYPR=1 ;;
        --yes)            ASSUME_YES=1 ;;
        --dry-run)        DRY_RUN=1 ;;
        --verbose)        VERBOSE=1 ;;
        -h|--help)        usage; exit 0 ;;
        *) die "Unknown option: $1 (run with --help)" ;;
    esac
    shift
done

TARGET_PKGS=("${CORE_PKGS[@]}")
[[ $WITH_OLLAMA -eq 1 ]] && TARGET_PKGS+=("${OLLAMA_PKGS[@]}")

printf '\n%s  Circle to Search  —  Installer%s\n' "$BOLD" "$RESET"
hr

section "1/6  Preflight"
require_cmd pacman
require_cmd python3
[[ -f "$APP_ENTRY" ]] || die "circle-to-search.py not found in: $SCRIPT_DIR"
ok "Arch Linux detected"
ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
ok "circle-to-search.py found"

section "2/6  Keybinding"
if [[ $SKIP_HYPR -eq 1 ]]; then
    skip "Skipped (--skip-hypr-bind)"
else
    ok "Default keybinding: ${KEYBIND_DISPLAY}"
    info "Managed file: $HYPR_BINDINGS"
    info "Change it later by editing the managed Circle to Search block in that file"
fi

section "3/6  Install plan"
printf '  %-22s %s\n' "Source directory"    "$SCRIPT_DIR"
printf '  %-22s %s\n' "OCR support"         "included"
printf '  %-22s %s\n' "Ollama translate"    "$([[ $WITH_OLLAMA -eq 1 ]] && echo enabled || echo disabled)"
printf '  %-22s %s\n' "Hyprland keybinding" "$([[ $SKIP_HYPR -eq 1 ]] && echo skip || echo "$KEYBIND_DISPLAY")"
printf '  %-22s %s\n' "Dry run"             "$([[ $DRY_RUN -eq 1 ]] && echo yes || echo no)"

MISSING_PKGS=()
PRESENT_PKGS=()
for pkg in "${TARGET_PKGS[@]}"; do
    if pacman -Q "$pkg" >/dev/null 2>&1; then
        PRESENT_PKGS+=("$pkg")
    else
        MISSING_PKGS+=("$pkg")
    fi
done

printf '\n  Packages already installed: '
if [[ ${#PRESENT_PKGS[@]} -eq 0 ]]; then
    printf 'none\n'
else
    printf '%s\n' "${PRESENT_PKGS[*]}"
fi

printf '  Packages to install:        '
if [[ ${#MISSING_PKGS[@]} -eq 0 ]]; then
    printf 'none\n'
else
    printf '%s\n' "${MISSING_PKGS[*]}"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    printf '\n'
    info "Dry run — no changes made."
    printf '\n'
    exit 0
fi

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    confirm "Install ${#MISSING_PKGS[@]} package(s) via pacman?" || die "Aborted by user."
fi

section "4/6  Dependencies"
if [[ ${#MISSING_PKGS[@]} -eq 0 ]]; then
    ok "All dependencies already installed"
else
    info "Requesting sudo for pacman..."
    sudo -v || die "sudo authentication failed"

    if [[ $VERBOSE -eq 1 ]]; then
        sudo pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
    else
        LOG_FILE="/tmp/circle-to-search-install-$$.log"
        if ! sudo pacman -S --needed --noconfirm --noprogressbar "${MISSING_PKGS[@]}" >"$LOG_FILE" 2>&1; then
            fail "pacman failed. Tail of log:"
            tail -n 20 "$LOG_FILE" >&2
            die "Full log: $LOG_FILE"
        fi
        rm -f "$LOG_FILE"
        LOG_FILE=""
    fi
    ok "Installed: ${MISSING_PKGS[*]}"
fi

section "5/6  Validation"
python3 - <<'PY'
import importlib.util
import sys

required = {"gi": "python-gobject", "PIL": "python-pillow"}
optional = {"pytesseract": "python-pytesseract"}

missing = [label for mod, label in required.items() if importlib.util.find_spec(mod) is None]
if missing:
    print(f"  [FAIL] Missing required Python modules: {', '.join(missing)}")
    sys.exit(1)

print("  [OK]   Python modules: gi, PIL")

absent = [label for mod, label in optional.items() if importlib.util.find_spec(mod) is None]
if absent:
    print(f"  [INFO] Optional modules absent: {', '.join(absent)}")
else:
    print("  [OK]   Optional modules: pytesseract")
PY

for tool in grim wl-copy hyprctl; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "$tool found"
    else
        warn "$tool not found — runtime may be incomplete"
    fi
done

if command -v omarchy-launch-browser >/dev/null 2>&1; then
    ok "omarchy-launch-browser found"
elif command -v xdg-open >/dev/null 2>&1; then
    ok "xdg-open found"
else
    warn "No browser launcher found — URL opening may not work"
fi

if command -v notify-send >/dev/null 2>&1; then
    ok "notify-send found"
else
    warn "notify-send not found — desktop notifications disabled"
fi

if python3 "$APP_ENTRY" --help >/dev/null 2>&1; then
    ok "Application starts cleanly"
else
    warn "Application --help check failed (non-fatal)"
fi

section "6/6  Hyprland keybinding"
if [[ $SKIP_HYPR -eq 1 ]]; then
    skip "Skipped (--skip-hypr-bind)"
else
    mkdir -p "$(dirname "$HYPR_BINDINGS")"
    [[ -f "$HYPR_BINDINGS" ]] || touch "$HYPR_BINDINGS"

    HYPR_BACKUP_FILE="$(backup_path_for "$HYPR_BINDINGS")"
    cp "$HYPR_BINDINGS" "$HYPR_BACKUP_FILE"

    local_tmp="$(new_tempfile)"
    strip_marker_blocks "$HYPR_BINDINGS" "$local_tmp"

    cat >>"$local_tmp" <<EOF

$HYPR_MARKER_START
unbind = ${DEFAULT_MODS}, ${DEFAULT_KEY}
bindd = ${DEFAULT_MODS}, ${DEFAULT_KEY}, Circle to Search, exec, $APP_ENTRY
$HYPR_MARKER_END
EOF

    mv "$local_tmp" "$HYPR_BINDINGS"
    HYPR_CONFIGURED=1
    ok "Keybinding block written"
    info "Bindings file: $HYPR_BINDINGS"
    info "Backup:        $HYPR_BACKUP_FILE"

    if hyprctl reload >/dev/null 2>&1; then
        ok "Hyprland reloaded"
    else
        warn "hyprctl reload failed — reload manually"
    fi
fi

section "Manifest"
mkdir -p "$MANIFEST_DIR"
PREVIOUS_INSTALLED="$(read_manifest_value INSTALLED_PKGS "$MANIFEST_FILE")"
RECORDED_PKGS="$(merge_recorded_packages "$PREVIOUS_INSTALLED" "${MISSING_PKGS[@]}")"
cat >"$MANIFEST_FILE" <<EOF
# Circle to Search install manifest
# Generated: $(date -Iseconds)
SCRIPT_DIR="$SCRIPT_DIR"
APP_ENTRY="$APP_ENTRY"
HYPR_CONFIGURED=$HYPR_CONFIGURED
HYPR_BINDINGS="$HYPR_BINDINGS"
BIND_MODS="$DEFAULT_MODS"
BIND_KEY=$DEFAULT_KEY
WITH_OCR=$WITH_OCR
WITH_OLLAMA=$WITH_OLLAMA
INSTALLED_PKGS="$RECORDED_PKGS"
HYPR_BACKUP_FILE="$HYPR_BACKUP_FILE"
EOF
ok "Manifest written: $MANIFEST_FILE"

hr
printf '\n  %sInstallation complete.%s\n\n' "$GREEN$BOLD" "$RESET"
printf '  %-16s %s\n' "Run" "$APP_ENTRY"
if [[ $SKIP_HYPR -eq 0 ]]; then
    printf '  %-16s %s\n' "Keybinding" "$KEYBIND_DISPLAY"
    printf '  %-16s %s\n' "Change bind" "$HYPR_BINDINGS"
fi
printf '  %-16s %s\n' "Uninstall" "./uninstall.sh"
printf '\n'
