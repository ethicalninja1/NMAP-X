#!/usr/bin/env bash
# NMAP-X installer: Termux, Kali Linux, Debian/Ubuntu, Arch, Fedora
# Author : Ethical Ninja
# GitHub : https://github.com/ethicalninja1
set -u

G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; C='\033[1;36m'; N='\033[0m'
info() { echo -e "${C}[*]${N} $1"; }
ok()   { echo -e "${G}[+]${N} $1"; }
warn() { echo -e "${Y}[!]${N} $1"; }
die()  { echo -e "${R}[x]${N} $1"; exit 1; }

# Use sudo only when not already root
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [[ "${PREFIX:-}" == *com.termux* ]]; then
    info "Termux detected"
    pkg update -y && pkg install -y python nmap || die "pkg install failed"
    warn "Optional GUI: pkg install x11-repo python-tkinter termux-x11-nightly"
    RUN="python nmapx.py"
elif command -v apt-get >/dev/null 2>&1; then
    info "Kali / Debian / Ubuntu detected"
    $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-tk nmap || die "apt install failed"
    RUN="sudo python3 nmapx.py"
elif command -v pacman >/dev/null 2>&1; then
    info "Arch detected"
    $SUDO pacman -Sy --noconfirm python tk nmap || die "pacman install failed"
    RUN="sudo python3 nmapx.py"
elif command -v dnf >/dev/null 2>&1; then
    info "Fedora detected"
    $SUDO dnf install -y python3 python3-tkinter nmap || die "dnf install failed"
    RUN="sudo python3 nmapx.py"
else
    die "Unsupported system. Please install python3 and nmap manually (tkinter is optional)."
fi

# Python packages (none required, but safe to run if the file exists)
PY=$(command -v python3 || command -v python)
if [ -f requirements.txt ]; then
    "$PY" -m pip install -r requirements.txt >/dev/null 2>&1 || true
fi

chmod +x nmapx.py 2>/dev/null || true

if command -v nmap >/dev/null 2>&1; then ok "nmap: $(nmap --version | head -n1)"; else warn "nmap was not installed"; fi
if "$PY" -c "import tkinter" >/dev/null 2>&1; then ok "tkinter found: GUI mode available"; else warn "tkinter not found: only CLI mode will work"; fi

echo
ok "Done! Run it with:  $RUN"
