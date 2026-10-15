"""Exercise real terminal commands, quoting, input, isolation and process cleanup."""
from dataclasses import replace
from pathlib import Path
import os
import queue
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from launcher_core import create_system
from terminal_session import TerminalSession, split_command


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "System with spaces"
        self.folder.mkdir()
        (self.folder / "app.py").write_text("", encoding="utf-8")
        self.config = replace(create_system(self.folder), python_path=sys.executable)
        self.session = TerminalSession(self.config)
        self.addCleanup(self.cleanup_session, self.session)

    def cleanup_session(self, session):
        session.close()
        self.wait_for(lambda: not session.busy, timeout=16)
        if session.process:
            self.assertIsNotNone(session.process.poll(), "Terminal process was left running")

    @staticmethod
    def wait_for(predicate, timeout=5):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def output(self, session=None):
        session = session or self.session
        chunks = []
        while True:
            try:
                kind, text = session.events.get_nowait()
            except queue.Empty:
                break
            if kind in {"output", "error", "meta"}:
                chunks.append(text)
        return "".join(chunks)

    def run_command(self, command, session=None):
        session = session or self.session
        self.assertTrue(session.execute(command))
        self.assertTrue(self.wait_for(lambda: not session.busy), command)
        return self.output(session)

    def test_python_runs_in_own_folder_using_selected_interpreter(self):
        result = self.run_command('python -c "import os,sys; print(os.getcwd()); print(sys.executable)"')
        self.assertIn(str(self.folder), result)
        self.assertIn(sys.executable, result)
        self.assertEqual(self.session.last_exit, 0)

    def test_cd_and_working_folder_are_isolated_between_systems(self):
        original = Path.cwd()
        (self.folder / "child folder").mkdir()
        other = TerminalSession(self.config)
        self.addCleanup(self.cleanup_session, other)
        self.run_command('cd "child folder"')
        self.assertEqual(self.session.cwd, self.folder / "child folder")
        self.assertEqual(other.cwd, self.folder)
        self.assertEqual(Path.cwd(), original)
        self.assertIn(str(self.folder / "child folder"), self.run_command("pwd"))
        self.assertIn(str(self.folder), self.run_command("cd .."))

    def test_partial_prompt_and_interactive_input_without_newline(self):
        script = self.folder / "ask.py"
        script.write_text('name = input("Your name? ")\nprint("Hello " + name)\n', encoding="utf-8")
        self.assertTrue(self.session.execute("python ask.py"))
        captured = []
        def prompt_visible():
            captured.append(self.output())
            return "Your name? " in "".join(captured)
        self.assertTrue(self.wait_for(prompt_visible))
        self.assertTrue(self.session.send_input("Arjun"))
        self.assertTrue(self.wait_for(lambda: not self.session.busy))
        self.assertIn("Hello Arjun", self.output())

    def test_pip_uses_same_python(self):
        result = self.run_command("pip --version")
        self.assertIn("pip ", result)
        self.assertEqual(self.session.last_exit, 0)

    def test_directory_listing_and_spaces(self):
        (self.folder / "child folder").mkdir()
        (self.folder / "child folder" / "hello.txt").write_text("hello", encoding="utf-8")
        self.assertIn("hello.txt", self.run_command('dir "child folder"'))

    def test_error_exit_and_subsequent_command(self):
        self.run_command('python -c "import sys; sys.exit(7)"')
        self.assertEqual(self.session.last_exit, 7)
        self.assertIn("Command not found", self.run_command("datatelcom_nonexistent_tool"))
        self.assertIn("Commands run", self.run_command("help"))
        self.assertIn("app.py", self.run_command("ls"))

    def test_one_command_at_a_time_and_stop(self):
        self.assertTrue(self.session.execute('python -c "import time; print(123); time.sleep(60)"'))
        self.assertTrue(self.wait_for(lambda: self.session.process is not None))
        self.assertFalse(self.session.execute("pwd"))
        proc = self.session.process
        self.session.stop()
        self.assertTrue(self.wait_for(lambda: not self.session.busy, timeout=16))
        self.assertIsNotNone(proc.poll())
        self.assertIn(str(self.folder), self.run_command("pwd"))

    def test_close_stops_running_command_and_rejects_new_commands(self):
        self.session.execute('python -c "import time; time.sleep(60)"')
        self.assertTrue(self.wait_for(lambda: self.session.process is not None))
        self.session.close()
        self.assertTrue(self.wait_for(lambda: not self.session.busy, timeout=16))
        self.assertFalse(self.session.execute("pwd"))

    @unittest.skipUnless(os.name == "nt", "Windows process-tree termination")
    def test_stop_kills_child_processes_and_keeps_other_terminal_running(self):
        import ctypes
        script = self.folder / "tree.py"
        script.write_text(
            'import subprocess, sys, time\n'
            'from pathlib import Path\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'Path("child.pid").write_text(str(child.pid))\n'
            'time.sleep(60)\n', encoding="utf-8")
        other = TerminalSession(self.config)
        self.addCleanup(self.cleanup_session, other)
        other.execute('python -c "import time; time.sleep(60)"')
        self.assertTrue(self.wait_for(lambda: other.process is not None))
        self.session.execute("python tree.py")
        pid_file = self.folder / "child.pid"
        self.assertTrue(self.wait_for(pid_file.exists))
        child_pid = int(pid_file.read_text())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        child_handle = kernel.OpenProcess(0x00100000, False, child_pid)
        self.assertTrue(child_handle)
        self.addCleanup(kernel.CloseHandle, child_handle)
        self.session.stop()
        self.assertTrue(self.wait_for(lambda: not self.session.busy, timeout=16))
        self.assertEqual(kernel.WaitForSingleObject(child_handle, 3000), 0, "Child survived Stop")
        self.assertIsNone(other.process.poll(), "Stopping one terminal affected another")

    def test_stop_during_startup_prevents_launch(self):
        import threading
        entered = threading.Event()
        proceed = threading.Event()
        real_split = split_command
        def delayed(command):
            entered.set()
            proceed.wait(timeout=3)
            return real_split(command)
        with patch("terminal_session.split_command", side_effect=delayed):
            self.session.execute('python -c "raise RuntimeError()"')
            self.assertTrue(entered.wait(timeout=3))
            self.session.stop()
            proceed.set()
            self.assertTrue(self.wait_for(lambda: not self.session.busy))
        self.assertIsNone(self.session.process)
        self.assertIn(str(self.folder), self.run_command("pwd"))

    def test_windows_quoting_preserves_backslashes_and_quoted_code(self):
        if os.name != "nt":
            self.skipTest("Windows command-line quoting")
        self.assertEqual(split_command(r'"C:\Program Files\Python\python.exe" "D:\My Apps\app.py"'),
                         [r"C:\Program Files\Python\python.exe", r"D:\My Apps\app.py"])
        args = ["python", "-c", 'print("hello world")', "", "path with spaces\\"]
        self.assertEqual(split_command(subprocess.list2cmdline(args)), args)

    def test_shell_operators_and_batch_files_are_not_executed(self):
        result = self.run_command('python -c "print(123)" && anything')
        self.assertIn("Shell operators", result)
        batch = self.folder / "bad.cmd"
        batch.write_text("@echo unexpected", encoding="utf-8")
        self.assertIn("Batch scripts require a shell", self.run_command('"' + str(batch) + '"'))

    def test_output_queue_is_bounded_and_child_is_still_drained(self):
        self.run_command('python -c "print(\'x\' * 5000000)"')
        self.assertEqual(self.session.last_exit, 0)
        self.assertGreater(self.session.dropped, 0)


if __name__ == "__main__":
    unittest.main()
