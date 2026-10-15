"""Datatelcom System Manager — Windows desktop process supervisor.

Tkinter/ttk only; designed to be packaged with PyInstaller --onefile --windowed.
Every system is explicitly registered via a folder containing root-level app.py.
Each registered system gets application logs and an independent command terminal.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
import ctypes
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from launcher_core import (
    APP_NAME, MAX_SYSTEMS, LauncherConfig, SystemConfig, command_for,
    config_path, create_system, load_config, normalized_folder,
    save_config, update_system,
)
from terminal_ui import CommandTerminal

VERSION = "3.1"
POLL_MS = 100
MAX_OUTPUT_EVENTS = 2500
MAX_VISIBLE_LINES = 1800
MAX_LOG_CHARS = 2800
MAX_CRASH_RESTARTS = 3
CRASH_WINDOW_SEC = 60
ANSI_CODES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")

# Palette
BG = "#0C1220"
PANEL = "#111C2D"
SURFACE = "#172438"
SURFACE_HOVER = "#20334D"
BORDER = "#2A3952"
TEXT = "#E9F0FB"
MUTED = "#92A5BE"
ACCENT = "#4F95F5"
ACCENT_HOVER = "#70A9FA"
GREEN = "#38D6A0"
YELLOW = "#FFD27A"
RED = "#FF778A"
CONSOLE = "#0A1220"


def clean_line(raw: str) -> str:
    """Display untrusted child output as plain text, never as commands or markup."""
    raw = ANSI_CODES.sub("", raw.rstrip("\r\n"))
    cleaned = "".join(c if c in "\t" or ord(c) >= 32 and ord(c) != 127 else " " for c in raw)
    return cleaned.rstrip("\r\n")[:MAX_LOG_CHARS]


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _singleton_mutex() -> int | None:
    if os.name != "nt":
        return None
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    dll.CreateMutexW.restype = ctypes.c_void_p
    handle = dll.CreateMutexW(None, False, "Local\\DatatelcomPOSLauncher")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Unable to create launcher mutex")
    if ctypes.get_last_error() == 183:
        dll.CloseHandle.argtypes = [ctypes.c_void_p]
        dll.CloseHandle(handle)
        return -1
    return int(handle)


def _release_mutex(handle: int | None) -> None:
    if handle and handle > 0 and os.name == "nt":
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(ctypes.c_void_p(handle))


@dataclass
class Runtime:
    config: SystemConfig
    process: subprocess.Popen[str] | None = None
    status: str = "Stopped"
    started_at: float | None = None
    stopping: bool = False
    restart_after_stop: bool = False
    auto_restart_after: str | None = None
    crash_history: deque[float] = field(default_factory=deque)
    restart_timer: str | None = None
    exit_code: int | None = None
    dropped_logs: int = 0
    text: tk.Text | None = None
    tab: tk.Frame | None = None
    header_name: tk.Label | None = None
    tab_status: tk.Label | None = None
    tab_info: tk.Label | None = None
    tab_path: tk.Label | None = None
    start_btn: tk.Button | None = None
    stop_btn: tk.Button | None = None
    restart_btn: tk.Button | None = None
    terminal: CommandTerminal | None = None
    console_tabs: ttk.Notebook | None = None


def ui_button(parent: tk.Misc, label: str, command, *, primary: bool = False,
              danger: bool = False, small: bool = False) -> tk.Button:
    normal = ACCENT if primary else ("#47283B" if danger else SURFACE)
    hover = ACCENT_HOVER if primary else ("#633148" if danger else SURFACE_HOVER)
    btn = tk.Button(
        parent, text=label, command=command, bg=normal, fg=TEXT,
        activebackground=hover, activeforeground=TEXT, borderwidth=0,
        font=("Segoe UI", 9 if small else 10, "bold" if primary else "normal"),
        padx=9 if small else 15, pady=6 if small else 9, cursor="hand2",
        disabledforeground=MUTED, relief="flat", highlightthickness=0,
    )
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover) if str(btn["state"]) == "normal" else None)
    btn.bind("<Leave>", lambda _e: btn.configure(bg=normal))
    return btn


class LauncherUI:
    def __init__(self, root: tk.Tk, mutex: int | None) -> None:
        self.root = root
        self.mutex = mutex
        self.file = config_path()
        self.config, self.config_error = load_config(self.file)
        self.services: dict[str, Runtime] = {cfg.id: Runtime(cfg) for cfg in self.config.systems}
        self.log_events: queue.Queue[tuple[str, subprocess.Popen[str], str]] = queue.Queue(maxsize=MAX_OUTPUT_EVENTS)
        self.lifecycle_events: queue.SimpleQueue[tuple] = queue.SimpleQueue()
        self.closing = False
        self.selected_id: str | None = None
        self.rows: dict[str, tk.Frame] = {}
        self.startup_toggle = tk.BooleanVar(value=self.config.auto_start_on_open)
        self.search_value = tk.StringVar()
        self.search_value.trace_add("write", lambda *_: self._refresh_sidebar())
        self._close_since: float | None = None
        self._theme()
        root.title(f"{APP_NAME}  |  v{VERSION}")
        root.geometry("1250x800")
        root.minsize(900, 660)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build_ui()
        for runtime in self.services.values():
            self._create_tab(runtime)
        self._refresh_sidebar()
        self._refresh_stats()
        if self.config_error:
            messagebox.showwarning("Configuration issue", self.config_error + "\n\nNo systems were loaded. Your existing file was not overwritten.", parent=root)
        self._pump_job: str | None = root.after(POLL_MS, self._pump)
        if not self.config_error and self.config.auto_start_on_open:
            root.after(450, self.start_autostart_systems)

    def _theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Dark.TNotebook", background=PANEL, borderwidth=0, tabmargins=(8, 8, 0, 0),
                        bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, relief="flat")
        style.configure("Dark.TNotebook.Tab", background=SURFACE, foreground=MUTED,
                        padding=(15, 10), borderwidth=0, font=("Segoe UI", 10),
                        bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE, relief="flat")
        style.map("Dark.TNotebook.Tab", background=[("selected", SURFACE_HOVER), ("active", SURFACE_HOVER)],
                  foreground=[("selected", TEXT), ("active", TEXT)])
        style.configure("Console.Dark.TNotebook.Tab", padding=(10, 3), font=("Segoe UI", 9))
        style.configure("Dark.Vertical.TScrollbar", background=SURFACE, troughcolor=PANEL,
                        borderwidth=0, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=SURFACE, darkcolor=SURFACE)
        style.configure("Dark.TEntry", fieldbackground=SURFACE, foreground=TEXT, padding=7,
                        insertcolor=TEXT, bordercolor=BORDER)

    def _label(self, parent: tk.Misc, title: str, *, color: str = TEXT, size: int = 10,
               bold: bool = False, bg: str | None = None, wraplength: int = 0) -> tk.Label:
        return tk.Label(parent, text=title, bg=bg or PANEL, fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"),
                        anchor="w", wraplength=wraplength, justify="left")

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg=BG, padx=24, pady=12)
        top.pack(fill="x")
        head = tk.Frame(top, bg=BG)
        head.pack(side="left", fill="x", expand=True)
        self._label(head, "DATATELCOM  /  SYSTEM MANAGER", bg=BG,
                    size=18, bold=True).pack(anchor="w")
        self._label(head, "A single workspace for your Python systems and their live terminals",
                    bg=BG, color=MUTED, size=10).pack(anchor="w", pady=(4, 0))
        ui_button(top, "+  Add System", self.add_system, primary=True).pack(side="right")

        actions = tk.Frame(self.root, bg=BG, padx=24)
        actions.pack(fill="x", pady=(0, 12))
        ui_button(actions, "Start All", self.start_all).pack(side="left", padx=(0, 7))
        ui_button(actions, "Stop All", self.stop_all, danger=True).pack(side="left", padx=(0, 7))
        ui_button(actions, "Restart All", self.restart_all).pack(side="left", padx=(0, 18))
        start_check = tk.Checkbutton(
            actions, text="Auto-start enabled systems on launch", variable=self.startup_toggle,
            command=self._change_global_autostart, bg=BG, fg=MUTED,
            activebackground=BG, activeforeground=TEXT, selectcolor=SURFACE,
            font=("Segoe UI", 10), cursor="hand2"
        )
        start_check.pack(side="left")

        stats = tk.Frame(self.root, bg=BG, padx=24)
        stats.pack(fill="x", pady=(0, 14))
        self.stats_labels = {}
        for label, caption, color in (("systems", "REGISTERED SYSTEMS", ACCENT),
                                      ("running", "RUNNING NOW", GREEN),
                                      ("issues", "NEED ATTENTION", YELLOW)):
            card = tk.Frame(stats, bg=PANEL, padx=17, pady=10, highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 9))
            self._label(card, caption, color=MUTED, bg=PANEL, size=9, bold=True).pack(anchor="w")
            value = self._label(card, "0", color=color, bg=PANEL, size=21, bold=True)
            value.pack(anchor="w", pady=(3, 0))
            self.stats_labels[label] = value

        body = tk.Frame(self.root, bg=BG, padx=24)
        body.pack(fill="both", expand=True, pady=(0, 13))

        sidebar = tk.Frame(body, bg=PANEL, width=322, highlightbackground=BORDER, highlightthickness=1)
        sidebar.pack(side="left", fill="y", padx=(0, 14))
        sidebar.pack_propagate(False)
        sidebar_header = tk.Frame(sidebar, bg=PANEL, padx=13, pady=12)
        sidebar_header.pack(fill="x")
        self._label(sidebar_header, "SYSTEMS", color=MUTED, size=10, bold=True).pack(anchor="w")
        search = tk.Entry(sidebar_header, textvariable=self.search_value, bg=SURFACE, fg=TEXT,
                          insertbackground=TEXT, borderwidth=0, font=("Segoe UI", 10),
                          highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        search.pack(fill="x", pady=(12, 0), ipady=9)
        self._label(sidebar_header, "Filter systems by name or folder", color=MUTED, size=9).pack(
            anchor="w", pady=(6, 0))

        side_list_wrap = tk.Frame(sidebar, bg=PANEL)
        side_list_wrap.pack(fill="both", expand=True)
        self.side_canvas = tk.Canvas(side_list_wrap, bg=PANEL, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(side_list_wrap, orient="vertical", command=self.side_canvas.yview,
                               style="Dark.Vertical.TScrollbar")
        self.side_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.side_canvas.pack(side="left", fill="both", expand=True)
        self.side_list = tk.Frame(self.side_canvas, bg=PANEL)
        self.side_window = self.side_canvas.create_window((0, 0), window=self.side_list, anchor="nw")
        self.side_list.bind("<Configure>", lambda _e: self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all")))
        self.side_canvas.bind("<Configure>", lambda e: self.side_canvas.itemconfigure(self.side_window, width=e.width))

        right = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        right.pack(side="left", fill="both", expand=True)
        self.notebook = ttk.Notebook(right, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.home_tab = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(self.home_tab, text="  Overview  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self._build_home()

        foot = tk.Frame(self.root, bg=BG, padx=24, pady=8)
        foot.pack(fill="x")
        self.footer = self._label(foot, "Ready", color=MUTED, bg=BG, size=9)
        self.footer.pack(side="left")
        self._label(foot, f"VERSION {VERSION}    •    WINDOWS", color=MUTED, bg=BG, size=9).pack(side="right")

    def _build_home(self) -> None:
        page = tk.Frame(self.home_tab, bg=PANEL, padx=29, pady=28)
        page.pack(fill="both", expand=True)
        self._label(page, "Workspace overview", size=22, bold=True).pack(anchor="w")
        self._label(page, "Select a system from the left to open its dedicated live terminal.",
                    color=MUTED, size=11).pack(anchor="w", pady=(7, 24))
        steps = (
            ("01", "Add a Python system", "Browse to a folder that contains app.py directly inside it."),
            ("02", "Manage it independently", "Start, stop and restart without affecting other systems."),
            ("03", "Use its terminal", "Run Python, pip and Git in each system's folder; view application logs alongside."),
            ("04", "Set launch behavior", "Rename systems, select Python and configure auto-start / crash recovery."),
        )
        for number, title, description in steps:
            section = tk.Frame(page, bg=SURFACE, padx=17, pady=13, highlightbackground=BORDER, highlightthickness=1)
            section.pack(fill="x", pady=(0, 9))
            self._label(section, number, color=ACCENT, bg=SURFACE, bold=True, size=10).pack(side="left", padx=(0, 15))
            column = tk.Frame(section, bg=SURFACE)
            column.pack(side="left", fill="x", expand=True)
            self._label(column, title, bg=SURFACE, size=11, bold=True).pack(anchor="w")
            self._label(column, description, color=MUTED, bg=SURFACE, size=9, wraplength=530).pack(anchor="w", pady=(2, 0))
        self.home_footer = self._label(page, "No systems registered. Click + Add System to begin.",
                                       color=MUTED, size=10)
        self.home_footer.pack(anchor="w", pady=(17, 0))

    def _status_color(self, status: str) -> str:
        if status.startswith("Running"):
            return GREEN
        if status.startswith("Starting") or status.startswith("Stopping") or status.startswith("Restarting"):
            return YELLOW
        if status.startswith("Error") or status.startswith("Exited") or status.startswith("Crash"):
            return RED
        return MUTED

    def _tab_changed(self, _event=None) -> None:
        current = self.notebook.select()
        if not current:
            return
        self.selected_id = next((k for k, r in self.services.items()
                                 if r.tab is not None and str(r.tab) == current), None)
        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        if not hasattr(self, "side_list"):
            return
        for child in self.side_list.winfo_children():
            child.destroy()
        self.rows.clear()
        query_text = self.search_value.get().strip().casefold()
        visible = [r for r in self.services.values()
                   if query_text in r.config.name.casefold() or query_text in r.config.folder.casefold()]
        if not visible:
            empty = self._label(self.side_list, "No matching systems." if self.services else "No systems added yet.",
                                color=MUTED, size=10, wraplength=245)
            empty.pack(fill="x", padx=16, pady=24)
            return
        for rt in visible:
            key = rt.config.id
            selected = key == self.selected_id
            background = SURFACE_HOVER if selected else SURFACE
            card = tk.Frame(self.side_list, bg=background, padx=12, pady=10,
                            highlightthickness=1, highlightbackground=ACCENT if selected else BORDER)
            card.pack(fill="x", padx=10, pady=5)
            self.rows[key] = card
            name = self._label(card, rt.config.name, bg=background, size=11, bold=True)
            name.pack(anchor="w", fill="x")
            name.configure(wraplength=255)
            path_label = self._label(card, rt.config.folder, color=MUTED, bg=background, size=9)
            path_label.pack(anchor="w", fill="x", pady=(4, 0))
            path_label.configure(wraplength=270)
            status = self._label(card, "●  " + rt.status, color=self._status_color(rt.status), bg=background, size=9)
            status.pack(anchor="w", pady=(7, 0))
            for widget in (card, name, path_label, status):
                widget.bind("<Button-1>", lambda _e, ident=key: self.select_system(ident))
                widget.configure(cursor="hand2")
            controls = tk.Frame(card, bg=background)
            controls.pack(fill="x", pady=(9, 0))
            ui_button(controls, "Terminal", lambda ident=key: self.select_system(ident), small=True).pack(
                side="left", padx=(0, 5))
            ui_button(controls, "Settings", lambda ident=key: self.edit_system(ident), small=True).pack(side="left")

    def _refresh_stats(self) -> None:
        registered = len(self.services)
        running = sum(bool(r.process and r.process.poll() is None) for r in self.services.values())
        issues = sum(r.status.startswith(("Error", "Exited", "Crash")) for r in self.services.values())
        self.stats_labels["systems"].configure(text=str(registered))
        self.stats_labels["running"].configure(text=str(running))
        self.stats_labels["issues"].configure(text=str(issues))
        self.home_footer.configure(text=(f"{registered} registered  •  {running} running  •  {issues} need attention"
                                         if registered else "No systems registered. Click + Add System to begin."))

    def _set_status(self, rt: Runtime, value: str) -> None:
        rt.status = value
        running = rt.process is not None and rt.process.poll() is None
        if rt.tab_status is not None:
            rt.tab_status.configure(text="●  " + value, fg=self._status_color(value))
        if rt.start_btn is not None:
            rt.start_btn.configure(state="disabled" if running or rt.stopping or self.closing else "normal")
        if rt.stop_btn is not None:
            rt.stop_btn.configure(state="normal" if (running or rt.restart_timer) and not rt.stopping and not self.closing else "disabled")
        if rt.restart_btn is not None:
            rt.restart_btn.configure(state="disabled" if rt.stopping or self.closing else "normal")
        self._refresh_sidebar()
        self._refresh_stats()

    def _create_tab(self, rt: Runtime) -> None:
        panel = tk.Frame(self.notebook, bg=PANEL)
        rt.tab = panel
        self.notebook.add(panel, text=self._tab_label(rt.config.name))
        header = tk.Frame(panel, bg=PANEL, padx=18, pady=7)
        header.pack(fill="x")
        rt.header_name = self._label(header, rt.config.name, size=15, bold=True)
        rt.header_name.pack(side="left")
        rt.tab_status = self._label(header, "●  Stopped", color=MUTED, size=10, bold=True)
        rt.tab_status.pack(side="right")
        details = tk.Frame(panel, bg=PANEL, padx=18)
        details.pack(fill="x")
        rt.tab_info = self._label(details, "PID —   •   Uptime —", color=MUTED, size=9)
        rt.tab_info.pack(side="right")
        rt.tab_path = self._label(details, rt.config.folder, color=MUTED, size=9)
        rt.tab_path.pack(side="left", fill="x", expand=True)

        controls = tk.Frame(panel, bg=PANEL, padx=22, pady=8)
        controls.pack(fill="x")
        rt.start_btn = ui_button(controls, "Start", lambda key=rt.config.id: self.start(key), primary=True)
        rt.start_btn.pack(side="left", padx=(0, 7))
        rt.stop_btn = ui_button(controls, "Stop", lambda key=rt.config.id: self.stop(key), danger=True)
        rt.stop_btn.pack(side="left", padx=(0, 7))
        rt.restart_btn = ui_button(controls, "Restart", lambda key=rt.config.id: self.restart(key))
        rt.restart_btn.pack(side="left", padx=(0, 7))
        ui_button(controls, "Settings", lambda key=rt.config.id: self.edit_system(key)).pack(side="right")
        ui_button(controls, "Open Folder", lambda key=rt.config.id: self.open_folder(key)).pack(side="right", padx=(0, 7))

        rt.console_tabs = ttk.Notebook(panel, style="Console.Dark.TNotebook")
        rt.console_tabs.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        rt.terminal = CommandTerminal(rt.console_tabs, rt.config)
        rt.console_tabs.add(rt.terminal, text="Command Terminal")
        log_outer = tk.Frame(rt.console_tabs, bg=PANEL, padx=8, pady=8)
        rt.console_tabs.add(log_outer, text="Application Logs")
        console_title = tk.Frame(log_outer, bg=SURFACE, padx=12, pady=9)
        console_title.pack(fill="x")
        self._label(console_title, "APPLICATION  /  STDOUT + STDERR", bg=SURFACE,
                    color=MUTED, size=9, bold=True).pack(side="left")
        ui_button(console_title, "Save Log", lambda key=rt.config.id: self.save_log(key), small=True).pack(side="right")
        ui_button(console_title, "Copy", lambda key=rt.config.id: self.copy_log(key), small=True).pack(side="right", padx=(0, 6))
        ui_button(console_title, "Clear", lambda key=rt.config.id: self.clear_log(key), small=True).pack(side="right", padx=(0, 6))
        log_area = tk.Frame(log_outer, bg=CONSOLE)
        log_area.pack(fill="both", expand=True)
        text = tk.Text(log_area, bg=CONSOLE, fg="#CEDCED", insertbackground=TEXT,
                       selectbackground="#345E91", font=("Consolas", 10),
                       relief="flat", bd=0, padx=14, pady=14, wrap="word", state="disabled",
                       undo=False, highlightthickness=0)
        vertical = ttk.Scrollbar(log_area, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vertical.set)
        vertical.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("meta", foreground="#73A7DF")
        text.tag_configure("error", foreground=RED)
        text.tag_configure("output", foreground="#D6E4F5")
        rt.text = text
        self._append(rt, "meta", f"Terminal initialized for {rt.config.name}")
        self._append(rt, "meta", "Application output appears here. Use Command Terminal to run commands in this system's folder.")
        self._set_status(rt, "Stopped")

    @staticmethod
    def _tab_label(name: str) -> str:
        return (name[:17] + "…") if len(name) > 18 else name

    def select_system(self, key: str) -> None:
        rt = self.services.get(key)
        if rt and rt.tab:
            self.notebook.select(rt.tab)
            self.selected_id = key
            self._refresh_sidebar()

    def _append(self, rt: Runtime, tag: str, text: str) -> None:
        widget = rt.text
        if widget is None:
            return
        text = clean_line(text)
        stamp = timestamp()
        at_bottom = widget.yview()[1] >= 0.97
        widget.configure(state="normal")
        widget.insert("end", f"[{stamp}]  {text}\n", tag)
        total = int(widget.index("end-1c").split(".")[0])
        if total > MAX_VISIBLE_LINES:
            widget.delete("1.0", "201.0")
        if at_bottom:
            widget.see("end")
        widget.configure(state="disabled")

    def _set_footer(self, message: str) -> None:
        self.footer.configure(text=f"{timestamp()}   {message}")

    def _persist(self, new: LauncherConfig) -> bool:
        try:
            save_config(self.file, new)
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)
            return False
        self.config = new
        return True

    def _change_global_autostart(self) -> None:
        enabled = self.startup_toggle.get()
        if not self._persist(replace(self.config, auto_start_on_open=enabled)):
            self.startup_toggle.set(self.config.auto_start_on_open)
        else:
            self._set_footer("Automatic startup " + ("enabled" if enabled else "disabled"))

    def add_system(self) -> None:
        if self.closing:
            return
        folder_name = filedialog.askdirectory(parent=self.root, title="Choose a folder with app.py at its root", mustexist=True)
        if not folder_name:
            return
        try:
            cfg = create_system(Path(folder_name))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot add system", str(exc), parent=self.root)
            return
        if any(normalized_folder(Path(r.config.folder)) == normalized_folder(Path(cfg.folder))
               for r in self.services.values()):
            messagebox.showinfo("Already registered", "This folder has already been added.", parent=self.root)
            return
        if len(self.services) >= MAX_SYSTEMS:
            messagebox.showerror("System limit", f"Maximum of {MAX_SYSTEMS} systems reached.", parent=self.root)
            return
        if not self._persist(replace(self.config, systems=self.config.systems + (cfg,))):
            return
        rt = Runtime(cfg)
        self.services[cfg.id] = rt
        self._create_tab(rt)
        self.select_system(cfg.id)
        self._refresh_stats()
        self._set_footer(f"Added {cfg.name}")
        self.start(cfg.id)

    def edit_system(self, key: str) -> None:
        rt = self.services.get(key)
        if rt is None or self.closing:
            return
        cfg = rt.config
        dialog = tk.Toplevel(self.root, bg=PANEL)
        dialog.title("System Settings — " + cfg.name)
        dialog.geometry("560x510")
        dialog.minsize(480, 480)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        form = tk.Frame(dialog, bg=PANEL, padx=26, pady=24)
        form.pack(fill="both", expand=True)
        self._label(form, "System settings", size=19, bold=True).pack(anchor="w")
        self._label(form, cfg.folder, color=MUTED, size=9, wraplength=500).pack(anchor="w", pady=(3, 22))
        name_var = tk.StringVar(value=cfg.name)
        python_var = tk.StringVar(value=cfg.python_path or "")
        autostart_var = tk.BooleanVar(value=cfg.auto_start)
        recovery_var = tk.BooleanVar(value=cfg.restart_on_crash)
        self._label(form, "Display name", color=MUTED, size=10, bold=True).pack(anchor="w")
        name_field = tk.Entry(form, textvariable=name_var, bg=SURFACE, fg=TEXT,
                              insertbackground=TEXT, borderwidth=0, font=("Segoe UI", 11))
        name_field.pack(fill="x", pady=(6, 17), ipady=9)
        tk.Checkbutton(form, text="Auto-start this system when launcher opens", variable=autostart_var,
                       bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=TEXT,
                       selectcolor=SURFACE, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 10))
        tk.Checkbutton(form, text="Restart on crash (max 3 attempts per minute)", variable=recovery_var,
                       bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=TEXT,
                       selectcolor=SURFACE, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 20))
        self._label(form, "Python interpreter (optional)", color=MUTED, size=10, bold=True).pack(anchor="w")
        py_row = tk.Frame(form, bg=PANEL)
        py_row.pack(fill="x", pady=(6, 5))
        py_field = tk.Entry(py_row, textvariable=python_var, bg=SURFACE, fg=TEXT,
                            insertbackground=TEXT, borderwidth=0, font=("Segoe UI", 10))
        py_field.pack(side="left", fill="x", expand=True, ipady=9)

        def browse_python() -> None:
            candidate = filedialog.askopenfilename(parent=dialog, title="Choose python.exe",
                                                    filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
            if candidate:
                python_var.set(candidate)
        ui_button(py_row, "Browse", browse_python, small=True).pack(side="left", padx=(6, 0))
        self._label(form, "Leave blank to use .venv, venv, or Python from PATH.", color=MUTED, size=9).pack(anchor="w")

        bottom = tk.Frame(form, bg=PANEL)
        bottom.pack(fill="x", side="bottom", pady=(23, 0))

        def save() -> None:
            try:
                changed = update_system(cfg, name=name_var.get(), auto_start=autostart_var.get(),
                                        restart_on_crash=recovery_var.get(), python_path=python_var.get() or None)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Invalid system settings", str(exc), parent=dialog)
                return
            all_configs = tuple(changed if s.id == key else s for s in self.config.systems)
            if not self._persist(replace(self.config, systems=all_configs)):
                return
            rt.config = changed
            if rt.terminal:
                rt.terminal.session.config = changed
            rt.header_name.configure(text=changed.name)
            rt.tab_path.configure(text=changed.folder)
            self.notebook.tab(rt.tab, text=self._tab_label(changed.name))
            self._refresh_sidebar()
            self._set_footer(f"Updated {changed.name}")
            dialog.destroy()

        ui_button(bottom, "Save Changes", save, primary=True).pack(side="right", padx=(8, 0))
        ui_button(bottom, "Cancel", dialog.destroy).pack(side="right")
        ui_button(bottom, "Remove System", lambda: (dialog.destroy(), self.remove_system(key)),
                  danger=True).pack(side="left")
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        name_field.focus_set()

    def remove_system(self, key: str) -> None:
        rt = self.services.get(key)
        if rt is None or self.closing:
            return
        if rt.stopping or (rt.process and rt.process.poll() is None) or (rt.terminal and rt.terminal.session.busy):
            messagebox.showwarning("Stop first", "Stop this system and its terminal command before removing it.", parent=self.root)
            return
        if not messagebox.askyesno("Remove system", f"Remove '{rt.config.name}' from the launcher?\n\n"
                                   "The application's folder and files will not be deleted.", parent=self.root):
            return
        new_config = replace(self.config, systems=tuple(s for s in self.config.systems if s.id != key))
        if not self._persist(new_config):
            return
        self._cancel_auto_restart(rt)
        if rt.tab:
            self.notebook.select(self.home_tab)
            self.notebook.forget(rt.tab)
            rt.tab.destroy()
        del self.services[key]
        self.selected_id = None
        self._refresh_sidebar()
        self._refresh_stats()
        self._set_footer(f"Removed {rt.config.name} (files kept)")

    def open_folder(self, key: str) -> None:
        rt = self.services.get(key)
        if rt is None:
            return
        folder = Path(rt.config.folder)
        if not folder.is_dir():
            messagebox.showerror("Folder missing", f"Folder not found:\n{folder}", parent=self.root)
            return
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]  # Windows shell, no subprocess shell=True
        except OSError as exc:
            messagebox.showerror("Cannot open folder", str(exc), parent=self.root)

    def _cancel_auto_restart(self, rt: Runtime) -> None:
        if rt.restart_timer:
            try:
                self.root.after_cancel(rt.restart_timer)
            except (ValueError, tk.TclError):
                pass
            rt.restart_timer = None

    def start(self, key: str) -> None:
        rt = self.services.get(key)
        if rt is None or self.closing or rt.stopping:
            return
        if rt.process and rt.process.poll() is None:
            return
        self._cancel_auto_restart(rt)
        rt.process = None
        rt.exit_code = None
        self._set_status(rt, "Starting…")
        try:
            argv, cwd = command_for(rt.config)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                argv, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                env=env, creationflags=flags,
            )
        except (OSError, ValueError) as exc:
            self._set_status(rt, "Error: could not start")
            self._append(rt, "error", f"Launch failed: {type(exc).__name__}: {exc}")
            self._set_footer(f"Could not start {rt.config.name}")
            return
        rt.process = proc
        rt.started_at = time.monotonic()
        self._set_status(rt, "Running")
        self._append(rt, "meta", f"Started PID {proc.pid}  •  Interpreter: {argv[0]}")
        self._set_footer(f"Started {rt.config.name} (PID {proc.pid})")
        threading.Thread(target=self._stream_output, args=(key, proc), daemon=True).start()
        threading.Thread(target=self._wait_for_exit, args=(key, proc), daemon=True).start()

    def _stream_output(self, key: str, proc: subprocess.Popen[str]) -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            while True:
                chunk = stream.readline(4096)  # Bound a single log event / enormous line.
                if not chunk:
                    break
                try:
                    self.log_events.put_nowait((key, proc, chunk))
                except queue.Full:
                    # Child stdout is still drained to avoid pipe deadlock.
                    pass
        except (OSError, UnicodeError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _wait_for_exit(self, key: str, proc: subprocess.Popen[str]) -> None:
        try:
            code = proc.wait()
        except OSError as exc:
            code = f"wait failed: {exc}"
        self.lifecycle_events.put(("exit", key, proc, code))

    def stop(self, key: str, *, restart: bool = False) -> None:
        rt = self.services.get(key)
        if rt is None or rt.stopping:
            return
        self._cancel_auto_restart(rt)
        proc = rt.process
        if proc is None or proc.poll() is not None:
            rt.process = None
            self._set_status(rt, "Stopped")
            if restart and not self.closing:
                self.start(key)
            return
        rt.stopping = True
        rt.restart_after_stop = restart and not self.closing
        self._set_status(rt, "Stopping…")
        threading.Thread(target=self._stop_tree, args=(key, proc), daemon=True).start()

    def _stop_tree(self, key: str, proc: subprocess.Popen[str]) -> None:
        error: str | None = None
        try:
            if proc.poll() is None:
                if os.name == "nt":
                    # Only this tracked PID and its descendants, never taskkill /IM python.exe.
                    result = subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12,
                        creationflags=subprocess.CREATE_NO_WINDOW, check=False,
                    )
                    if result.returncode and proc.poll() is None:
                        error = "taskkill could not stop the process tree (check access rights)."
                else:
                    proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f"Failed to stop: {type(exc).__name__}: {exc}"
        self.lifecycle_events.put(("stopped", key, proc, error))

    def restart(self, key: str) -> None:
        self.stop(key, restart=True)

    def start_autostart_systems(self) -> None:
        if not self.closing:
            for key, rt in list(self.services.items()):
                if rt.config.auto_start:
                    self.start(key)

    def start_all(self) -> None:
        if not self.closing:
            for key in list(self.services):
                self.start(key)

    def stop_all(self) -> None:
        if self.closing:
            return
        for key in list(self.services):
            self.stop(key)

    def restart_all(self) -> None:
        if not self.closing:
            for key in list(self.services):
                self.restart(key)

    def _handle_exit(self, rt: Runtime, proc: subprocess.Popen[str], code: object) -> None:
        if rt.process is not proc or rt.stopping:
            return
        rt.exit_code = code if isinstance(code, int) else None
        rt.process = None
        self._append(rt, "meta" if code == 0 else "error", f"Process ended with exit code {code}")
        if code == 0:
            self._set_status(rt, "Stopped")
        else:
            self._set_status(rt, f"Exited ({code})")
        self._set_footer(f"{rt.config.name} exited: {code}")
        if self.closing or code == 0 or not rt.config.restart_on_crash:
            return
        now = time.monotonic()
        while rt.crash_history and now - rt.crash_history[0] > CRASH_WINDOW_SEC:
            rt.crash_history.popleft()
        if len(rt.crash_history) >= MAX_CRASH_RESTARTS:
            self._set_status(rt, "Crash loop — restart paused")
            self._append(rt, "error", "Crash recovery paused after 3 attempts in 60 seconds.")
            return
        rt.crash_history.append(now)
        delay = 2 ** (len(rt.crash_history) - 1)
        self._set_status(rt, f"Restarting in {delay}s…")
        self._append(rt, "meta", f"Crash recovery will retry after {delay} seconds")
        rt.restart_timer = self.root.after(delay * 1000, lambda key=rt.config.id: self.start(key))

    def _handle_stopped(self, rt: Runtime, proc: subprocess.Popen[str], error: str | None) -> None:
        if rt.process is not proc:
            return
        rt.stopping = False
        if proc.poll() is None:
            rt.restart_after_stop = False
            self._set_status(rt, "Error: still running")
            self._append(rt, "error", error or "Could not terminate the process")
            return
        rt.process = None
        should_restart = rt.restart_after_stop and not self.closing
        rt.restart_after_stop = False
        self._append(rt, "meta" if not error else "error", error or "Process stopped")
        self._set_status(rt, "Stopped")
        if should_restart:
            self.start(rt.config.id)

    def _pump(self) -> None:
        if not self.root.winfo_exists():
            return
        # Exit/stop signals cannot be starved by log-heavy processes.
        for _ in range(200):
            try:
                kind, key, proc, value = self.lifecycle_events.get_nowait()
            except queue.Empty:
                break
            rt = self.services.get(key)
            if rt is None:
                continue
            if kind == "exit":
                self._handle_exit(rt, proc, value)
            elif kind == "stopped":
                self._handle_stopped(rt, proc, value)
        for _ in range(270):
            try:
                key, proc, line = self.log_events.get_nowait()
            except queue.Empty:
                break
            rt = self.services.get(key)
            if rt is None:
                continue
            # Drain buffered logs belonging to previous run until a subsequent restart;
            # never mix an old process's output with the new one.
            if rt.process is not proc and rt.process is not None:
                continue
            self._append(rt, "output", line)
        for rt in self.services.values():
            if rt.tab_info is None:
                continue
            if rt.process and rt.process.poll() is None:
                elapsed = int(time.monotonic() - (rt.started_at or time.monotonic()))
                rt.tab_info.configure(text=f"PID {rt.process.pid}    •    Uptime {elapsed // 3600:02d}:{(elapsed // 60) % 60:02d}:{elapsed % 60:02d}")
            else:
                rt.tab_info.configure(text=f"PID —    •    Exit {rt.exit_code if rt.exit_code is not None else '—'}")
        # Continue draining lifecycle events during shutdown so Stopping state clears.
        self._pump_job = self.root.after(POLL_MS, self._pump)

    def _cancel_pump(self) -> None:
        if self._pump_job:
            try:
                self.root.after_cancel(self._pump_job)
            except (tk.TclError, ValueError):
                pass
            self._pump_job = None

    def clear_log(self, key: str) -> None:
        rt = self.services.get(key)
        if rt and rt.text:
            rt.text.configure(state="normal")
            rt.text.delete("1.0", "end")
            rt.text.configure(state="disabled")
            self._append(rt, "meta", "Terminal cleared")

    def copy_log(self, key: str) -> None:
        rt = self.services.get(key)
        if rt and rt.text:
            content = rt.text.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self._set_footer(f"Copied {rt.config.name} log")

    def save_log(self, key: str) -> None:
        rt = self.services.get(key)
        if rt is None or rt.text is None:
            return
        filename = filedialog.asksaveasfilename(parent=self.root, title="Export terminal log",
                                                defaultextension=".log", filetypes=[("Log files", "*.log"),
                                                                                     ("Text files", "*.txt")])
        if not filename:
            return
        content = rt.text.get("1.0", "end-1c")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        self._set_footer(f"Saved log for {rt.config.name}")

    def close(self) -> None:
        if self.closing:
            return
        alive = [rt for rt in self.services.values() if (rt.process and rt.process.poll() is None)
                 or (rt.terminal and rt.terminal.session.busy)]
        if alive and not messagebox.askyesno(
            "Quit System Manager",
            f"Exit and force-stop applications and terminal commands in {len(alive)} system(s)?\n\n"
            "Unsaved transactions in the systems may be lost.", parent=self.root,
        ):
            return
        self.closing = True
        self._close_since = time.monotonic()
        self._set_footer("Shutting down managed processes…")
        for rt in self.services.values():
            self._cancel_auto_restart(rt)
            rt.restart_after_stop = False
            if rt.terminal:
                rt.terminal.session.close()
        for key in list(self.services):
            self.stop(key)
        self.root.after(POLL_MS, self._check_shutdown)

    def _check_shutdown(self) -> None:
        if not self.closing or not self.root.winfo_exists():
            return
        pending = any(rt.stopping or rt.process and rt.process.poll() is None
                      or rt.terminal and rt.terminal.session.busy for rt in self.services.values())
        if not pending:
            self._cancel_pump()
            _release_mutex(self.mutex)
            self.root.destroy()
            return
        if time.monotonic() - (self._close_since or time.monotonic()) > 16:
            if messagebox.askyesno("Processes still running", "Some processes could not be stopped.\n"
                                     "Exit the manager anyway? Those processes may remain running.", parent=self.root):
                self._cancel_pump()
                _release_mutex(self.mutex)
                self.root.destroy()
            else:
                self.closing = False
                for rt in self.services.values():
                    if rt.terminal:
                        rt.terminal.session.closed = False
                    self._set_status(rt, rt.status)
                self._set_footer("Close canceled — some processes may remain running")
            return
        self.root.after(250, self._check_shutdown)


def main() -> None:
    root = tk.Tk()
    if os.name != "nt":
        root.withdraw()
        messagebox.showerror(APP_NAME, "This GUI is supported on Windows 10/11.\nThe core tests are cross-platform.")
        root.destroy()
        return
    try:
        mutex = _singleton_mutex()
    except OSError as exc:
        root.withdraw()
        messagebox.showerror(APP_NAME, str(exc))
        root.destroy()
        return
    if mutex == -1:
        root.withdraw()
        messagebox.showinfo(APP_NAME, "The launcher is already running in this Windows session.")
        root.destroy()
        return
    LauncherUI(root, mutex)
    root.mainloop()


if __name__ == "__main__":
    main()
