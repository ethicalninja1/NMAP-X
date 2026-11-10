#!/usr/bin/env python3
"""
NMAP-X  |  Professional Nmap Scanner (CLI + GUI)
-----------------------------------------------
Author    : Ethical Ninja
GitHub    : https://github.com/ethicalninja1
Platforms : Kali Linux, Termux (Android), other Linux, macOS, Windows
Features  : 16 scan profiles (Basic -> Advanced), pick by number, colorful + animated.

Educational purpose only. Scan only your own systems or targets you have written permission to test.

Quick start:
    bash install.sh            # auto-install nmap + Python deps (Termux / Kali / Debian)
    python3 nmapx.py           # launcher (choose CLI or GUI)
    python3 nmapx.py --cli     # CLI directly
    python3 nmapx.py --gui     # GUI directly (desktop / Termux:X11)

Kali   : sudo python3 nmapx.py   -> full power (OS, SYN, UDP scans)
Termux : python nmapx.py         -> no root needed; root-only scans use a safe automatic fallback
"""

import math
import os
import queue
import random
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import webbrowser
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    HAS_TK = True
except Exception:  # tkinter missing
    HAS_TK = False

APP_NAME = "NMAP-X"
VERSION = "1.0"
AUTHOR = "Ethical Ninja"
GITHUB = "https://github.com/ethicalninja1"

BANNER = [
    "███╗   ██╗███╗   ███╗ █████╗ ██████╗       ██╗  ██╗",
    "████╗  ██║████╗ ████║██╔══██╗██╔══██╗      ╚██╗██╔╝",
    "██╔██╗ ██║██╔████╔██║███████║██████╔╝█████╗ ╚███╔╝ ",
    "██║╚██╗██║██║╚██╔╝██║██╔══██║██╔═══╝ ╚════╝ ██╔██╗ ",
    "██║ ╚████║██║ ╚═╝ ██║██║  ██║██║           ██╔╝ ██╗",
    "╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚═╝  ╚═╝",
]

# ----------------------------------------------------------------------------
# Scan profiles  (number = list position + 1)
# ----------------------------------------------------------------------------
def _s(level, name, args, desc, root=False, custom=False):
    return {"level": level, "name": name, "args": args, "desc": desc,
            "root": root, "custom": custom}


SCANS = [
    _s("BASIC", "Quick Scan", ["-T4", "-F"],
       "Fastest scan. Checks the 100 most common ports."),
    _s("BASIC", "Ping Sweep (Host Discovery)", ["-sn"],
       "Finds which hosts are online. No port scan is performed."),
    _s("BASIC", "Default Port Scan", [],
       "Nmap's default scan: top 1000 TCP ports."),
    _s("BASIC", "Well-Known Ports (1-1024)", ["-p", "1-1024"],
       "Standard service ports, 1 to 1024."),
    _s("INTERMEDIATE", "Service Version Detection", ["-sV"],
       "Detects the services and versions running on open ports."),
    _s("INTERMEDIATE", "Default Scripts + Versions", ["-sC", "-sV"],
       "Safe default NSE scripts plus version detection.", False),
    _s("INTERMEDIATE", "OS Detection", ["-O"],
       "Guesses the target's operating system. (requires admin/root)", True),
    _s("INTERMEDIATE", "Aggressive Scan", ["-A", "-T4"],
       "OS + versions + scripts + traceroute, all in one. (requires admin/root)", True),
    _s("INTERMEDIATE", "Service + Traceroute", ["-sV", "--traceroute"],
       "Detects versions and shows the network path (hops). (requires admin/root)", True),
    _s("ADVANCED", "Full TCP Scan (All 65535 Ports)", ["-p-", "-T4"],
       "Scans every TCP port. May take a long time."),
    _s("ADVANCED", "SYN Stealth Scan", ["-sS", "-T4"],
       "Half-open scan: fast and less noisy. (requires admin/root)", True),
    _s("ADVANCED", "UDP Scan (Top 100)", ["-sU", "--top-ports", "100"],
       "Common UDP services (DNS, SNMP, DHCP...). Slow. (requires admin/root)", True),
    _s("ADVANCED", "Vulnerability Scripts", ["-sV", "--script", "vuln"],
       "Checks for known vulnerabilities using NSE 'vuln' scripts."),
    _s("ADVANCED", "Firewall Evasion Test (Fragmented)", ["-sS", "-f", "-T2"],
       "Tests firewall/IDS behaviour using fragmented packets. (requires admin/root)", True),
    _s("ADVANCED", "Full Comprehensive Scan", ["-p-", "-A", "-T4"],
       "All ports + OS + versions + scripts. Most detailed. (requires admin/root)", True),
    _s("ADVANCED", "Custom Scan (Your Own Options)", [],
       "Enter your own Nmap options, e.g.: -sV -p 80,443 --script http-title", False, True),
]

LEVEL_CLI_COLOR = {"BASIC": 82, "INTERMEDIATE": 220, "ADVANCED": 203}
LEVEL_GUI_COLOR = {"BASIC": "#3ddc84", "INTERMEDIATE": "#ffd166", "ADVANCED": "#ff6b81"}

TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_:/\[\]]*$")
PROGRESS_RE = re.compile(r"About ([\d.]+)% done")
OPEN_RE = re.compile(r"^\d+/(tcp|udp)\s+open")


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------
def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def platform_name():
    if IS_TERMUX:
        return "TERMUX"
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            data = f.read().lower()
        if "kali" in data:
            return "KALI LINUX"
        m = re.search(r'^pretty_name="?([^"\n]+)', data, re.M)
        if m:
            return m.group(1).upper()
    except OSError:
        pass
    return "WINDOWS" if os.name == "nt" else sys.platform.upper()


def term_width():
    return shutil.get_terminal_size((80, 24)).columns


def can_use_gui():
    """Returns (ok, reason). The GUI cannot run on Termux or headless Linux without a display."""
    if not HAS_TK:
        return False, ("tkinter is not installed.  Kali: sudo apt install python3-tk"
                       "  |  Termux: pkg install python-tkinter")
    if os.name == "posix" and sys.platform != "darwin" \
            and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        if IS_TERMUX:
            return False, "The GUI on Termux needs Termux:X11 (DISPLAY is not set). Use CLI mode."
        return False, ("No display found. Run from a desktop terminal "
                       "(with sudo: sudo -E python3 nmapx.py --gui).")
    return True, ""


# Unprivileged versions of root-only scans (None = impossible without root)
FALLBACKS = {
    "OS Detection": ["-sV"],
    "Aggressive Scan": ["-sV", "-sC", "-T4"],
    "Service + Traceroute": ["-sV"],
    "SYN Stealth Scan": ["-sT", "-T4"],
    "Full Comprehensive Scan": ["-p-", "-sV", "-sC", "-T4"],
    "UDP Scan (Top 100)": None,
    "Firewall Evasion Test (Fragmented)": None,
}


def resolve_scan(scan):
    """Returns (scan, note, blocked). Switches to an unprivileged scan when not root."""
    if scan["root"] and os.name != "nt" and not is_root():
        fb = FALLBACKS.get(scan["name"], [])
        if fb is None:
            return scan, None, True
        new = dict(scan, args=fb)
        return new, ("Not running as root, so the scan runs in unprivileged mode: "
                     + " ".join(fb)), False
    return scan, None, False


def parse_targets(text):
    """Parses IP / domain / CIDR / range targets. Raises ValueError on invalid input."""
    tokens = [t for t in re.split(r"[,\s]+", text.strip()) if t]
    if not tokens:
        raise ValueError("Target is empty. Enter an IP address or domain.")
    for t in tokens:
        if not TARGET_RE.match(t):
            raise ValueError(f"Invalid target: {t}")
    return tokens


def build_command(scan, targets, extra=""):
    cmd = ["nmap"] + scan["args"] + ["--stats-every", "2s"]
    if IS_TERMUX:  # Android: no /etc/resolv.conf and no raw sockets
        cmd.append("--system-dns")
        if not is_root():
            cmd.append("--unprivileged")
    if extra.strip():
        cmd += shlex.split(extra)
    return cmd + targets


def fmt_time(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


class ScanRunner:
    """Runs Nmap in a background thread and streams its output line by line."""

    def __init__(self, cmd, on_line, on_done):
        self.cmd, self.on_line, self.on_done = cmd, on_line, on_done
        self.proc = None
        self.stopped = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _run(self):
        rc = -1
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=flags)
            for line in self.proc.stdout:
                self.on_line(line.rstrip("\n"))
            rc = self.proc.wait()
        except Exception as exc:
            self.on_line(f"[error] {exc}")
        self.on_done(rc, self.stopped)


NMAP_HELP = ("Nmap is not installed.\n"
             "  Windows : https://nmap.org/download (run the installer)\n"
             "  Termux  : pkg install nmap\n"
             "  Kali    : sudo apt install nmap\n"
             "  macOS   : brew install nmap\n"
             "  (or run: bash install.sh)")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
R = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def fg(n):
    return f"\033[38;5;{n}m"


def enable_ansi():
    if os.name == "nt":
        os.system("")  # enable ANSI colors in the Windows terminal


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def typewriter(text, delay=0.012):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def animated_banner():
    grad = [46, 47, 48, 49, 50, 51]
    tw = term_width()
    print()
    if tw >= 56:
        for line, color in zip(BANNER, grad):
            print(f"  {fg(color)}{BOLD}{line}{R}")
            time.sleep(0.07)
    else:  # small screen (Termux portrait)
        for color, text in ((46, "╔" + "═" * 15 + "╗"), (48, "║  N M A P - X  ║"), (51, "╚" + "═" * 15 + "╝")):
            print(f"  {fg(color)}{BOLD}{text}{R}")
            time.sleep(0.07)
    print(f"\n  {fg(245)}Nmap Scanner {fg(51)}v{VERSION}{fg(245)} | {platform_name()}{R}")
    print(f"  {fg(245)}Educational Use Only{R}")
    print(f"  {fg(245)}Author: {fg(46)}{BOLD}{AUTHOR}{R}")
    print(f"  {fg(245)}GitHub: {fg(51)}{GITHUB}{R}\n")


def boot_animation():
    tw = term_width()
    steps = ["Loading modules", "Checking Nmap engine", "Preparing scan profiles", "Ready"]
    wide = tw >= 72
    width = 28 if wide else max(8, min(28, tw - 16))
    for i, step in enumerate(steps, 1):
        label = f" {step:<24}" if wide else ""
        for p in range(width + 1):
            filled = "█" * p + "░" * (width - p)
            pct = int((i - 1 + p / width) / len(steps) * 100)
            sys.stdout.write(f"\r  {fg(51)}[{filled}]{R} {fg(46)}{pct:3d}%{R}{fg(245)}{label}{R}")
            sys.stdout.flush()
            time.sleep(0.004)
    sys.stdout.write(f"\r\033[K  {fg(46)}System ready ✔{R}\n\n")


def colorize(line):
    s = line.strip()
    if OPEN_RE.match(s):
        return f"{fg(46)}{line}{R}"
    if re.match(r"^\d+/(tcp|udp)\s+closed", s):
        return f"{fg(203)}{line}{R}"
    if re.match(r"^\d+/(tcp|udp)\s+(filtered|open\|filtered)", s):
        return f"{fg(220)}{line}{R}"
    if "VULNERABLE" in line or "State: VULNERABLE" in line:
        return f"{BOLD}{fg(196)}{line}{R}"
    if line.startswith("Nmap scan report"):
        return f"{BOLD}{fg(51)}{line}{R}"
    if line.startswith("Host is up"):
        return f"{fg(82)}{line}{R}"
    if line.startswith("|"):
        return f"{fg(177)}{line}{R}"
    if line.startswith(("OS details", "Running", "Service Info", "MAC Address")):
        return f"{fg(87)}{line}{R}"
    if line.startswith(("Starting Nmap", "Nmap done")):
        return f"{fg(245)}{line}{R}"
    return line


def print_menu():
    tw = term_width()
    w = max(30, min(60, tw - 4))
    title = " SCAN PROFILES "
    side = (w - len(title)) // 2
    print(f"  {fg(51)}{BOLD}{'═' * side}{title}{'═' * (w - side - len(title))}{R}")
    compact = tw < 60  # phone: show names only, 'i <no>' for details
    last = None
    for i, sc in enumerate(SCANS, 1):
        if sc["level"] != last:
            last = sc["level"]
            print(f"\n  {fg(LEVEL_CLI_COLOR[last])}{BOLD}── {last} ──{R}")
        lock = f" {fg(203)}*{R}" if sc["root"] else ""
        print(f"   {fg(51)}[{i:>2}]{R} {BOLD}{sc['name']}{R}{lock}")
        if not compact:
            for part in textwrap.wrap(sc["desc"], max(20, tw - 12)):
                print(f"        {fg(245)}{part}{R}")
    print(f"\n   {fg(51)}[ 0]{R} Exit")
    print(f"\n  {fg(203)}*{R} {fg(245)}= needs root (automatic fallback if not root){R}")
    print(f"  {fg(245)}Tip: type 'i 5' to see details of scan 5{R}\n")


def ask(prompt):
    return input(f"  {fg(46)}❯{R} {BOLD}{prompt}{R} ").strip()


def cli_scan(cmd):
    lock = threading.Lock()
    state = {"done": False, "pct": None}
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    start = time.time()
    lines = []

    def spinner():
        i = 0
        while not state["done"]:
            with lock:
                if state["done"]:
                    break
                bar = ""
                if state["pct"] is not None:
                    bw = max(8, min(20, term_width() - 28))
                    n = int(state["pct"] / 100 * bw)
                    bar = f" {fg(46)}{'█' * n}{fg(240)}{'░' * (bw - n)}{R} {state['pct']:.0f}%"
                sys.stdout.write(f"\r\033[K  {fg(51)}{frames[i % 10]}{R} {fg(245)}Scanning {fmt_time(time.time() - start)}{R}{bar}")
                sys.stdout.flush()
            i += 1
            time.sleep(0.08)

    def on_line(line):
        m = PROGRESS_RE.search(line)
        if m:
            state["pct"] = float(m.group(1))
            return
        if line.startswith("Stats:"):
            return
        lines.append(line)
        with lock:
            sys.stdout.write("\r\033[K" + colorize(line) + "\n")
            sys.stdout.flush()

    def on_done(rc, stopped):
        state["done"] = True
        state["rc"] = rc

    runner = ScanRunner(cmd, on_line, on_done)
    spin_thread = threading.Thread(target=spinner, daemon=True)
    runner.start()
    spin_thread.start()
    try:
        while not state["done"]:
            time.sleep(0.1)
    except KeyboardInterrupt:
        runner.stop()
        time.sleep(0.3)
        print(f"\n  {fg(220)}⚠ Scan stopped by user.{R}")
    state["done"] = True
    time.sleep(0.1)
    sys.stdout.write("\r\033[K")
    return lines, time.time() - start


def cli_main():
    enable_ansi()
    clear_screen()
    animated_banner()
    boot_animation()

    if not shutil.which("nmap"):
        print(f"  {fg(203)}{NMAP_HELP}{R}")
        return

    root_txt = f"{fg(46)}root ✔" if is_root() else f"{fg(220)}non-root"
    print(f"  {fg(245)}Platform:{R} {fg(51)}{platform_name()}{R} {fg(245)}|{R} {root_txt}{R}")
    if not is_root() and os.name != "nt":
        hint = ("On Termux, root-only scans use automatic fallbacks." if IS_TERMUX
                else "For full power run: sudo python3 nmapx.py")
        print(f"  {fg(220)}⚠ {hint}{R}")
    print()
    sep = "─" * max(10, min(52, term_width() - 4))

    while True:
        print_menu()
        choice = ask("Scan number (0 = exit):")
        low = choice.lower()
        if low.startswith("i ") and low[2:].strip().isdigit() and 1 <= int(low[2:]) <= len(SCANS):
            sc = SCANS[int(low[2:]) - 1]
            print(f"\n  {fg(51)}{BOLD}{sc['name']}{R}")
            for part in textwrap.wrap(sc["desc"], max(20, term_width() - 4)):
                print(f"  {fg(245)}{part}{R}")
            print()
            continue
        if choice == "0":
            typewriter(f"  {fg(51)}Bye! Stay ethical. 🛡{R}")
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(SCANS):
            print(f"  {fg(203)}✘ Enter a number between 1 and {len(SCANS)}.{R}\n")
            continue
        scan = SCANS[int(choice) - 1]
        print(f"\n  {fg(46)}✔ Selected:{R} {BOLD}{scan['name']}{R}\n")

        scan, note, blocked = resolve_scan(scan)
        if blocked:
            print(f"  {fg(203)}✘ This scan cannot run without root.{R}")
            print(f"  {fg(245)}Kali: sudo python3 nmapx.py  |  Termux: rooted devices only.{R}\n")
            continue
        if note:
            print(f"  {fg(220)}⚠ {note}{R}\n")

        try:
            targets = parse_targets(ask("Target IP / Domain (multiple: space/comma):"))
        except ValueError as exc:
            print(f"  {fg(203)}✘ {exc}{R}\n")
            continue

        if scan["custom"]:
            extra = ask("Enter your Nmap options:")
            if not extra:
                print(f"  {fg(203)}✘ Options are required for a custom scan.{R}\n")
                continue
        else:
            extra = ask("Extra options (optional, Enter = skip):")

        try:
            cmd = build_command(scan, targets, extra)
        except ValueError as exc:
            print(f"  {fg(203)}✘ Invalid options: {exc}{R}\n")
            continue

        print(f"\n  {fg(245)}Command:{R} {fg(51)}{' '.join(cmd)}{R}")
        if ask("Do you have permission to scan this target? (y/N):").lower() != "y":
            print(f"  {fg(203)}✘ The scan will not run without permission.{R}\n")
            continue

        print(f"\n  {fg(46)}{BOLD}▶ Starting scan...{R}  {fg(245)}(Ctrl+C = stop){R}\n")
        lines, elapsed = cli_scan(cmd)
        open_count = sum(1 for l in lines if OPEN_RE.match(l.strip()))
        print(f"\n  {fg(51)}{sep}{R}")
        print(f"  {fg(46)}✔ Complete{R} | {fmt_time(elapsed)} | Open ports: {fg(46)}{BOLD}{open_count}{R}")
        print(f"  {fg(51)}{sep}{R}\n")

        if lines and ask("Save report? (Y/n):").lower() != "n":
            name = f"nmapx_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
            with open(name, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print(f"  {fg(46)}💾 Saved: {os.path.abspath(name)}{R}\n")

        if ask("Run another scan? (Y/n):").lower() == "n":
            typewriter(f"  {fg(51)}Bye! Stay ethical. 🛡{R}")
            return
        clear_screen()
        animated_banner()


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
BG = "#070b11"
PANEL = "#0e151e"
PANEL2 = "#121c28"
BORDER = "#1c2a3a"
ACCENT = "#00ff9c"
CYAN = "#00d8ff"
TEXT = "#cfd8e3"
MUTED = "#6b7c8f"
RED = "#ff4d6d"
YELLOW = "#ffd166"
VIOLET = "#c792ea"


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


if HAS_TK:
    MONO = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"{APP_NAME} - Professional Nmap Scanner")
            self.geometry("1220x780")
            self.minsize(1050, 680)
            self.configure(bg=BG)

            self.q = queue.Queue()
            self.runner = None
            self.scanning = False
            self.pct = None
            self.start_time = 0
            self.open_count = 0
            self.tick = 0
            self.angle = 0
            self.blips = [(random.randint(0, 359), random.randint(10, 36)) for _ in range(7)]

            self._build_header()
            self._build_body()
            self._build_status()
            self.protocol("WM_DELETE_WINDOW", self._close)

            self._select(0)
            self._animate()
            self._poll()
            self._intro()

        # ---------- UI building ----------
        def _btn(self, parent, text, cmd, color, fg_color=BG):
            b = tk.Button(parent, text=text, command=cmd, bg=color, fg=fg_color,
                          activebackground=mix(color, "#ffffff", 0.25), activeforeground=fg_color,
                          relief="flat", bd=0, cursor="hand2", padx=14, pady=9,
                          font=(MONO, 10, "bold"))
            b.bind("<Enter>", lambda e: b.config(bg=mix(color, "#ffffff", 0.2)) if str(b["state"]) == "normal" else None)
            b.bind("<Leave>", lambda e: b.config(bg=color) if str(b["state"]) == "normal" else None)
            return b

        def _entry(self, parent, var=None):
            return tk.Entry(parent, textvariable=var, bg=PANEL2, fg=ACCENT, insertbackground=ACCENT,
                            relief="flat", font=(MONO, 11), highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT)

        def _label(self, parent, text, color=MUTED, size=9, bold=True):
            return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                            font=(MONO, size, "bold" if bold else "normal"))

        def _build_header(self):
            head = tk.Frame(self, bg=PANEL, height=96)
            head.pack(fill="x")
            head.pack_propagate(False)
            tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

            self.radar = tk.Canvas(head, width=90, height=90, bg=PANEL, highlightthickness=0)
            self.radar.pack(side="left", padx=(18, 10), pady=3)
            for r in (40, 28, 16):
                self.radar.create_oval(45 - r, 45 - r, 45 + r, 45 + r, outline="#16402f")
            self.radar.create_line(5, 45, 85, 45, fill="#16402f")
            self.radar.create_line(45, 5, 45, 85, fill="#16402f")

            titles = tk.Frame(head, bg=PANEL)
            titles.pack(side="left", pady=12)
            self.title_lbl = tk.Label(titles, text=APP_NAME, bg=PANEL, fg=ACCENT,
                                      font=(MONO, 26, "bold"))
            self.title_lbl.pack(anchor="w")
            self._label(titles, "NETWORK MAPPER  •  PROFESSIONAL SCANNER", MUTED, 9).pack(anchor="w")

            right = tk.Frame(head, bg=PANEL)
            right.pack(side="right", padx=22)
            nm = shutil.which("nmap")
            self.engine_lbl = tk.Label(right, bg=PANEL, font=(MONO, 10, "bold"),
                                       text="● NMAP ENGINE READY" if nm else "● NMAP NOT FOUND",
                                       fg=ACCENT if nm else RED)
            self.engine_lbl.pack(anchor="e")
            priv = "ADMIN/ROOT" if is_root() else "STANDARD USER"
            self._label(right, f"{platform_name()}  •  {priv}", MUTED, 9).pack(anchor="e")
            self._label(right, f"by {AUTHOR}", ACCENT, 9).pack(anchor="e", pady=(4, 0))
            link = tk.Label(right, text=GITHUB, bg=PANEL, fg=CYAN, cursor="hand2",
                            font=(MONO, 9, "underline"))
            link.pack(anchor="e")
            link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB))

        def _build_body(self):
            body = tk.Frame(self, bg=BG)
            body.pack(fill="both", expand=True, padx=14, pady=12)

            left = tk.Frame(body, bg=PANEL, width=420, highlightthickness=1, highlightbackground=BORDER)
            left.pack(side="left", fill="y")
            left.pack_propagate(False)
            pad = tk.Frame(left, bg=PANEL)
            pad.pack(fill="both", expand=True, padx=16, pady=14)

            self._label(pad, "▌ TARGET  (IP / Domain / CIDR)", CYAN).pack(anchor="w")
            self.target_var = tk.StringVar()
            self.target_entry = self._entry(pad, self.target_var)
            self.target_entry.pack(fill="x", ipady=7, pady=(5, 12))
            self.target_entry.bind("<Return>", lambda e: self.start_scan())

            self._label(pad, "▌ SCAN PROFILE  (pick by number)", CYAN).pack(anchor="w")
            lb_frame = tk.Frame(pad, bg=BORDER)
            lb_frame.pack(fill="both", expand=True, pady=(5, 8))
            self.listbox = tk.Listbox(lb_frame, bg=PANEL2, fg=TEXT, selectbackground="#10382b",
                                      selectforeground=ACCENT, activestyle="none", relief="flat",
                                      highlightthickness=0, exportselection=False, font=(MONO, 10), height=12)
            sb = tk.Scrollbar(lb_frame, command=self.listbox.yview, bg=PANEL2, troughcolor=PANEL2,
                              relief="flat", bd=0)
            self.listbox.config(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.listbox.pack(side="left", fill="both", expand=True, padx=1, pady=1)
            for i, sc in enumerate(SCANS, 1):
                tag = {"BASIC": "B", "INTERMEDIATE": "I", "ADVANCED": "A"}[sc["level"]]
                self.listbox.insert("end", f" {i:02d}  [{tag}]  {sc['name']}")
                self.listbox.itemconfig(i - 1, fg=LEVEL_GUI_COLOR[sc["level"]])
            self.listbox.bind("<<ListboxSelect>>", lambda e: self._select(self.listbox.curselection()[0])
                              if self.listbox.curselection() else None)

            numrow = tk.Frame(pad, bg=PANEL)
            numrow.pack(fill="x")
            self._label(numrow, "SCAN NO.", MUTED).pack(side="left")
            self.num_var = tk.StringVar(value="1")
            self.spin = tk.Spinbox(numrow, from_=1, to=len(SCANS), width=4, textvariable=self.num_var,
                                   command=self._spin_changed, bg=PANEL2, fg=ACCENT, relief="flat",
                                   buttonbackground=PANEL2, font=(MONO, 11, "bold"),
                                   highlightthickness=1, highlightbackground=BORDER, justify="center")
            self.spin.pack(side="left", padx=8, ipady=3)
            self.spin.bind("<KeyRelease>", lambda e: self._spin_changed())
            self._label(numrow, "[B]asic [I]nter [A]dv", MUTED, 8, False).pack(side="right")

            self.desc_lbl = tk.Label(pad, bg=PANEL, fg=TEXT, justify="left", wraplength=370,
                                     anchor="w", font=(MONO, 9))
            self.desc_lbl.pack(fill="x", pady=(10, 4))
            self.cmd_lbl = tk.Label(pad, bg=PANEL, fg=CYAN, justify="left", wraplength=370,
                                    anchor="w", font=(MONO, 9))
            self.cmd_lbl.pack(fill="x")

            self._label(pad, "▌ EXTRA OPTIONS (optional)", CYAN).pack(anchor="w", pady=(10, 0))
            self.extra_var = tk.StringVar()
            self.extra_entry = self._entry(pad, self.extra_var)
            self.extra_entry.pack(fill="x", ipady=6, pady=(5, 8))
            self.extra_var.trace_add("write", lambda *a: self._update_preview())
            self.target_var.trace_add("write", lambda *a: self._update_preview())

            self.auth_var = tk.IntVar()
            tk.Checkbutton(pad, text="I have permission to scan this target",
                           variable=self.auth_var, bg=PANEL, fg=YELLOW, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=YELLOW, font=(MONO, 9),
                           wraplength=370, justify="left", anchor="w").pack(fill="x", pady=(0, 10))

            row = tk.Frame(pad, bg=PANEL)
            row.pack(fill="x")
            self.start_btn = self._btn(row, "▶  START SCAN", self.start_scan, ACCENT)
            self.start_btn.pack(side="left", fill="x", expand=True)
            self.stop_btn = self._btn(row, "■  STOP", self.stop_scan, RED, "#ffffff")
            self.stop_btn.pack(side="left", padx=(8, 0))
            self.stop_btn.config(state="disabled", bg="#3a2230")

            # right: output
            right = tk.Frame(body, bg=BG)
            right.pack(side="left", fill="both", expand=True, padx=(12, 0))

            bar = tk.Frame(right, bg=PANEL, height=38, highlightthickness=1, highlightbackground=BORDER)
            bar.pack(fill="x")
            bar.pack_propagate(False)
            for color in (RED, YELLOW, ACCENT):
                tk.Label(bar, text="●", fg=color, bg=PANEL, font=(MONO, 11)).pack(side="left", padx=(10, 0))
            self._label(bar, "  SCAN OUTPUT  —  terminal", MUTED, 9).pack(side="left")
            self._btn(bar, "Clear", self.clear_output, PANEL2, TEXT).pack(side="right", padx=4, pady=4)
            self._btn(bar, "Save", self.save_output, PANEL2, TEXT).pack(side="right", pady=4)

            self.prog = tk.Canvas(right, height=8, bg=BG, highlightthickness=0)
            self.prog.pack(fill="x", pady=(6, 6))

            wrap = tk.Frame(right, bg=BORDER)
            wrap.pack(fill="both", expand=True)
            self.out = tk.Text(wrap, bg="#05080d", fg=TEXT, insertbackground=ACCENT, relief="flat",
                               font=(MONO, 10), wrap="word", padx=12, pady=10, state="disabled",
                               selectbackground="#10382b")
            osb = tk.Scrollbar(wrap, command=self.out.yview, bg=PANEL, troughcolor=BG, relief="flat", bd=0)
            self.out.config(yscrollcommand=osb.set)
            osb.pack(side="right", fill="y")
            self.out.pack(side="left", fill="both", expand=True, padx=1, pady=1)

            tags = {"open": (ACCENT, True), "closed": (RED, False), "filtered": (YELLOW, False),
                    "host": (CYAN, True), "vuln": ("#ff3355", True), "script": (VIOLET, False),
                    "info": (MUTED, False), "cmd": (CYAN, False), "ok": (ACCENT, True),
                    "warn": (YELLOW, True), "err": (RED, True), "osinfo": ("#5eead4", False)}
            for name, (color, bold) in tags.items():
                self.out.tag_config(name, foreground=color,
                                    font=(MONO, 10, "bold") if bold else (MONO, 10))
            for i, c in enumerate(["#00ff9c", "#00f5b0", "#00ebc4", "#00e1d8", "#00d8ec", "#00d8ff"]):
                self.out.tag_config(f"b{i}", foreground=c, font=(MONO, 10, "bold"))

        def _build_status(self):
            st = tk.Frame(self, bg=PANEL, height=30)
            st.pack(fill="x", side="bottom")
            st.pack_propagate(False)
            self.status_lbl = tk.Label(st, text="● IDLE", bg=PANEL, fg=MUTED, font=(MONO, 9, "bold"))
            self.status_lbl.pack(side="left", padx=14)
            self.time_lbl = tk.Label(st, text="TIME 00:00", bg=PANEL, fg=MUTED, font=(MONO, 9))
            self.time_lbl.pack(side="left", padx=14)
            self.open_lbl = tk.Label(st, text="OPEN PORTS: 0", bg=PANEL, fg=ACCENT, font=(MONO, 9, "bold"))
            self.open_lbl.pack(side="left", padx=14)
            tk.Label(st, text=f"Educational use only  •  Author: {AUTHOR}  •  {GITHUB}", bg=PANEL, fg=MUTED,
                     font=(MONO, 8)).pack(side="right", padx=14)

        # ---------- profile selection ----------
        def _select(self, idx):
            idx = max(0, min(idx, len(SCANS) - 1))
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self.num_var.set(str(idx + 1))
            self.cur = idx
            self._update_preview()

        def _spin_changed(self):
            v = self.num_var.get().strip()
            if v.isdigit() and 1 <= int(v) <= len(SCANS):
                self._select(int(v) - 1)

        def _update_preview(self):
            sc = SCANS[self.cur]
            lock = "  🔒 admin/root" if sc["root"] else ""
            self.desc_lbl.config(text=f"{sc['name']}{lock}\n{sc['desc']}")
            tgt = self.target_var.get().strip() or "<target>"
            extra = self.extra_var.get().strip()
            self.cmd_lbl.config(text="$ nmap " + " ".join(sc["args"] + ([extra] if extra else [])) + " " + tgt)

        # ---------- output helpers ----------
        def write(self, text, tag=None):
            self.out.config(state="normal")
            self.out.insert("end", text + "\n", tag or ())
            self.out.config(state="disabled")
            self.out.see("end")

        def clear_output(self):
            self.out.config(state="normal")
            self.out.delete("1.0", "end")
            self.out.config(state="disabled")

        def save_output(self):
            content = self.out.get("1.0", "end").strip()
            if not content:
                messagebox.showinfo(APP_NAME, "There is no output to save.")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".txt", filetypes=[("Text", "*.txt"), ("All", "*.*")],
                initialfile=f"nmapx_report_{datetime.now():%Y%m%d_%H%M%S}.txt")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.write(f"💾 Saved: {path}", "ok")

        def _intro(self):
            self._intro_lines = list(enumerate(BANNER))

            def step():
                if self._intro_lines:
                    i, line = self._intro_lines.pop(0)
                    self.write(line, f"b{i}")
                    self.after(90, step)
                else:
                    self.write("")
                    self.write("Welcome! Enter a target, pick a scan number, then press START.", "info")
                    self.write("Scan authorized targets only.", "warn")
                    self.write(f"Author: {AUTHOR}  |  GitHub: {GITHUB}\n", "info")
                    if not shutil.which("nmap"):
                        self.write(NMAP_HELP, "err")
            step()

        # ---------- scanning ----------
        def start_scan(self):
            if self.scanning:
                return
            if not shutil.which("nmap"):
                messagebox.showerror(APP_NAME, NMAP_HELP)
                return
            try:
                targets = parse_targets(self.target_var.get())
            except ValueError as exc:
                messagebox.showwarning(APP_NAME, str(exc))
                return
            sc = SCANS[self.cur]
            extra = self.extra_var.get()
            if sc["custom"] and not extra.strip():
                messagebox.showwarning(APP_NAME, "Enter your Nmap options in 'Extra options' for a custom scan.")
                return
            if not self.auth_var.get():
                messagebox.showwarning(APP_NAME, "Please tick the permission checkbox first.")
                return
            sc, note, blocked = resolve_scan(sc)
            if blocked:
                messagebox.showwarning(APP_NAME, "This scan cannot run without root.\n"
                                       "Kali: sudo -E python3 nmapx.py --gui")
                return
            try:
                cmd = build_command(sc, targets, extra)
            except ValueError as exc:
                messagebox.showwarning(APP_NAME, f"Invalid options: {exc}")
                return

            self.write("─" * 70, "info")
            self.write(f"▶ {sc['name']}   [{datetime.now():%H:%M:%S}]", "ok")
            self.write("$ " + " ".join(cmd), "cmd")
            if note:
                self.write("⚠ " + note, "warn")
            self.write("")

            self.scanning = True
            self.pct = None
            self.open_count = 0
            self.start_time = time.time()
            self.open_lbl.config(text="OPEN PORTS: 0")
            self.start_btn.config(state="disabled", bg="#14382c")
            self.stop_btn.config(state="normal", bg=RED)
            self.runner = ScanRunner(cmd, lambda l: self.q.put(("line", l)),
                                     lambda rc, st: self.q.put(("done", rc, st)))
            self.runner.start()

        def stop_scan(self):
            if self.runner and self.scanning:
                self.runner.stop()

        def _handle_line(self, line):
            m = PROGRESS_RE.search(line)
            if m:
                self.pct = float(m.group(1))
                return
            if line.startswith("Stats:"):
                return
            s = line.strip()
            tag = None
            if OPEN_RE.match(s):
                tag = "open"
                self.open_count += 1
                self.open_lbl.config(text=f"OPEN PORTS: {self.open_count}")
            elif re.match(r"^\d+/(tcp|udp)\s+closed", s):
                tag = "closed"
            elif re.match(r"^\d+/(tcp|udp)\s+(filtered|open\|filtered)", s):
                tag = "filtered"
            elif "VULNERABLE" in line:
                tag = "vuln"
            elif line.startswith("Nmap scan report"):
                tag = "host"
            elif line.startswith("Host is up"):
                tag = "ok"
            elif line.startswith("|"):
                tag = "script"
            elif line.startswith(("OS details", "Running", "Service Info", "MAC Address")):
                tag = "osinfo"
            elif line.startswith(("Starting Nmap", "Nmap done")):
                tag = "info"
            self.write(line, tag)

        def _poll(self):
            try:
                while True:
                    item = self.q.get_nowait()
                    if item[0] == "line":
                        self._handle_line(item[1])
                    else:
                        _, rc, stopped = item
                        self.scanning = False
                        self.pct = None
                        elapsed = fmt_time(time.time() - self.start_time)
                        self.start_btn.config(state="normal", bg=ACCENT)
                        self.stop_btn.config(state="disabled", bg="#3a2230")
                        if stopped:
                            self.write(f"\n⚠ Scan stopped ({elapsed})", "warn")
                        elif rc == 0:
                            self.write(f"\n✔ Scan complete  |  Time {elapsed}  |  Open ports: {self.open_count}", "ok")
                        else:
                            self.write(f"\n✘ Scan error (exit code {rc})", "err")
            except queue.Empty:
                pass
            self.after(40, self._poll)

        # ---------- animation ----------
        def _animate(self):
            self.tick += 1
            # radar
            self.angle = (self.angle + (7 if self.scanning else 3)) % 360
            c = self.radar
            c.delete("sweep")
            for i in range(26):
                a = math.radians(self.angle - i * 3.5)
                col = mix(ACCENT, PANEL, i / 26)
                c.create_line(45, 45, 45 + 40 * math.cos(a), 45 + 40 * math.sin(a),
                              fill=col, width=3, tags="sweep")
            for ang, r in self.blips:
                diff = (self.angle - ang) % 360
                if diff < 140:
                    col = mix(ACCENT, PANEL, diff / 140)
                    x = 45 + r * math.cos(math.radians(ang))
                    y = 45 + r * math.sin(math.radians(ang))
                    c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=col, outline="", tags="sweep")

            # title pulse
            t = (math.sin(self.tick / 12) + 1) / 2
            self.title_lbl.config(fg=mix(ACCENT, CYAN, t))

            # progress bar
            p = self.prog
            p.delete("all")
            w = p.winfo_width() or 600
            p.create_rectangle(0, 0, w, 8, fill="#0b121a", outline=BORDER)
            if self.scanning:
                if self.pct is not None:
                    p.create_rectangle(0, 0, w * self.pct / 100, 8, fill=ACCENT, outline="")
                else:
                    seg = 220
                    x0 = (self.tick * 9) % (w + seg) - seg
                    for i in range(22):
                        x1 = x0 + i * seg / 22
                        col = mix(PANEL, ACCENT, math.sin(math.pi * i / 22))
                        p.create_rectangle(max(x1, 0), 1, max(x1 + seg / 22 + 1, 0), 7, fill=col, outline="")

            # status bar
            if self.scanning:
                dots = "." * (self.tick // 8 % 4)
                pct = f" {self.pct:.0f}%" if self.pct is not None else ""
                self.status_lbl.config(text=f"● SCANNING{dots}{pct}", fg=ACCENT if self.tick // 10 % 2 else CYAN)
                self.time_lbl.config(text=f"TIME {fmt_time(time.time() - self.start_time)}", fg=TEXT)
            else:
                self.status_lbl.config(text="● IDLE", fg=MUTED)
            self.after(40, self._animate)

        def _close(self):
            if self.runner and self.scanning:
                self.runner.stop()
            self.destroy()


def gui_main():
    ok, reason = can_use_gui()
    if not ok:
        print(f"\n  {reason}\n  Switching to CLI mode...\n")
        time.sleep(1.2)
        return cli_main()
    try:
        App().mainloop()
    except tk.TclError as exc:
        print(f"\n  The GUI failed to start: {exc}\n  Switching to CLI mode...\n")
        time.sleep(1.2)
        cli_main()


# ----------------------------------------------------------------------------
# Launcher
# ----------------------------------------------------------------------------
def launcher():
    enable_ansi()
    clear_screen()
    animated_banner()
    ok, reason = can_use_gui()
    print(f"  {fg(51)}[1]{R} {BOLD}CLI Mode{R}  {fg(245)}- colorful animated terminal{R}")
    gui_desc = "- professional dashboard" if ok else "- unavailable (no display or tkinter)"
    print(f"  {fg(51)}[2]{R} {BOLD}GUI Mode{R}  {fg(245)}{gui_desc}{R}")
    print(f"  {fg(51)}[0]{R} Exit\n")
    while True:
        c = ask("Choose an interface:")
        if c == "1":
            cli_main()
            return
        if c == "2":
            if not ok:
                print(f"  {fg(203)}✘ {reason}{R}")
                continue
            gui_main()
            return
        if c == "0":
            return
        print(f"  {fg(203)}✘ Enter 0, 1 or 2.{R}")


def main():
    args = sys.argv[1:]
    if "--gui" in args or "-g" in args:
        gui_main()
    elif "--cli" in args or "-c" in args:
        cli_main()
    else:
        launcher()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(f"\n  Exit.")
