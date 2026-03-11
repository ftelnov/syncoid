#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/ftelnov/syncoid"
INSTALL_DIR="${SYNCOID_INSTALL_DIR:-$HOME/.local/share/syncoid}"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/syncoid"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

detect_pkg_manager() {
    if command -v pkg &>/dev/null; then
        echo "pkg"
    elif command -v apt-get &>/dev/null; then
        echo "apt-get"
    else
        echo ""
    fi
}

check_dependencies() {
    local missing=()

    command -v git &>/dev/null || missing+=("git")
    command -v python3 &>/dev/null || missing+=("python")
    command -v pip &>/dev/null || missing+=("python-pip")
    command -v termux-battery-status &>/dev/null || missing+=("termux-api")
    command -v syncthing &>/dev/null || missing+=("syncthing")

    if [ ${#missing[@]} -gt 0 ]; then
        local pm
        pm=$(detect_pkg_manager)

        if [ -z "$pm" ]; then
            log_error "Missing dependencies: ${missing[*]}"
            log_error "No package manager found. Install manually."
            exit 1
        fi

        log_info "Installing missing dependencies: ${missing[*]}"
        $pm install -y "${missing[@]}" || {
            log_error "Failed to install: ${missing[*]}"
            log_info "Try manually: $pm install ${missing[*]}"
            exit 1
        }
    fi

    # Optional: inotify-tools for watch mode
    if ! command -v inotifywait &>/dev/null; then
        local pm
        pm=$(detect_pkg_manager)

        if [ -n "$pm" ]; then
            log_info "Installing inotify-tools for file-watch mode..."
            $pm install -y inotify-tools 2>/dev/null || \
                log_warn "Could not install inotify-tools. Watch mode won't work."
        else
            log_warn "inotify-tools not found. Install for file-watch mode."
        fi
    fi
}

install_syncoid() {
    log_info "Installing Syncoid..."

    mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$CONFIG_DIR"

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git pull -q
    else
        log_info "Cloning repository..."
        git clone -q "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi

    log_info "Installing Python package..."
    pip install -q --upgrade .

    ln -sf "$INSTALL_DIR/scripts/syncoid-run" "$BIN_DIR/syncoid-run"
    ln -sf "$INSTALL_DIR/scripts/syncoid-configure" "$BIN_DIR/syncoid-configure"
    ln -sf "$INSTALL_DIR/scripts/syncoid-watch" "$BIN_DIR/syncoid-watch"
    ln -sf "$INSTALL_DIR/shortcuts/sync-now" "$BIN_DIR/sync-now"

    mkdir -p ~/.shortcuts
    ln -sf "$INSTALL_DIR/shortcuts/sync-now" ~/.shortcuts/sync-now

    log_info "Installation complete!"
}

configure_syncoid() {
    log_info "Configuring Syncoid..."

    if ! grep -q 'export PATH.*\.local/bin' ~/.bashrc 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    fi

    export PATH="$HOME/.local/bin:$PATH"

    if python3 -m syncoid configure 2>/dev/null; then
        log_info "Configuration saved and job scheduled!"
    else
        log_warn "Auto-configuration failed. Run: syncoid configure --api-key YOUR_KEY"
    fi
}

print_usage() {
    echo ""
    echo "Commands:"
    echo "  syncoid now             - Sync right now"
    echo "  syncoid watch           - Watch folders, sync on file change"
    echo "  syncoid watch-boot enable  - Auto-start watch on boot"
    echo "  syncoid status          - Show current status"
    echo "  syncoid configure       - Change settings"
    echo "  syncoid enable          - Enable periodic scheduled sync"
    echo "  syncoid disable         - Disable periodic scheduled sync"
    echo ""
    echo "Background watch (recommended):"
    echo "  tmux new -s syncoid -d 'syncoid watch'"
    echo ""
    echo "Home screen shortcut:"
    echo "  Install Termux:Widget, add widget -> tap 'sync-now'"
    echo ""
}

main() {
    echo "==================================="
    echo "  Syncoid Installer"
    echo "==================================="
    echo ""

    check_dependencies
    install_syncoid
    configure_syncoid
    print_usage

    log_info "Done! Run 'syncoid now' to test."
}

main "$@"
