import io
import subprocess
import sys
import threading
import time

import pytest

from coach import app


def test_classify_sorts_the_coach_log():
    assert app.classify("17:35:12 Coach: Power rune in 15 seconds.\n") == app.Event(
        "said", "Power rune in 15 seconds.", "17:35:12")
    assert app.classify("17:35:12 Skipped late line: Stack now").kind == "skipped"
    assert app.classify("17:35:12 Dota 2 is connected now").kind == "connected"
    assert app.classify("17:35:12 Game state: DOTA_GAMERULES_STATE_PRE_GAME").kind == "connected"
    assert app.classify("17:35:12 New match 123").kind == "match"
    assert app.classify("17:35:12 No game state from Dota 2 yet. Check:").kind == "problem"
    assert app.classify("Traceback (most recent call last):").kind == "problem"
    version = app.classify("17:35:12 Dota 2 Live Coach, version from 2026-11-06 17:00 (abc1234)")
    assert version == app.Event("version", "2026-11-06 17:00 (abc1234)", "17:35:12")
    assert app.classify("  - The config file: OK") == app.Event("log", "  - The config file: OK")


def test_status_follows_the_events():
    status = app.Status()
    assert "off" in status.headline()
    status.running = True
    assert "Waiting for Dota 2" in status.headline()
    status.update(app.Event("problem", "No game state from Dota 2 yet. Check:"))
    assert status.problem
    status.update(app.Event("connected", "Dota 2 is connected now"))
    assert status.connected and not status.problem and "connected" in status.headline()
    status.update(app.Event("said", "Power rune in 15 seconds."))
    assert status.last_said == "Power rune in 15 seconds."
    status.update(app.Event("stopped", "The coach stopped."))
    assert not status.running and not status.connected


def test_command_runs_the_module_from_python():
    assert app.command("run") == [sys.executable, "-m", "coach", "run"]


def test_command_runs_the_console_exe_from_the_app(tmp_path, monkeypatch):
    (tmp_path / "DotaCoach.exe").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Dota 2 Live Coach.exe"))
    assert app.command("install") == [str(tmp_path / "DotaCoach.exe"), "install"]


class FakeProc:
    def __init__(self, lines, code=0):
        self.stdout = io.StringIO("".join(lines))
        self.code, self.done, self.terminated = code, False, False

    def poll(self):
        return self.code if self.done else None

    def wait(self, timeout=None):
        self.done = True
        return self.code

    def terminate(self):
        self.terminated = self.done = True


def wait_for(coach, kind):
    events = []
    for _ in range(1000):
        events += coach.events()
        if any(e.kind == kind for e in events):
            return events
        time.sleep(0.01)
    raise AssertionError(f"no {kind} event in {events}")


def test_coach_process_reads_lines_into_events():
    calls = []
    proc = FakeProc(["17:00:00 Coach: Hi\n", "\n", "17:00:01 New match 1\n"], code=1)

    def popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return proc

    coach = app.CoachProcess(popen=popen)
    coach.start()
    events = wait_for(coach, "stopped")
    assert [e.kind for e in events] == ["said", "match", "stopped"]
    assert "exit code 1" in events[-1].text
    cmd, kwargs = calls[0]
    assert cmd[-1] == "run"
    assert kwargs["stdout"] is subprocess.PIPE and kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"


def test_stop_ends_a_running_coach_and_start_twice_starts_once():
    started = []

    class Endless(FakeProc):
        def __init__(self):
            super().__init__([])
            self.ended = threading.Event()

        def wait(self, timeout=None):
            self.ended.wait(timeout)
            return super().wait()

        def terminate(self):
            super().terminate()
            self.ended.set()

    def popen(cmd, **kwargs):
        started.append(Endless())
        return started[-1]

    coach = app.CoachProcess(popen=popen)
    coach.start()
    coach.start()
    assert len(started) == 1 and coach.running
    coach.stop()
    assert started[0].terminated and not coach.running


def test_the_real_coach_starts_and_stops():
    # The same command line as the app: --version prints and exits.
    coach = app.CoachProcess(args=("--version",))
    coach.start()
    events = wait_for(coach, "stopped")
    assert [e.kind for e in events] == ["version", "stopped"]


def test_window_builds_without_a_coach_running(tmp_path):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from coach.app_window import AppWindow

    class Idle:
        running = False

        def events(self):
            return [app.Event("said", "Power rune in 15 seconds.", "17:00:00")]

        def stop(self):
            pass

    try:
        window = AppWindow(root, tmp_path, coach=Idle())
        window.poll()
        assert "Power rune" in window.log.get("1.0", "end")
        assert window.go.cget("text") == "Start"
    finally:
        root.destroy()
