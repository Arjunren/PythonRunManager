"""Per-system command sessions. Commands run directly, without a shell window."""
from __future__ import annotations

import codecs
import ctypes
import os
from pathlib import Path
import queue
import shlex
import shutil
import signal
import subprocess
import threading

from launcher_core import SystemConfig, resolved_python

HELP = """Commands run in this system's working folder:
  pwd / cd / cd "folder" / cd ..   Show or change folder
  ls / dir [folder]               List files
  clear / cls                    Clear this terminal
  python script.py                Use this system's Python
  pip install -r requirements.txt Use this system's pip
  git status                     Run an installed executable
  help                           Show this help
Up/Down recalls commands. While a command runs, Enter sends input to it.
Stop command (or Ctrl+C in the input) ends its process tree.
Quote paths with spaces. Shell operators (pipes, redirects, &&), .bat/.cmd
scripts, and full-screen console programs are not supported."""


def split_command(command: str) -> list[str]:
    if not command.strip():
        return []
    if "\x00" in command or "\n" in command or "\r" in command:
        raise ValueError("Enter one command at a time.")
    if os.name != "nt":
        return shlex.split(command)
    # Match native Windows quoting, preserving drive paths and backslashes.
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    # A dummy program name ensures even the first user argument uses normal quoting.
    argv = shell.CommandLineToArgvW("terminal " + command.strip(), ctypes.byref(count))
    if not argv:
        raise ValueError("Could not parse this command.")
    try:
        return [argv[i] for i in range(1, count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


class TerminalSession:
    def __init__(self, config: SystemConfig):
        self.config = config
        self.cwd = Path(config.folder)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1000)
        self.process: subprocess.Popen[bytes] | None = None
        self.busy = False
        self.stopping = False
        self.closed = False
        self.last_exit: int | None = None
        self.dropped = 0
        self._lock = threading.Lock()
        self._input: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self._generation = 0

    def _emit(self, kind: str, text: str) -> None:
        try:
            self.events.put_nowait((kind, text))
        except queue.Full:
            self.dropped += 1

    def execute(self, command: str) -> bool:
        with self._lock:
            if self.busy or self.closed or not command.strip():
                return False
            self.busy = True
            self.stopping = False
            self.last_exit = 0
            self.process = None
            self._generation += 1
            self._input = queue.Queue(maxsize=64)
        self._emit("command", f"{self.cwd}> {command}\n")
        threading.Thread(target=self._run, args=(command,), daemon=True).start()
        return True

    def _run(self, command: str) -> None:
        proc = None
        try:
            args = split_command(command)
            name = args[0].casefold()
            if any(arg in {"|", "||", "&&", ">", ">>", "<", "&"} for arg in args):
                raise ValueError("Shell operators are unsupported. Run each command separately.")
            if self.stopping or self.closed:
                return
            if name in {"clear", "cls"}:
                self._emit("clear", "")
                return
            if name == "help":
                self._emit("output", HELP + "\n")
                return
            if name == "pwd" or name == "cd" and len(args) == 1:
                self._emit("output", str(self.cwd) + "\n")
                return
            if name == "cd":
                if len(args) != 2:
                    raise ValueError('Usage: cd "folder"')
                target = self._path(args[1]).resolve(strict=True)
                if not target.is_dir():
                    raise ValueError("That path is not a folder.")
                self.cwd = target
                self._emit("output", str(target) + "\n")
                return
            if name in {"ls", "dir"}:
                if len(args) > 2:
                    raise ValueError('Usage: dir ["folder"]')
                target = self._path(args[1]) if len(args) == 2 else self.cwd
                with os.scandir(target) as entries:
                    for entry in entries:
                        if self.stopping or self.closed:
                            break
                        self._emit("output", f"{'<DIR> ' if entry.is_dir() else '      '}{entry.name}\n")
                return
            env = os.environ.copy()
            env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1", TERM="dumb")
            try:
                python = resolved_python(Path(self.config.folder), self.config.python_path)
            except (OSError, ValueError):
                if name in {"python", "python.exe", "python3", "py", "pip", "pip.exe", "pip3"}:
                    raise
                python = []
            # Prefer the registered system's environment for all executables as well.
            if python:
                env["PATH"] = str(Path(python[0]).parent) + os.pathsep + env.get("PATH", "")
            if name in {"python", "python.exe", "python3", "py"}:
                args = [*python, "-u", *args[1:]]
                if len(args) == len(python) + 1:
                    raise ValueError("Use python script.py or python -c \"code\"; the Python REPL needs a console.")
            elif name in {"pip", "pip.exe", "pip3"}:
                args = [*python, "-u", "-m", "pip", *args[1:]]
            else:
                candidate = self._path(args[0])
                executable = str(candidate.resolve()) if candidate.is_file() else shutil.which(args[0], path=env["PATH"])
                if not executable:
                    raise FileNotFoundError(f"Command not found: {args[0]}. Type help for available commands.")
                if Path(executable).suffix.casefold() in {".bat", ".cmd"}:
                    raise ValueError("Batch scripts require a shell. Run the tool's executable or Python module instead.")
                args[0] = executable
            with self._lock:
                if self.stopping or self.closed:
                    return
                proc = subprocess.Popen(
                    args, cwd=self.cwd, env=env, shell=False, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
                self.process = proc
            reader = threading.Thread(target=self._read, args=(proc,), daemon=True)
            reader.start()
            threading.Thread(target=self._write, args=(proc, self._input), daemon=True).start()
            self.last_exit = proc.wait()
            reader.join(timeout=1)
            self._emit("meta", f"\n[Command exited: {self.last_exit}]\n")
        except (OSError, ValueError, IndexError) as exc:
            self.last_exit = 1
            self._emit("error", str(exc) + "\n")
        finally:
            if proc is not None:
                try:
                    self._input.put_nowait(None)
                except queue.Full:
                    pass
            with self._lock:
                self.busy = False
                self.stopping = False

    def _path(self, value: str) -> Path:
        path = Path(os.path.expandvars(value)).expanduser()
        return path if path.is_absolute() else self.cwd / path

    def _read(self, proc: subprocess.Popen[bytes]) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            with proc.stdout:
                while chunk := proc.stdout.read(4096):
                    # Ignore output from an older command after the next one starts.
                    if self.process is proc and not self.closed:
                        self._emit("output", decoder.decode(chunk))
                tail = decoder.decode(b"", final=True)
                if tail and self.process is proc and not self.closed:
                    self._emit("output", tail)
        except (OSError, ValueError):
            pass

    def send_input(self, text: str) -> bool:
        proc = self.process
        if not self.busy or proc is None or proc.poll() is not None or self.stopping:
            return False
        try:
            self._input.put_nowait((text + "\n").encode("utf-8"))
            return True
        except queue.Full:
            self._emit("error", "Input queue is full; wait for the command to read input.\n")
            return False

    @staticmethod
    def _write(proc: subprocess.Popen[bytes], pending: queue.Queue[bytes | None]) -> None:
        try:
            with proc.stdin:
                while proc.poll() is None:
                    try:
                        data = pending.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if data is None:
                        break
                    proc.stdin.write(data)
                    proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def stop(self) -> None:
        if not self.busy or self.stopping:
            return
        self.stopping = True
        threading.Thread(target=self._stop, args=(self._generation,), daemon=True).start()

    def _stop(self, generation: int) -> None:
        proc = None
        try:
            with self._lock:
                if generation != self._generation:
                    return
                proc = self.process
            if proc is not None and proc.poll() is None:
                if os.name == "nt":
                    result = subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True, timeout=12,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if result.returncode and proc.poll() is None:
                        self._emit("error", "Could not stop the command's process tree.\n")
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                if proc.poll() is None:
                    proc.kill()
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._emit("error", f"Stop failed: {exc}\n")
        finally:
            if self.busy and generation == self._generation and proc is not None and proc.poll() is None:
                self.stopping = False  # Allow retry if termination failed.

    def close(self) -> None:
        self.closed = True
        self.stop()
