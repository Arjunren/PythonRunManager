# Contributing

## Development

Clone PythonRunManager and run `py -3 launcher.py` on Windows with Python 3.10+ and Tkinter. Runtime code uses only the standard library. Use disposable test projects: adding a system immediately executes its chosen script.

1. Create a branch describing your change.
2. Keep configuration and entry validation in `launcher_core.py`, application lifecycle/UI in `launcher.py`, and terminal execution/UI in `terminal_session.py` / `terminal_ui.py`.
3. Add focused regression tests for behavior changes, especially migrations and process ownership.
4. Run `python -m unittest discover -s tests -v` on a Windows desktop.
5. Update README and CHANGELOG when user-facing behavior changes.
6. Open a pull request explaining the problem, resulting behavior, and validation.

Core tests run cross-platform. GUI tests require a display; Windows quoting and process-tree tests require Windows. Use `build.bat` to verify packaging changes.

## Expectations

- Pass argument lists with `shell=False`; never interpolate user text into shell commands.
- Keep terminals and supervised applications independent.
- Preserve migrations and never delete user projects.
- Bound queues and visible output; keep blocking work off the Tk event loop.
- Exclude credentials, environments, local settings, logs, and build products from commits.
- Document supported behavior and limitations accurately.

Bug reports should include the manager version, Windows/Python versions, reproduction steps, and sanitized logs. Contributions are provided under the MIT license.
