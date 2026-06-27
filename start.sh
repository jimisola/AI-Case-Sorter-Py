#!/usr/bin/env bash
# Launcher for the AI Case Sorter OSS client.
#
# Usage:
#   ./start.sh                Launch the client (prompt before any sudo).
#   ./start.sh --auto         Auto-confirm any sudo apt/dnf/pacman installs.
#   AUTO_INSTALL=1 ./start.sh Same as --auto, for non-interactive shells.
#
# Forwards any extra args to main.py.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON_MIN="3.10"
AUTO_INSTALL="${AUTO_INSTALL:-0}"
FORWARD_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --auto|-y) AUTO_INSTALL=1 ;;
        *) FORWARD_ARGS+=("$arg") ;;
    esac
done

log()  { printf '[start] %s\n' "$*"; }
warn() { printf '[start] %s\n' "$*" >&2; }
die()  { printf '[start] ERROR: %s\n' "$*" >&2; exit 1; }

if [ "$AUTO_INSTALL" = "1" ]; then
    warn "AUTO_INSTALL is enabled: any required system packages (tkinter, libGL,"
    warn "glib, venv) will be installed via 'sudo' WITHOUT prompting."
fi

# ---------------------------------------------------------------------------
# Package-manager detection. We only know how to auto-install on apt, dnf,
# pacman. On anything else we still print a clear hint.
# ---------------------------------------------------------------------------
PKG_MGR=""
PKG_INSTALL=""
if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR=apt
    PKG_INSTALL="sudo apt-get install -y"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR=dnf
    PKG_INSTALL="sudo dnf install -y"
elif command -v pacman >/dev/null 2>&1; then
    PKG_MGR=pacman
    PKG_INSTALL="sudo pacman -S --noconfirm"
fi

# Map a generic feature to the right package name for the detected distro.
pkg_for() {
    local feature="$1"
    case "$PKG_MGR:$feature" in
        apt:venv)
            # Prefer the python3.X-venv that matches the installed python3.
            local pv
            pv="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo)"
            if [ -n "$pv" ] && apt-cache show "python${pv}-venv" >/dev/null 2>&1; then
                echo "python${pv}-venv"
            else
                echo "python3-venv"
            fi
            ;;
        apt:tk)   echo "python3-tk" ;;
        apt:gl)   echo "libgl1" ;;
        apt:glib) echo "libglib2.0-0" ;;
        dnf:venv) echo "" ;;                # bundled with python3
        dnf:tk)   echo "python3-tkinter" ;;
        dnf:gl)   echo "mesa-libGL" ;;
        dnf:glib) echo "glib2" ;;
        pacman:venv) echo "" ;;             # bundled with python
        pacman:tk)   echo "tk" ;;
        pacman:gl)   echo "libglvnd" ;;
        pacman:glib) echo "glib2" ;;
        *) echo "" ;;
    esac
}

confirm() {
    local prompt="$1"
    if [ "$AUTO_INSTALL" = "1" ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        # Launched without a TTY (desktop shortcut etc.); don't run sudo silently.
        return 1
    fi
    printf '[start] %s [Y/n] ' "$prompt"
    read -r reply
    case "$reply" in
        ''|y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

try_install() {
    local feature="$1" purpose="$2"
    if [ -z "$PKG_INSTALL" ]; then
        return 1
    fi
    local pkg
    pkg="$(pkg_for "$feature")"
    if [ -z "$pkg" ]; then
        return 1
    fi
    warn "About to install the system package '$pkg' ($purpose)."
    warn "This runs '$PKG_INSTALL $pkg' with sudo and modifies system packages."
    if ! confirm "Install $pkg ($purpose)?"; then
        return 1
    fi
    log "Running: $PKG_INSTALL $pkg"
    # shellcheck disable=SC2086
    $PKG_INSTALL $pkg
}

install_hint() {
    local feature="$1"
    case "$feature" in
        python)
            echo "  apt:    sudo apt install python3 python3-venv python3-tk"
            echo "  dnf:    sudo dnf install python3 python3-tkinter"
            echo "  pacman: sudo pacman -S python tk"
            ;;
        venv)
            echo "  apt:    sudo apt install $(PKG_MGR=apt pkg_for venv)"
            echo "  dnf:    (bundled with python3)"
            echo "  pacman: (bundled with python)"
            ;;
        tk)
            echo "  apt:    sudo apt install python3-tk"
            echo "  dnf:    sudo dnf install python3-tkinter"
            echo "  pacman: sudo pacman -S tk"
            ;;
        gl)
            echo "  apt:    sudo apt install libgl1"
            echo "  dnf:    sudo dnf install mesa-libGL"
            echo "  pacman: sudo pacman -S libglvnd"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# 1. Python 3.10+
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 is not installed."
    install_hint python >&2
    exit 1
fi

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= tuple(int(x) for x in '${PYTHON_MIN}'.split('.')) else 1)"; then
    pv="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    die "Python ${PYTHON_MIN}+ required (found ${pv})."
fi

# ---------------------------------------------------------------------------
# 2. venv module (Debian/Ubuntu split this out of python3).
# ---------------------------------------------------------------------------
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    log "Python venv/ensurepip is missing."
    if ! try_install venv "needed to create the project virtualenv"; then
        warn "Install the venv package and re-run:"
        install_hint venv >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 3. Tkinter (Debian/Ubuntu split this out of python3 too). Check BEFORE
#    running pip so we fail fast instead of after a long install.
# ---------------------------------------------------------------------------
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    log "Tkinter is missing from this Python."
    if ! try_install tk "the case sorter GUI uses Tkinter"; then
        warn "Install tkinter and re-run:"
        install_hint tk >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 4. Create / refresh the virtualenv.
# ---------------------------------------------------------------------------
if [ ! -d .venv ]; then
    log "Creating virtual environment at .venv ..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ---------------------------------------------------------------------------
# 5. Install pip deps. Use a hash of requirements.txt as the install marker so
#    edits to requirements.txt trigger a refresh instead of being silently
#    ignored.
# ---------------------------------------------------------------------------
if command -v sha256sum >/dev/null 2>&1; then
    REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
else
    REQ_HASH="$(shasum -a 256 requirements.txt | awk '{print $1}')"
fi
CURRENT_HASH="$(cat .installed 2>/dev/null || true)"

if [ "$CURRENT_HASH" != "$REQ_HASH" ]; then
    log "Installing Python dependencies ..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    printf '%s\n' "$REQ_HASH" > .installed
fi

# ---------------------------------------------------------------------------
# 6. opencv-python needs libGL.so.1 and libglib at runtime, which are missing
#    on minimal Ubuntu/WSL/Docker images. Catch that here instead of letting
#    main.py crash with a confusing ImportError.
# ---------------------------------------------------------------------------
cv_err="$(python -c "import cv2" 2>&1 || true)"
if [ -n "$cv_err" ]; then
    if printf '%s' "$cv_err" | grep -qi "libGL"; then
        log "OpenCV needs libGL.so.1 from the system."
        if ! try_install gl "OpenCV uses the system OpenGL library"; then
            warn "Install the system OpenGL library and re-run:"
            install_hint gl >&2
            exit 1
        fi
    elif printf '%s' "$cv_err" | grep -qi "libgthread\|libglib"; then
        log "OpenCV needs glib from the system."
        if ! try_install glib "OpenCV uses glib2"; then
            warn "Install glib2 (apt: libglib2.0-0) and re-run."
            exit 1
        fi
    else
        die "OpenCV failed to import: $cv_err"
    fi
fi

python main.py "${FORWARD_ARGS[@]}"
