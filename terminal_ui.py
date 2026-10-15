"""Tkinter command terminal embedded in each system tab."""
from __future__ import annotations

from collections import deque
import queue
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from launcher_core import SystemConfig
from terminal_session import TerminalSession

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


class CommandTerminal(tk.Frame):
    def __init__(self, parent: tk.Misc, config: SystemConfig):
        super().__init__(parent, bg="#111C2D", padx=12, pady=10)
        self.session = TerminalSession(config)
        self.history: deque[str] = deque(maxlen=100)
        self.history_index = 0
        self.draft = ""
        self._job = None
        bar = tk.Frame(self, bg=self["bg"])
        bar.pack(fill="x")
        self.status = tk.Label(bar, bg=self["bg"], fg="#92A5BE", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.stop_button = self._button(bar, "Stop command", self.session.stop)
        self.stop_button.pack(side="right")
        self._button(bar, "Clear", self.clear).pack(side="right", padx=5)
        self._button(bar, "Save", self.save).pack(side="right")
        area = tk.Frame(self, bg="#0A1220")
        area.pack(fill="both", expand=True, pady=(8, 6))
        self.output = tk.Text(area, bg="#0A1220", fg="#D6E4F5", font=("Consolas", 10),
                              wrap="word", state="disabled", relief="flat", padx=12, pady=10,
                              selectbackground="#345E91", highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, command=self.output.yview)
        scrollbar.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(fill="both", expand=True)
        self.output.tag_configure("command", foreground="#38D6A0")
        self.output.tag_configure("error", foreground="#FF778A")
        self.output.tag_configure("meta", foreground="#73A7DF")
        row = tk.Frame(self, bg=self["bg"])
        # Reserve the input row before the expanding output area at small sizes.
        row.pack(side="bottom", fill="x", before=area)
        self.prompt = tk.Label(row, text=">", bg=self["bg"], fg="#38D6A0", font=("Consolas", 12))
        self.prompt.pack(side="left", padx=(0, 8))
        self.entry = tk.Entry(row, bg="#172438", fg="#E9F0FB", insertbackground="#E9F0FB",
                              font=("Consolas", 11), relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.run_button = self._button(row, "Run", self.submit)
        self.run_button.pack(side="right", padx=(8, 0))
        self.entry.bind("<Return>", self.submit)
        self.entry.bind("<Up>", lambda event: self.recall(-1))
        self.entry.bind("<Down>", lambda event: self.recall(1))
        self.entry.bind("<Control-c>", self._interrupt)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.append("meta", "Integrated terminal ready. Type help for commands. Up/Down: history.\n"
                    "Use Python, pip and installed executables here. No external console opens.\n")
        self._poll()

    @staticmethod
    def _button(parent, label, command):
        return tk.Button(parent, text=label, command=command, bg="#172438", fg="#E9F0FB",
                         activebackground="#20334D", activeforeground="#E9F0FB", relief="flat",
                         padx=10, pady=6, disabledforeground="#92A5BE", cursor="hand2")

    def submit(self, _event=None):
        if self.session.closed:
            return "break"
        command = self.entry.get()
        if self.session.busy:
            accepted = self.session.send_input(command)
            if accepted:
                # Do not echo responses: they might be passwords or other secrets.
                self.append("meta", "[Input sent]\n")
        else:
            accepted = self.session.execute(command)
            if accepted:
                if not self.history or self.history[-1] != command:
                    self.history.append(command)
                self.history_index = len(self.history)
                self.draft = ""
        if accepted:
            self.entry.delete(0, "end")
        self.entry.focus_set()
        return "break"

    def recall(self, direction: int):
        if self.session.busy:
            return "break"
        if self.history_index == len(self.history):
            self.draft = self.entry.get()
        self.history_index = max(0, min(len(self.history), self.history_index + direction))
        value = self.history[self.history_index] if self.history_index < len(self.history) else self.draft
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        self.entry.icursor("end")
        return "break"

    def _interrupt(self, _event):
        if self.session.busy:
            self.session.stop()
            return "break"
        return None

    def append(self, kind: str, text: str):
        text = ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
        text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32 and ord(c) != 127)
        at_bottom = self.output.yview()[1] >= 0.97
        self.output.configure(state="normal")
        self.output.insert("end", text, kind)
        # Bound both long unterminated lines and ordinary multiline output.
        count = int(self.output.count("1.0", "end-1c", "chars")[0])
        if count > 300000:
            self.output.delete("1.0", f"1.0+{count - 250000}c")
        lines = int(self.output.index("end-1c").split(".")[0])
        if lines > 1800:
            self.output.delete("1.0", f"{lines - 1600}.0")
        self.output.configure(state="disabled")
        if at_bottom:
            self.output.see("end")

    def clear(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def save(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save command terminal", defaultextension=".log",
                                           filetypes=[("Log files", "*.log"), ("Text files", "*.txt")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as file:
                    file.write(self.output.get("1.0", "end-1c"))
            except OSError as exc:
                messagebox.showerror("Save failed", str(exc), parent=self)

    def _poll(self):
        for _ in range(120):
            try:
                kind, text = self.session.events.get_nowait()
            except queue.Empty:
                break
            if kind == "clear":
                self.clear()
            else:
                self.append(kind, text)
        if self.session.dropped:
            dropped = self.session.dropped
            self.session.dropped = 0
            self.append("meta", f"\n[{dropped} output chunks dropped: output is too fast]\n")
        busy = self.session.busy
        status = "Stopping" if self.session.stopping else "Running" if busy else "Ready"
        self.status.configure(text=f"{status}  |  {self.session.cwd}")
        self.run_button.configure(text="Send input" if busy else "Run")
        self.prompt.configure(text="stdin>" if busy else ">")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self._job = self.after(100, self._poll)

    def _destroyed(self, event):
        if event.widget is self:
            if self._job:
                self.after_cancel(self._job)
                self._job = None
            self.session.close()
