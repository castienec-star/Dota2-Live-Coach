from coach import first_run
from coach.config import Config
from coach.install import install, render_cfg

LOCALCONFIG = """\
"UserLocalConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"apps"
				{
					"570"
					{
						"LastPlayed"		"1730000000"
						"LaunchOptions"		"%s"
					}
					"440"
					{
						"LaunchOptions"		"-gamestateintegration"
					}
				}
			}
		}
	}
}
"""


def steam_with(tmp_path, options=None, account="12345"):
    steam = tmp_path / "Steam"
    if options is not None:
        vdf = steam / "userdata" / account / "config" / "localconfig.vdf"
        vdf.parent.mkdir(parents=True)
        vdf.write_text(LOCALCONFIG % options, encoding="utf-8")
    return steam


def run(tmp_path, cfg, steam, dota, said=None, printed=None):
    said = [] if said is None else said
    printed = [] if printed is None else printed
    setup = first_run.run(cfg, said.append, printed.append, steam=lambda: steam, dota=lambda _: dota)
    return setup, said, printed


def test_parse_vdf_nests_and_lowercases_keys():
    data = first_run.parse_vdf('"A" { "B" "1" "C" { "D" "two words" } }')
    assert data == {"a": {"b": "1", "c": {"d": "two words"}}}


def test_launch_option_found_missing_or_unknown(tmp_path):
    assert first_run.has_launch_option(steam_with(tmp_path / "a", "-novid -gamestateintegration")) is True
    # Another game having it doesn't count.
    assert first_run.has_launch_option(steam_with(tmp_path / "b", "-novid")) is False
    assert first_run.has_launch_option(steam_with(tmp_path / "c")) is None
    assert first_run.has_launch_option(None) is None


def test_first_start_writes_config_and_tests_the_voice(tmp_path):
    cfg = Config(port=4242, token="abc123")
    dota = tmp_path / "dota 2 beta"
    steam = steam_with(tmp_path, "-gamestateintegration")
    setup, said, printed = run(tmp_path, cfg, steam, dota)
    target = dota / "game" / "dota" / "cfg" / "gamestate_integration" / "gamestate_integration_coach.cfg"
    assert setup.wrote == target
    assert target.read_text(encoding="utf-8") == render_cfg(cfg)
    assert said == [first_run.VOICE_TEST + " If Dota is open, restart it."]
    assert any("py -m coach say" in line for line in printed)
    # Restarting Dota is the only step left.
    assert len(setup.steps) == 1 and "restart" in setup.steps[0]


def test_already_set_up_says_nothing(tmp_path):
    cfg = Config(port=4242, token="abc123")
    dota = tmp_path / "dota 2 beta"
    install(cfg, dota)
    setup, said, printed = run(tmp_path, cfg, steam_with(tmp_path, "-gamestateintegration"), dota)
    assert setup.ready and setup.wrote is None
    assert said == [] and printed == []


def test_out_of_date_config_is_rewritten(tmp_path):
    dota = tmp_path / "dota 2 beta"
    install(Config(port=3000, token="old"), dota)
    cfg = Config(port=4242, token="abc123")
    setup, said, _ = run(tmp_path, cfg, steam_with(tmp_path, "-gamestateintegration"), dota)
    assert setup.wrote is not None
    assert setup.wrote.read_text(encoding="utf-8") == render_cfg(cfg)
    assert said


def test_missing_launch_option_is_explained(tmp_path):
    cfg = Config(port=4242, token="abc123")
    dota = tmp_path / "dota 2 beta"
    setup, said, printed = run(tmp_path, cfg, steam_with(tmp_path, "-novid"), dota)
    assert setup.launch_option is False
    assert "what is left to do" in said[0]
    assert any("Launch Options" in line for line in printed)
    # Later starts print it but don't speak it: Steam's file may be stale.
    setup, said, printed = run(tmp_path, cfg, steam_with(tmp_path / "x", "-novid"), dota)
    assert setup.wrote is None and said == []
    assert any("Launch Options" in line for line in printed)


def test_unknown_launch_option_gives_the_plain_step(tmp_path):
    setup, _, printed = run(tmp_path, Config(port=4242, token="abc"), None, tmp_path / "dota 2 beta")
    assert setup.launch_option is None
    assert any("skip this if it is already there" in line for line in printed)


def test_dota_not_found_is_printed_not_spoken(tmp_path):
    setup, said, printed = run(tmp_path, Config(), None, None)
    assert not setup.ready
    assert said == []
    assert any("--dota-path" in line for line in printed)


def test_a_failing_check_never_stops_the_coach(tmp_path):
    def broken():
        raise RuntimeError("registry exploded")

    said = []
    setup = first_run.run(Config(), said.append, lambda _: None, steam=broken)
    assert setup.wrote is None and said == []
