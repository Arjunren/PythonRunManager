# PythonRunManager

A Windows desktop manager for Python projects, with a command terminal for every system and configurable entry scripts. Launch **`app.py`, `run.py`, `main.py`, or `src/main.py`** without editing the manager's source.

[Download Windows EXE](https://github.com/Arjunren/PythonRunManager/releases/latest/download/PythonRunManager.exe) · [All releases](https://github.com/Arjunren/PythonRunManager/releases) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)

## Features

- Register up to 64 project folders and select each one's Python entry file.
- Change the entry script in Settings; the next Start or Restart uses it.
- Start, stop, and restart individual applications or all registered applications.
- Use independent command terminals with their own working folders, live output, command history, and interactive standard input.
- Run Python, pip, Git, and installed executables without opening CMD or PowerShell.
- Keep supervised application logs separate from terminal command output.
- Automatically select each project's `.venv` or `venv`, or configure a Python interpreter explicitly.
- Configure global and individual auto-start, plus optional bounded crash recovery.
- Search systems and inspect status, PID, uptime, and exit code.
- Copy, clear, or save application logs; clear or save terminal output.
- Store registrations locally and migrate settings from Datatelcom System Manager.

## Download and requirements

1. Download **[PythonRunManager.exe](https://github.com/Arjunren/PythonRunManager/releases/latest/download/PythonRunManager.exe)** from the latest release. A ZIP containing the executable and documentation is also available.
2. Place the executable in an accessible folder and double-click it. No installer is required.
3. Add your projects using **+ Add System**.

**Published executable:** Windows 10/11 x64, a desktop session, and a minimum 900 × 660 client area. The executable is unsigned.

**Managed projects:** Install Python and each project's dependencies separately. The executable bundles the manager's runtime; it does not bundle the interpreters or packages for your managed projects.

**Running source:** Python 3.10+ with Tkinter. No third-party runtime packages are required. The release was built and tested on Windows with Python 3.14.3 and PyInstaller 6.22.3.

## Quick start

1. Click **+ Add System** and choose the project's working folder, such as `D:\Apps\MyProject`.
2. Select the Python entry file inside that folder: `run.py`, `app.py`, or a nested file such as `src/main.py`.
3. The system is saved and starts immediately. Only add a project when you are ready to execute its code.
4. Open **Application Logs** to see its output, or **Command Terminal** to run commands in its folder.
5. Manage the project independently using **Start**, **Stop**, **Restart**, and **Settings**.

Example project:

```text
MyProject/
  run.py
  requirements.txt
  .venv/
    Scripts/
      python.exe
```

`app.py` is not required when you select another entry file. One registration is allowed per project folder. The entry must be an existing `.py` file inside that folder; absolute paths, parent-directory traversal, and links outside the project are rejected.

## Change app.py to run.py

1. Select a registered system and click **Settings**.
2. In **Python entry file**, type `run.py`, or click **Browse** to select it.
3. Click **Save Changes**.
4. Click **Start** if stopped, or **Restart** to apply the change to a running application.

The field also accepts `main.py`, `server.py`, `src/main.py`, and other Python filenames. Saving Settings does not interrupt a running application. Missing entry files produce an error; the manager does not silently choose another script.

## Python environments and launch behavior

Interpreter selection order:

1. The interpreter configured in **Settings → Python interpreter**.
2. `<project>/.venv/Scripts/python.exe`.
3. `<project>/venv/Scripts/python.exe`.
4. Portable core fallbacks for `.venv/bin/python` and `venv/bin/python`.
5. Python or the Python launcher on PATH; source execution can also use its current interpreter.

The supervised application's working directory is always its registered project folder, even with a nested entry file. The launch uses an argument list equivalent to:

```text
D:\Apps\MyProject\.venv\Scripts\python.exe -u D:\Apps\MyProject\run.py
```

Paths are passed as individual arguments with `shell=False` and hidden console windows. Entry scripts currently have no dedicated command-line-arguments field; use Command Terminal for a custom one-off invocation.

## Command Terminal

Every system has a terminal that works while its supervised application is stopped or running. Terminal commands and applications have separate controls.

```text
pwd
dir
cd "folder with spaces"
cd ..
python --version
pip install -r requirements.txt
python maintenance.py
python -m package_name
git status
help
```

| Control or command | Behavior |
| --- | --- |
| Enter / Run | Start one command in the terminal's current folder |
| Enter / Send input | Send a line to the running terminal command's standard input |
| Up / Down | Recall up to 100 commands from the current session |
| Stop command / Ctrl+C in the input field | Force-stop the terminal command's tracked process tree |
| `pwd`, `cd`, `cd ..` | Show or change this terminal's folder |
| `dir`, `ls` | List folder contents |
| `clear`, `cls` | Clear displayed output |
| `help` | Show supported commands and limitations |
| Save | Export displayed terminal output as a text log |

`python` and `pip` use the system's interpreter, even after `cd`. `pip` runs as that interpreter's `-m pip`. Its executable directory is also added to the command's PATH; environment activation is unnecessary.

Output streams live, including prompts without a newline. Responses sent as standard input are excluded from command history and are not echoed by the manager. The input field is visible, and the child program may echo or log responses itself.

This terminal uses standard input/output pipes. Full-screen console programs, console-only password prompts, the interactive Python REPL, `.bat`/`.cmd` wrappers, and shell operators such as `|`, `>`, and `&&` are unsupported. Run each command separately and invoke a tool's executable or Python module directly. Use `python script.py` or `python -c "print('hello')"` instead of a bare Python REPL.

Terminal folders, output, and history reset when the manager closes. `cd` affects only that terminal, not another terminal or its supervised application.

## Application controls and logs

- **Start / Stop / Restart** manage the selected entry script. Stop is forceful and targets the recorded PID and descendants.
- **Start All / Stop All / Restart All** operate on supervised applications; use **Stop command** for terminal commands.
- **Auto-start** runs systems when both their individual setting and the global switch are enabled. New systems default to auto-start enabled.
- **Crash recovery** is off by default. When enabled, nonzero exits retry with backoff, limited to three retries in a rolling minute. Intentional Stop cancels retries.
- **Application Logs** merges the supervised application's stdout and stderr. It has Clear, Copy, and Save Log actions. It is read-only; terminal input goes to the separate terminal command.
- **Remove System** requires both its application and terminal command to be stopped. It removes the registration without deleting project files.
- Closing the manager confirms before stopping active work and waits for process cleanup.

Displays and pending output are bounded. Extremely fast output may be dropped; the command terminal shows a notice. Export logs before closing to retain them. Detached processes can outlive their parent depending on how the project creates them.

## Configuration and upgrades

To preserve existing registrations, PythonRunManager retains the legacy location:

```text
%LOCALAPPDATA%\DatatelcomPOSLauncher\systems.json
```

Schema version 3 adds `entry_file` to each system. Versions 1 and 2 load with `app.py` as the default. The next settings save writes version 3 atomically, preserving names, interpreter paths, startup choices, and recovery settings. Older managers cannot read version 3; back up settings before upgrading if rollback is needed.

The legacy single-instance mutex is retained so PythonRunManager and the older manager cannot manage the same registrations simultaneously. Close the older manager before opening PythonRunManager.

Settings store project paths and launch preferences, not source code or dependencies. A malformed configuration shows a warning and is not automatically overwritten on startup. To reset registrations, close the manager, back up or rename `systems.json`, and reopen it.

## Run from source

```text
git clone https://github.com/Arjunren/PythonRunManager.git
cd PythonRunManager
py -3 launcher.py
```

The GUI is intended for Windows. Core and command-session tests can run elsewhere; GUI tests require Windows or a graphical display such as a Linux virtual display.

## Build the Windows executable

Double-click **build.bat**. It creates an isolated `.buildenv`, installs pinned PyInstaller 6.22.3, runs tests, and builds the single-file windowed **`dist/PythonRunManager.exe`**. Windows, Python 3.10+ with Tkinter, the `py` launcher, and internet access for the initial dependency installation are required.

Alternatively, use a chosen Python environment:

```text
python -m pip install pyinstaller==6.22.3
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PythonRunManager launcher.py
```

## Tests

```text
python -m unittest discover -s tests -v
```

Tests cover entry selection and updates, projects without `app.py`, nested scripts, legacy migration, path validation, application lifecycle, terminal folder isolation, Python/pip selection, Windows quoting, interactive prompts, bounded output, process-tree termination, removal guards, and shutdown cleanup.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Python not found | Install Python, create a project environment, or choose an interpreter in Settings |
| Entry file not found | Select the correct existing `.py` file in Settings; check whether the project moved |
| Missing package | Run `pip install -r requirements.txt` in that system's terminal |
| Wrong interpreter | Set it explicitly, then check `python --version` and `pip --version` |
| Prompt is missing in logs | Application Logs is line-oriented; use Command Terminal for prompts without newlines |
| Command not found | Install it on PATH or use its executable path; batch wrappers need an executable/module alternative |
| Crash recovery paused | Fix the error in Application Logs, then manually Start or Restart |
| Already running | Close the existing PythonRunManager or legacy Datatelcom window |
| Download warning | The executable is unsigned; verify its source and checksum before deciding whether to run it |

Releases include `SHA256SUMS.txt`. Compute a downloaded executable's checksum with `certutil -hashfile PythonRunManager.exe SHA256` and compare it with the published value.

## Source layout

```text
launcher.py             Desktop UI and supervised application lifecycle
launcher_core.py        Settings, migrations, entry validation and Python resolution
terminal_session.py     Independent command execution and process cleanup
terminal_ui.py          Embedded terminal widgets
tests/                  Core, GUI and terminal regression tests
build.bat               Tested Windows EXE build
docs/                   Architecture and release documentation
```

## Contributing, security, and license

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Report reproducible bugs through [GitHub Issues](https://github.com/Arjunren/PythonRunManager/issues).

Maintained by [Arjunren](https://github.com/Arjunren). Released under the [MIT license](LICENSE). PythonRunManager continues the Datatelcom System Manager codebase.
