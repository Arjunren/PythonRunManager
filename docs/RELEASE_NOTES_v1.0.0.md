# PythonRunManager v1.0.0

Manage Python projects in a Windows desktop workspace with an independent command terminal per system and a configurable entry script.

## Highlights

- Select `app.py`, `run.py`, `main.py`, or a nested script when adding a project.
- Change the entry in Settings and apply it with Start or Restart.
- Start, stop, restart, and inspect applications independently.
- Run Python, pip, Git, and installed executables in embedded terminals without opening CMD or PowerShell.
- Use project environments, live logs, stdin, history, auto-start, and bounded crash recovery.
- Migrate existing Datatelcom configuration versions 1/2.

## Downloads

- **PythonRunManager.exe** — portable Windows x64 application.
- **PythonRunManager-1.0.0-windows-x64.zip** — executable, README, LICENSE, and CHANGELOG.
- **SHA256SUMS.txt** — checksums for both downloads.

Requires Windows 10/11. Managed projects need their own interpreter and dependencies. The executable is unsigned. Terminals use input/output pipes; shell operators, batch wrappers, and full-screen console programs are unsupported.

## Upgrading

Close the older manager first. Existing systems default to `app.py`; change it in Settings when needed. Settings remain at `%LOCALAPPDATA%\DatatelcomPOSLauncher\systems.json`. Saving writes schema version 3, which older managers cannot read. Back up that file before upgrading if rollback is needed.

## Validation

46 automated tests passed on Windows, including entry selection, settings migration, command isolation, interactive input, process-tree termination, and GUI lifecycle checks. Built with Python 3.14.3 and PyInstaller 6.22.3. The packaged executable is also checked for startup and clean exit with isolated settings.
