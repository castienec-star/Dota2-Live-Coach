import json

import pytest

from coach import i18n, options, voice
from coach.app import Event
from coach.app_api import Api
from coach.config import load
from coach.game_questions import ASKS, ITEMS_CHECK, parse_result, parse_yes_no
from coach.lineup import parse_position
from coach.rules import objectives, timers, windows
from coach.rules.death_tip import STAGE_TIPS, now_worded
from coach.speaker import Speaker


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def english_left(text: str) -> list[str]:
    """The sentences the catalog leaves in English."""
    return [piece for piece, done in i18n.SPEECH.split(text) if not done]


def test_language_codes():
    assert i18n.normalize("es") == i18n.normalize("ES") == i18n.normalize("Español") == "es"
    assert i18n.normalize("es-MX") == "es"
    assert i18n.normalize("en") == i18n.normalize("") == i18n.normalize("french") == "en"


def test_config_reads_the_language(tmp_path):
    user = tmp_path / "coach.toml"
    assert load(user, tmp_path).language == "en"
    user.write_text('[coach]\nlanguage = "es"\n', encoding="utf-8")
    assert load(user, tmp_path).language == "es"


def test_time_critical_lines_have_built_in_spanish():
    # Rune, stack and neutral item calls must never wait for a model.
    for name, defaults in timers.DEFAULTS.items():
        for key in ("message", "first_message", "explain"):
            if key in defaults:
                line = defaults[key].format(lead=15, camp="large", tier=2)
                assert not english_left(line), (name, line)
    assert i18n.speech("Stack the ancient camp.", "es") == "Stackea el campamento ancestral."
    assert i18n.speech("Power rune in 15 seconds.", "es") == "Runa de poder en 15 segundos."
    for line in ("Low health, back off.", "You're at 20 percent health. Use your Healing Salve before the next fight.",
                 "You are under buyback gold. Buyback costs 1200.", "Use your wand, 12 charges.",
                 "Skill point unused.", "You have gold for Black King Bar.", "Place your observer ward."):
        assert not english_left(line), line


def test_fixed_lines_have_built_in_spanish():
    lines = [objectives.NIGHT, objectives.ROSHAN, windows.OURS.format(end=25), windows.THEIRS.format(end=30),
             ITEMS_CHECK, *(ask.text for ask in ASKS)]
    for tips in STAGE_TIPS.values():
        lines += tips + [now_worded(t) for t in tips]
    for line in lines:
        assert not english_left(line), line


def test_templates_fill_in_their_values():
    say = lambda text: i18n.speech(text, "es")  # noqa: E731
    assert say("Buy a Magic Wand now: Lina and Lion cast a lot of spells.") == (
        "Compra Magic Wand ahora: Lina y Lion lanzan muchos hechizos."
    )
    assert say("The laning phase is over. Your focus now: Farm on your side of the map.") == (
        "Terminó la fase de líneas. Tu enfoque ahora: Farmea en tu lado del mapa."
    )
    assert say("Power rune at 6:00, Gold runes at 8:00.") == "Runa de poder a los 6:00, Runas de oro a los 8:00."
    # Two reminders said as one line.
    assert say("Power rune in 15 seconds. Stack the small camp.") == (
        "Runa de poder en 15 segundos. Stackea el campamento pequeño."
    )
    # A value never swallows the sentence before it.
    assert say("Match review. 50 last hits at 10 minutes is right on target.") == (
        "Revisión de la partida. 50 last hits en el minuto 10 está justo en la meta."
    )


def test_english_is_left_alone():
    assert i18n.speech("Power rune in 15 seconds.", "en") == "Power rune in 15 seconds."
    assert i18n.Translator("en", ask=lambda _: "nope")("Power rune in 15 seconds.") == "Power rune in 15 seconds."


def test_model_translates_the_rest_once_and_remembers(tmp_path):
    asked = []

    def ask(text):
        asked.append(text)
        return "Algo que el catálogo no tiene."

    cache = tmp_path / "translations_es.json"
    translate = i18n.Translator("es", ask, cache)
    line = "Power rune in 15 seconds. Something new here."
    assert translate(line) == "Runa de poder en 15 segundos. Algo que el catálogo no tiene."
    assert translate(line) == "Runa de poder en 15 segundos. Algo que el catálogo no tiene."
    assert asked == ["Something new here."]
    assert json.loads(cache.read_text(encoding="utf-8")) == {"Something new here.": "Algo que el catálogo no tiene."}
    # A new run reads the file: no model call at all.
    again = i18n.Translator("es", lambda text: pytest.fail("asked again"), cache)
    assert again(line).endswith("Algo que el catálogo no tiene.")
    assert again.quick("Something new here.") == "Algo que el catálogo no tiene."


def test_model_replies_in_spanish_are_not_translated_again():
    translate = i18n.Translator("es", ask=lambda text: pytest.fail("asked"))
    tip = "Ve con tu equipo y no farmees solo en la línea de arriba."
    assert translate(tip) == tip


def test_without_a_model_the_line_stays_english():
    assert i18n.Translator("es")("Something new here.") == "Something new here."
    # A model that answers in English is not kept.
    translate = i18n.Translator("es", ask=lambda text: "Something new here, again.")
    assert translate("Something new here.") == "Something new here."


def test_speaker_says_and_reports_the_translated_line():
    spoken, told = [], []

    class Backend:
        def speak(self, text):
            spoken.append(text)

    speaker = Speaker(lambda: Backend(), translate=i18n.Translator("es"))
    speaker.on_line = lambda text, ok: told.append(text)
    speaker.say("Low health, back off.")
    speaker.close()
    assert spoken == told == ["Poca vida, retírate."]


def test_spanish_voice_is_picked_when_none_is_set():
    voices = ["Microsoft Zira Desktop - English (United States)", "Microsoft Helena Desktop - Spanish (Spain)",
              "Microsoft Sabina Desktop - Spanish (Mexico)"]
    assert i18n.spanish_voice(voices) == "Microsoft Sabina Desktop - Spanish (Mexico)"
    assert i18n.spanish_voice(voices[:1]) is None


def test_models_are_asked_for_spanish():
    assert i18n.prompt("You are a coach.", "en") == "You are a coach."
    assert "Spanish" in i18n.prompt("You are a coach.", "es")
    i18n.set_language("es")
    assert "Spanish" in i18n.prompt("You are a coach.")


@pytest.mark.parametrize(
    "question, kind",
    [
        ("¿Cómo voy?", "how_am_i_doing"),
        ("¿Qué compro?", "what_to_buy"),
        ("¿Cuál es mi siguiente objeto?", "next_item"),
        ("¿Puedo hacer buyback?", "buyback"),
        ("¿Cuándo sale la próxima runa?", "rune"),
        ("¿En qué me enfoco?", "focus"),
        ("¿Cómo me fue hoy?", "today"),
        ("Mi rango es Archon", "rank"),
    ],
)
def test_spanish_questions(question, kind):
    i18n.set_language("es")
    assert voice.intent(question) == kind


def test_english_questions_still_work_in_spanish_mode():
    i18n.set_language("es")
    assert voice.intent("how am I doing?") == "how_am_i_doing"
    assert voice.intent("what should I buy?") == "what_to_buy"


def test_spanish_answers_to_the_coach_questions():
    assert parse_position("medio") == 2
    assert parse_position("posición cuatro") == 4
    assert parse_position("soporte") == 5
    assert parse_result("la gané") == "won"
    assert parse_result("más o menos pareja") == "even"
    assert parse_result("la perdí") == "lost"
    assert parse_yes_no("sí, mucho") is True
    assert parse_yes_no("no") is False


def test_settings_page_in_spanish():
    schema = options.schema("es")
    language = next(g for g in schema["general"] if g["id"] == "language")
    assert language["title"] == "Idioma"
    assert language["fields"][0]["choices"] == [["en", "English"], ["es", "Español"]]
    power = schema["reminders"][0]["reminders"][0]
    assert power["label"] == "Runa de poder"
    assert options.schema()["reminders"][0]["reminders"][0]["label"] == "Power rune"


def test_language_is_saved_only_when_not_the_default(tmp_path):
    api = Api(tmp_path, coach=FakeCoach(), voices=[])
    data = api.load_settings()
    assert data["language"] == "en" and data["values"]["fields"]["coach.language"] == "en"
    sent = data["values"]
    sent["fields"]["coach.language"] = "es"
    out = api.save_settings(sent)
    assert out["ok"] and out["language_changed"]
    assert 'language = "es"' in (tmp_path / "coach.toml").read_text(encoding="utf-8")
    assert api.language() == "es"
    assert api.poll()["status"]["headline"] == "El coach está apagado. Presiona Iniciar antes de tu partida."
    sent = api.load_settings()["values"]
    sent["fields"]["coach.language"] = "en"
    assert api.save_settings(sent)["language_changed"]
    assert "language" not in (tmp_path / "coach.toml").read_text(encoding="utf-8")


def test_errors_and_licence_messages_in_spanish(tmp_path):
    (tmp_path / "coach.toml").write_text('[coach]\nlanguage = "es"\n', encoding="utf-8")
    api = Api(tmp_path, coach=FakeCoach(), voices=[])
    sent = api.load_settings()["values"]
    sent["fields"]["voice.rate"] = "50"
    out = api.save_settings(sent)
    assert out["errors"] == ["Velocidad: de -10 a 10"]
    assert i18n.ui("Thanks! The coach is unlocked.", "es") == "¡Gracias! El coach está desbloqueado."


class FakeCoach:
    running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def events(self):
        return [Event("stopped", "The coach stopped.", "")] if self.running else []
