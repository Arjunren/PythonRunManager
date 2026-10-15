"""Core config and command tests — use: python -m unittest discover -s tests -v"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from launcher_core import (
    LauncherConfig, SystemConfig, MAX_SYSTEMS, create_system, command_for,
    folder_id, load_config, normalized_folder, save_config, update_system, valid_folder,
)
from launcher import clean_line


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.project = self.home / "Cafe POS"
        self.project.mkdir()
        (self.project / "app.py").write_text("print('hello')\n", encoding="utf-8")
        self.config_path = self.home / "data" / "systems.json"
        self.config_path.parent.mkdir()

    def test_initial_config_is_empty(self):
        config, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(config.systems, ())
        self.assertTrue(config.auto_start_on_open)

    def test_validate_root_app(self):
        config = create_system(self.project)
        self.assertEqual(config.name, "Cafe POS")
        self.assertEqual(config.id, folder_id(self.project))
        other = self.home / "nested"
        (other / "src").mkdir(parents=True)
        (other / "src" / "app.py").write_text("", encoding="utf-8")
        self.assertEqual(valid_folder(str(other)), other.resolve())
        with self.assertRaises(FileNotFoundError):
            create_system(other)
        self.assertEqual(create_system(other, "src/app.py").entry_file, "src/app.py")

    def test_round_trip_and_custom_settings(self):
        item = create_system(self.project)
        changed = update_system(item, name="My Counter", auto_start=False,
                                restart_on_crash=True, python_path=None)
        config = LauncherConfig((changed,), False)
        save_config(self.config_path, config)
        loaded, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(loaded, config)
        self.assertEqual(json.loads(self.config_path.read_text())["version"], 3)

    def test_version_one_migration_removes_no_defaults_needed(self):
        self.config_path.write_text(json.dumps({"version": 1, "systems": [str(self.project)]}), encoding="utf-8")
        loaded, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(len(loaded.systems), 1)
        self.assertEqual(loaded.systems[0].folder, str(self.project))

    def test_legacy_duplicate_is_ignored(self):
        self.config_path.write_text(json.dumps({"version": 1, "systems": [str(self.project), str(self.project)]}), encoding="utf-8")
        loaded, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(len(loaded.systems), 1)

    def test_no_executable_command_interpolation(self):
        item = create_system(self.project)
        with patch("launcher_core.resolved_python", return_value=["C:\\Python311\\python.exe"]):
            argv, cwd = command_for(item)
        self.assertEqual(argv, ["C:\\Python311\\python.exe", "-u", str(self.project / "app.py")])
        self.assertEqual(cwd, self.project.resolve())

    def test_local_venv_selected(self):
        venv = self.project / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_bytes(b"executable")
        argv, _ = command_for(create_system(self.project))
        self.assertEqual(argv[0], str(venv / "python"))

    def test_missing_app_refuses_launch(self):
        item = create_system(self.project)
        (self.project / "app.py").unlink()
        with self.assertRaises(FileNotFoundError):
            command_for(item)

    def test_invalid_name(self):
        item = create_system(self.project)
        for bad in ("", "x" * 73, "bad\nname"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    update_system(item, name=bad, auto_start=True, restart_on_crash=False, python_path=None)

    def test_reject_invalid_explicit_python(self):
        item = create_system(self.project)
        with self.assertRaises(ValueError):
            update_system(item, name=item.name, auto_start=True, restart_on_crash=False,
                          python_path=str(self.home / "notfound.exe"))

    def test_duplicate_rejected_in_new_config(self):
        item = create_system(self.project)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            save_config(self.config_path, LauncherConfig((item, item)))

    def test_max_system_limit(self):
        systems = tuple(SystemConfig(folder_id(self.home / f"S{i}"), str(self.home / f"S{i}"), f"S{i}")
                        for i in range(MAX_SYSTEMS + 1))
        with self.assertRaises(ValueError):
            save_config(self.config_path, LauncherConfig(systems))

    def test_untrusted_fields_rejected(self):
        item = create_system(self.project)
        save_config(self.config_path, LauncherConfig((item,)))
        data = json.loads(self.config_path.read_text())
        data["systems"][0]["evil"] = "whoami"
        self.config_path.write_text(json.dumps(data))
        loaded, error = load_config(self.config_path)
        self.assertEqual(loaded.systems, ())
        self.assertIsNotNone(error)

    def test_corrupt_and_oversized_config(self):
        self.config_path.write_text("{ invalid", encoding="utf-8")
        self.assertIsNotNone(load_config(self.config_path)[1])
        self.config_path.write_bytes(b" " * (512 * 1024 + 1))
        self.assertIn("too large", load_config(self.config_path)[1].lower())

    def test_clean_line_plain_text(self):
        self.assertEqual(clean_line("\x1b[31mFAIL\x1b[0m\n"), "FAIL")
        self.assertEqual(clean_line("x\x00y\r\n"), "x y")
        self.assertLessEqual(len(clean_line("a" * 200000)), 2800)

    def test_config_is_atomic_on_serialization_failure(self):
        item = create_system(self.project)
        save_config(self.config_path, LauncherConfig((item,)))
        original = self.config_path.read_bytes()
        with self.assertRaises(ValueError):
            save_config(self.config_path, LauncherConfig((replace(item, name="\x00"),)))
        self.assertEqual(self.config_path.read_bytes(), original)

    def test_run_py_without_app_py_and_round_trip(self):
        (self.project / "app.py").rename(self.project / "run.py")
        item = create_system(self.project, "run.py")
        argv, cwd = command_for(item)
        self.assertEqual(argv[-1], str(self.project / "run.py"))
        self.assertEqual(cwd, self.project)
        save_config(self.config_path, LauncherConfig((item,)))
        loaded, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(loaded.systems[0].entry_file, "run.py")

    def test_update_entry_file_for_next_launch(self):
        (self.project / "run.py").write_text("print('run')", encoding="utf-8")
        item = create_system(self.project)
        changed = update_system(item, name=item.name, auto_start=True,
                                restart_on_crash=False, python_path=None, entry_file="run.py")
        self.assertEqual(changed.id, item.id)
        self.assertEqual(command_for(changed)[0][-1], str(self.project / "run.py"))
        self.assertEqual(item.entry_file, "app.py")

    def test_version_two_migration_preserves_settings_and_defaults_to_app_py(self):
        item = replace(create_system(self.project), auto_start=False, restart_on_crash=True)
        entry = vars(item).copy()
        entry.pop("entry_file")
        self.config_path.write_text(json.dumps({"version": 2, "auto_start_on_open": False,
                                               "systems": [entry]}), encoding="utf-8")
        loaded, error = load_config(self.config_path)
        self.assertIsNone(error)
        self.assertEqual(loaded, LauncherConfig((item,), False))
        save_config(self.config_path, loaded)
        data = json.loads(self.config_path.read_text())
        self.assertEqual(data["version"], 3)
        self.assertEqual(data["systems"][0]["entry_file"], "app.py")

    def test_invalid_entry_paths_are_rejected(self):
        for bad in ("", "../run.py", r"..\run.py", "/run.py", r"C:\run.py", r"C:run.py",
                    "run.py\n", "run.bat", "run.py:secret.py", "run.py --debug"):
            with self.subTest(entry=bad):
                with self.assertRaises(ValueError):
                    create_system(self.project, bad)

    def test_missing_selected_entry_does_not_fall_back_to_app(self):
        with self.assertRaises(FileNotFoundError):
            create_system(self.project, "run.py")
        with self.assertRaisesRegex(FileNotFoundError, "run.py"):
            command_for(replace(create_system(self.project), entry_file="run.py"))

    def test_entry_file_cannot_escape_folder_through_symlink(self):
        outside = self.home / "outside.py"
        outside.write_text("print('outside')", encoding="utf-8")
        link = self.project / "linked.py"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        with self.assertRaises(ValueError):
            create_system(self.project, "linked.py")


if __name__ == "__main__":
    unittest.main()
