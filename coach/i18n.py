"""The coach in English or Spanish ([coach] language in coach.toml).

The coach's own lines are written in English all over the code. Rather than
touch every rule, the speaker hands each line to a Translator just before it
is spoken (coach/speaker.py):

1. Built-in Spanish first: SPEECH_ES below holds the lines and templates the
   coach says most, and every time-critical one (runes, stacks, low health,
   buyback, wand), so those never wait for a model.
2. Anything else goes to the local model (Ollama, the death tips' model), once:
   the answer is kept in translations_es.json in the app folder, so the same
   line is instant the next time.
3. Without a model the line is said in English rather than not at all.

Lines the model writes itself (death tips, the briefing, chat answers, item
advice) are asked for in Spanish to begin with (prompt()), and are left as
they are. Hero, item and ability names stay in English, as Spanish-speaking
players use them in game.

The app window's text uses the same catalog idea (UI_ES, ui()).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path

log = logging.getLogger(__name__)

LANGUAGES = (("en", "English"), ("es", "Español"))
CODES = tuple(code for code, _ in LANGUAGES)

_language = "en"


def normalize(value: object) -> str:
    """A language code the coach knows: "es" for "es", "ES", "spanish",
    "español"; anything else is English."""
    text = fold(str(value or "")).strip()
    if text in ("es", "spanish", "espanol", "castellano") or text.startswith("es-") or text.startswith("es_"):
        return "es"
    return "en"


def set_language(value: object) -> str:
    """The language for this run, set once from coach.toml at start-up."""
    global _language
    _language = normalize(value)
    return _language


def language() -> str:
    return _language


def fold(text: str) -> str:
    """Lower case without accents: "¿Cómo voy?" -> "¿como voy?" (for
    matching what the player said, in either language)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Models: write in Spanish -------------------------------------------------

REPLY_IN_SPANISH = (
    "\n\nIMPORTANT: the player speaks Spanish. Write every reply in natural, neutral "
    "Latin American Spanish (tú, not usted), even though these instructions are in "
    "English. Keep hero, item and ability names exactly as they are in English."
)


def prompt(system: str, lang: str | None = None) -> str:
    """A model's system prompt, asking for Spanish when the coach speaks it."""
    return system + REPLY_IN_SPANISH if (lang or _language) == "es" else system


# Voices --------------------------------------------------------------------

# Windows names its voices "Microsoft Sabina Desktop - Spanish (Mexico)".
SPANISH_VOICE = ("spanish", "espanol", "sabina", "helena", "laura", "pablo", "raul")


def spanish_voice(voices: Iterable[str]) -> str | None:
    """An installed Spanish voice, Latin American ones first, or None."""
    found = [v for v in voices if any(hint in fold(v) for hint in SPANISH_VOICE)]
    found.sort(key=lambda v: 0 if "mexico" in fold(v) or "latin" in fold(v) else 1)
    return found[0] if found else None


# Is this already Spanish? -------------------------------------------------

_SPANISH_WORDS = {
    "el", "la", "los", "las", "que", "tu", "tus", "con", "para", "es", "una", "por", "del", "al",
    "ahora", "cuando", "pero", "esta", "estas", "muy", "mas", "antes", "despues", "tienes",
    "puedes", "compra", "usa", "vuelve", "equipo", "oro", "vida", "partida", "juego", "enemigo",
    "enemigos", "aliados", "muertes", "si", "y", "o", "de", "en", "un", "lo", "le", "te",
}
_ENGLISH_WORDS = {
    "the", "you", "your", "and", "is", "are", "to", "of", "for", "with", "now", "buy", "use",
    "it", "in", "on", "at", "a", "an", "be", "have", "has", "can", "do", "don't", "you're",
}


def looks_spanish(text: str) -> bool:
    """True when text reads as Spanish rather than English (a model's reply
    in Spanish needs no translating)."""
    if any(c in text for c in "¿¡ñÑáéíóúÁÉÍÓÚ"):
        return True
    words = re.findall(r"[a-z']+", fold(text))
    spanish = sum(w in _SPANISH_WORDS for w in words)
    english = sum(w in _ENGLISH_WORDS for w in words)
    return spanish >= 2 and spanish > english


# The catalog engine -------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(¿¡A-Z0-9])")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


class _Entry:
    def __init__(self, english: str, spanish: str) -> None:
        self.english, self.spanish = english, spanish
        self.size = len(sentences(_PLACEHOLDER.sub("x", english)))
        self.literal = len(_PLACEHOLDER.sub("", english))
        pattern, seen = "", set()
        last = 0
        for found in _PLACEHOLDER.finditer(english):
            pattern += re.escape(english[last : found.start()])
            name = found.group(1)
            # A value never runs across sentences: "{lh} last hits ..." must
            # not swallow the sentence before it.
            pattern += f"(?P={name})" if name in seen else f"(?P<{name}>(?:(?![.!?]\\s).)+?)"
            seen.add(name)
            last = found.end()
        pattern += re.escape(english[last:])
        self.regex = re.compile(pattern, re.DOTALL)


class Catalog:
    """English lines and templates with their translation.

    A template's {name} matches any text; that text is translated too when
    the catalog (or `phrases`) knows it, so "Stack the {camp} camp." says
    the camp's size in Spanish and "Your focus now: {tip}" the tip."""

    def __init__(self, entries: Iterable[tuple[str, str]], phrases: dict[str, str] | None = None,
                 lists: Iterable[str] = ()) -> None:
        self.entries = sorted((_Entry(e, s) for e, s in entries), key=lambda e: -e.literal)
        self.exact = {e.english: e.spanish for e in self.entries if "{" not in e.english}
        self.phrases = {fold(k): v for k, v in (phrases or {}).items()}
        self.lists = set(lists)  # placeholders holding "A and B" lists
        self.longest = max((e.size for e in self.entries), default=1)

    def one(self, text: str, depth: int = 0) -> str | None:
        """The translation of text as a whole, or None when no entry fits."""
        text = text.strip()
        if text in self.exact:
            return self.exact[text]
        phrase = self.phrases.get(fold(text))
        if phrase is not None:
            return phrase
        if depth > 3:
            return None
        for entry in self.entries:
            found = entry.regex.fullmatch(text)
            if found:
                values = {k: self.value(k, v, depth) for k, v in found.groupdict().items()}
                return entry.spanish.format(**values)
        return None

    def value(self, name: str, text: str, depth: int) -> str:
        known = self.one(text, depth + 1)
        if known is not None:
            return known
        if name in self.lists:
            text = re.sub(r"\band\b", "y", text)
        return text

    def split(self, text: str) -> list[tuple[str, bool]]:
        """text as pieces, each (piece, translated?), sentence by sentence;
        templates may span a few sentences."""
        parts = sentences(text)
        out: list[tuple[str, bool]] = []
        i = 0
        while i < len(parts):
            for size in range(min(self.longest, len(parts) - i), 0, -1):
                chunk = " ".join(parts[i : i + size])
                done = self.one(chunk)
                if done is not None:
                    out.append((done, True))
                    i += size
                    break
            else:
                out.append((parts[i], looks_spanish(parts[i])))
                i += 1
        return out

    def translate(self, text: str) -> str:
        """Every sentence the catalog knows in Spanish, the rest as it was."""
        return " ".join(piece for piece, _ in self.split(text))


# Spoken lines -------------------------------------------------------------

SPEECH_ES: list[tuple[str, str]] = [
    # Map and clock (coach/rules/timers.py, objectives.py, windows.py)
    ("Power rune in {lead} seconds.", "Runa de poder en {lead} segundos."),
    ("Gold runes in {lead} seconds.", "Runas de oro en {lead} segundos."),
    ("Wisdom shrines in {lead} seconds.", "Santuarios de sabiduría en {lead} segundos."),
    ("Water rune in {lead} seconds.", "Runa de agua en {lead} segundos."),
    ("Stack the {camp} camp.", "Stackea el campamento {camp}."),
    ("Neutral items are open. Clear jungle camps to collect Madstone, and when the Madstone "
     "counter flashes, click it and pick one.",
     "Ya hay objetos neutrales. Limpia campamentos de la jungla para juntar Madstone, y cuando "
     "el contador de Madstone parpadee, haz clic y elige uno."),
    ("Tier {tier} neutral items are open. Click the Madstone counter when it flashes to upgrade yours.",
     "Ya están los objetos neutrales de nivel {tier}. Haz clic en el contador de Madstone cuando "
     "parpadee para mejorar el tuyo."),
    ("Night has started: vision is shorter, so stay near your team and ward the paths you use.",
     "Empezó la noche: ves menos, así que quédate cerca de tu equipo y pon wards en los caminos que usas."),
    ("From now on, when your team wins a fight, think Roshan: the Aegis is worth more than one more kill.",
     "Desde ahora, cuando tu equipo gane una pelea, piensa en Roshan: el Aegis vale más que una kill más."),
    ("Your team's strongest stretch starts now, until about {end} minutes. Group up and look for fights.",
     "Ahora empieza el mejor momento de tu equipo, hasta el minuto {end} más o menos. Agrúpense y busquen peleas."),
    ("The enemy lineup is strongest from now until about {end} minutes. Play safe and only fight with an advantage.",
     "El equipo enemigo es más fuerte desde ahora hasta el minuto {end} más o menos. Juega seguro y "
     "pelea solo con ventaja."),
    # Your hero (coach/rules/hero.py)
    ("Low health, back off.", "Poca vida, retírate."),
    ("You're at {hp} percent health. Use your {regen} before the next fight.",
     "Tienes {hp} por ciento de vida. Usa tu {regen} antes de la próxima pelea."),
    ("You're at {hp} percent health. Go heal before the next fight.",
     "Tienes {hp} por ciento de vida. Ve a curarte antes de la próxima pelea."),
    ("You are under buyback gold. Buyback costs {cost}.",
     "No te alcanza el oro para el buyback. El buyback cuesta {cost}."),
    ("Skill point unused.", "Tienes un punto de habilidad sin usar."),
    ("You have gold for {item}.", "Tienes oro para {item}."),
    ("Buy a {item} now: {why}.", "Compra {item} ahora: {why}."),
    ("Buy an {item} now: {why}.", "Compra {item} ahora: {why}."),
    ("Buy {item} now: {why}.", "Compra {item} ahora: {why}."),
    ("Buy a {item} now, you'll get your {target} later.", "Compra {item} ahora, tu {target} lo sacas después."),
    ("Buy an {item} now, you'll get your {target} later.", "Compra {item} ahora, tu {target} lo sacas después."),
    ("Buy {item} now, you'll get your {target} later.", "Compra {item} ahora, tu {target} lo sacas después."),
    ("Use your wand, {charges} charges.", "Usa tu varita, tiene {charges} cargas."),
    ("Place your observer ward.", "Pon tu observer ward."),
    # Why a cheap item (hero.py, situational.py); {heroes} is "Lina and Lion"
    ("{heroes} do a lot of magic damage", "{heroes} hacen mucho daño mágico"),
    ("{heroes} does a lot of magic damage", "{heroes} hace mucho daño mágico"),
    ("{heroes} cast a lot of spells", "{heroes} lanzan muchos hechizos"),
    ("{heroes} casts a lot of spells", "{heroes} lanza muchos hechizos"),
    ("{heroes} can turn invisible", "{heroes} pueden volverse invisibles"),
    ("{heroes} dodge your attacks", "{heroes} esquivan tus ataques"),
    ("{heroes} dodges your attacks", "{heroes} esquiva tus ataques"),
    ("{heroes} make illusions", "{heroes} hacen ilusiones"),
    ("{heroes} makes illusions", "{heroes} hace ilusiones"),
    ("{heroes} heal a lot", "{heroes} se curan mucho"),
    ("{heroes} heals a lot", "{heroes} se cura mucho"),
    ("{heroes} have a lot of stuns", "{heroes} tienen muchos stuns"),
    ("{heroes} has a lot of stuns", "{heroes} tiene muchos stuns"),
    ("{heroes} hit hard with attacks", "{heroes} pegan fuerte con ataques"),
    ("{heroes} hits hard with attacks", "{heroes} pega fuerte con ataques"),
    ("your team is losing fights", "tu equipo está perdiendo las peleas"),
    ("their carry is farming freely", "su carry está farmeando libre"),
    ("your lane was hard", "tu línea fue difícil"),
    ("your build list is done", "ya terminaste tu lista de objetos"),
    # What to buy (coach/situational.py)
    ("You're ahead for {minutes} minutes.", "Vas adelante a los {minutes} minutos."),
    ("You're about even for {minutes} minutes.", "Vas más o menos parejo a los {minutes} minutos."),
    ("You're behind for {minutes} minutes.", "Vas atrás a los {minutes} minutos."),
    ("You own every item I would suggest. Keep gold for buyback.",
     "Ya tienes todo lo que te recomendaría. Guarda oro para el buyback."),
    ("Buy {item} now.", "Compra {item} ahora."),
    ("Buy {item} now to stay alive.", "Compra {item} ahora para sobrevivir."),
    ("Get {item} next, {gold} more gold.", "Lo siguiente es {item}, te faltan {gold} de oro."),
    ("Get {item} next, {gold} more gold: {why}.", "Lo siguiente es {item}, te faltan {gold} de oro: {why}."),
    ("Get {item} next, {gold} more gold to stay alive.",
     "Lo siguiente es {item}, te faltan {gold} de oro, para sobrevivir."),
    # Ahead or behind (coach/benchmarks.py)
    ("You're ahead for {minutes}. Use it: group with your team and take a tower, or Roshan after a won fight.",
     "Vas adelante {minutes}. Aprovéchalo: agrúpate con tu equipo y tira una torre, o Roshan "
     "después de ganar una pelea."),
    ("You're about even for {minutes}. Keep farming and fight together with your team.",
     "Vas más o menos parejo {minutes}. Sigue farmeando y pelea junto a tu equipo."),
    ("You're behind for {minutes}, your {low}. Stay near your cores and soak experience from fights.",
     "Vas atrás {minutes}, {low}. Quédate cerca de tus cores y gana experiencia de las peleas."),
    ("You're behind for {minutes}, your {low}. Stay near your cores, soak experience from fights, "
     "and buy Glimmer Cape or Force Staff to stay alive.",
     "Vas atrás {minutes}, {low}. Quédate cerca de tus cores, gana experiencia de las peleas "
     "y compra Glimmer Cape o Force Staff para sobrevivir."),
    ("You're behind for {minutes}, your {low}. Farm the safe side of the map near your towers and skip risky fights.",
     "Vas atrás {minutes}, {low}. Farmea en el lado seguro del mapa cerca de tus torres y "
     "evita peleas arriesgadas."),
    ("You're behind for {minutes}, your {low}. Farm the safe side of the map near your towers, "
     "skip risky fights, and buy a Black King Bar or a defensive item.",
     "Vas atrás {minutes}, {low}. Farmea en el lado seguro del mapa cerca de tus torres, "
     "evita peleas arriesgadas y compra un Black King Bar o un objeto defensivo."),
    ("{minutes} minutes", "a los {minutes} minutos"),
    ("{rank} at {minutes} minutes", "para un {rank} a los {minutes} minutos"),
    ("gold is low", "tu oro está bajo"),
    ("experience is low", "tu experiencia está baja"),
    ("last hits are low", "tus last hits están bajos"),
    ("That's a rough comparison with {group} in general.", "Es una comparación aproximada con {group} en general."),
    ("cores", "los cores"),
    ("supports", "los supports"),
    ("{rank} cores", "los cores {rank}"),
    ("{rank} supports", "los supports {rank}"),
    ("The game has just started. Focus on last hits and don't die, and ask me again in a few minutes.",
     "La partida acaba de empezar. Concéntrate en los last hits y en no morir, y vuelve a preguntarme "
     "en unos minutos."),
    ("No deaths yet, good.", "Ninguna muerte todavía, bien."),
    ("One death so far: stay out of the enemy's reach in lane.",
     "Una muerte hasta ahora: mantente fuera del alcance del enemigo en la línea."),
    ("{deaths} deaths already: play safer and stay near your tower.",
     "Ya van {deaths} muertes: juega más seguro y quédate cerca de tu torre."),
    ("It's too early to judge a support at {minute} minutes.",
     "Es muy pronto para juzgar a un support en el minuto {minute}."),
    ("Keep your core safe and stack a camp when you can.",
     "Cuida a tu core y stackea un campamento cuando puedas."),
    ("{lh} last hits at {minute} minutes, that's on track.",
     "{lh} last hits en el minuto {minute}, vas bien."),
    ("{lh} last hits at {minute} minutes, aim for about {target}.",
     "{lh} last hits en el minuto {minute}, apunta a unos {target}."),
    # Last hits, focus (coach/rules/last_hits.py, focus_check.py)
    ("{have} last hits at {minute} minutes, great farming. Keep it up.",
     "{have} last hits en el minuto {minute}, muy buen farm. Sigue así."),
    ("{have} last hits at {minute} minutes, up from {previous} last game, great farming. Keep it up.",
     "{have} last hits en el minuto {minute}, más que los {previous} de la partida anterior, muy buen "
     "farm. Sigue así."),
    ("{have} last hits at {minute} minutes, close to the {target} to aim for. Keep at it.",
     "{have} last hits en el minuto {minute}, cerca de los {target} que buscas. Sigue así."),
    ("{have} last hits at {minute} minutes, up from {previous} last game, close to the {target} to aim for. Keep at it.",
     "{have} last hits en el minuto {minute}, más que los {previous} de la partida anterior, cerca de "
     "los {target} que buscas. Sigue así."),
    ("{have} last hits at {minute} minutes; aim for about {target}.",
     "{have} last hits en el minuto {minute}; apunta a unos {target}."),
    ("{have} last hits at {minute} minutes, up from {previous} last game; aim for about {target}.",
     "{have} last hits en el minuto {minute}, más que los {previous} de la partida anterior; apunta a "
     "unos {target}."),
    ("Hit a creep when its health drops under one of your attacks, and don't chase kills in lane.",
     "Golpea al creep cuando su vida baje de uno de tus ataques, y no persigas kills en la línea."),
    ("Between waves, take the nearest jungle camp instead of walking around.",
     "Entre oleadas, toma el campamento de jungla más cercano en vez de caminar por ahí."),
    ("The laning phase is over.", "Terminó la fase de líneas."),
    ("Your focus now: {tip}", "Tu enfoque ahora: {tip}"),
    # Death tips (coach/rules/death_tip.py) and "what should I focus on?"
    ("Next life, last hit when a creep's health drops under one hit, and don't chase kills.",
     "En tu próxima vida, haz last hit cuando la vida del creep baje de un golpe, y no persigas kills."),
    ("Last hit when a creep's health drops under one hit, and don't chase kills.",
     "Haz last hit cuando la vida del creep baje de un golpe, y no persigas kills."),
    ("Early deaths usually come from walking past the river without vision.",
     "Las muertes tempranas suelen venir de cruzar el río sin visión."),
    ("Stay on your side of the lane.", "Quédate en tu lado de la línea."),
    ("Ward before you walk forward.", "Pon un ward antes de avanzar."),
    ("Go back or use your regen when your health is low, instead of staying for one more creep.",
     "Vuelve o usa tu regeneración cuando tengas poca vida, en vez de quedarte por un creep más."),
    ("Go back or use your regen when your health is low, instead of staying for one more hit.",
     "Vuelve o usa tu regeneración cuando tengas poca vida, en vez de quedarte por un golpe más."),
    ("Stack the nearest camp when the clock shows 53 seconds, and take the gold runes for your team.",
     "Stackea el campamento más cercano cuando el reloj marque 53 segundos, y toma las runas de oro "
     "para tu equipo."),
    ("Next life, farm the jungle camp between waves instead of walking around the map.",
     "En tu próxima vida, farmea el campamento de jungla entre oleadas en vez de caminar por el mapa."),
    ("Farm the jungle camp between waves instead of walking around the map.",
     "Farmea el campamento de jungla entre oleadas en vez de caminar por el mapa."),
    ("Farm on your side of the map.", "Farmea en tu lado del mapa."),
    ("The far lanes are where you get caught alone.", "En las líneas lejanas es donde te atrapan solo."),
    ("After a won fight, take a tower or Roshan instead of going back to farm.",
     "Después de ganar una pelea, tira una torre o haz Roshan en vez de volver a farmear."),
    ("As a support, stay with your team, and buy wards and a Glimmer Cape or Force Staff.",
     "Como support, quédate con tu equipo y compra wards y una Glimmer Cape o Force Staff."),
    ("Keep wards up on your side of the map and walk with your cores, not alone.",
     "Mantén wards en tu lado del mapa y camina con tus cores, no solo."),
    ("After a won fight, take a tower or Roshan with your team.",
     "Después de ganar una pelea, tira una torre o haz Roshan con tu equipo."),
    ("Never farm a side lane alone now.", "Ya no farmees solo en una línea lateral."),
    ("One death this late can lose the game.", "Una muerte tan tarde puede costar la partida."),
    ("Go to the enemy high ground only with your whole team, best with Aegis.",
     "Sube a la base enemiga solo con todo tu equipo, mejor con Aegis."),
    ("Defend your base together.", "Defiendan la base juntos."),
    ("Don't trade a Barracks for farm in a far lane.", "No cambies unas barracas por farm en una línea lejana."),
    ("Stay with your team now.", "Ahora quédate con tu equipo."),
    ("One pick-off this late can lose the game.", "Que te atrapen tan tarde puede costar la partida."),
    ("Defend your base together, and keep a Town Portal scroll to get there.",
     "Defiendan la base juntos, y ten un Town Portal para llegar."),
    ("Save gold for buyback before you take the next fight.",
     "Guarda oro para el buyback antes de la próxima pelea."),
    ("Next life, find {name} on the minimap before you fight, and don't meet {name} alone.",
     "En tu próxima vida, busca a {name} en el minimapa antes de pelear, y no te encuentres con {name} solo."),
    ("Find {name} on the minimap before you fight, and don't meet {name} alone.",
     "Busca a {name} en el minimapa antes de pelear, y no te encuentres con {name} solo."),
    ("Your last hits are low. Farm safer lanes and jungle camps next life.",
     "Tienes pocos last hits. En tu próxima vida farmea líneas más seguras y campamentos de jungla."),
    ("Your last hits are low. Farm safe lanes and jungle camps between waves.",
     "Tienes pocos last hits. Farmea líneas seguras y campamentos de jungla entre oleadas."),
    ("You are dying often. Play closer to your team and back off earlier.",
     "Estás muriendo mucho. Juega más cerca de tu equipo y retírate antes."),
    ("Your team is losing fights. Next life, wait for them and fight together near your towers.",
     "Tu equipo está perdiendo las peleas. En tu próxima vida, espéralos y peleen juntos cerca de sus torres."),
    ("Your team is losing fights. Wait for them and fight together near your towers.",
     "Tu equipo está perdiendo las peleas. Espéralos y peleen juntos cerca de sus torres."),
    ("Buy a Town Portal scroll before you leave the fountain.", "Compra un Town Portal antes de salir de la fuente."),
    ("Buy a Town Portal scroll and keep it on you, so you can join fights and save towers.",
     "Compra un Town Portal y llévalo siempre, para unirte a peleas y salvar torres."),
    ("Your health is low. Back off and heal before anything else.",
     "Tienes poca vida. Retírate y cúrate antes que nada."),
    ("As {name}, stand behind your team and attack from as far away as you can. You are fragile.",
     "Con {name}, quédate detrás de tu equipo y ataca desde lo más lejos que puedas. Eres frágil."),
    ("As {name}, join the next fight with your team instead of farming alone.",
     "Con {name}, únete a la próxima pelea con tu equipo en vez de farmear solo."),
    ("That's {deaths} deaths in {minutes} minutes. Take a breath: farm near your towers until your team groups up.",
     "Son {deaths} muertes en {minutes} minutos. Respira: farmea cerca de tus torres hasta que tu equipo se agrupe."),
    ("That's {deaths} deaths in {minutes} minutes. Take a breath: farm near your towers until your "
     "team groups up and get {item} before anything greedy.",
     "Son {deaths} muertes en {minutes} minutos. Respira: farmea cerca de tus torres hasta que tu equipo "
     "se agrupe, y compra {item} antes que cualquier objeto de farm."),
    ("You used {spell} at low health. Heal up before you start the next fight.",
     "Usaste {spell} con poca vida. Cúrate antes de empezar la próxima pelea."),
    ("You died with your {item} ready. Press it as soon as the fight turns.",
     "Moriste con tu {item} listo. Úsalo apenas la pelea se complique."),
    ("You died with {spell} ready. Use your ultimate earlier in the fight.",
     "Moriste con {spell} listo. Usa tu ultimate antes en la pelea."),
    ("You died with {charges} wand charges. Press your wand when you get low.",
     "Moriste con {charges} cargas en la varita. Úsala cuando tengas poca vida."),
    # Answers to questions (coach/voice.py, chat.py, rank.py, review.py)
    ("I can't help with that yet. Ask me how you're doing, what to focus on, what to buy, how you did "
     "today, or about your next item, buyback or runes.",
     "Todavía no puedo ayudarte con eso. Pregúntame cómo vas, en qué enfocarte, qué comprar, cómo te fue "
     "hoy, o por tu siguiente objeto, el buyback o las runas."),
    ("I can't answer that one without the AI model. Ask me how you're doing, what to buy, or about your "
     "next item, buyback or runes.",
     "No puedo responder eso sin el modelo de IA. Pregúntame cómo vas, qué comprar, o por tu siguiente "
     "objeto, el buyback o las runas."),
    ("Start Ollama to ask me anything.", "Abre Ollama para preguntarme lo que quieras."),
    ("I'm not sure about that one. Try asking another way.", "No estoy seguro de eso. Pregúntamelo de otra forma."),
    ("I can't see your hero yet. Ask me again once the game has started.",
     "Todavía no veo tu héroe. Pregúntame de nuevo cuando empiece la partida."),
    ("Your build list is done.", "Ya terminaste tu lista de objetos."),
    ("Buy {item} now, you have the gold.", "Compra {item} ahora, tienes el oro."),
    ("Next is {item}. You need {gold} more gold.", "Lo siguiente es {item}. Te faltan {gold} de oro."),
    ("Buyback isn't available yet.", "El buyback todavía no está disponible."),
    ("Buyback is on cooldown for {seconds} seconds.", "El buyback está en enfriamiento por {seconds} segundos."),
    ("You can't buy back. It costs {cost} and you have {gold}.",
     "No puedes hacer buyback. Cuesta {cost} y tienes {gold}."),
    ("You can buy back for {cost}.", "Puedes hacer buyback por {cost}."),
    ("Only do it to defend your base or join a big fight.",
     "Hazlo solo para defender tu base o unirte a una pelea grande."),
    ("Rune reminders are turned off.", "Los avisos de runas están apagados."),
    ("{a} at {t1}.", "{a} a los {t1}."),
    ("{a} at {t1}, {b} at {t2}.", "{a} a los {t1}, {b} a los {t2}."),
    ("{a} at {t1}, {b} at {t2}, {c} at {t3}.", "{a} a los {t1}, {b} a los {t2}, {c} a los {t3}."),
    ("Power rune", "Runa de poder"),
    ("Gold runes", "Runas de oro"),
    ("Wisdom shrines", "Santuarios de sabiduría"),
    ("What's your rank? Say your medal, like Crusader or Legend, or your MMR.",
     "¿Cuál es tu rango? Di tu medalla, como Crusader o Legend, o tu MMR."),
    ("Got it, {rank}.", "Entendido, {rank}."),
    ("I'll compare you with {rank} players.", "Te voy a comparar con jugadores {rank}."),
    ("I don't have numbers for each rank yet, so for now it's all players.",
     "Todavía no tengo números para cada rango, así que por ahora es con todos los jugadores."),
    ("I can't keep your rank in this mode.", "No puedo guardar tu rango en este modo."),
    ("I don't know your rank yet. Say my rank is, and your medal, like Archon, or your MMR.",
     "Todavía no sé tu rango. Di \"my rank is\" y tu medalla, como Archon, o tu MMR."),
    ("Match reviews are off, so I don't keep count of today's games.",
     "Las revisiones de partidas están apagadas, así que no cuento las partidas de hoy."),
    ("No games today yet. I count them from my match reviews, so ask me again after a game.",
     "Todavía no hay partidas hoy. Las cuento con mis revisiones, así que pregúntame después de una partida."),
    ("No point came up twice: steady games.", "Ningún punto se repitió: partidas estables."),
    ("You won the last one, a good game to stop on if you're tired.",
     "Ganaste la última, buena partida para parar si estás cansado."),
    ("Match reviews are off, so I can't compare your games.",
     "Las revisiones de partidas están apagadas, así que no puedo comparar tus partidas."),
    ("I need at least {need} games in my match reviews to see a trend, and I have {have}.",
     "Necesito al menos {need} partidas en mis revisiones para ver una tendencia, y tengo {have}."),
    ("Ask me again after a few more games.", "Pregúntame de nuevo después de unas partidas más."),
    ("In your last {n} games you died {d} times a game, down from {b}.",
     "En tus últimas {n} partidas moriste {d} veces por partida, menos que las {b} de antes."),
    ("In your last {n} games you died {d} times a game, up from {b}.",
     "En tus últimas {n} partidas moriste {d} veces por partida, más que las {b} de antes."),
    ("In your last {n} games you died {d} times a game, about the same as before.",
     "En tus últimas {n} partidas moriste {d} veces por partida, más o menos igual que antes."),
    ("Last hits at 10 minutes: {lh}, down from {b}.", "Last hits en el minuto 10: {lh}, menos que los {b} de antes."),
    ("Last hits at 10 minutes: {lh}, up from {b}.", "Last hits en el minuto 10: {lh}, más que los {b} de antes."),
    ("Last hits at 10 minutes: {lh}, about the same as before.",
     "Last hits en el minuto 10: {lh}, más o menos igual que antes."),
    ("You're getting better.", "Estás mejorando."),
    ("Keep doing what changed.", "Sigue haciendo lo que cambiaste."),
    ("Dying less is the quickest way to win more games.", "Morir menos es la forma más rápida de ganar más partidas."),
    ("Next game, walk back to your tower when your health is low, and don't chase into the fog.",
     "La próxima partida, vuelve a tu torre cuando tengas poca vida, y no persigas hacia la niebla."),
    ("Steady so far.", "Estable por ahora."),
    ("Pick one thing to work on: ask me what to focus on during the game.",
     "Elige una cosa para mejorar: pregúntame en qué enfocarme durante la partida."),
    # The post-game review (coach/review.py); also the Progress page's notes
    ("Match review.", "Revisión de la partida."),
    ("You died {n} times before 10 minutes.", "Moriste {n} veces antes del minuto 10."),
    ("In lane, stand behind your creeps and walk back to your tower when your health is low.",
     "En la línea, quédate detrás de tus creeps y vuelve a tu torre cuando tengas poca vida."),
    ("You died {n} times between {a} and {b} minutes.", "Moriste {n} veces entre el minuto {a} y el {b}."),
    ("After a death, farm near your towers for a minute instead of walking back into the same fight.",
     "Después de morir, farmea un minuto cerca de tus torres en vez de volver a la misma pelea."),
    ("You died {n} times.", "Moriste {n} veces."),
    ("Before you walk forward, think about where the enemies you can't see might be, and keep a Town Portal scroll.",
     "Antes de avanzar, piensa dónde pueden estar los enemigos que no ves, y lleva un Town Portal."),
    ("You had {lh} last hits at 10 minutes; aim for {target}.",
     "Tuviste {lh} last hits en el minuto 10; apunta a {target}."),
    ("Five minutes of last hitting in a lobby before you queue helps a lot.",
     "Cinco minutos practicando last hits en un lobby antes de buscar partida ayudan mucho."),
    ("Five minutes of last hitting in a lobby before you queue helps.",
     "Cinco minutos practicando last hits en un lobby antes de buscar partida ayudan."),
    ("You didn't finish an item over {cost} gold in {minutes} minutes.",
     "No terminaste ningún objeto de más de {cost} de oro en {minutes} minutos."),
    ("A support's Glimmer Cape or Force Staff saves lives, so save up for one.",
     "Una Glimmer Cape o Force Staff de support salva vidas, así que ahorra para una."),
    ("Farm your lane and the jungle camps next to it between fights.",
     "Farmea tu línea y los campamentos de jungla cercanos entre peleas."),
    ("Your first big item, {item}, came at {minutes} minutes.",
     "Tu primer objeto grande, {item}, llegó en el minuto {minutes}."),
    ("Pull or stack a camp when your core can lane alone.",
     "Haz pull o stackea un campamento cuando tu core pueda estar solo en la línea."),
    ("Aim for about {minutes}: take the jungle camps near your lane between creep waves.",
     "Apunta al minuto {minutes} más o menos: toma los campamentos cerca de tu línea entre oleadas."),
    ("Only {deaths} deaths in {minutes} minutes: staying alive like that wins games, keep it up.",
     "Solo {deaths} muertes en {minutes} minutos: sobrevivir así gana partidas, sigue así."),
    ("{lh} last hits at 10 minutes is right on target.", "{lh} last hits en el minuto 10 está justo en la meta."),
    ("A steady game with nothing big to fix.", "Una partida estable, sin nada grande que corregir."),
    ("Next game, try to stack a camp or take a rune you'd usually skip.",
     "La próxima partida, intenta stackear un campamento o tomar una runa que normalmente dejarías."),
    ("You fixed last game's point: {what}. Well done.", "Corregiste el punto de la partida anterior: {what}. Bien hecho."),
    ("Better than last game: {what}. Keep working on it.", "Mejor que la partida anterior: {what}. Sigue trabajándolo."),
    ("Last game's point is still the one to work on: {what}.",
     "El punto de la partida anterior sigue siendo el que hay que trabajar: {what}."),
    ("{now} death this game, after {before} last game", "{now} muerte esta partida, después de {before} en la anterior"),
    ("{now} deaths this game, after {before} last game", "{now} muertes esta partida, después de {before} en la anterior"),
    ("{now} last hits at 10 minutes, up from {before}", "{now} last hits en el minuto 10, más que los {before} de antes"),
    ("{now} last hits at 10 minutes, after {before} last game",
     "{now} last hits en el minuto 10, después de {before} en la partida anterior"),
    ("no big item this game", "ningún objeto grande esta partida"),
    ("your first big item came at {now} minutes, after none last game",
     "tu primer objeto grande llegó en el minuto {now}, y en la anterior no hubo"),
    ("your first big item came at {now} minutes, after {before} last game",
     "tu primer objeto grande llegó en el minuto {now}, después del {before} en la anterior"),
    ("That's {n} losses in a row.", "Son {n} derrotas seguidas."),
    ("Take a ten-minute break before the next game: stand up, drink some water.",
     "Toma un descanso de diez minutos antes de la próxima partida: levántate, toma agua."),
    ("A short break helps more than another queue.", "Un descanso corto ayuda más que otra partida."),
    ("Deaths", "Muertes"),
    ("Last hits", "Last hits"),
    ("A late first item", "Un primer objeto tardío"),
    ("walk back to your tower when your health is low, and don't chase into the fog",
     "vuelve a tu torre cuando tengas poca vida, y no persigas en la niebla"),
    ("watch the creeps' health and only hit when one is about to die",
     "mira la vida de los creeps y golpea solo cuando uno esté por morir"),
    ("farm the jungle camps next to your lane between waves",
     "farmea los campamentos de jungla junto a tu línea entre oleadas"),
    ("{what} came up most, in {times} of {games} reviews. Next game, {tip}.",
     "{what} salió más, en {times} de {games} revisiones. La próxima partida, {tip}."),
    # Questions the coach asks (coach/game_questions.py, lineup.py, enemy_items.py)
    ("Check the enemy items, then tell me what you see.", "Revisa los objetos enemigos y dime qué ves."),
    ("How did your lane go: won, even or lost?", "¿Cómo te fue en la línea: ganada, pareja o perdida?"),
    ("Which enemy hero is giving you the most trouble?", "¿Qué héroe enemigo te está dando más problemas?"),
    ("Is their carry farming freely?", "¿Su carry está farmeando libre?"),
    ("Is your team ahead or behind in fights?", "¿Tu equipo va ganando o perdiendo las peleas?"),
    ("Okay, it happens. Farm the safe camps near your towers and catch up; the game is long.",
     "Bueno, pasa. Farmea los campamentos seguros cerca de tus torres y recupérate; la partida es larga."),
    ("Nice. Use the lead: push a tower or help another lane.",
     "Bien. Aprovecha la ventaja: empuja una torre o ayuda a otra línea."),
    ("Okay. Keep last hitting and watch the minimap.", "Bien. Sigue haciendo last hits y mira el minimapa."),
    ("Got it, {name}. Check where {name} is on the map before you fight, and don't fight them alone.",
     "Entendido, {name}. Mira dónde está {name} en el mapa antes de pelear, y no lo enfrentes solo."),
    ("Then group up with your team and go find their carry, or they will win the late game.",
     "Entonces agrúpate con tu equipo y vayan por su carry, o ganarán el juego tardío."),
    ("Good. Keep putting pressure on them.", "Bien. Sigan presionándolos."),
    ("Then stay together, don't fight in the open and farm until your big item is ready.",
     "Entonces quédense juntos, no peleen en campo abierto y farmea hasta tener tu objeto grande."),
    ("Then after each won fight take a tower or Roshan; don't just go back to farming.",
     "Entonces después de cada pelea ganada tiren una torre o hagan Roshan; no vuelvan solo a farmear."),
    ("Okay. Fight when your key spells and items are ready, and together.",
     "Bien. Peleen cuando tengan listos sus hechizos y objetos clave, y juntos."),
    ("What position are you playing, one to five?", "¿Qué posición juegas, del uno al cinco?"),
    ("Sorry, I didn't catch that. Skipping.", "Perdón, no te entendí. Lo salto."),
    ("Position {n}, {role}.", "Posición {n}, {role}."),
    ("safe lane carry", "carry de línea segura"),
    ("mid", "medio"),
    ("offlane", "línea difícil"),
    ("soft support", "support 4"),
    ("hard support", "support 5"),
    ("Who's on your team?", "¿Quiénes están en tu equipo?"),
    ("Who are the enemy heroes?", "¿Cuáles son los héroes enemigos?"),
    ("Okay, skipping.", "Bueno, lo salto."),
    ("Okay, say them again.", "Bueno, dímelos otra vez."),
    ("Sorry, I didn't catch any heroes. You can type them instead.",
     "Perdón, no entendí ningún héroe. Puedes escribirlos."),
    ("Type your position, your team and the enemy heroes in the coach window.",
     "Escribe tu posición, tu equipo y los héroes enemigos en la ventana del coach."),
    ("Okay, I forgot the enemy items.", "Bueno, olvidé los objetos enemigos."),
    ("Got it, {hero} has {items}.", "Entendido, {hero} tiene {items}."),
    # Start-up and health (coach/first_run.py, health.py, voice.py)
    ("Hi, I'm your Dota coach.", "Hola, soy tu coach de Dota."),
    ("Dota is set up.", "Dota está configurado."),
    ("If you hear me, the voice works.", "Si me escuchas, la voz funciona."),
    ("If Dota is open, restart it.", "Si Dota está abierto, reinícialo."),
    ("The coach window shows what is left to do.", "La ventana del coach muestra lo que falta hacer."),
    ("Dota sends game data with an old setup. Run coach install again, then restart Dota.",
     "Dota manda los datos con una configuración vieja. Vuelve a instalar el coach y reinicia Dota."),
    ("I haven't heard from Dota yet. Check the coach window for what to fix.",
     "Todavía no recibo nada de Dota. Mira la ventana del coach para ver qué arreglar."),
    ("Voice questions are off. Run update dot bat to turn them on.",
     "Las preguntas por voz están apagadas. Ejecuta update punto bat para activarlas."),
    ("Dota 2 is connected now.", "Dota 2 ya está conectado."),
]

# Words inside templates ({camp}, {low}, ...).
PHRASES_ES = {
    "small": "pequeño",
    "medium": "mediano",
    "large": "grande",
    "ancient": "ancestral",
}

LIST_PLACEHOLDERS = ("heroes", "items")

SPEECH = Catalog(SPEECH_ES, PHRASES_ES, LIST_PLACEHOLDERS)


# The model, for lines not in the catalog ----------------------------------

TRANSLATE_PROMPT = (
    "You translate short lines that a Dota 2 coach says to a player through their headset "
    "into natural, neutral Latin American Spanish (tú, not usted). Keep hero, item, ability "
    "and rune names in English as Dota players say them, keep every number, and keep it short "
    "and spoken. Reply with the Spanish line only: no quotes, no notes."
)
CACHE_FILE = "translations_es.json"


class Translator:
    """Turns an English line into the coach's language (see the module notes).

    ask(text) is the model (None when it is off or slow); cache_file keeps its
    answers between matches. Call it from the speaker's thread: a model call
    can take a second or two."""

    def __init__(
        self,
        lang: str = "es",
        ask: Callable[[str], str | None] | None = None,
        cache_file: Path | None = None,
        catalog: Catalog = SPEECH,
    ) -> None:
        self.lang = normalize(lang)
        self.ask = ask
        self.catalog = catalog
        self.cache_file = cache_file
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}
        if cache_file is not None and cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self._cache = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
            except (OSError, ValueError) as exc:
                log.warning("Could not read %s (%s); translating again", cache_file, exc)

    def quick(self, text: str) -> str:
        """Only what is known already (the catalog and earlier model answers)."""
        if self.lang == "en":
            return text
        return " ".join(self._cache.get(piece, piece) if not done else piece
                        for piece, done in self.catalog.split(text))

    def __call__(self, text: str) -> str:
        if self.lang == "en" or not text.strip():
            return text
        out: list[str] = []
        waiting: list[str] = []  # English sentences in a row, translated together

        def flush() -> None:
            if waiting:
                out.append(self._model(" ".join(waiting)))
                waiting.clear()

        for piece, done in self.catalog.split(text):
            if done:
                flush()
                out.append(piece)
            else:
                waiting.append(piece)
        flush()
        return " ".join(out)

    def _model(self, english: str) -> str:
        with self._lock:
            if english in self._cache:
                return self._cache[english]
        if self.ask is None:
            return english
        try:
            spanish = self.ask(english)
        except Exception:
            log.exception("Could not translate %r", english)
            spanish = None
        if not spanish or not looks_spanish(spanish):
            log.info("No Spanish for %r; saying it in English", english)
            return english
        with self._lock:
            self._cache[english] = spanish
            self._save()
        return spanish

    def _save(self) -> None:
        if self.cache_file is None:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save %s (%s)", self.cache_file, exc)


# The app window -----------------------------------------------------------

UI_ES: list[tuple[str, str]] = [
    # Status (coach/app.py)
    ("The coach is off. Press Start before your match.", "El coach está apagado. Presiona Iniciar antes de tu partida."),
    ("Coaching: Dota 2 is connected.", "Entrenando: Dota 2 está conectado."),
    ("Waiting for Dota 2. Start a match (a bot match works).",
     "Esperando a Dota 2. Empieza una partida (sirve una contra bots)."),
    ("The coach stopped.", "El coach se detuvo."),
    ("The coach stopped (exit code {code}).", "El coach se detuvo (código {code})."),
    # The simple window (coach/app_window.py)
    ("Start", "Iniciar"),
    ("Stop", "Detener"),
    ("Settings", "Configuración"),
    ("Set up Dota 2", "Configurar Dota 2"),
    ("Match reviews", "Revisiones de partidas"),
    ("Show details", "Mostrar detalles"),
    ("Lines the coach says will appear here.", "Aquí aparecen las frases del coach."),
    ("(too late, skipped)", "(tarde, saltada)"),
    ("Last line: {line}", "Última frase: {line}"),
    ("version {v}", "versión {v}"),
    ("Setting up Dota 2's Game State Integration...", "Configurando el Game State Integration de Dota 2..."),
    ("Match reviews are in {folder}", "Las revisiones de partidas están en {folder}"),
    # Licence (coach/license.py)
    ("Your subscription has ended. Renew it to keep using the coach.",
     "Tu suscripción terminó. Renuévala para seguir usando el coach."),
    ("This key was turned off. Check your subscription, or contact support.",
     "Esta clave fue desactivada. Revisa tu suscripción o contacta a soporte."),
    ("This key is already used on another PC. Deactivate it there first.",
     "Esta clave ya se usa en otra PC. Desactívala allá primero."),
    ("That key doesn't work. Copy it from your receipt email and try again.",
     "Esa clave no funciona. Cópiala del correo de tu compra e inténtalo de nuevo."),
    ("Paste the licence key from your receipt email.", "Pega la clave de licencia del correo de tu compra."),
    ("Can't reach the licence server. Check your internet connection and try again.",
     "No se puede conectar al servidor de licencias. Revisa tu conexión a internet e inténtalo de nuevo."),
    ("Thanks! The coach is unlocked.", "¡Gracias! El coach está desbloqueado."),
    ("Enter your licence key to start.", "Ingresa tu clave de licencia para empezar."),
    ("The coach couldn't check your key for {days} days. Connect to the internet.",
     "El coach no pudo revisar tu clave en {days} días. Conéctate a internet."),
    # Progress (coach/progress.py)
    ("Write your MMR as a number, like 2450.", "Escribe tu MMR como número, por ejemplo 2450."),
    ("Saved: {mmr} MMR ({medal}).", "Guardado: {mmr} MMR ({medal})."),
    ("Saved: {mmr} MMR.", "Guardado: {mmr} MMR."),
    ("Switched to Experienced mode for your rank: only item gold, stacks, the power rune and buyback. "
     "Change it any time on the Reminders page.",
     "Cambiado al modo Experimentado por tu rango: solo oro para objetos, stacks, la runa de poder y buyback. "
     "Cámbialo cuando quieras en la página Avisos."),
    ("Win", "Victoria"),
    ("Loss", "Derrota"),
    ("A steady game with nothing big to fix.", "Una partida estable, sin nada grande que corregir."),
    ("Fewer deaths", "Menos muertes"),
    ("More deaths lately", "Más muertes últimamente"),
    ("Last hits improving", "Los last hits mejoran"),
    ("Last hits dropping", "Los last hits bajan"),
    ("Your best hero: {name}", "Tu mejor héroe: {name}"),
    ("You die {now} times a game now, down from {before}. Staying alive wins games: keep it up.",
     "Ahora mueres {now} veces por partida, antes {before}. Sobrevivir gana partidas: sigue así."),
    ("You die {now} times a game now, up from {before}. Check the minimap before you walk forward, "
     "and back off when you're low.",
     "Ahora mueres {now} veces por partida, antes {before}. Mira el minimapa antes de avanzar y "
     "retírate cuando tengas poca vida."),
    ("It came up in {times} of your last {games} games. Next game, {tip}.",
     "Salió en {times} de tus últimas {games} partidas. La próxima partida, {tip}."),
    ("{what}: your main thing to fix", "{what}: lo principal a corregir"),
    ("{l1} last hits at 10 minutes on average, up from {l0}.",
     "{l1} last hits en el minuto 10 en promedio, más que {l0}."),
    ("{l1} last hits at 10 minutes on average, down from {l0}.",
     "{l1} last hits en el minuto 10 en promedio, menos que {l0}."),
    ("{wr}% wins in {games} games. Pick it when you want a win, like in ranked.",
     "{wr}% de victorias en {games} partidas. Elígelo cuando quieras ganar, como en ranked."),
    ("{name} isn't working yet", "{name} todavía no te funciona"),
    ("{wr}% wins in {games} games. Practise it in unranked, or play your better heroes in ranked.",
     "{wr}% de victorias en {games} partidas. Practícalo en unranked, o juega tus mejores héroes en ranked."),
    ("{label}: better than only {pct}% of games on this hero. {tip}",
     "{label}: mejor que solo el {pct}% de las partidas con este héroe. {tip}"),
    ("{label}: better than {pct}% of games on this hero. That's a strength.",
     "{label}: mejor que el {pct}% de las partidas con este héroe. Es una fortaleza."),
    ("Gold per minute", "Oro por minuto"),
    ("Experience per minute", "Experiencia por minuto"),
    ("Last hits per minute", "Last hits por minuto"),
    ("Kills per minute", "Kills por minuto"),
    ("Hero damage per minute", "Daño a héroes por minuto"),
    ("Tower damage", "Daño a torres"),
    ("Net worth", "Patrimonio"),
    ("Hero damage", "Daño a héroes"),
    ("Healing", "Curación"),
    ("Observer wards", "Observer wards"),
    ("Sentry wards", "Sentry wards"),
    ("Camps stacked", "Campamentos stackeados"),
    ("Runes taken", "Runas tomadas"),
    ("Stun seconds", "Segundos de stun"),
    ("Farm the jungle camps next to your lane between waves.",
     "Farmea los campamentos de jungla junto a tu línea entre oleadas."),
    ("Stay near creep waves and fights instead of walking around the map.",
     "Quédate cerca de las oleadas y las peleas en vez de caminar por el mapa."),
    ("Last hit every creep you can; push a wave out, then take a camp.",
     "Haz last hit a cada creep que puedas; empuja la oleada y luego toma un campamento."),
    ("Join fights your team starts near you; look for kills after your team wins a fight.",
     "Únete a las peleas que tu equipo empieza cerca de ti; busca kills después de ganar una pelea."),
    ("Use your spells in fights, and stay close enough to hit.",
     "Usa tus hechizos en las peleas y quédate lo bastante cerca para pegar."),
    ("After a won fight, hit towers before going back to farm.",
     "Después de ganar una pelea, pega a las torres antes de volver a farmear."),
    ("This match has no match id or account id to look up.",
     "Esta partida no tiene id de partida ni de cuenta para buscar."),
    ("OpenDota doesn't have this match for you yet. It needs \"Expose Public Match Data\" on in Dota's "
     "settings, and can take a few minutes after the game.",
     "OpenDota todavía no tiene esta partida. Necesita \"Expose Public Match Data\" activado en la "
     "configuración de Dota, y puede tardar unos minutos después de la partida."),
    # Settings (coach/options.py)
    ("Map and clock", "Mapa y reloj"),
    ("Runes, camps and the game clock.", "Runas, campamentos y el reloj de la partida."),
    ("Power rune", "Runa de poder"),
    ("Before each power rune spawns in the river.", "Antes de que aparezca cada runa de poder en el río."),
    ("Say it this early", "Decirlo con esta anticipación"),
    ("Seconds before it happens.", "Segundos antes de que pase."),
    ("Every other rune after", "Una runa sí y otra no después de"),
    ("Late game, only every other rune is called. 0:00 calls them all.",
     "En el juego tardío se avisa una runa sí y otra no. 0:00 las avisa todas."),
    ("Bounty runes", "Runas de recompensa"),
    ("Before the gold runes spawn.", "Antes de que aparezcan las runas de oro."),
    ("0:00 calls them all.", "0:00 las avisa todas."),
    ("Wisdom shrines", "Santuarios de sabiduría"),
    ("Before the experience shrines activate.", "Antes de que se activen los santuarios de experiencia."),
    ("Water runes", "Runas de agua"),
    ("At 2:00 and 4:00, for mid players only.", "A los 2:00 y 4:00, solo para el medio."),
    ("Stack the camp", "Stackear el campamento"),
    ("At :53 each minute, only when you're near a neutral camp.",
     "A los :53 de cada minuto, solo si estás cerca de un campamento neutral."),
    ("Stop reminding after", "Dejar de avisar después de"),
    ("Game time of the last stack reminder.", "Tiempo de partida del último aviso de stack."),
    ("Neutral item tiers", "Niveles de objetos neutrales"),
    ("When each tier of neutral items opens.", "Cuando se abre cada nivel de objetos neutrales."),
    ("Night is starting", "Empieza la noche"),
    ("When night falls and vision gets shorter.", "Cuando cae la noche y la visión se acorta."),
    ("For the first", "Durante las primeras"),
    ("Number of nights.", "Número de noches."),
    ("Think Roshan", "Pensar en Roshan"),
    ("Once, a reminder that Roshan is worth taking after a won fight.",
     "Una vez, un aviso de que conviene hacer Roshan después de ganar una pelea."),
    ("At minute", "En el minuto"),
    ("Your hero", "Tu héroe"),
    ("Gold, health and items: only from your own hero.", "Oro, vida y objetos: solo de tu propio héroe."),
    ("Gold for your next item", "Oro para tu siguiente objeto"),
    ("When you can afford the next item on your build.", "Cuando te alcanza para el siguiente objeto de tu build."),
    ("A cheap item while you save", "Un objeto barato mientras ahorras"),
    ("Magic Wand or a stats item while a big item is far away.",
     "Magic Wand o un objeto de atributos mientras falta mucho para un objeto grande."),
    ("When the next item is still", "Cuando al siguiente objeto aún le faltan"),
    ("Gold short of your next build item.", "Oro que falta para el siguiente objeto de tu build."),
    ("Until minute", "Hasta el minuto"),
    ("Low health: back off", "Poca vida: retírate"),
    ("Once when your health drops low, and \"go heal\" if it stays low.",
     "Una vez cuando tu vida baja, y \"ve a curarte\" si sigue baja."),
    ("Back off under", "Retírate con menos de"),
    ("Health percent.", "Porcentaje de vida."),
    ("Go heal under", "Ve a curarte con menos de"),
    ("...for this long", "...durante este tiempo"),
    ("Seconds without taking damage.", "Segundos sin recibir daño."),
    ("Use your Magic Wand", "Usa tu Magic Wand"),
    ("When you're hurt and your wand has charges.", "Cuando estás herido y tu varita tiene cargas."),
    ("Health under", "Vida menor a"),
    ("With at least", "Con al menos"),
    ("Wand charges.", "Cargas de la varita."),
    ("Buyback gold", "Oro para buyback"),
    ("When your gold drops under the buyback cost.", "Cuando tu oro baja del costo del buyback."),
    ("From minute", "Desde el minuto"),
    ("Unspent skill point", "Punto de habilidad sin usar"),
    ("When you've levelled up and not spent the point.", "Cuando subiste de nivel y no usaste el punto."),
    ("Wait before reminding", "Esperar antes de avisar"),
    ("Up to level", "Hasta el nivel"),
    ("Place your ward", "Pon tu ward"),
    ("When an observer ward stays in your inventory.", "Cuando un observer ward se queda en tu inventario."),
    ("After carrying it", "Después de llevarlo"),
    ("Coaching", "Coaching"),
    ("Tips and check-ins that help you improve.", "Consejos y revisiones que te ayudan a mejorar."),
    ("A tip after you die", "Un consejo cuando mueres"),
    ("One short tip while you wait to respawn.", "Un consejo corto mientras esperas reaparecer."),
    ("Only when the respawn is at least", "Solo si la reaparición tarda al menos"),
    ("Calm-down line after", "Frase para calmarte después de"),
    ("Deaths close together. 0 turns it off.", "Muertes seguidas. 0 lo apaga."),
    ("Last-hit check", "Revisión de last hits"),
    ("Your last hits against a target for your rank (cores only).",
     "Tus last hits contra una meta para tu rango (solo cores)."),
    ("At minutes", "En los minutos"),
    ("For example 5, 10.", "Por ejemplo 5, 10."),
    ("Focus after laning", "Enfoque después de la fase de líneas"),
    ("The one thing to work on once the laning phase ends.", "Lo único a trabajar cuando termina la fase de líneas."),
    ("At", "A los"),
    ("Game time.", "Tiempo de partida."),
    ("Ahead or behind?", "¿Adelante o atrás?"),
    ("How your gold and experience compare, with what to do and what to buy.",
     "Cómo se comparan tu oro y tu experiencia, con qué hacer y qué comprar."),
    ("For example 15, 25.", "Por ejemplo 15, 25."),
    ("When your team is strongest", "Cuando tu equipo es más fuerte"),
    ("When the stretches from the pre-game briefing start.", "Cuando empiezan los momentos del resumen previo a la partida."),
    ("Review after the match", "Revisión después de la partida"),
    ("Three things to work on, also saved as a text file.", "Tres cosas a mejorar, también guardadas como archivo de texto."),
    ("Suggest a break after", "Sugerir un descanso después de"),
    ("Losses in a row. 0 turns it off.", "Derrotas seguidas. 0 lo apaga."),
    ("Language", "Idioma"),
    ("What the coach speaks and the app shows.", "Lo que habla el coach y muestra la app."),
    ("Coach language", "Idioma del coach"),
    ("Spoken lines, answers and this window. Spanish needs a Spanish Windows voice (Settings > Time & "
     "language > Speech).",
     "Frases, respuestas y esta ventana. El español necesita una voz de Windows en español "
     "(Configuración > Hora e idioma > Voz)."),
    ("Voice", "Voz"),
    ("How the coach sounds.", "Cómo suena el coach."),
    ("An installed Windows voice.", "Una voz de Windows instalada."),
    ("Speed", "Velocidad"),
    ("From -10 (slow) to 10 (fast).", "De -10 (lento) a 10 (rápido)."),
    ("At most this many lines at once", "Como máximo esta cantidad de frases a la vez"),
    ("When several reminders are due together, the most important are said.",
     "Cuando tocan varios avisos juntos, se dicen los más importantes."),
    ("Skip a reminder that is late by", "Saltar un aviso que se retrasa"),
    ("Questions", "Preguntas"),
    ("Talk to the coach. Your microphone is only heard on this PC.",
     "Habla con el coach. Tu micrófono solo se escucha en esta PC."),
    ("Voice questions (\"hey coach ...\")", "Preguntas por voz (\"hey coach ...\")"),
    ("Wake word", "Palabra de activación"),
    ("Ask my position and the heroes before the horn", "Preguntar mi posición y los héroes antes de la bocina"),
    ("Ask short questions at calm moments", "Hacer preguntas cortas en momentos tranquilos"),
    ("Ask me to check the enemy items", "Pedirme que revise los objetos enemigos"),
    ("Answer any other question with the AI model", "Responder cualquier otra pregunta con el modelo de IA"),
    ("Before the game", "Antes de la partida"),
    ("The briefing and what the coach knows about you.", "El resumen y lo que el coach sabe de ti."),
    ("Spoken briefing before the horn", "Resumen hablado antes de la bocina"),
    ("Longest briefing", "Resumen más largo"),
    ("Words.", "Palabras."),
    ("My position", "Mi posición"),
    ("Or let the coach ask each game.", "O deja que el coach pregunte en cada partida."),
    ("Ask each game", "Preguntar en cada partida"),
    ("1 - Safe lane", "1 - Línea segura"),
    ("2 - Mid", "2 - Medio"),
    ("3 - Offlane", "3 - Línea difícil"),
    ("4 - Soft support", "4 - Support semi"),
    ("5 - Hard support", "5 - Support duro"),
    ("My rank", "Mi rango"),
    ("Targets compare you with players of your medal.", "Las metas te comparan con jugadores de tu medalla."),
    ("Ask me / from OpenDota", "Preguntarme / desde OpenDota"),
    ("Say item advice unasked when it changes", "Decir el consejo de objetos sin preguntar cuando cambia"),
    ("Unknown mode {mode}", "Modo desconocido {mode}"),
    ("{label}: pick one of the list", "{label}: elige uno de la lista"),
    ("{label}: write a game time like 11:53", "{label}: escribe un tiempo de partida como 11:53"),
    ("{label}: write minutes like 15, 25", "{label}: escribe minutos como 15, 25"),
    ("{label}: minutes from 1 to 120", "{label}: minutos del 1 al 120"),
    ("{label}: write a whole number", "{label}: escribe un número entero"),
    ("{label}: from {low} to {high}", "{label}: de {low} a {high}"),
    # Replay review (coach/replay_api.py)
    ("can't tell which hero is yours yet. Pick your hero in the Replay review window.",
     "todavía no sé cuál héroe es el tuyo. Elige tu héroe en la ventana Revisar replay."),
    ("this is a live match, so the screen stays off. Close Replay review and start the live coach instead.",
     "esta es una partida en vivo, así que la pantalla queda apagada. Cierra Revisar replay e inicia el coach en vivo."),
    ("Ollama isn't running. Start Ollama, or the coach reviews without looking at the screen.",
     "Ollama no está abierto. Ábrelo, o el coach revisa sin mirar la pantalla."),
    ("Not installed yet. In Command Prompt: ollama pull {model}",
     "Todavía no está instalado. En el Símbolo del sistema: ollama pull {model}"),
    ("Installed and ready.", "Instalado y listo."),
]

UI = Catalog(UI_ES)


def ui(text: str, lang: str | None = None) -> str:
    """App window text in the language (whole strings; unknown ones stay)."""
    if (lang or _language) != "es" or not text:
        return text
    return UI.one(text) or SPEECH.one(text) or UI.translate(text)


def speech(text: str, lang: str | None = None) -> str:
    """A spoken line in the language from the catalog only (no model)."""
    if (lang or _language) != "es" or not text:
        return text
    return SPEECH.translate(text)
