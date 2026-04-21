#!/bin/bash
# Circle to Search - Uninstaller
set -euo pipefail

MANIFEST_DIR="$HOME/.local/share/circle-to-search"
MANIFEST_FILE="$MANIFEST_DIR/install.manifest"
HYPR_MARKER_START="# >>> circle-to-search >>>"
HYPR_MARKER_END="# <<< circle-to-search <<<"
LEGACY_MARKER_START="# >>> circle-to-search-autobind >>>"
LEGACY_MARKER_END="# <<< circle-to-search-autobind <<<"

ASSUME_YES=0
DRY_RUN=0
REMOVE_PACKAGES=0
TMP_FILES=()
AVAILABLE_RECORDED_PKGS=()
REMOVABLE_PKGS=()
PROTECTED_PKGS=()
PROTECTED_REASONS=()
KEEP_MANIFEST=0
KEEP_MANIFEST_REASON=""

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
    return 0
}
trap cleanup EXIT

usage() {
    cat <<EOF
${BOLD}Circle to Search  —  Uninstaller${RESET}

${BOLD}Usage:${RESET} ./uninstall.sh [options]

${BOLD}Options:${RESET}
  --remove-packages  Also remove packages recorded as installed by install.sh
  --yes              Skip confirmation prompts
  --dry-run          Show plan, make no changes
  -h, --help         Show this help
EOF
}

confirm() {
    local prompt="$1"
    if [[ $ASSUME_YES -eq 1 ]]; then
        return 0
    fi
    printf '\n  %s [y/N] ' "$prompt"
    read -r reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

new_tempfile() {
    local file
    file=$(mktemp)
    TMP_FILES+=("$file")
    printf '%s\n' "$file"
}

contains_word() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

join_by() {
    local separator="$1"
    shift
    local first=1
    local item
    for item in "$@"; do
        if [[ $first -eq 1 ]]; then
            printf '%s' "$item"
            first=0
        else
            printf '%s%s' "$separator" "$item"
        fi
    done
}

pacman_field_words() {
    local field="$1"
    local pkg="$2"
    pacman -Qi "$pkg" 2>/dev/null | awk -v field="$field" '
        BEGIN { capture=0 }
        $0 ~ "^" field "[[:space:]]*:" {
            line=$0
            sub("^[^:]*:[[:space:]]*", "", line)
            if (line != "None") {
                printf "%s", line
            }
            capture=1
            next
        }
        capture && /^[[:space:]]/ {
            line=$0
            gsub(/^[[:space:]]+/, "", line)
            if (line != "None") {
                printf " %s", line
            }
            next
        }
        capture { exit }
        END { print "" }
    '
}

analyze_recorded_packages() {
    AVAILABLE_RECORDED_PKGS=()
    REMOVABLE_PKGS=()
    PROTECTED_PKGS=()
    PROTECTED_REASONS=()

    [[ -z "${INSTALLED_PKGS// /}" ]] && return 0

    local pkg
    local required_raw
    local optional_raw
    local reason_parts
    local required_item
    local optional_item
    local external_required=()
    local external_optional=()
    local recorded_pkgs=()

    read -ra recorded_pkgs <<< "$INSTALLED_PKGS"
    for pkg in "${recorded_pkgs[@]}"; do
        if pacman -Q "$pkg" >/dev/null 2>&1; then
            AVAILABLE_RECORDED_PKGS+=("$pkg")
        fi
    done

    for pkg in "${AVAILABLE_RECORDED_PKGS[@]}"; do
        external_required=()
        external_optional=()

        required_raw="$(pacman_field_words "Required By" "$pkg")"
        optional_raw="$(pacman_field_words "Optional For" "$pkg")"

        if [[ -n "${required_raw// /}" ]]; then
            read -ra required_items <<< "$required_raw"
            for required_item in "${required_items[@]}"; do
                [[ "$required_item" == "None" ]] && continue
                if ! contains_word "$required_item" "${AVAILABLE_RECORDED_PKGS[@]}"; then
                    external_required+=("$required_item")
                fi
            done
        fi

        if [[ -n "${optional_raw// /}" ]]; then
            read -ra optional_items <<< "$optional_raw"
            for optional_item in "${optional_items[@]}"; do
                [[ "$optional_item" == "None" ]] && continue
                if ! contains_word "$optional_item" "${AVAILABLE_RECORDED_PKGS[@]}"; then
                    external_optional+=("$optional_item")
                fi
            done
        fi

        reason_parts=()
        if [[ ${#external_required[@]} -gt 0 ]]; then
            reason_parts+=("required by $(join_by ', ' "${external_required[@]}")")
        fi
        if [[ ${#external_optional[@]} -gt 0 ]]; then
            reason_parts+=("optional for $(join_by ', ' "${external_optional[@]}")")
        fi

        if [[ ${#reason_parts[@]} -gt 0 ]]; then
            PROTECTED_PKGS+=("$pkg")
            PROTECTED_REASONS+=("$(join_by '; ' "${reason_parts[@]}")")
        else
            REMOVABLE_PKGS+=("$pkg")
        fi
    done
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remove-packages) REMOVE_PACKAGES=1 ;;
        --yes)             ASSUME_YES=1 ;;
        --dry-run)         DRY_RUN=1 ;;
        -h|--help)         usage; exit 0 ;;
        *) die "Unknown option: $1 (run with --help)" ;;
    esac
    shift
done

printf '\n%s  Circle to Search  —  Uninstaller%s\n' "$BOLD" "$RESET"
hr

section "1/4  Manifest"
if [[ ! -f "$MANIFEST_FILE" ]]; then
    warn "Install manifest not found"
    info "Expected: $MANIFEST_FILE"
    printf '\n'
    info "Manual cleanup if needed:"
    info "  Remove the Circle to Search block from $HOME/.config/hypr/bindings.conf"
    info "  Run: hyprctl reload"
    exit 1
fi

HYPR_CONFIGURED=0
HYPR_BINDINGS=""
INSTALLED_PKGS=""
SCRIPT_DIR=""
BIND_MODS=""
BIND_KEY=""

while IFS='=' read -r key val; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${key// /}" ]] && continue
    val="${val#\"}" ; val="${val%\"}"
    case "$key" in
        SCRIPT_DIR)      SCRIPT_DIR="$val" ;;
        HYPR_CONFIGURED) HYPR_CONFIGURED="${val:-0}" ;;
        HYPR_BINDINGS)   HYPR_BINDINGS="$val" ;;
        INSTALLED_PKGS)  INSTALLED_PKGS="$val" ;;
        BIND_MODS)       BIND_MODS="$val" ;;
        BIND_KEY)        BIND_KEY="$val" ;;
    esac
done < "$MANIFEST_FILE"

KEYBIND_DISPLAY=""
if [[ -n "$BIND_MODS" && -n "$BIND_KEY" ]]; then
    KEYBIND_DISPLAY="${BIND_MODS// /+}+${BIND_KEY}"
fi

ok "Manifest loaded"
printf '  %-22s %s\n' "Source directory"      "${SCRIPT_DIR:-unknown}"
printf '  %-22s %s\n' "Managed keybinding"    "${KEYBIND_DISPLAY:-none}"
printf '  %-22s %s\n' "Packages recorded"     "${INSTALLED_PKGS:-none}"
printf '  %-22s %s\n' "Remove packages"       "$([[ $REMOVE_PACKAGES -eq 1 ]] && echo yes || echo no)"

analyze_recorded_packages

if [[ ${#REMOVABLE_PKGS[@]} -gt 0 ]]; then
    printf '  %-22s %s\n' "Removable packages"    "$(join_by ' ' "${REMOVABLE_PKGS[@]}")"
else
    printf '  %-22s %s\n' "Removable packages"    "none"
fi

if [[ ${#PROTECTED_PKGS[@]} -gt 0 ]]; then
    printf '  %-22s %s\n' "Protected packages"    "$(join_by ' ' "${PROTECTED_PKGS[@]}")"
    local_index=0
    for pkg in "${PROTECTED_PKGS[@]}"; do
        printf '  %-22s %s\n' "  - $pkg" "${PROTECTED_REASONS[$local_index]}"
        local_index=$((local_index + 1))
    done
fi

if [[ $DRY_RUN -eq 1 ]]; then
    printf '\n'
    info "Dry run — no changes made."
    printf '\n'
    exit 0
fi

confirm "Proceed with uninstall?" || die "Aborted by user."

section "2/4  Hyprland keybinding"
if [[ $HYPR_CONFIGURED -eq 1 && -n "$HYPR_BINDINGS" && -f "$HYPR_BINDINGS" ]]; then
    BACKUP_FILE="$(backup_path_for "$HYPR_BINDINGS")"
    cp "$HYPR_BINDINGS" "$BACKUP_FILE"

    tmpfile="$(new_tempfile)"
    strip_marker_blocks "$HYPR_BINDINGS" "$tmpfile"
    mv "$tmpfile" "$HYPR_BINDINGS"

    ok "Managed keybinding block removed"
    info "Bindings file: $HYPR_BINDINGS"
    info "Backup:        $BACKUP_FILE"

    if hyprctl reload >/dev/null 2>&1; then
        ok "Hyprland reloaded"
    else
        warn "hyprctl reload failed — reload manually"
    fi
else
    skip "No managed Hyprland keybinding found"
fi

section "3/4  Packages"
if [[ $REMOVE_PACKAGES -eq 0 ]]; then
    skip "Package removal skipped by default"
    info "Use ./uninstall.sh --remove-packages if you want to remove recorded packages"
    if [[ -n "${INSTALLED_PKGS// /}" ]]; then
        KEEP_MANIFEST=1
        KEEP_MANIFEST_REASON="package removal was skipped"
    fi
    if [[ ${#PROTECTED_PKGS[@]} -gt 0 ]]; then
        info "Shared host packages would be skipped automatically: $(join_by ' ' "${PROTECTED_PKGS[@]}")"
    fi
elif [[ -z "${INSTALLED_PKGS// /}" ]]; then
    skip "No packages were recorded as installed by install.sh"
elif [[ ${#AVAILABLE_RECORDED_PKGS[@]} -eq 0 ]]; then
    skip "All recorded packages are already absent"
elif [[ ${#REMOVABLE_PKGS[@]} -eq 0 ]]; then
    skip "All recorded packages are shared with the current host and will be kept"
    local_index=0
    for pkg in "${PROTECTED_PKGS[@]}"; do
        info "$pkg kept: ${PROTECTED_REASONS[$local_index]}"
        local_index=$((local_index + 1))
    done
else
    if [[ ${#PROTECTED_PKGS[@]} -gt 0 ]]; then
        warn "Shared host packages will be preserved"
        local_index=0
        for pkg in "${PROTECTED_PKGS[@]}"; do
            info "$pkg kept: ${PROTECTED_REASONS[$local_index]}"
            local_index=$((local_index + 1))
        done
    fi

    if [[ ${#REMOVABLE_PKGS[@]} -eq 0 ]]; then
        skip "All recorded packages are already absent"
    else
        info "Only non-shared packages will be removed"
        printf '  Packages: %s\n' "${REMOVABLE_PKGS[*]}"
        if ! confirm "Remove these package(s) with pacman?"; then
            skip "Package removal skipped"
            KEEP_MANIFEST=1
            KEEP_MANIFEST_REASON="package removal was canceled"
        else
            info "Requesting sudo for pacman..."
            sudo -v || die "sudo authentication failed"
            if sudo pacman -R --noconfirm "${REMOVABLE_PKGS[@]}"; then
                ok "Package removal step finished"
            else
                warn "pacman remove failed"
                KEEP_MANIFEST=1
                KEEP_MANIFEST_REASON="pacman remove failed"
            fi
        fi
    fi
fi

if [[ $REMOVE_PACKAGES -eq 1 && $KEEP_MANIFEST -eq 0 ]]; then
    analyze_recorded_packages
    if [[ ${#AVAILABLE_RECORDED_PKGS[@]} -gt 0 ]]; then
        KEEP_MANIFEST=1
        KEEP_MANIFEST_REASON="some recorded packages are still installed"
    fi
fi

section "4/4  Cleanup"
if [[ $KEEP_MANIFEST -eq 1 ]]; then
    info "Keeping manifest so package removal can be retried later"
    info "Reason: $KEEP_MANIFEST_REASON"
    info "Retry with: ./uninstall.sh --remove-packages"
else
    rm -f "$MANIFEST_FILE"
    ok "Removed manifest: $MANIFEST_FILE"
fi

if [[ -d "$MANIFEST_DIR" ]] && [[ -z "$(ls -A "$MANIFEST_DIR")" ]]; then
    rmdir "$MANIFEST_DIR"
    ok "Removed empty manifest directory"
fi

LOCK_FILE="/tmp/circle-to-search.lock"
if [[ -f "$LOCK_FILE" ]]; then
    rm -f "$LOCK_FILE"
    ok "Removed: $LOCK_FILE"
else
    skip "No lock file present"
fi

hr
printf '\n  %sUninstall complete.%s\n\n' "$GREEN$BOLD" "$RESET"
printf '  %-16s %s\n' "Project dir" "${SCRIPT_DIR:-$(pwd)}"
printf '  %-16s %s\n' "Remove manually" "Project directory and optional user config if no longer needed"
printf '\n'
