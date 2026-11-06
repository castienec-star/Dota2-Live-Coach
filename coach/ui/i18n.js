// The page in the coach's language ([coach] language in coach.toml).
// Text Python sends is translated in Python (coach/i18n.py); this file covers
// the page's own words. t("English {n}", {n: 3}) gives the Spanish when the
// language is "es", and English otherwise. Hero and item names stay English.
"use strict";

const ES = {
  // Side bar and pages
  "Live Coach": "Live Coach", "for Dota 2": "para Dota 2",
  "Dashboard": "Inicio", "Progress": "Progreso", "Reminders": "Avisos",
  "Voice & questions": "Voz y preguntas", "Game & profile": "Partida y perfil", "Licence": "Licencia",
  "Off": "Apagado", "Waiting for Dota": "Esperando a Dota", "Coaching": "Entrenando",
  // Dashboard
  "Start the coach before your match. It speaks; it never reads your screen during your games.":
    "Inicia el coach antes de tu partida. Habla; nunca lee tu pantalla durante tus partidas.",
  "What's your MMR now?": "¿Cuál es tu MMR ahora?",
  "Keep it up to date so the coach compares you with players of your rank.":
    "Mantenlo al día para que el coach te compare con jugadores de tu rango.",
  "Save": "Guardar", "e.g. 2450": "p. ej. 2450",
  "Coach off": "Coach apagado", "Coach running": "Coach encendido", "Live": "En vivo",
  "The coach is off. Press Start before your match.": "El coach está apagado. Presiona Iniciar antes de tu partida.",
  "Start coach": "Iniciar coach", "Stop coach": "Detener coach",
  "Lines said": "Frases dichas", "Dota 2": "Dota 2", "Not connected": "No conectado",
  "Connected": "Conectado", "Waiting": "Esperando", "Mode": "Modo", "Beginner": "Principiante",
  "Experienced": "Experimentado", "Reminders on": "Avisos activos", "Live feed": "En vivo",
  "Show details": "Mostrar detalles", "Lines the coach says will appear here.": "Aquí aparecen las frases del coach.",
  "Quick actions": "Acciones rápidas", "Set up Dota 2": "Configurar Dota 2",
  "Adds Valve's Game State Integration file.": "Agrega el archivo de Game State Integration de Valve.",
  "Match reviews": "Revisiones de partidas", "Your saved post-game reviews.": "Tus revisiones guardadas después de cada partida.",
  "Item builds": "Builds de objetos", "Edit the build of any hero.": "Edita la build de cualquier héroe.",
  "Add": "Agrega", "to Dota 2's launch options in Steam once.": "a las opciones de lanzamiento de Dota 2 en Steam, una sola vez.",
  "Last line: ": "Última frase: ", "Version ": "Versión ",
  "Setting up Dota 2...": "Configurando Dota 2...",
  "Dota 2 is set up. Restart Dota if it is open.": "Dota 2 está configurado. Reinicia Dota si está abierto.",
  // Feed labels
  "Coach": "Coach", "Late": "Tarde", "Dota": "Dota", "Match": "Partida", "Check": "Revisar", "App": "App", "Log": "Log",
  // Progress
  "Your MMR over time and your best heroes, from the games the coach recorded.":
    "Tu MMR en el tiempo y tus mejores héroes, de las partidas que grabó el coach.",
  "Current MMR": "MMR actual", "Since first entry": "Desde el primer registro", "Games recorded": "Partidas grabadas",
  "Win rate": "Tasa de victorias", "Coach's recommendations": "Recomendaciones del coach",
  "From your last 20 recorded games.": "De tus últimas 20 partidas grabadas.",
  "MMR over time": "MMR en el tiempo", "Update your MMR": "Actualiza tu MMR",
  "Find it in Dota under your profile. The coach uses it to compare you with players of your rank, so it won't ask during games.":
    "Lo encuentras en tu perfil de Dota. El coach lo usa para compararte con jugadores de tu rango, así no pregunta durante las partidas.",
  "Last 20 games": "Últimas 20 partidas", "One column per game, oldest on the left.": "Una columna por partida, la más vieja a la izquierda.",
  "Deaths": "Muertes", "Last hits at 10:00": "Last hits a los 10:00", "GPM": "GPM", "Gold per minute": "Oro por minuto",
  "Your heroes": "Tus héroes", "Win rate in your recorded games. Most played first.":
    "Tasa de victorias en tus partidas grabadas. Los más jugados primero.",
  "Recent matches": "Partidas recientes",
  "Click a match for its summary and what to fix. More numbers come from OpenDota (needs \"Expose Public Match Data\" in Dota).":
    "Haz clic en una partida para ver su resumen y qué corregir. Más números vienen de OpenDota (necesita \"Expose Public Match Data\" en Dota).",
  "Save your MMR to start your graph.": "Guarda tu MMR para empezar tu gráfico.",
  "Play a match with the coach running and your heroes show up here.":
    "Juega una partida con el coach encendido y tus héroes aparecen aquí.",
  "Play a few games with the coach running and its recommendations show up here.":
    "Juega algunas partidas con el coach encendido y sus recomendaciones aparecen aquí.",
  "No recorded games yet.": "Todavía no hay partidas grabadas.",
  "{name}: {wins} wins, {losses} losses in {games} games · average K/D/A {kda}":
    "{name}: {wins} victorias, {losses} derrotas en {games} partidas · K/D/A promedio {kda}",
  "game": "partida", "games": "partidas",
  "{metric} in the last games": "{metric} en las últimas partidas",
  "Win": "Victoria", "Loss": "Derrota", "Result unknown": "Resultado desconocido", "-": "-",
  "Loading...": "Cargando...", "Try again": "Reintentar",
  "Against all games on this hero": "Contra todas las partidas con este héroe",
  "Better than {pct}% of games on this hero": "Mejor que el {pct}% de las partidas con este héroe",
  "What to work on": "Qué trabajar",
  "Date": "Fecha", "Hero": "Héroe", "Result": "Resultado", "K/D/A": "K/D/A", "LH/DN": "LH/DN", "XPM": "XPM",
  "Length": "Duración", "No recorded matches yet.": "Todavía no hay partidas grabadas.",
  "Load OpenDota numbers": "Cargar números de OpenDota",
  "{n} last hits at 10:00": "{n} last hits a los 10:00",
  "{n} death before 10:00": "{n} muerte antes de los 10:00", "{n} deaths before 10:00": "{n} muertes antes de los 10:00",
  "Coach's review": "Revisión del coach", "Not set": "Sin datos",
  "{n} entry since {day}": "{n} registro desde {day}", "{n} entries since {day}": "{n} registros desde {day}",
  "Last updated {day}. Update it every {n} days to track your progress.":
    "Última actualización {day}. Actualízalo cada {n} días para seguir tu progreso.",
  "Enter it once and the coach won't ask your rank during games.":
    "Ingrésalo una vez y el coach no te preguntará tu rango durante las partidas.",
  // Reminders and settings
  "Choose exactly what the coach tells you, and when.": "Elige exactamente qué te dice el coach, y cuándo.",
  "Search reminders": "Buscar avisos", "All on": "Todos activos", "All off": "Todos apagados",
  "Reset to defaults": "Restablecer", "{on} of {all} on": "{on} de {all} activos", "{on} of {all}": "{on} de {all}",
  "Essential": "Esencial", "Timing": "Tiempos", "Windows default": "Predeterminada de Windows", "Test": "Probar",
  "sec": "seg", "min": "min", "%": "%", "m:ss": "m:ss",
  "How the coach sounds, and what you can ask it.": "Cómo suena el coach, y qué le puedes preguntar.",
  "The pre-game briefing and what the coach knows about you.": "El resumen previo y lo que el coach sabe de ti.",
  "You have unsaved changes.": "Tienes cambios sin guardar.", "Discard": "Descartar", "Save changes": "Guardar cambios",
  "Defaults restored. Save to keep them.": "Valores restablecidos. Guarda para conservarlos.",
  "Saved. The coach restarted with your settings.": "Guardado. El coach se reinició con tu configuración.",
  "Saved. The coach uses them next time it starts.": "Guardado. El coach los usa la próxima vez que inicie.",
  // Licence
  "Your subscription unlocks the coach on this PC.": "Tu suscripción desbloquea el coach en esta PC.",
  "Licence key": "Clave de licencia", "Activate": "Activar",
  "The key is in the receipt email from your purchase.": "La clave está en el correo de tu compra.",
  "Get a subscription: $2.50 a month or $25 a year": "Suscríbete: $2.50 al mes o $25 al año",
  "Welcome to Live Coach": "Bienvenido a Live Coach", "Enter your licence key to start.": "Ingresa tu clave de licencia para empezar.",
  "Licence key from your receipt email": "Clave de licencia del correo de tu compra",
  "Unlock the coach": "Desbloquear el coach", "No key yet? Subscribe for $2.50 a month": "¿No tienes clave? Suscríbete por $2.50 al mes",
  "Free test build: no licence needed yet.": "Versión de prueba gratis: todavía no necesitas licencia.",
  "Active on this PC.": "Activa en esta PC.",
  // Replay review (replay.html)
  "Replay review": "Revisar replay",
  "Watch a replay and get advice on your decisions.": "Mira un replay y recibe consejos sobre tus decisiones.",
  "Watch one of your replays in Dota 2 and the coach reviews it with you, out loud.":
    "Mira uno de tus replays en Dota 2 y el coach lo revisa contigo, en voz alta.",
  "Start review": "Iniciar revisión", "Stop review": "Detener revisión",
  "Review off": "Revisión apagada", "Waiting for a replay": "Esperando un replay", "Reviewing": "Revisando",
  "Pick how the coach should look, then press Start review.":
    "Elige cómo debe mirar el coach y presiona Iniciar revisión.",
  "Open one of your replays in Dota 2 (Watch > Replays).": "Abre uno de tus replays en Dota 2 (Ver > Repeticiones).",
  "Reviewing your {hero}.": "Revisando tu {hero}.", "Last: ": "Último: ",
  "Review started. Open your replay in Dota 2.": "Revisión iniciada. Abre tu replay en Dota 2.",
  "Key moments": "Momentos clave",
  "The coach talks over the seconds before your deaths, fights that went badly, every pause, and every 90 seconds.":
    "El coach comenta los segundos antes de tus muertes, las peleas que salieron mal, cada pausa y cada 90 segundos.",
  "Any graphics card with 6 GB or more. Good when you have little time: pause where you want advice.":
    "Cualquier tarjeta gráfica de 6 GB o más. Ideal si tienes poco tiempo: pausa donde quieras un consejo.",
  "Continuous": "Continuo",
  "The coach keeps watching the whole replay and talks over your mistakes as they happen, like a coach next to you.":
    "El coach mira todo el replay y comenta tus errores a medida que pasan, como un coach a tu lado.",
  "Needs a strong graphics card (8 GB or more free). Slow the replay down if the coach falls behind.":
    "Necesita una tarjeta gráfica potente (8 GB libres o más). Pon el replay más lento si el coach se queda atrás.",
  "Vision model": "Modelo de visión", "Checking...": "Revisando...", "Talk it over every": "Comentar cada",
  "It takes a frame every second and looks back over them this often.": "Toma una imagen cada segundo y las revisa con esta frecuencia.",
  "Your hero in this replay": "Tu héroe en este replay", "Find it from my account": "Encontrarlo con mi cuenta",
  "The coach follows only this hero, like in your real game.": "El coach sigue solo a este héroe, como en tu partida real.",
  "What the coach said": "Lo que dijo el coach",
  "Advice from the review will appear here.": "Aquí aparecen los consejos de la revisión.",
  "How to review": "Cómo revisar",
  "Press Start review, then open your match in Dota 2 under Watch > Replays.":
    "Presiona Iniciar revisión y abre tu partida en Dota 2, en Ver > Repeticiones.",
  "Set the replay's vision to your team and the camera to your hero, so you only see what you saw in the game.":
    "Pon la visión del replay en tu equipo y la cámara en tu héroe, para ver solo lo que viste en la partida.",
  "Pause the replay whenever you want the coach's view of that moment.":
    "Pausa el replay cuando quieras la opinión del coach sobre ese momento.",
  "Fair play.": "Juego limpio.",
  "The coach only looks at your screen while Dota is playing a replay. In your own live games it never looks at your screen, and the moment a live match starts, the screen is off. Frames stay on your PC and are never saved.":
    "El coach solo mira tu pantalla mientras Dota reproduce un replay. En tus partidas en vivo nunca mira tu pantalla, y en cuanto empieza una partida en vivo, la pantalla se apaga. Las imágenes se quedan en tu PC y nunca se guardan.",
  "{n} seconds": "{n} segundos", "Note": "Nota", "following your hero {hero}": "siguiendo a tu héroe {hero}",
};

let LANG = "en";

function t(text, vars) {
  let out = LANG === "es" && Object.prototype.hasOwnProperty.call(ES, text) ? ES[text] : text;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split("{" + k + "}").join(String(v));
  return out;
}

// Dates and numbers written the way the language does.
function locale() { return LANG === "es" ? "es" : "en-US"; }

// The page's own HTML: every text node and placeholder the dictionary knows.
function translatePage(lang) {
  LANG = lang === "es" ? "es" : "en";
  document.documentElement.lang = LANG;
  if (LANG === "en") return;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.trim();
    if (text && Object.prototype.hasOwnProperty.call(ES, text)) node.nodeValue = node.nodeValue.replace(text, ES[text]);
  }
  for (const input of document.querySelectorAll("[placeholder]")) input.placeholder = t(input.placeholder);
}
