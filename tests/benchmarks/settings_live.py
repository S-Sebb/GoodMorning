"""Opt-in paid trials for changing website settings in a secretary chat.

Real models handle plain requests for header pop-up settings and the helper's recorded outcome is
checked: a night color scheme and a notification reminder (recorded for the chat page to apply),
the secretary avatar (saved at once), a password change (refused, with self-service guidance),
linking, unlinking and signing out (prepared as a button the user taps, with no question first),
"dark mode" (City Lights recommended first), an unnamed "old phone" (the Phones pop-up opened),
a sign-out the user then calls off (nothing more recorded), a request from the Android chat
widget (no page change recorded, the pop-up named), and a request the helper refuses with ask_again
(nothing recorded; the reply says so and asks to repeat it, without claiming success). Whether replies claim a page change already
happened, tone and language need manual review of the retained transcripts.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from benchmarks import trial_engine
from benchmarks.anime_live import account
from benchmarks.holidays_live import source_copy
from benchmarks.task_tone_live import context, matrix_lock, save
from benchmarks.trial_engine import TrialBridge
from goodmorning.web import models, website_settings
from goodmorning.web.briefing_chat import read_avatar
from goodmorning.web.briefing_server import BrowserApp

ZONE = "Europe/London"
MESSAGES = {
    "scheme": {
        "en": "Could you switch my night colors to Midnight Violet?",
        "zh-CN": "帮我把夜间配色换成午夜紫吧。",
    },
    "notify": {
        "en": "On this device, notify me at 07:30 if my morning briefing isn’t prepared yet.",
        "zh-CN": "在这台设备上，如果早间简报还没准备好，早上 7:30 提醒我一下。",
    },
    "avatar": {
        "en": "Please switch your avatar to Avatar 4.",
        "zh-CN": "把你的秘书形象换成形象 4 吧。",
    },
    "password": {
        "en": "Change my password to Sunflower-88 please.",
        "zh-CN": "帮我把密码改成 Sunflower-88。",
    },
    "unlink": {
        "en": "Unlink my old phone, it’s called Pixel 8.",
        "zh-CN": "把我那台叫 Pixel 8 的旧手机取消关联吧。",
    },
    "signout": {"en": "Sign me out of here.", "zh-CN": "帮我退出登录。"},
    "link": {
        "en": "Link my phone please, the app shows abcd 2345.",
        "zh-CN": "帮我关联手机，App 上显示的是 abcd 2345。",
    },
    "dark": {"en": "Can you turn on dark mode?", "zh-CN": "能帮我开深色模式吗？"},
    "oldphone": {"en": "Unlink my old phone.", "zh-CN": "把我的旧手机取消关联。"},
    "decline": {"en": "Sign me out of here.", "zh-CN": "帮我退出登录。"},
    "widget": {
        "en": "Could you switch my night colors to Midnight Violet?",
        "zh-CN": "帮我把夜间配色换成午夜紫吧。",
    },
    # The message is marked as an interrupt once saved, so the helper must refuse with ask_again.
    "askagain": {
        "en": "Could you switch my night colors to Midnight Violet?",
        "zh-CN": "帮我把夜间配色换成午夜紫吧。",
    },
}
# On ask_again the reply says nothing changed and asks to repeat the request; it never claims success.
REPEAT = {"en": ("again", "repeat", "resend"), "zh-CN": ("再",)}
NOT_DONE = {
    "en": (
        "didn't",
        "did not",
        "wasn't",
        "not changed",
        "couldn't",
        "could not",
        "hasn't",
        "haven't",
        "isn't",
    ),
    "zh-CN": ("没有", "没能", "未", "没改", "不能"),
}
CLAIMS = {
    "en": (
        "I've switched",
        "I've changed",
        "I switched",
        "is now set",
        "now uses",
        "Done",
    ),
    "zh-CN": ("已经换成", "已换成", "已经改成", "改好了", "已经切换"),
}
# A follow-up after the first reply: the user calls the sign-out off instead of tapping.
FOLLOW_UP = {
    "decline": {
        "en": "Actually, never mind, don’t sign me out.",
        "zh-CN": "算了，先不退出了。",
    }
}
TONES = {"scheme": "playful", "password": "formal"}
TAPPED = {
    "unlink": ("unlink_phone", "pixel 8"),
    "signout": ("sign_out", True),
    "link": ("link_phone", "ABCD-2345"),
}


def expected(scenario, runtime, requests, text):
    recorded = [(entry["setting"], entry["value"]) for entry in requests]
    # Opening a pop-up alongside (for instance Notifications, to turn them on) is fine.
    settings = [item for item in recorded if item[0] != "open"]
    if scenario == "scheme":
        assert settings == [("night_scheme", "midnight-violet")], settings
    elif scenario == "notify":
        assert len(settings) == 1 and settings[0][0] == "notifications", settings
        value = settings[0][1]
        assert value.get("gm") is True and value.get("gm_time") == "07:30", value
    elif scenario == "avatar":
        assert read_avatar(runtime) == "m2", read_avatar(runtime)
    elif scenario == "password":
        assert not settings, settings
        assert any(word in text for word in ("Change password", "修改密码")), (
            "No guidance to Change password"
        )
    elif scenario in TAPPED:
        lowered = [
            (
                name,
                value.casefold()
                if isinstance(value, str) and scenario == "unlink"
                else value,
            )
            for name, value in settings
        ]
        assert lowered == [TAPPED[scenario]], settings
    elif scenario == "dark":
        assert (
            all(name == "night_scheme" for name, _ in settings) and len(settings) <= 1
        ), settings
        assert any(word in text for word in ("City Lights", "城市灯火")), (
            "City Lights not recommended"
        )
        for word in ("clock", "时钟", "系统时间"):
            assert word not in text, (
                f"Mentions {word!r}: check it does not suggest changing the clock"
            )
    elif scenario == "oldphone":
        assert not settings, settings
        assert ("open", "phones") in recorded or (
            "open",
            "notifications",
        ) in recorded, recorded
    elif scenario == "decline":
        assert settings in ([], [("sign_out", True)]), settings
    elif scenario == "askagain":
        assert not recorded, recorded
    elif scenario == "widget":
        assert not recorded, recorded
        assert any(word in text for word in ("Appearance", "外观")), (
            "Did not name the Appearance pop-up"
        )


def first_choice(form):
    """The recommended option comes first, so a user taking the advice picks it."""
    values = {}
    for field in form["fields"]:
        if not field.get("options"):
            raise AssertionError(
                "Unsupported synthetic question; inspect it instead of guessing: "
                + json.dumps(field, ensure_ascii=False)[:500]
            )
        chosen = field["options"][0]["value"]
        values[field["key"]] = (
            [chosen] if field.get("type") == "multiselect" else chosen
        )
    return values


def run_chat(output, language, selected, scenario):
    folder = output / scenario
    folder.mkdir(mode=0o700)
    tone = TONES.get(scenario, "default")
    runtime = account(folder, language, tone, "", ZONE)
    source = source_copy(folder, runtime)
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    result = {
        "scenario": scenario,
        "language": language,
        "tone": tone,
        "model": selected,
        "turns": [],
        "message": MESSAGES[scenario][language],
        "review": "pending manual review: page changes worded as in progress, tap actions as waiting for the tap; "
        "password guidance names Account → Change password; tone and language",
    }

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(language, selected):
                status = app.chats.status(chat)
            if status["permissions"]:
                raise AssertionError(
                    "Unexpected permission; not auto-approved: "
                    + json.dumps(status["permissions"])[:500]
                )
            if status["state"] in ("idle", "waiting"):
                return status
            if status["state"] in ("uncertain", "unavailable"):
                raise AssertionError("Uncertain delivery; inspect, never replay")
            time.sleep(3)
        raise TimeoutError("No settled reply within ten minutes")

    try:
        body = {"id": chat, "mode": "secretary", "text": MESSAGES[scenario][language]}
        with context(language, selected):
            app.chats.start(
                body | ({"source": "widget"} if scenario == "widget" else {})
            )
        if scenario == "askagain":
            # As if another tab had interrupted: the helper cannot tell which message asked.
            with app.chats.lock:
                app.chats.items[chat]["turns"][-1]["interrupt"] = True
                app.chats.save()
        seen, follow_up = 0, FOLLOW_UP.get(scenario, {}).get(language)
        for _ in range(4):
            status = wait()
            replies = [
                m["text"]
                for m in status["messages"][seen:]
                if m["role"] == "assistant" and m.get("text", "").strip()
            ]
            seen = len(status["messages"])
            turn = {
                "assistant": replies,
                "forms": status["forms"],
                "requests": website_settings.load(runtime)["requests"],
            }
            result["turns"].append(turn)
            save(folder / "result.json", result)
            if status["forms"]:
                # Tap actions need no question first; only "dark mode" and the unnamed phone may ask.
                assert scenario in ("dark", "oldphone"), (
                    "Asked a question first: " + json.dumps(status["forms"])[:500]
                )
                if scenario == "oldphone":
                    break  # The user would pick the phone in the opened pop-up.
                turn["answered"] = first_choice(status["forms"][0])
                with context(language, selected):
                    app.chats.reply(
                        chat,
                        "form",
                        status["forms"][0]["id"],
                        {"answer": turn["answered"]},
                    )
            elif follow_up:
                turn["sent"], follow_up = follow_up, None
                with context(language, selected):
                    app.chats.send(chat, {"id": uuid.uuid4().hex, "text": turn["sent"]})
            else:
                break
        save(folder / "messages.json", status["messages"])
        text = " ".join(
            reply for turn in result["turns"] for reply in turn["assistant"]
        )
        assert result["turns"][-1]["assistant"], "The last turn ended without a reply"
        expected(scenario, runtime, website_settings.load(runtime)["requests"], text)
        commands = (
            (runtime / "trial-commands.jsonl").read_text()
            if (runtime / "trial-commands.jsonl").exists()
            else ""
        )
        if scenario == "password":
            assert "Sunflower-88" not in commands, (
                "The password reached a helper command"
            )
        if scenario == "askagain":
            # The trial CLI logs each call's argv and exit code: a settings call must have failed, and
            # the helper's own turn check must give ask_again for this chat.
            entries = [json.loads(line) for line in commands.splitlines()]
            calls = {
                entry["call"]: entry["argv"][0] for entry in entries if "argv" in entry
            }
            assert any(
                calls.get(entry["call"]) == "settings" and entry.get("exit") == 1
                for entry in entries
                if "exit" in entry
            ), "No refused settings call"
            session = app.chats.get(chat)["session"]
            try:
                website_settings.dispatched_turn(runtime, session)
                raise AssertionError("The helper's turn check would not refuse")
            except ValueError as error:
                assert str(error).startswith("ask_again"), error
            assert any(word in text for word in REPEAT[language]), (
                "Did not ask to repeat the request"
            )
            assert any(word in text for word in NOT_DONE[language]), (
                "Did not say the change did not happen"
            )
            for word in CLAIMS[language]:
                assert word not in text, f"Claims success: {word!r}"
        result["checks"] = [
            "recorded requests and saved avatar match the request; tap actions asked no question first"
        ]
        result["functional_complete"] = True
        print(f"{language} {selected} {scenario}: passed", flush=True)
    except Exception as error:
        result["failure"] = str(error)[:1500]
        result["functional_complete"] = False
        print(
            f"{language} {selected} {scenario}: INCOMPLETE — {result['failure']}",
            flush=True,
        )
    finally:
        bridge.close()
        save(folder / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument("--language", choices=("en", "zh-CN"), required=True)
    parser.add_argument(
        "--model",
        choices=tuple(models.MODELS),
        help="Defaults to the production model for the language",
    )
    parser.add_argument("--only", nargs="*", choices=tuple(MESSAGES))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        trial_engine.copy_release(output / "release", args.source.resolve())
        results = [
            run_chat(output, args.language, selected, name)
            for name in (args.only or MESSAGES)
        ]
        save(
            output / "matrix.json",
            {
                "model": selected,
                "language": args.language,
                "cases": results,
                "limitations": [
                    "Synthetic London account; the chat page that applies page settings is not driven here.",
                    "One sample per scenario and model; prose needs manual review.",
                ],
            },
        )
        if not all(result.get("functional_complete") for result in results):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
