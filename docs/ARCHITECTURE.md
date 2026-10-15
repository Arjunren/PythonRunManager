# Architecture

| Module | Responsibility |
| --- | --- |
| `launcher_core.py` | Configuration models, validation, migrations, atomic writes, interpreter and entry-file resolution |
| `launcher.py` | Tk UI, registration/settings, application lifecycle, logs, crash recovery, shutdown |
| `terminal_session.py` | Independent command sessions, built-ins, executable resolution, stream decoding, queued stdin, cancellation |
| `terminal_ui.py` | Input widgets, history, bounded output, terminal controls, polling, export |

## Two process channels

Each system owns a supervised application runtime and an independent terminal session. The runtime launches the configured script with the registered folder as `cwd`. Its stdout/stderr go to Application Logs and stdin is disconnected.

The terminal begins in that folder, but `cd` affects only its session. It runs one command at a time, accepts queued stdin, and uses the registered interpreter for Python and pip aliases. Terminal commands do not change application lifecycle state.

Worker threads handle stream reads, process waits, input writes, and termination. Tk drains queues and updates widgets. Queues and display buffers are bounded. The terminal incrementally decodes UTF-8 and displays plain text, without full console-emulator behavior.

## Configuration

Schema version 3 stores `auto_start_on_open` and systems with `id`, `folder`, `name`, `auto_start`, `restart_on_crash`, `python_path`, and `entry_file`. IDs derive from normalized folder paths; changing a script preserves identity, and each folder has one registration.

Entry paths are relative to the project. Validation rejects absolute paths and traversal; launch resolution verifies the existing script stays within the project. Absolute script arguments avoid treating option-like filenames as interpreter flags.

Versions 1/2 migrate with `app.py` as default. The next save writes version 3 via a temporary file and atomic replacement. Missing project folders remain registered for diagnosis.

## Lifecycle and compatibility

Windows processes start without console windows. Stop uses `taskkill /PID <tracked-pid> /T /F`. Application recovery is limited to three retries in a rolling minute; intentional stops cancel retries.

Closing stops both process channels and waits for cleanup. Removing a system requires both channels to be idle. Legacy settings and mutex names are retained for compatibility with Datatelcom System Manager.
