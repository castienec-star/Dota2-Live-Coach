from pathlib import Path

import pytest

from coach import config
from coach.gsi_server import Coach
from coach.install import find_dota, install, library_folders, render_cfg
from coach.recorder import MatchRecorder
from coach.replay import replay


def test_token_is_created_once(tmp_path):
    first = config.load_token(tmp_path)
    assert len(first) == 32
    assert config.load_token(tmp_path) == first


def test_load_defaults_and_user_override(tmp_path):
    (tmp_path / "coach.toml").write_text("[server]\nport = 5000\n", encoding="utf-8")
    cfg = config.load(app_dir=tmp_path)
    assert cfg.port == 5000
    assert cfg.host == "127.0.0.1"
    assert cfg.record_dir == tmp_path / "recordings"


def test_refuses_non_local_host(tmp_path):
    (tmp_path / "coach.toml").write_text('[server]\nhost = "0.0.0.0"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load(app_dir=tmp_path)


def test_cfg_contains_url_and_token():
    cfg = config.Config(port=4242, token="abc123")
    text = render_cfg(cfg)
    assert '"uri"\t\t"http://127.0.0.1:4242/"' in text
    assert '"token"\t\t"abc123"' in text
    assert text.count("{") == text.count("}")


def test_finds_dota_in_second_library(tmp_path):
    steam = tmp_path / "Steam"
    other = tmp_path / "Games"
    (steam / "steamapps").mkdir(parents=True)
    (other / "steamapps" / "common" / "dota 2 beta" / "game" / "dota").mkdir(parents=True)
    escaped = str(other).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t}}\n}}\n',
        encoding="utf-8",
    )
    assert library_folders(steam) == [steam, other]
    assert find_dota(steam) == other / "steamapps" / "common" / "dota 2 beta"


def test_install_writes_cfg(tmp_path):
    target = install(config.Config(token="t"), tmp_path)
    assert target == tmp_path / "game" / "dota" / "cfg" / "gamestate_integration" / "gamestate_integration_coach.cfg"
    assert '"t"' in target.read_text(encoding="utf-8")


def test_replay_feeds_recording(tmp_path, payload):
    recorder = MatchRecorder(tmp_path)
    recorder.start("8012345678")
    for gold in (100, 200, 300):
        payload["player"]["gold"] = gold
        recorder.write(payload)
    recorder.close()

    coach = Coach("unused")
    assert replay(coach, recorder.path) == 3
    assert coach.state.current.gold == 300
