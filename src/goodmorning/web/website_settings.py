"""Website settings the secretary changes for the user in chat.

The account's runtime holds only the secretary avatar, which this helper changes directly. Everything
else in the header pop-ups belongs to the gateway or to the device the user chats from, which the
secretary cannot reach. For those it records a request bound to the newest conversation turn the
engine accepted, in the engine's own session (OPENCODE_SESSION_ID). Once that turn's reply ends, the
page that sent the turn (its in-memory page token) claims the exact request, once, within a few
minutes, and applies it through the same pop-up controls and checked routes as a tap. Linking a
phone, unlinking one and signing out are never applied by the page: the request becomes a button
the user taps, which is the confirmation, and a link code must be one the user typed.
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from goodmorning.runtime_files import atomic_text, runtime_lock, secretary_path
from goodmorning.web import color_schemes
from goodmorning.web.avatar_images import MAX_AVATAR_BYTES, VARIANTS, save_image
from goodmorning.web.briefing_chat import AVATAR_IDS, write_avatar

FILE = "website-settings-requests.json"
KEEP_SECONDS = (
    7 * 86400
)  # Longer than any retry, so a repeated key is always recognized.
CLAIM_SECONDS = (
    10 * 60
)  # Past this, a page no longer applies a request; the card says to ask again.
LABEL = re.compile(r"[^\x00-\x1f\x7f]{1,80}")
NOTIFY_SWITCHES = ("briefing", "waiting", "chat", "events", "gm", "gn")
NOTIFY_TIMES = ("gm_time", "gn_time")
LEADS = (5, 10, 15, 30, 60)
POP_UPS = (
    "appearance",
    "notifications",
    "phones",
    "account",
    "password",
    "avatar",
    "download",
)
# Applied only when the user taps the card's button.
TAP = ("link_phone", "unlink_phone", "sign_out")


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def label(value):
    if not isinstance(value, str) or not LABEL.fullmatch(value.strip()):
        raise ValueError(
            "invalid_value: name the phone or device as the user said it or the pop-up lists it"
        )
    return " ".join(value.split())


def notifications(value):
    if (
        not isinstance(value, dict)
        or not value
        or set(value) - {*NOTIFY_SWITCHES, *NOTIFY_TIMES, "lead"}
    ):
        raise ValueError(
            "invalid_value: send only the notification choices that change: "
            + ", ".join((*NOTIFY_SWITCHES, *NOTIFY_TIMES, "lead"))
        )
    for name, item in value.items():
        if name in NOTIFY_SWITCHES and not isinstance(item, bool):
            raise ValueError(f"invalid_value: {name} is true or false")
        if name in NOTIFY_TIMES and not (
            isinstance(item, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item)
        ):
            raise ValueError(f'invalid_value: {name} is a 24-hour time such as "07:30"')
        if name == "lead" and (isinstance(item, bool) or item not in LEADS):
            raise ValueError(
                "invalid_value: lead is one of "
                + ", ".join(map(str, LEADS))
                + " minutes"
            )
    return value


def choice(options, message):
    def check(value):
        if isinstance(value, bool) or value not in options:
            raise ValueError(
                "invalid_value: " + message + ": " + ", ".join(map(str, options))
            )
        return value

    return check


def phone_code(value):
    raw = re.sub(r"[\s-]", "", value.upper()) if isinstance(value, str) else ""
    if not re.fullmatch(r"[A-Z0-9]{8}", raw):
        raise ValueError(
            "invalid_value: the code the app shows has 8 letters and digits, such as ABCD-2345"
        )
    return raw[:4] + "-" + raw[4:]


def sign_out(value):
    if value is not True:
        raise ValueError("invalid_value: sign_out takes the value true")
    return value


# What the chat page applies, each with the check its value must pass here first.
PAGE = {
    "language": choice(("en", "zh-CN"), "website language is one of"),
    "style": choice(tuple(color_schemes.OPTIONS["style"]), "style is one of"),
    "day_scheme": choice(
        tuple(color_schemes.OPTIONS["day"]), "day color scheme is one of"
    ),
    "night_scheme": choice(
        tuple(color_schemes.OPTIONS["night"]), "night color scheme is one of"
    ),
    "widget_theme": choice(
        ("clock", "phone", "day", "night"), "widget theme is one of"
    ),
    "notifications": notifications,
    "notifications_here": choice(
        ("off",),
        'only "off": turning notifications on needs the user\'s own tap, so open the pop-up',
    ),
    "device_notifications_off": label,
    "link_phone": phone_code,
    "unlink_phone": label,
    "sign_out": sign_out,
    "open": choice(POP_UPS, "open one of"),
}


def path(runtime):
    target = Path(runtime) / FILE
    if target.is_symlink():
        raise ValueError("unsafe_path: settings requests must belong to this runtime")
    return target


def load(runtime):
    """The stored requests and the next request ID, which only goes up: an old card never meets a new request."""
    target = path(runtime)
    data = (
        json.loads(target.read_text(encoding="utf-8"))
        if target.is_file()
        else {"requests": []}
    )
    requests = data["requests"]
    return {
        "next": data.get("next")
        or max((entry["seq"] for entry in requests), default=0) + 1,
        "requests": requests,
    }


def store(runtime, data):
    atomic_text(path(runtime), encode(data) + "\n")


def page_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def chat_items(runtime):
    chats = Path(runtime) / "browser-chats" / "chats.json"
    if chats.is_symlink() or not chats.is_file():
        raise ValueError("no_active_turn: settings change only from a website chat")
    return json.loads(chats.read_text(encoding="utf-8"))


def dispatched_turn(runtime, session):
    """The turn this command answers, from the backend's own chat state, or a refusal when unsure.

    The engine does not tell a command which message it answers. So the newest delivered turn counts
    only if the engine has acknowledged it, it did not interrupt a reply still running and it does not
    merge messages from different pages; otherwise another tab could take the change."""
    for item in chat_items(runtime).values():
        if item.get("session") == session:
            turns = [
                turn
                for turn in item.get("turns", [])
                if not turn.get("undelivered") and not turn.get("local")
            ]
            if not turns:
                break
            newest = turns[-1]
            if (
                not newest.get("accepted")
                or newest.get("interrupt")
                or newest.get("mixed")
            ):
                raise ValueError(
                    "ask_again: a newer message arrived while you worked, or it is still being "
                    "delivered, so this change cannot be tied to the right message; nothing changed. "
                    "Tell the user to ask again once this reply ends"
                )
            return item["id"], newest
    raise ValueError("no_active_turn: settings change only from a website chat")


def user_code(turn, value):
    """A link code counts only if the user typed it, whole, in one message or answer field: injected
    text could otherwise link someone else's phone."""
    typed = turn.get("typed", []) if "answer" in turn else [turn.get("text", "")]
    code = re.compile(
        rf"(?<![A-Z0-9]){value[:4]}[\s-]?{value[5:]}(?![A-Z0-9])", re.IGNORECASE
    )
    if not any(isinstance(text, str) and code.search(text) for text in typed):
        raise ValueError(
            "invalid_value: link only a code the user typed in their own message; "
            "ask them to type the code the GoodMorning app shows"
        )


def change(runtime, session, key, request):
    if (
        not isinstance(request, dict)
        or set(request) - {"setting", "value"}
        or not isinstance(request.get("setting"), str)
    ):
        raise ValueError(
            'invalid_input: send {"setting":NAME,"value":VALUE}; see docs/helper-inputs.md'
        )
    setting, value = request["setting"], request.get("value")
    if setting == "password":
        raise ValueError(
            "password_self_service: never change a password; guide the user to Account → Change password, "
            'optionally with {"setting":"open","value":"password"}'
        )
    if setting not in ("avatar", "avatar_upload", *PAGE):
        raise ValueError(
            "unknown_setting: one of " + ", ".join(("avatar", "avatar_upload", *PAGE))
        )
    chat, turn = dispatched_turn(runtime, session)
    if setting in PAGE:
        value = PAGE[setting](value)
        if turn.get("source") == "widget":
            raise ValueError(
                "widget_source: the phone's chat widget has no page to change this on; "
                "tell the user to ask from the website or the app's chat page, naming the pop-up"
            )
        if setting == "link_phone":
            user_code(turn, value)
    with runtime_lock(runtime, ".website-settings.lock", wait=2):
        now = time.time()
        data = load(runtime)
        requests = [
            entry
            for entry in data["requests"]
            if now - entry.get("created", now) < KEEP_SECONDS
        ]
        # A retried command never applies twice; a reused key for another change changes nothing.
        old = next(
            (
                entry
                for entry in requests
                if entry["session"] == session and entry["key"] == key
            ),
            None,
        )
        if old:
            if (old["setting"], old["request"]) != (setting, value):
                raise ValueError(
                    "request_key_reused: use a new request key for a different change"
                )
            return receipt(old, repeated=True)
        stored = value
        if setting == "avatar":
            write_avatar(
                runtime, choice((*AVATAR_IDS, "custom"), "avatar is one of")(value)
            )
        elif setting == "avatar_upload":
            stored = avatar_upload(runtime, turn, value)
        entry = {
            "seq": data["next"],
            "at": datetime.now().astimezone().isoformat(),
            "created": now,
            "session": session,
            "key": key,
            "chat": chat,
            "turn": turn["id"],
            "page": turn.get("page"),
            "setting": setting,
            "request": value,
            "value": stored,
        }
        store(runtime, {"next": data["next"] + 1, "requests": [*requests, entry]})
        return receipt(entry)


def receipt(entry, repeated=False):
    setting = entry["setting"]
    result = {
        "saved": True,
        "setting": setting,
        "value": entry["value"],
        "id": entry["seq"],
    }
    if repeated:
        result["repeated"] = True
    if setting.startswith("avatar"):
        return result | {"applies": "account"}
    if setting in TAP:
        return result | {
            "applies": "user_tap",
            "next": "A button under your reply does this when the user taps it. "
            "Ask them to tap it; do not say it is done.",
        }
    return result | {
        "applies": "this_page",
        "next": "The page the user wrote from applies this after your reply and "
        "shows the outcome under it. Word it as in progress; do not claim it already changed.",
    }


def avatar_upload(runtime, turn, value):
    if (
        not isinstance(value, dict)
        or set(value) != {"variant", "source"}
        or value["variant"] not in VARIANTS
    ):
        raise ValueError(
            'invalid_value: avatar_upload is {"variant":"day|night|profile","source":PATH}'
        )
    source = Path(value["source"].removeprefix("file://")).resolve()
    # Only an image the user attached to the message being answered becomes the avatar.
    uploads = Path(runtime).resolve() / "browser-uploads"
    attached = {
        (uploads / entry["id"] / "files" / entry["name"]).resolve()
        for entry in turn.get("attachments", [])
    }
    if (
        source not in attached
        or not source.is_file()
        or source.stat().st_size > MAX_AVATAR_BYTES
    ):
        raise ValueError(
            "invalid_value: the source must be a PNG, JPEG or WebP image of at most 5 MB "
            "attached to the message you are answering"
        )
    save_image(runtime, source.read_bytes(), value["variant"])
    write_avatar(runtime, "custom")
    return {"variant": value["variant"]}


def state(entry, now=None):
    """How the chat page may treat a request: open, used (claimed once) or stale."""
    if entry["setting"].startswith("avatar"):
        return "saved"
    if entry.get("claimed"):
        return "used"
    return (
        "stale" if (now or time.time()) - entry["created"] > CLAIM_SECONDS else "open"
    )


def claim(runtime, chat, seq, body, finished):
    """The page's one-time claim of the exact request it shows: returns the change to apply, or why not.

    Only the page that sent the request's turn (its page token) may claim, only after the reply has
    finished, and linking, unlinking or signing out only from the user's tap on its button."""
    if (
        set(body) != {"setting", "page", "tap"}
        or not isinstance(body["setting"], str)
        or not isinstance(body["page"], str)
        or not isinstance(body["tap"], bool)
    ):
        raise ValueError("Invalid settings claim")
    with runtime_lock(runtime, ".website-settings.lock", wait=2):
        data = load(runtime)
        entry = next(
            (
                item
                for item in data["requests"]
                if item["seq"] == seq and item.get("chat") == chat
            ),
            None,
        )
        if (
            entry is None
            or entry["setting"] != body["setting"]
            or entry["setting"].startswith("avatar")
        ):
            raise ValueError("Unknown settings request")
        if not entry.get("page") or not hmac.compare_digest(
            entry["page"], page_hash(body["page"])
        ):
            raise ValueError("Only the page that sent this message can apply it")
        if body["tap"] != (entry["setting"] in TAP):
            raise ValueError(
                "This change is applied only by a tap on its button"
                if entry["setting"] in TAP
                else "Invalid settings claim"
            )
        if not finished:
            return {"claimed": False, "state": "running"}
        current = state(entry)
        if current != "open":
            return {"claimed": False, "state": current}
        entry["claimed"] = time.time()
        store(runtime, data)
        return {
            "claimed": True,
            "seq": seq,
            "setting": entry["setting"],
            "value": entry["value"],
        }


def changes(runtime, owners):
    """Receipts for chat history: session-owned and bounded, like the other action receipts."""
    now = time.time()
    return [
        {
            "seq": entry["seq"],
            "at": entry["at"],
            "turn": entry.get("turn"),
            "setting": entry["setting"],
            "value": entry["value"],
            "state": state(entry, now),
        }
        for entry in load(runtime)["requests"]
        if entry["session"] in owners
    ][-30:]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="JSON input fields and tested examples: docs/helper-inputs.md",
    )
    parser.add_argument("--secretary-dir")
    parser.add_argument("--session")
    parser.add_argument("--request-key")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input-stdin", action="store_true")
    inputs.add_argument("--input-json")
    args = parser.parse_args(argv)
    # The engine sets its own session for each command; the model's --session is only a fallback.
    args.session = os.environ.get("OPENCODE_SESSION_ID") or args.session
    try:
        if not args.session or not args.request_key:
            raise ValueError(
                "session_required: pass the native --session and a stable --request-key"
            )
        text = args.input_json if args.input_json is not None else sys.stdin.read(2001)
        if not text or len(text) > 2000:
            raise ValueError(
                "input_required: supply bounded JSON with --input-stdin or --input-json"
            )
        print(
            encode(
                change(
                    secretary_path(args.secretary_dir),
                    args.session,
                    args.request_key,
                    json.loads(text),
                )
            )
        )
        return 0
    except (ValueError, OSError) as error:
        message = (
            f"invalid_input: malformed JSON ({error.msg}); nothing was saved"
            if isinstance(error, json.JSONDecodeError)
            else str(error)
            if isinstance(error, ValueError)
            else "settings_unavailable: preserve storage and inspect the runtime"
        )
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
