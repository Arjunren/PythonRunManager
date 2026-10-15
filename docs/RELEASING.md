# Release process

1. Update `VERSION` in `launcher.py`, CHANGELOG, and release notes. Configuration schema and product versions are independent.
2. Run the full test suite on Windows and build using `build.bat` or the README's PyInstaller command.
3. Smoke-test the executable with disposable settings: launch a project containing only `run.py`, inspect terminal behavior, and close cleanly.
4. Create `PythonRunManager-<version>-windows-x64.zip` containing the EXE, README, LICENSE, and CHANGELOG.
5. Generate `SHA256SUMS.txt` for the standalone EXE and ZIP.
6. Commit and push source. Create an annotated `v<version>` tag at that commit and push it.
7. Publish a GitHub release with the reviewed notes and upload the EXE, ZIP, and checksums.
8. Verify public repository visibility, the tag's commit, published release status, and all downloadable assets. Compare a downloaded EXE's hash with the local build.

Executables are unsigned. State platform and external Python requirements. Keep builds, environments, local settings, and generated logs out of Git.
