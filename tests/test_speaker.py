import sys
import threading
import time

import pytest

from coach.speaker import HIGH, LOW, NORMAL, URGENT, PrintBackend, Speaker, make_backend


class Recorder:
    def __init__(self, delay=0.0):
        self.spoken = []
        self.delay = delay

    def speak(self, text):
        time.sleep(self.delay)
        self.spoken.append(text)


def test_speaks_lines_in_order():
    backend = Recorder()
    speaker = Speaker(lambda: backend)
    speaker.say("one")
    speaker.say("two")
    speaker.close()
    assert backend.spoken == ["one", "two"]


def test_drops_lines_that_waited_too_long():
    backend = Recorder(delay=0.3)
    speaker = Speaker(lambda: backend, max_delay=0.1)
    speaker.say("first")
    speaker.say("late")
    speaker.close()
    assert backend.spoken == ["first"]


def test_backend_is_created_on_speaker_thread():
    threads = []

    def factory():
        threads.append(threading.current_thread().name)
        return PrintBackend()

    Speaker(factory).close()
    assert threads == ["speaker"]


def test_print_backend_fallback():
    assert isinstance(make_backend("print"), PrintBackend)


@pytest.mark.skipif(sys.platform != "win32", reason="SAPI is Windows-only")
def test_sapi_backend_starts_on_windows():
    # Building it on a fresh thread mirrors how Speaker uses it.
    errors = []

    def build():
        try:
            from coach.speaker import SapiBackend

            SapiBackend(voice="no-such-voice", rate=1)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=build)
    t.start()
    t.join(30)
    assert errors == []


def test_busy_while_speaking():
    backend = Recorder(delay=0.3)
    speaker = Speaker(lambda: backend)
    assert not speaker.busy
    speaker.say("one")
    assert speaker.busy
    speaker.close()
    assert not speaker.busy


def test_most_important_waiting_line_goes_first():
    backend = Recorder(delay=0.2)
    speaker = Speaker(lambda: backend, max_delay=5)
    speaker.say("briefing", priority=LOW)
    time.sleep(0.05)  # the briefing is being spoken now
    speaker.say("item reminder", priority=NORMAL)
    speaker.say("rune", priority=HIGH)
    speaker.say("low health", priority=URGENT)
    speaker.close()
    assert backend.spoken == ["briefing", "low health", "rune", "item reminder"]


def test_each_line_can_wait_its_own_time():
    backend = Recorder(delay=0.3)
    speaker = Speaker(lambda: backend, max_delay=0.1)
    speaker.say("first")
    speaker.say("rune call, late")
    speaker.say("answer the player waits for", max_delay=5)
    speaker.close()
    assert backend.spoken == ["first", "answer the player waits for"]


def test_tells_each_line_spoken_or_skipped():
    backend = Recorder(delay=0.3)
    speaker = Speaker(lambda: backend, max_delay=0.1)
    told = []
    speaker.on_line = lambda text, spoken: told.append((text, spoken))
    speaker.say("first")
    speaker.say("late")
    speaker.close()
    assert told == [("first", True), ("late", False)]
