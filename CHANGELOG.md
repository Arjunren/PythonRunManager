# Changelog

## 1.0.0 — 2026-10-15

Initial public PythonRunManager release, continuing Datatelcom System Manager.

### Added

- Choose a Python entry file when registering a project, including `run.py`, `main.py`, and nested scripts.
- Change the entry file in Settings and apply it on the next Start or Restart.
- Configuration schema version 3 with `entry_file`; versions 1/2 migrate using `app.py` by default.
- Validate selected scripts and launch absolute file paths with the project as the working folder.
- Documentation for use, building, troubleshooting, architecture, contributing, and releases.
- Portable Windows executable, documented ZIP package, and SHA-256 checksums.

### Retained

- Independent command terminals, input, history, and application logs.
- Individual/global controls, environment selection, startup settings, and crash recovery.
- Legacy settings directory and single-instance protection for upgrade compatibility.

### Compatibility

Older managers cannot read schema version 3; back up settings before upgrading if rollback is needed. Published binaries target Windows x64. Managed projects require their own Python interpreter and dependencies.
