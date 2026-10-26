import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from coach.draft import Draft, Window, analyse, counter_lines, power_windows, team_traits
from coach.heroes import HeroIndex
from coach.opendota import OpenDota, account_id

INDEX = HeroIndex()


def heroes(*names):
    return [INDEX.find(n) for n in names]


@pytest.mark.parametrize(
    "text, name",
    [("am", "Anti-Mage"), ("CM", "Crystal Maiden"), ("qop", "Queen of Pain"),
     ("Lion", "Lion"), ("naix", "Lifestealer"), ("void spirit", "Void Spirit"),
     ("npc_dota_hero_luna", "Luna"), ("tre", "Treant Protector")],
)
def test_find_hero(text, name):
    assert INDEX.find(text).name == name


def test_parse_list_with_unknown_words():
    found, unknown = INDEX.parse("am crystal maiden, lion xyz")
    assert [h.name for h in found] == ["Anti-Mage", "Crystal Maiden", "Lion"]
    assert unknown == ["xyz"]


def test_account_id_from_steam_id():
    assert account_id("76561198000000000") == 39734272
    assert account_id("39734272") == 39734272
    assert account_id(None) is None
    assert account_id("abc") is None


class FakeStats:
    """Stands in for OpenDota with made-up numbers."""

    def __init__(self, matchups=None, durations=None):
        self._matchups = matchups or {}
        self._durations = durations or {}

    def matchups(self, hero_id):
        return self._matchups.get(hero_id, {})

    def durations(self, hero_id):
        return self._durations.get(hero_id, {})


def test_team_traits_from_roles():
    good, bad = team_traits(heroes("lion", "es", "cm", "tide", "sven"))
    assert "lots of stuns and disables" in good
    assert "strong initiation" in good
    bad_team = team_traits(heroes("am", "pa", "jug"))[1]
    assert "little crowd control" in bad_team
    assert "no clear initiator to start fights" in bad_team


def test_counters_name_the_hardest_enemy():
    luna, cm = heroes("luna", "cm")
    am, pudge = heroes("am", "pudge")
    stats = FakeStats(matchups={
        luna.id: {am.id: (100, 40), pudge.id: (100, 60), 99: (800, 400)},
        cm.id: {am.id: (100, 45), pudge.id: (100, 55), 99: (800, 400)},
    })
    lines = counter_lines(Draft([luna, cm], [am, pudge], luna), stats)
    assert "Anti-Mage is the hardest enemy for your lineup overall." in lines
    assert any("Anti-Mage counters your Luna" in line for line in lines)
    assert any("Luna does well against Pudge" in line for line in lines)


def test_counters_skip_thin_samples():
    luna, am = heroes("luna", "am")
    stats = FakeStats(matchups={luna.id: {am.id: (5, 0), 99: (800, 400)}})
    assert counter_lines(Draft([luna], [am], luna), stats) == []


def curve(*rates):
    """5-minute bins from 10 minutes, 1000 games each, at these win rates."""
    return {10 + 5 * i: (1000, round(r * 1000)) for i, r in enumerate(rates)}


def test_power_windows_join_neighbouring_bins():
    luna, am = heroes("luna", "am")
    stats = FakeStats(durations={
        luna.id: curve(0.60, 0.60, 0.50, 0.40, 0.40),
        am.id: curve(0.40, 0.40, 0.50, 0.60, 0.60),
    })
    windows = power_windows(Draft([luna], [am], luna), stats)
    assert windows == [Window(10, 20, True), Window(25, 35, False)]


def test_analyse_without_stats_uses_roles_only():
    analysis = analyse(Draft(heroes("lion", "es"), heroes("am"), INDEX.find("luna")), None)
    assert analysis.counters == [] and analysis.windows == []
    assert analysis.strengths or analysis.weaknesses


@pytest.fixture
def fake_opendota():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            if self.path == "/api/heroes/48/matchups":
                body = [{"hero_id": 1, "games_played": 50, "wins": 20}]
            elif self.path == "/api/heroes/48/durations":
                body = [{"duration_bin": 1200, "games_played": 40, "wins": 25}]
            elif self.path == "/api/players/39734272/heroes":
                body = [{"hero_id": 48, "games": 12, "win": 7}]
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/api", calls
    server.shutdown()


def test_opendota_reads_and_caches(tmp_path, fake_opendota):
    url, calls = fake_opendota
    stats = OpenDota(tmp_path, base_url=url)
    assert stats.matchups(48) == {1: (50, 20)}
    assert stats.durations(48) == {20: (40, 25)}
    assert stats.player_heroes(39734272) == {48: (12, 7)}
    # A second lookup comes from the saved copy.
    assert OpenDota(tmp_path, base_url=url).matchups(48) == {1: (50, 20)}
    assert calls.count("/api/heroes/48/matchups") == 1


def test_opendota_offline_uses_saved_copy(tmp_path, fake_opendota):
    url, _ = fake_opendota
    OpenDota(tmp_path, base_url=url).matchups(48)
    offline = OpenDota(tmp_path, base_url="http://127.0.0.1:9/api", timeout=1, max_age_days=0)
    assert offline.matchups(48) == {1: (50, 20)}
    assert offline.durations(7) == {}


def test_opendota_stops_trying_after_a_failure(tmp_path, fake_opendota):
    url, calls = fake_opendota
    stats = OpenDota(tmp_path, base_url="http://127.0.0.1:9/api", timeout=1)
    assert stats.matchups(48) == {}
    stats.base_url = url
    assert stats.matchups(48) == {}
    assert calls == []
