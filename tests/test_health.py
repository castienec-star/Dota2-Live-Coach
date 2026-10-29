import asyncio

from coach.config import Config
from coach.gsi_server import Coach, make_app
from coach.health import Health, cfg_problem, watch
from coach.install import install


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(tmp_path, installed=True, **kwargs):
    cfg = Config(port=4242, token="abc123")
    dota = tmp_path / "dota 2 beta"
    if installed:
        install(cfg, dota)
    clock = Clock()
    return Health(cfg, clock=clock, dota=lambda: dota, **kwargs), clock


def test_quiet_for_the_first_minute(tmp_path):
    health, clock = make(tmp_path)
    clock.now = 59
    assert health.check() is None


def test_warns_once_when_dota_stays_silent(tmp_path, caplog):
    health, clock = make(tmp_path, installed=False)
    clock.now = 61
    assert "haven't heard from Dota" in health.check()
    assert "config file is missing" in caplog.text
    assert "-gamestateintegration" in caplog.text
    clock.now = 200
    assert health.check() is None


def test_says_when_dota_connects_after_a_warning(tmp_path):
    health, clock = make(tmp_path)
    clock.now = 61
    health.check()
    health.accepted()
    assert health.check() == "Dota is connected. Good luck!"
    assert health.check() is None


def test_no_warning_when_dota_connects_in_time(tmp_path):
    health, clock = make(tmp_path)
    health.accepted()
    clock.now = 600
    assert health.check() is None


def test_wrong_token_means_install_again(tmp_path):
    health, clock = make(tmp_path)
    health.rejected()
    clock.now = 61
    assert "install again" in health.check()


def test_cfg_problems(tmp_path):
    cfg = Config(port=4242, token="abc123")
    dota = tmp_path / "dota 2 beta"
    assert "Could not find Dota" in cfg_problem(cfg, None)
    assert "missing" in cfg_problem(cfg, dota)
    install(cfg, dota)
    assert cfg_problem(cfg, dota) is None
    assert "out of date" in cfg_problem(Config(port=5000, token="abc123"), dota)


async def test_server_reports_updates(aiohttp_client, payload, tmp_path):
    coach = Coach("test-token")
    coach.health, _ = make(tmp_path)
    client = await aiohttp_client(make_app(coach))
    payload["auth"]["token"] = "nope"
    await client.post("/", json=payload)
    assert coach.health._rejected == 1 and not coach.health._connected
    payload["auth"]["token"] = "test-token"
    await client.post("/", json=payload)
    assert coach.health._connected


async def test_watch_speaks_the_check(aiohttp_client, tmp_path):
    health, clock = make(tmp_path)
    clock.now = 61
    said = []
    app = make_app(Coach("t"))
    watch(app, health, said.append, every=0.01)
    await aiohttp_client(app)
    for _ in range(100):
        if said:
            break
        await asyncio.sleep(0.01)
    assert said and "haven't heard" in said[0]
