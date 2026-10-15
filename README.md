# Datatelcom System Manager — v3.1

A **Windows 10/11 desktop GUI** for managing your own Python `app.py` systems. Built with **Tkinter/ttk**, with a dark UI, a **command terminal for every system**, separate application logs, and independent process management. Build to a single windowed `.exe` using PyInstaller. No third-party packages are needed to run the source.

## New in v3.1: type commands inside the manager

Select a system, open **Command Terminal**, type a command, and press **Enter** or **Run**. Each system starts in its own registered folder and retains its own working directory and last 100 commands for the current manager session. Terminals work while the managed application is stopped or running.

```text
pwd
dir
cd "folder with spaces"
cd ..
python --version
pip install -r requirements.txt
python maintenance.py
git status
help
```

- **Python and pip** use the system's interpreter from Settings, its `.venv`/`venv`, or Python on PATH. `pip` runs as that interpreter's `-m pip`; its executable folder is also added to the command's PATH. No environment activation is necessary. `python -m package` is supported.
- **Run installed executables** with quoted arguments or absolute executable paths. Built-in commands are `help`, `pwd`, `cd`, `dir`/`ls`, and `clear`/`cls`.
- **Live stdout and stderr** appear immediately, including prompts without a newline. While a command runs, the button changes to **Send input**; type a response and press Enter. Responses are excluded from command history and are not echoed by the manager. The program itself may echo them, and the input field is visible.
- **Up/Down** recalls commands. **Stop command** or **Ctrl+C in the input field** force-stops only that terminal command and its child process tree. Application Start/Stop/Restart controls remain independent.
- **Clear** clears terminal output; **Save** exports it. Each terminal's display and pending output are bounded. Exceptionally fast output may be dropped with a visible notice.
- **Application Logs** contains output from the app started using the system's Start control. Command Terminal input goes to its own running command, not that supervised app.
- Closing the manager stops both managed applications and running terminal commands. A system must have both stopped before it can be removed.

Commands execute directly with `shell=False` and hidden Windows process windows. **Neither CMD nor PowerShell is required for this terminal.** This is a command terminal using standard input/output pipes; full-screen console applications, console-only password prompts, the interactive Python REPL, `.bat`/`.cmd` wrappers, shell operators (`|`, `>`, `&&`), and shell scripting are unsupported. Run commands individually, use `python script.py` / `python -c "code"`, or invoke a tool's executable or Python module directly.

## What's changed since v2

- **No default applications whatsoever.** The Resort Management, MiniMart POS, and Cloudflare tunnel built-in entries have been removed. A new installation starts with an empty list. No existing folder beside the EXE is automatically scanned or launched.
- **Per-system tabs.** Each registered system gets a named tab with **Command Terminal** and **Application Logs**. Logs merge the app's `stdout` and `stderr` and remain available after it exits, until cleared or the launcher closes.
- **Add System** selects an existing folder with `app.py` directly in the folder root; no source edit or rebuild is needed. It saves and immediately starts the selected system.
- **Individual controls** on every terminal: Start, Stop, Restart, Settings, and Open Folder.
- **Global controls:** Start All, Stop All, Restart All, plus a global auto-start switch.
- **Settings:** rename a system, toggle its startup behavior, enable bounded crash recovery, or choose an explicit Python interpreter for its next launch.
- **System search**, clickable sidebar, running/registered/attention counters, PID, uptime, exit code, and terminal log actions (Clear, Copy, Save Log).
- **Compatible with the old v2 configuration:** a saved v2 `systems.json` (version 1 format) is loaded, preserving **only** your manually added folders, not the three old built-in services. It will be upgraded to the new format when you save settings.

## How to use

1. Build and open `DatatelcomSystemManager.exe`.
2. Click **+ Add System** and select e.g. `D:\Apps\CoffeeShop_POS` containing `D:\Apps\CoffeeShop_POS\app.py`.
3. The system is saved, gets a terminal tab, and launches immediately. Select it in the sidebar to type commands in **Command Terminal** or inspect the app's live output under **Application Logs**.
4. Manage it independently using **Start**, **Stop**, **Restart**. Use **Settings** to rename it, configure auto-start, or change its Python interpreter.
5. On later launches, all saved systems with per-system auto-start enabled start automatically if the **global auto-start** setting is enabled.
6. To remove an application, **stop it first**, choose **Settings → Remove System**, and confirm. This removes its registration only; it **never deletes your application folder**.

### Example app folder

```text
D:\Apps\CoffeeShop_POS\
  app.py
  requirements.txt
  .venv\
    Scripts\
      python.exe
```

A root `app.py` is required. `.venv` is recommended because each system can have separate dependencies. If the folder has no virtual environment, the manager checks `venv` and then Python on PATH; you can also configure a specific interpreter in Settings.

### System launch command

The manager runs the equivalent of:

```bat
cd /d "D:\Apps\CoffeeShop_POS"
"D:\Apps\CoffeeShop_POS\.venv\Scripts\python.exe" -u app.py
```

It **does not** use `cmd.exe`, a batch wrapper, or shell command interpolation. It captures stdout/stderr pipes to **Application Logs**. Windows consoles do not pop up for the managed Python process or terminal commands.

## Build a Windows EXE

You need Windows 10/11, Python 3.10+ with Tkinter, and Internet access for the one-time PyInstaller installation.

1. Extract the entire ZIP.
2. Double-click **`build.bat`** (or run it from Command Prompt). It creates a build-specific `.buildenv`, installs pinned PyInstaller 6.22.3, runs tests, and builds the EXE.
3. Find the built program at:

```text
dist\DatatelcomSystemManager.exe
```

The launcher EXE can be placed wherever you want. Your Python application folders can be anywhere you have access. **The managed `app.py` applications still need an external installed Python or a per-system virtual environment and their own dependencies**; PyInstaller does not bundle those projects.

Or run directly on Windows:

```bat
py -3 launcher.py
```

## Persistent settings

Saved to the currently logged-in Windows user's profile:

```text
%LOCALAPPDATA%\DatatelcomPOSLauncher\systems.json
```

The settings include registered absolute folder paths, a display name, auto-start/crash recovery options, and optional Python interpreter path. They contain no credentials. Atomic configuration writes reduce truncation risk. The old config directory is reused for compatibility. The manager does not scan or launch unregistered nearby folders.

To begin **completely empty** even if you've used v2, first quit the manager, back up or rename this `systems.json`, then reopen the manager. This affects only launcher registrations, not any app source folders.

## Important operations & security

- **Only add trusted folders.** Choosing a folder allows its `app.py` to execute as your Windows user immediately and on later launches. Don't add downloaded/untrusted scripts.
- **Stop is forceful on Windows.** `taskkill /PID <recorded-pid> /T /F` stops only the tracked process tree, not every Python process. Apps must safely persist data or handle forced termination. Closing the manager asks before force-stopping running applications.
- **No external application is hardcoded**, and the removed Cloudflare tunnel will not start unless you deliberately configure your own Python `app.py` for it (or manage it separately).
- A crashed app can be configured for **crash recovery**: at most three restarts in a rolling minute, with brief backoff. This option is off by default. Intentional Stop cancels pending restarts.
- Terminal commands execute as your Windows user and can change files or install packages. Only run commands you trust. Output and command history may contain sensitive data; they stay in bounded session memory unless you explicitly export or copy them. Treat exported logs as sensitive.
- Output collection is bounded to prevent an excessive memory buildup; output may be dropped when an application logs faster than the UI can display. Output stays untrusted text, never executes as code.
- Python applications may launch other windows (web browsers or GUI processes) under their own control. Those windows are not embedded inside the manager.
- Crash/force-close behavior of applications that spawn detached child processes is dependent on the application. Process management targets the tracked PID and its tree, not arbitrary detached services.
- If you edit an interpreter while the app is running, the new interpreter takes effect on its **next launch**.
- Only one copy of the manager can run at a time within a Windows user session.

## Tests

```bat
py -3 -m unittest discover -s tests -v
```

The suite covers configuration, application output capture and restarts, terminal directory isolation, selected Python and pip, Windows argument quoting, interactive prompts, bounded output, cancellation, removal guards, and shutdown cleanup. GUI tests need a Windows desktop or Linux virtual display. v3.1 was tested on Windows with Python 3.14 and built with PyInstaller 6.22.3.

## License

MIT. See [LICENSE](LICENSE).
