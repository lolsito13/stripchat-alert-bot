#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de avisos de Stripchat para grupos de Telegram.

Avisa al grupo cuando la modelo se conecta (y opcionalmente cuando se
desconecta). Usa la API pública de Stripchat y la API de bots de Telegram.

Comandos:
    python bot.py get-chat-id   averigua el ID del grupo
    python bot.py test-message  manda un mensaje de prueba al grupo
    python bot.py status        muestra el estado actual de la modelo
    python bot.py check         chequea una vez y avisa si se conectó
    python bot.py top           muestra el top de donadores de la modelo
    python bot.py loop          chequea para siempre (para dejar la PC encendida)

Configuración: variables de entorno o archivo .env junto a este script
(mirá .env.example).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
STATE_FILE = SCRIPT_DIR / "state.json"

HTTP_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

STRIPCHAT_API = "https://stripchat.com/api/front"
TELEGRAM_API = "https://api.telegram.org"
SNAPSHOT_API = "https://img.doppiocdn.com/thumbs"

DEFAULT_ONLINE = (
    "🔴 ¡{model} está EN VIVO en Stripchat!\n\n"
    "Show: {show}\n"
    "👉 Ver stream: {url}"
)
DEFAULT_OFFLINE = "⚫ {model} se desconectó de Stripchat"

SHOW_KIND_ES = {
    "public": "público",
    "groupShow": "grupal",
    "private": "privado",
    "p2p": "privado (P2P)",
    "p2pVoice": "privado (P2P con voz)",
    "virtualPrivate": "privado virtual",
}


def log(msg):
    print(time.strftime("[%d/%m %H:%M:%S] ") + str(msg), flush=True)


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def load_dotenv():
    """Lee el archivo .env (si existe) sin pisar variables ya definidas."""
    if not ENV_FILE.exists():
        return
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        sys.exit("No se pudo leer {}: {}".format(ENV_FILE, exc))
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def setting(name, default=""):
    # "\n" escrito en el .env cuenta como salto de línea (para mensajes
    # de varias líneas sin romper el formato clave=valor de una sola línea)
    return os.environ.get(name, default).strip().replace("\\n", "\n")


def require(*names):
    missing = [n for n in names if not setting(n)]
    if missing:
        sys.exit(
            "ERROR: falta configurar: {}.\nCompletalos en el archivo .env "
            "(hay un ejemplo en .env.example) o pasalos como variables de "
            "entorno.".format(", ".join(missing))
        )


def normalize_model(raw):
    """Acepta el usuario pelado o la URL del perfil y devuelve el usuario."""
    s = raw.strip()
    m = re.match(
        r"^(?:https?://)?(?:[a-z0-9\-]+\.)*(?:stripchat|xhamsterlive)\.com/+([a-z0-9\-_@]+)",
        s,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).lower()
    if "/" in s:
        # otra URL pegada: tomar el último pedacito del path
        s = s.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in s.split("/") if p]
        s = parts[-1] if parts else s
    return s.strip().lower()


def load_config():
    try:
        interval = int(setting("CHECK_INTERVAL", "60") or 60)
    except ValueError:
        interval = 60
    try:
        top_limit = int(setting("TOP_LIMIT", "10") or 10)
    except ValueError:
        top_limit = 10
    return {
        "token": setting("TELEGRAM_BOT_TOKEN"),
        "chat_id": setting("TELEGRAM_CHAT_ID"),
        "model": setting("STRIPCHAT_MODEL"),
        "send_photo": setting("SEND_PHOTO", "1") not in ("0", "false", "no"),
        "sticker_id": setting("STICKER_FILE_ID"),
        "notify_offline": setting("NOTIFY_OFFLINE", "0") in ("1", "true", "yes"),
        "top_enabled": setting("TOP_ENABLED", "1") not in ("0", "false", "no"),
        # la API de Stripchat devuelve como máximo 10 puestos
        "top_limit": min(10, max(1, top_limit)),
        "message_online": setting("MESSAGE_ONLINE") or DEFAULT_ONLINE,
        "message_offline": setting("MESSAGE_OFFLINE") or DEFAULT_OFFLINE,
        "interval": max(15, interval),
    }


# ---------------------------------------------------------------------------
# HTTP con reintentos
# ---------------------------------------------------------------------------

def make_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def http(session, method, url, **kwargs):
    """Pedido con reintentos ante errores de red o respuestas 5xx/429."""
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = session.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = RuntimeError("HTTP {}".format(resp.status_code))
            else:
                return resp
        except requests.RequestException as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(2 * attempt)
    raise last_error


# ---------------------------------------------------------------------------
# Stripchat
# ---------------------------------------------------------------------------

def resolve_model_id(session, username):
    """Devuelve el ID numérico de la modelo, o None si no existe."""
    resp = http(session, "GET", "{}/users/user-ids/{}".format(STRIPCHAT_API, username))
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError("HTTP {} al buscar el ID de la modelo".format(resp.status_code))
    data = resp.json()
    if data.get("newUsername"):
        # la modelo cambió de nombre: el usuario viejo ya no sirve
        return None
    return int(data["id"])


def query_status(session, model_id):
    """Devuelve (esta_en_vivo, tipo_de_show)."""
    resp = http(
        session,
        "POST",
        "{}/models/get-statuses".format(STRIPCHAT_API),
        json={"ids": [model_id]},
    )
    if resp.status_code != 200:
        raise RuntimeError("HTTP {} al consultar el estado".format(resp.status_code))
    data = resp.json()
    for entry in data.get("statuses", []):
        if entry.get("id") == model_id:
            return True, entry.get("status")
    # las modelos desconectadas o "idle" no aparecen en la lista
    return False, None


def download_snapshot(session, model_id):
    """Baja la última imagen de la sala (solo si está en vivo)."""
    url = "{}/{}/{}".format(SNAPSHOT_API, int(time.time()), model_id)
    try:
        resp = session.get(url, timeout=HTTP_TIMEOUT)
        ctype = resp.headers.get("Content-Type", "")
        if resp.ok and len(resp.content) > 500 and ctype.startswith("image"):
            return resp.content, ctype
    except requests.RequestException:
        pass
    return None, None


def query_tippers(session, model_id, period="day"):
    """Devuelve el top de donadores (lista de {tokens, user}).

    period: "day" (hoy), "month" (mes en curso) o "last" (mes pasado).
    """
    if period == "month":
        path = "/models/{}/tips-leaderboard/current-month".format(model_id)
    elif period == "last":
        last_month = date.today().replace(day=1) - timedelta(days=1)
        path = "/models/{}/tips-leaderboard/monthly/{:02d}/{}".format(
            model_id, last_month.month, last_month.year
        )
    else:
        path = "/models/{}/tips-leaderboard".format(model_id)
    resp = http(session, "GET", STRIPCHAT_API + path)
    if resp.status_code != 200:
        raise RuntimeError("HTTP {} al consultar el top".format(resp.status_code))
    return resp.json().get("leaderboard") or []


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def telegram(session, token, method, payload=None, files=None):
    resp = session.post(
        "{}/bot{}/{}".format(TELEGRAM_API, token, method),
        data=payload,
        files=files,
        timeout=HTTP_TIMEOUT + 15,
    )
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("Telegram respondió algo raro (HTTP {})".format(resp.status_code))
    if not data.get("ok"):
        raise RuntimeError(
            "Telegram rechazó {}: {}".format(method, data.get("description", resp.status_code))
        )
    return data


def send_text(session, cfg, text):
    """Manda texto al grupo, sin la preview del link (la miniatura)."""
    telegram(
        session,
        cfg["token"],
        "sendMessage",
        payload={
            "chat_id": cfg["chat_id"],
            "text": text,
            "link_preview_options": '{"is_disabled":true}',
        },
    )


def send_alert(session, cfg, text, model_id, is_online):
    """Manda el aviso: al conectarse, sticker si hay configurado, si no foto
    de la sala; al desconectarse, solo texto."""
    if is_online and cfg["sticker_id"]:
        try:
            telegram(
                session,
                cfg["token"],
                "sendSticker",
                payload={"chat_id": cfg["chat_id"], "sticker": cfg["sticker_id"]},
            )
        except RuntimeError as exc:
            log("Aviso: no se pudo mandar el sticker ({}); sigo con el texto.".format(exc))
        send_text(session, cfg, text)
        return
    if cfg["send_photo"] and model_id:
        photo, ctype = download_snapshot(session, model_id)
        if photo:
            ext = "webp" if "webp" in ctype else "jpg"
            try:
                telegram(
                    session,
                    cfg["token"],
                    "sendPhoto",
                    payload={"chat_id": cfg["chat_id"], "caption": text},
                    files={"photo": ("stream.{}".format(ext), photo, ctype or "image/jpeg")},
                )
                return
            except RuntimeError as exc:
                log("Aviso: no se pudo mandar la foto ({}); mando solo texto.".format(exc))
    send_text(session, cfg, text)


# ---------------------------------------------------------------------------
# Top de donadores (/top en el grupo)
# ---------------------------------------------------------------------------

TOP_PERIODS = {
    "day": "hoy",
    "month": "este mes",
    "last": "el mes pasado",
}

TOP_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def parse_top_period(arg):
    words = (arg or "").lower().split()
    if any(w in ("pasado", "anterior", "last") for w in words):
        return "last"
    if any(w in ("mes", "month", "actual") for w in words):
        return "month"
    return "day"


def format_tippers(username, tippers, period, limit):
    lines = [
        "🏆 Top donadores de {} ({})".format(
            username, TOP_PERIODS.get(period, "hoy")
        ),
        "",
    ]
    if not tippers:
        lines.append("Todavía no hay donadores en este período.")
    for pos, entry in enumerate(tippers[:limit], 1):
        user = entry.get("user") or {}
        name = user.get("username") or user.get("login") or "anónimo"
        tokens = int(entry.get("tokens") or 0)
        tokens_txt = "{:,}".format(tokens).replace(",", ".")
        prefix = TOP_MEDALS.get(pos, "{}.".format(pos))
        lines.append("{} {} — {} tokens".format(prefix, name, tokens_txt))
    lines += ["", "👉 https://stripchat.com/{}".format(username)]
    return "\n".join(lines)


def can_answer_chat(cfg, chat):
    """Solo contestamos en el grupo configurado o por privado al dueño."""
    if not chat:
        return False
    if cfg["chat_id"] and str(chat.get("id")) == str(cfg["chat_id"]):
        return True
    if chat.get("type") == "private":
        owner = setting("TELEGRAM_USER_ID")
        return not owner or str(owner) == str(chat.get("id"))
    return False


def answer_top(
    session, cfg, model_id, username, chat_id, message_id, period, thread_id=None
):
    try:
        tippers = query_tippers(session, model_id, period)
        text = format_tippers(username, tippers, period, cfg["top_limit"])
    except Exception as exc:
        log("Aviso: no se pudo armar el /top ({}).".format(exc))
        text = "No pude obtener el top de donadores ahora. Probá de nuevo en un rato."
    payload = {
        "chat_id": chat_id,
        "text": text,
        "link_preview_options": '{"is_disabled":true}',
        "reply_to_message_id": message_id,
        "allow_sending_without_reply": "true",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    telegram(session, cfg["token"], "sendMessage", payload=payload)


def handle_message(session, cfg, model_id, username, msg):
    chat = msg.get("chat") or {}
    if not can_answer_chat(cfg, chat):
        return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command != "/top":
        return
    period = parse_top_period(arg)
    log("Comando /top ({}) en el chat {}.".format(TOP_PERIODS[period], chat.get("id")))
    answer_top(
        session,
        cfg,
        model_id,
        username,
        chat.get("id"),
        msg.get("message_id"),
        period,
        msg.get("message_thread_id"),
    )


def process_updates(session, cfg, model_id, username):
    """Lee los mensajes nuevos del bot y contesta los /top.

    Telegram guarda los mensajes 24 h; el "offset" se guarda en state.json
    para no contestar dos veces el mismo comando.
    """
    if not cfg["top_enabled"]:
        return
    state = load_state() or {}
    offset = state.get("update_offset")
    payload = {
        "timeout": 0,
        "limit": 100,
        "allowed_updates": '["message","channel_post"]',
    }
    if offset:
        payload["offset"] = int(offset)
    data = telegram(session, cfg["token"], "getUpdates", payload=payload)
    updates = data.get("result") or []
    if not updates:
        return
    last_id = max(int(upd.get("update_id", 0)) for upd in updates)
    first_poll = not offset
    now = time.time()
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            continue
        # en la primera corrida ignoramos los comandos viejos (más de 10 min)
        if first_poll and now - int(msg.get("date") or 0) > 600:
            continue
        try:
            handle_message(session, cfg, model_id, username, msg)
        except Exception as exc:
            log("Aviso: no se pudo responder un comando ({}).".format(exc))
    save_state(update_offset=last_id + 1)


# ---------------------------------------------------------------------------
# Estado (para avisar solo en los cambios, no en cada chequeo)
# ---------------------------------------------------------------------------

def load_state():
    try:
        # utf-8-sig por si el archivo fue editado en Windows con BOM
        state = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def save_state(online=None, **extra):
    """Guarda el estado sin pisar los otros datos (online, offset, etc.)."""
    state = load_state() or {}
    if online is not None:
        state["online"] = bool(online)
    state.update(extra)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def build_message(template, model, show):
    url = "https://stripchat.com/{}".format(model)
    show_es = SHOW_KIND_ES.get(show, "público") if show else "público"
    try:
        return template.format(model=model, show=show_es, url=url)
    except (KeyError, IndexError, ValueError):
        return DEFAULT_ONLINE.format(model=model, show=show_es, url=url)


def run_check(session, cfg):
    username = normalize_model(cfg["model"])

    try:
        model_id = resolve_model_id(session, username)
        if model_id is None:
            log(
                "ERROR: no existe la modelo '{}'. Revisá STRIPCHAT_MODEL: es el "
                "nombre que aparece en la URL del perfil (ej: stripchat.com/USUARIO).".format(username)
            )
            return 1
        online, show = query_status(session, model_id)
    except Exception as exc:
        log("Aviso: no se pudo consultar Stripchat ({}). Se reintenta en el próximo chequeo.".format(exc))
        return 0

    if online:
        log("{}: EN VIVO (show {})".format(username, show))
    else:
        log("{}: desconectada".format(username))

    prev = load_state()

    if cfg["top_enabled"]:
        try:
            process_updates(session, cfg, model_id, username)
        except Exception as exc:
            log("Aviso: no se pudieron leer los comandos de Telegram ({}).".format(exc))

    if prev is None:
        # primera corrida: guardar el estado actual sin avisar, para no
        # spamear el grupo si la modelo ya estaba en vivo al configurar
        save_state(online)
        log("Primera corrida: estado guardado sin mandar avisos.")
        return 0

    was_online = bool(prev.get("online"))

    if online and not was_online:
        log("Se conectó -> mandando aviso al grupo...")
        text = build_message(cfg["message_online"], username, show)
        send_alert(session, cfg, text, model_id, True)
        save_state(True)
        log("Aviso enviado.")
    elif not online and was_online:
        if cfg["notify_offline"]:
            log("Se desconectó -> mandando aviso al grupo...")
            text = build_message(cfg["message_offline"], username, show)
            send_alert(session, cfg, text, None, False)
            save_state(False)
            log("Aviso enviado.")
        else:
            save_state(False)
            log("Se desconectó (los avisos de desconexión están desactivados).")
    return 0


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_check(cfg):
    return run_check(make_session(), cfg)


def cmd_loop(cfg):
    session = make_session()
    log("Modo continuo: chequeo cada {} segundos. Ctrl+C para salir.".format(cfg["interval"]))
    while True:
        try:
            run_check(session, cfg)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log("Aviso: error inesperado ({}); sigo intentando.".format(exc))
        try:
            time.sleep(cfg["interval"])
        except KeyboardInterrupt:
            raise


def cmd_status(cfg):
    session = make_session()
    username = normalize_model(cfg["model"])
    model_id = resolve_model_id(session, username)
    if model_id is None:
        print("No existe la modelo '{}'.".format(username))
        return 1
    online, show = query_status(session, model_id)
    if online:
        print("{} está EN VIVO (show {}).".format(username, SHOW_KIND_ES.get(show, show)))
        print("Link: https://stripchat.com/{}".format(username))
    else:
        print("{} está desconectada.".format(username))
    return 0


def cmd_top(cfg, args):
    session = make_session()
    username = normalize_model(cfg["model"])
    model_id = resolve_model_id(session, username)
    if model_id is None:
        print("No existe la modelo '{}'.".format(username))
        return 1
    period = parse_top_period(args.period or "")
    tippers = query_tippers(session, model_id, period)
    print(format_tippers(username, tippers, period, cfg["top_limit"]))
    return 0


def cmd_test_message(cfg):
    session = make_session()
    username = normalize_model(cfg["model"]) if cfg["model"] else "usuaria"
    text = (
        "🧪 Prueba: así va a llegar el aviso cuando se conecte:\n\n"
        + build_message(cfg["message_online"], username, "public")
    )
    if cfg["sticker_id"]:
        try:
            telegram(
                session,
                cfg["token"],
                "sendSticker",
                payload={"chat_id": cfg["chat_id"], "sticker": cfg["sticker_id"]},
            )
        except RuntimeError as exc:
            log("Aviso: no se pudo mandar el sticker ({}).".format(exc))
    send_text(session, cfg, text)
    print("Mensaje de prueba enviado. Fijate en el grupo.")
    return 0


def cmd_get_chat_id(cfg):
    session = make_session()
    data = telegram(session, cfg["token"], "getUpdates", payload={"limit": 100})
    chats = {}
    for upd in data.get("result", []):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            msg = upd.get(key)
            if not msg or "chat" not in msg:
                continue
            chat = msg["chat"]
            chats[chat.get("id")] = chat
    if not chats:
        print("No vi ningún mensaje reciente.")
        print("Hacé esto y volvé a correr el comando:")
        print("  1) Agregá el bot al grupo (al agregarlo solo ya se genera el")
        print("     evento que este comando detecta).")
        print("  2) Si no alcanzó, mandá en el grupo un mensaje que lo mencione")
        print("     (ej: @tubot hola) o respondé a algún mensaje del bot.")
        print("  3) Volvé a correr: python bot.py get-chat-id")
        print("No hace falta ser dueño/admin del grupo para nada de esto.")
        return 1
    print("Chats que ve el bot:")
    for chat_id, chat in chats.items():
        tipo = chat.get("type")
        nombre = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
        marca = "  <-- probablemente tu grupo" if tipo in ("group", "supergroup") else ""
        print("  {}  [{}] {}{}".format(chat_id, tipo, nombre, marca))
    print("\nCopiá el ID del grupo a TELEGRAM_CHAT_ID en el archivo .env")
    return 0


def cmd_get_sticker_id(cfg):
    session = make_session()
    data = telegram(session, cfg["token"], "getUpdates", payload={"limit": 100})
    found = []
    for upd in data.get("result", []):
        for key in ("message", "edited_message", "channel_post"):
            msg = upd.get(key)
            if msg and isinstance(msg.get("sticker"), dict):
                found.append(msg["sticker"])
    if not found:
        print("No vi ningún sticker todavía.")
        print("Hacé esto y volvé a correr el comando:")
        print("  1) Buscá al bot (ej: @panchiibot) en Telegram y abrí un chat privado.")
        print("  2) Mandale ahí el sticker que querés usar (de cualquier pack).")
        print("  3) Volvé a correr: python bot.py get-sticker-id")
        print(
            "Si el chequeo automático ya leyó el mensaje, poné TOP_ENABLED=0 un "
            "momento (o pausá el workflow), mandá el sticker de nuevo y repetí."
        )
        return 1
    print("Stickers que le mandaron al bot (el ÚLTIMO es el que se va a usar):")
    for st in found:
        emoji = st.get("emoji", "?")
        sset = st.get("sticker_set_name") or "sticker suelto (sin pack)"
        print('  emoji {}  pack: {}'.format(emoji, sset))
        print('  file_id: {}'.format(st.get("file_id")))
    print("\nEl file_id se configura en STICKER_FILE_ID (en el .env o el secret de GitHub).")
    return 0


def cmd_make_sticker_set(cfg, args):
    """Crea un pack de stickers desde un .webm y muestra el file_id."""
    session = make_session()
    path = Path(args.file).expanduser()
    if not path.is_file():
        print("No encontré el archivo: {}".format(path))
        return 1
    if path.suffix.lower() != ".webm":
        print("El archivo tiene que ser .webm (convertilo con ffmpeg primero).")
        return 1
    user_id = setting("TELEGRAM_USER_ID")
    if not user_id or not user_id.isdigit():
        print("Falta tu ID de usuario de Telegram (TELEGRAM_USER_ID en el .env).")
        print("Se ve corriendo get-chat-id después de escribirle al bot por privado.")
        return 1

    # el nombre del pack tiene que terminar en _by_<username del bot>
    me = telegram(session, cfg["token"], "getMe")["result"]
    suffix = "_by_" + me["username"]
    name = (args.name or setting("STICKER_SET_NAME") or "diosita").lower()
    if not name.endswith(suffix):
        name += suffix
    if not re.match(r"^[a-z0-9_]+$", name):
        print("El nombre del pack solo acepta letras, números y _ (sin espacios ni acentos).")
        return 1
    title = args.title or "Nuestra Diosa"

    try:
        with open(path, "rb") as f:
            telegram(
                session,
                cfg["token"],
                "createNewStickerSet",
                payload={
                    "user_id": user_id,
                    "name": name,
                    "title": title,
                    "sticker_type": "regular",
                    "stickers": json.dumps(
                        [{"sticker": "attach://sticker", "emoji_list": [args.emoji]}]
                    ),
                },
                files={"sticker": (path.name, f, "video/webm")},
            )
    except RuntimeError as exc:
        print("No se pudo crear el pack: {}".format(exc))
        msg = str(exc).lower()
        if "already" in msg or "occupied" in msg:
            print("Ese nombre de pack ya existe; probá con --name otro_nombre")
        else:
            print("¿Ya le mandaste un mensaje privado al bot? Es requisito para crear tu pack.")
        return 1

    data = telegram(session, cfg["token"], "getStickerSet", payload={"name": name})
    print("¡Pack creado!")
    print("Link para usarlo en tus chats: https://t.me/addstickers/{}".format(name))
    print("Poné este valor en STICKER_FILE_ID (y en el secret de GitHub si usás Actions):")
    for st in data["result"]["stickers"]:
        print("  {}".format(st["file_id"]))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # consola de Windows: evitar errores al imprimir emojis
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Bot de avisos de Stripchat para Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Comandos útiles:\n"
            "  get-chat-id    averigua el ID del grupo\n"
            "  get-sticker-id captura el sticker que le mandaste al bot por privado\n"
            "  make-sticker-set crea tu pack de stickers desde un .webm\n"
            "  test-message   manda un mensaje de prueba al grupo\n"
            "  status         muestra el estado actual de la modelo\n"
            "  top            muestra el top de donadores (hoy, mes, mes pasado)\n"
            "  check          chequea una vez y avisa si se conectó\n"
            "  loop           chequea para siempre (PC encendida)"
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check", help="chequea una vez y avisa si se conectó/desconectó (ideal para cron)")
    sub.add_parser("loop", help="chequea en forma continua, cada CHECK_INTERVAL segundos")
    sub.add_parser("status", help="muestra el estado actual, sin avisar nada")
    p = sub.add_parser("top", help="muestra el top de donadores de la modelo")
    p.add_argument(
        "period",
        nargs="?",
        default="",
        help="hoy (por defecto), 'mes' o 'mes pasado'",
    )
    sub.add_parser("test-message", help="manda un mensaje de prueba al grupo (previsualiza sticker y texto)")
    sub.add_parser("get-chat-id", help="lista los chats que ve el bot (para averiguar el ID del grupo)")
    sub.add_parser("get-sticker-id", help="lista los stickers que le mandaron al bot (para configurar el aviso)")
    p = sub.add_parser("make-sticker-set", help="crea un pack de stickers desde un .webm y devuelve el file_id")
    p.add_argument("file", help="archivo .webm (un lado de 512px, hasta 3s, VP9, sin audio)")
    p.add_argument("--emoji", default="👑", help="emoji asociado al sticker (default: 👑)")
    p.add_argument("--name", default=None, help="nombre del pack (default: diosita_by_<bot>)")
    p.add_argument("--title", default=None, help="título visible del pack (default: Nuestra Diosa)")
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    cfg = load_config()

    if args.command in ("check", "loop"):
        require("STRIPCHAT_MODEL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    elif args.command == "status":
        require("STRIPCHAT_MODEL")
    elif args.command == "top":
        require("STRIPCHAT_MODEL")
    elif args.command == "test-message":
        require("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    elif args.command == "get-chat-id":
        require("TELEGRAM_BOT_TOKEN")
    elif args.command == "get-sticker-id":
        require("TELEGRAM_BOT_TOKEN")
    elif args.command == "make-sticker-set":
        require("TELEGRAM_BOT_TOKEN")

    commands = {
        "check": cmd_check,
        "loop": cmd_loop,
        "status": cmd_status,
        "test-message": cmd_test_message,
        "get-chat-id": cmd_get_chat_id,
        "get-sticker-id": cmd_get_sticker_id,
        "make-sticker-set": cmd_make_sticker_set,
    }
    try:
        if args.command == "top":
            return cmd_top(cfg, args)
        return commands[args.command](cfg)
    except KeyboardInterrupt:
        print("Chau.")
        return 0
    except Exception as exc:
        log("ERROR: {}".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
