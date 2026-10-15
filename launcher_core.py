"""Portable configuration and command resolution for PythonRunManager.

No applications are hardcoded. Only folders explicitly registered by the user
are executable launch targets. The config is data, never a command template.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sys
import tempfile

APP_NAME = "PythonRunManager"
CONFIG_NAME = "systems.json"
CONFIG_VERSION = 3
MAX_SYSTEMS = 64
MAX_CONFIG_BYTES = 512 * 1024
MAX_PATH = 4096
MAX_NAME = 72


@dataclass(frozen=True)
class SystemConfig:
    id: str
    folder: str
    name: str
    auto_start: bool = True
    restart_on_crash: bool = False
    python_path: str | None = None
    entry_file: str = "app.py"


@dataclass(frozen=True)
class LauncherConfig:
    systems: tuple[SystemConfig, ...] = ()
    auto_start_on_open: bool = True


def config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Local") / "DatatelcomPOSLauncher" / CONFIG_NAME


def normalized_folder(folder: Path) -> str:
    # normcase handles case-insensitivity on Windows; resolve folds symlinks.
    return os.path.normcase(str(folder.resolve(strict=False)))


def folder_id(folder: Path) -> str:
    return hashlib.sha256(normalized_folder(folder).encode("utf-8")).hexdigest()[:24]


def valid_folder(raw: str) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_PATH:
        raise ValueError("Choose a valid system folder.")
    folder = Path(raw).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("Choose an existing absolute folder path.")
    folder = folder.resolve(strict=True)
    return folder


def _check_entry(entry_file: str) -> str:
    if not isinstance(entry_file, str) or not entry_file or len(entry_file) > MAX_PATH:
        raise ValueError("Choose a Python entry file inside the system folder.")
    entry_file = entry_file.replace("\\", "/")
    path = PurePosixPath(entry_file)
    if (path.is_absolute() or PureWindowsPath(entry_file).drive or ".." in path.parts
            or path.suffix.casefold() != ".py" or ":" in entry_file
            or any(ord(c) < 32 or ord(c) == 127 for c in entry_file)):
        raise ValueError("Entry file must be a relative .py path inside the system folder.")
    return path.as_posix()


def entry_path(folder: Path, entry_file: str) -> Path:
    name = _check_entry(entry_file)
    root = folder.resolve(strict=True)
    script = (root / name).resolve(strict=True)
    if not script.is_relative_to(root) or not script.is_file():
        raise ValueError("Choose a Python entry file inside the system folder.")
    return script


def _check_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Invalid system name")
    name = name.strip()
    if not name or len(name) > MAX_NAME or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("System name must contain 1–72 printable characters")
    return name


def _check_path(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > MAX_PATH or not Path(path).is_absolute():
        raise ValueError("System path must be an absolute folder path")
    if any(ord(c) < 32 for c in path):
        raise ValueError("System path contains control characters")
    return path


def create_system(folder: Path, entry_file: str = "app.py") -> SystemConfig:
    resolved = valid_folder(str(folder))
    entry_file = _check_entry(entry_file)
    entry_path(resolved, entry_file)
    return SystemConfig(folder_id(resolved), str(resolved), _check_name(resolved.name), entry_file=entry_file)


def update_system(system: SystemConfig, *, name: str, auto_start: bool,
                  restart_on_crash: bool, python_path: str | None,
                  entry_file: str | None = None) -> SystemConfig:
    selected_entry = _check_entry(system.entry_file if entry_file is None else entry_file)
    if entry_file is not None:
        entry_path(Path(system.folder), selected_entry)
    if python_path is not None:
        python_path = python_path.strip()
        if not python_path:
            python_path = None
        else:
            _check_path(python_path)
            executable = Path(python_path)
            if not executable.is_file():
                raise ValueError("Selected Python interpreter does not exist")
            if executable.suffix.lower() != ".exe" and os.name == "nt":
                raise ValueError("Select a Python .exe interpreter")
            python_path = str(executable.resolve(strict=True))
    return replace(system, name=_check_name(name), auto_start=bool(auto_start),
                   restart_on_crash=bool(restart_on_crash), python_path=python_path, entry_file=selected_entry)


def _validate_config(config: LauncherConfig) -> None:
    if type(config.auto_start_on_open) is not bool or len(config.systems) > MAX_SYSTEMS:
        raise ValueError("Invalid launcher settings")
    seen: set[str] = set()
    for s in config.systems:
        path = _check_path(s.folder)
        _check_name(s.name)
        _check_entry(s.entry_file)
        if type(s.auto_start) is not bool or type(s.restart_on_crash) is not bool:
            raise ValueError("Invalid per-system settings")
        if s.python_path is not None:
            _check_path(s.python_path)
        key = normalized_folder(Path(path))
        if key in seen or s.id != folder_id(Path(path)):
            raise ValueError("Duplicate system or invalid system identifier")
        seen.add(key)


def load_config(path: Path) -> tuple[LauncherConfig, str | None]:
    """Migrate legacy v1/v2 settings, defaulting existing systems to app.py."""
    try:
        if not path.exists():
            return LauncherConfig(), None
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("Configuration is too large")
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("Configuration root must be an object")
        version = data.get("version")
        entries = data.get("systems")
        if not isinstance(entries, list) or len(entries) > MAX_SYSTEMS:
            raise ValueError("Invalid systems array")
        systems: list[SystemConfig] = []
        seen: set[str] = set()
        if version == 1:
            # v2 stored just custom system paths; it never stored its three defaults.
            for entry in entries:
                path = _check_path(entry)
                folder = Path(path)
                identity = normalized_folder(folder)
                if identity in seen:
                    continue
                seen.add(identity)
                systems.append(SystemConfig(folder_id(folder), path,
                                             _check_name(folder.name or "Python system")))
            config = LauncherConfig(tuple(systems))
        elif version in {2, CONFIG_VERSION}:
            if type(data.get("auto_start_on_open")) is not bool:
                raise ValueError("Invalid auto-start setting")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid system entry")
                fields = {"id", "folder", "name", "auto_start", "restart_on_crash", "python_path"}
                if version == CONFIG_VERSION:
                    fields.add("entry_file")
                if set(entry) != fields:
                    raise ValueError("System entry contains missing or unknown fields")
                systems.append(SystemConfig(**entry))
            config = LauncherConfig(tuple(systems), data["auto_start_on_open"])
        else:
            raise ValueError("Unsupported configuration version")
        _validate_config(config)
        return config, None
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        return LauncherConfig(), f"Could not read {path}: {exc}"


def save_config(path: Path, config: LauncherConfig) -> None:
    _validate_config(config)
    data = {
        "version": CONFIG_VERSION,
        "auto_start_on_open": config.auto_start_on_open,
        "systems": [vars(s) for s in config.systems],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".config-", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def resolved_python(folder: Path, override: str | None) -> list[str]:
    if override:
        exe = Path(override)
        if not exe.is_file():
            raise FileNotFoundError(f"Python interpreter not found: {override}")
        return [str(exe)]
    candidates = (
        folder / ".venv" / "Scripts" / "python.exe",
        folder / "venv" / "Scripts" / "python.exe",
        folder / ".venv" / "bin" / "python",
        folder / "venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    for command in ("python.exe", "python", "py.exe", "py"):
        resolved = shutil.which(command)
        if resolved:
            if Path(resolved).name.casefold() in {"py", "py.exe"}:
                return [resolved, "-3"]
            return [resolved]
    # Only for running unbundled source, not for a frozen PyInstaller EXE.
    if not getattr(sys, "frozen", False) and sys.executable and Path(sys.executable).is_file():
        return [sys.executable]
    raise FileNotFoundError("Python not found. Add a .venv to the system folder or set an interpreter in Settings.")


def command_for(system: SystemConfig) -> tuple[list[str], Path]:
    folder = Path(system.folder)
    try:
        script = entry_path(folder, system.entry_file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Entry file '{system.entry_file}' not found in system folder: {folder}") from exc
    return [*resolved_python(folder, system.python_path), "-u", str(script)], folder
