"""Run GUI smoke tests on Windows desktop or on Linux using xvfb-run."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import os

import launcher
from launcher_core import create_system, LauncherConfig, save_config


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "Needs a graphical display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.appfolder = base / "Example Service"
        self.appfolder.mkdir()
        (self.appfolder / "app.py").write_text(
            'import time\nprint("READY FROM CHILD", flush=True)\n'
            'while True: time.sleep(0.1)\n', encoding="utf-8")
        self.config_file = base / "systems.json"
        self.item = create_system(self.appfolder)
        save_config(self.config_file, LauncherConfig((self.item,), auto_start_on_open=False))
        self.patcher = patch("launcher.config_path", return_value=self.config_file)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.root = tk.Tk()
        self.ui = launcher.LauncherUI(self.root, None)

    def tearDown(self):
        for rt in self.ui.services.values():
            if rt.terminal:
                rt.terminal.session.close()
                self.pump_until(lambda: not rt.terminal.session.busy, timeout=16)
            proc = rt.process
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)
        self.ui._cancel_pump()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump_until(self, predicate, timeout=4):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if predicate():
                return True
            time.sleep(0.04)
        return False

    def test_tab_is_created_and_child_output_visible(self):
        self.assertEqual(len(self.ui.services), 1)
        self.ui.select_system(self.item.id)
        self.assertEqual(self.ui.selected_id, self.item.id)
        self.ui.start(self.item.id)
        self.assertTrue(self.pump_until(lambda: "READY FROM CHILD" in self.ui.services[self.item.id].text.get("1.0", "end")))
        rt = self.ui.services[self.item.id]
        self.assertEqual(rt.status, "Running")
        self.ui.stop(self.item.id)
        self.assertTrue(self.pump_until(lambda: rt.status == "Stopped"))

    def test_manual_restart_preserves_a_single_live_process(self):
        rt = self.ui.services[self.item.id]
        self.ui.start(self.item.id)
        self.assertTrue(self.pump_until(lambda: "READY FROM CHILD" in rt.text.get("1.0", "end")))
        original = rt.process
        self.ui.restart(self.item.id)
        self.assertTrue(self.pump_until(lambda: rt.process is not None and rt.process is not original and rt.status == "Running"))
        self.assertIsNotNone(original.poll())
        self.ui.stop(self.item.id)
        self.assertTrue(self.pump_until(lambda: rt.status == "Stopped"))

    def test_terminal_command_does_not_change_application_state(self):
        rt = self.ui.services[self.item.id]
        terminal = rt.terminal
        self.ui.select_system(self.item.id)
        terminal.entry.insert(0, 'python -c "print(\'TERMINAL READY\')"')
        terminal.submit()
        self.assertTrue(self.pump_until(lambda: "TERMINAL READY\n" in terminal.output.get("1.0", "end")
                                       and not terminal.session.busy))
        self.assertEqual(rt.status, "Stopped")
        self.assertIsNone(rt.process)
        terminal.recall(-1)
        self.assertIn("TERMINAL READY", terminal.entry.get())
        terminal.recall(1)
        self.assertEqual(terminal.entry.get(), "")

    def test_terminal_input_and_application_output_stay_separate(self):
        rt = self.ui.services[self.item.id]
        terminal = rt.terminal
        (self.appfolder / "ask.py").write_text('print("RESPONSE=" + input("TOKEN? "))\n', encoding="utf-8")
        self.ui.start(self.item.id)
        terminal.entry.insert(0, "python ask.py")
        terminal.submit()
        self.assertTrue(self.pump_until(lambda: "TOKEN? " in terminal.output.get("1.0", "end")))
        terminal.entry.insert(0, "test-response")
        terminal.submit()
        self.assertTrue(self.pump_until(lambda: "RESPONSE=test-response" in terminal.output.get("1.0", "end")
                                       and not terminal.session.busy))
        self.assertEqual(list(terminal.history), ["python ask.py"])
        self.assertNotIn("RESPONSE=", rt.text.get("1.0", "end"))
        self.assertTrue(self.pump_until(lambda: "READY FROM CHILD" in rt.text.get("1.0", "end")))
        self.assertEqual(rt.status, "Running")

    def test_removal_is_blocked_while_terminal_command_runs(self):
        rt = self.ui.services[self.item.id]
        rt.terminal.session.execute('python -c "import time; time.sleep(60)"')
        with patch("launcher.messagebox.showwarning") as warning:
            self.ui.remove_system(self.item.id)
        warning.assert_called_once()
        self.assertIn(self.item.id, self.ui.services)

    def test_close_waits_for_terminal_command_cleanup(self):
        rt = self.ui.services[self.item.id]
        rt.terminal.session.execute('python -c "import time; time.sleep(60)"')
        self.assertTrue(self.pump_until(lambda: rt.terminal.session.process is not None))
        proc = rt.terminal.session.process
        with patch("launcher.messagebox.askyesno", return_value=True):
            self.ui.close()
        def destroyed():
            try:
                return not self.root.winfo_exists()
            except tk.TclError:
                return True
        self.assertTrue(self.pump_until(destroyed, timeout=16))
        self.assertIsNotNone(proc.poll())

    def test_large_output_remains_bounded(self):
        terminal = self.ui.services[self.item.id].terminal
        terminal.append("output", "x" * 400000)
        self.assertLess(len(terminal.output.get("1.0", "end")), 300001)
        terminal.append("output", "line\n" * 3000)
        self.assertLess(int(terminal.output.index("end-1c").split(".")[0]), 1801)

    def test_command_input_is_visible_at_minimum_window_size(self):
        width, height = self.root.minsize()
        self.root.geometry(f"{width}x{height}")
        self.ui.select_system(self.item.id)
        self.root.update()
        terminal = self.ui.services[self.item.id].terminal
        self.assertTrue(terminal.entry.winfo_viewable())
        entry_bottom = terminal.entry.winfo_rooty() + terminal.entry.winfo_height()
        self.assertLessEqual(entry_bottom, self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreater(terminal.output.winfo_height(), 35)


if __name__ == "__main__":
    unittest.main()
