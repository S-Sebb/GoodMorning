"""Focused paid custom-schedule trials. Synthetic records; native models, no production users.

Covers only the changed custom prompts: ambiguous requests ask until clear with
no write, fully specified requests save once with a receipt, briefing rows are
code-owned and deterministic, and tone matches the saved voice.
Transcripts need manual tone review; assertions alone are not acceptance.
"""
import argparse
import fcntl
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language, models


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


@contextmanager
def context(lang, selected):
    a = language.CURRENT.set(lang)
    b = models.CURRENT.set(selected)
    try:
        yield
    finally:
        language.CURRENT.reset(a)
        models.CURRENT.reset(b)


@contextmanager
def matrix_lock(output):
    lock_path = output.parent / ("." + output.name + ".lock")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This matrix already has an active runner; observe it instead of resuming")
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def custom_rules(runtime):
    from goodmorning.records.custom_store import CustomStore
    try:
        store = CustomStore(runtime, write=False)
    except ValueError:
        return []
    try:
        return list(store.all())
    finally:
        store.close()


def run_case(output, source, lang, selected, day):
    name = f"{lang}-custom"
    folder = output / name
    runtime = folder / "account"
    target = folder / "result.json"
    if target.exists() and json.loads(target.read_text()).get("complete"):
        return json.loads(target.read_text())
    runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not (runtime / "profile.md").exists():
        (runtime / "profile.md").write_text(
            "city: London, GB\ntimezone: Europe/London\nnews_country: GB\n"
            "secretary_language: English\nsecretary_name: Nora\ncalendar_source: custom\n")
        (runtime / "browser-policy.json").write_text(json.dumps(
            {key: False for key in ("live_project_access", "calendar_sync",
                                    "publisher_images", "news_acknowledgement")}))
        initialize(runtime)
    result = {"case": name, "language": lang, "model": selected,
              "stages": {}, "complete": False, "tone_review": "pending manual transcript review"}
    save(target, result)
    # A failed assertion ends the run; the engine then stops at exit.
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    today = day.isoformat()

    def wait(chat):
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            with context(lang, selected):
                status = app.chats.status(chat)
            if status["permissions"]:
                (folder / "permission-evidence.json").write_text(
                    json.dumps({"chat": chat, "permissions": status["permissions"],
                                "state": status.get("state")}, ensure_ascii=False, indent=2))
                raise AssertionError(
                    "Unexpected permission; do not auto-approve. Evidence in permission-evidence.json: "
                    + json.dumps(status["permissions"], ensure_ascii=False)[:1000])
            if status["state"] in ("idle", "waiting"):
                return status
            if status["state"] in ("uncertain", "unavailable"):
                raise AssertionError("Uncertain delivery; inspect, never replay")
            time.sleep(3)
        raise TimeoutError("Native request did not settle in seven minutes")

    def ask(chat, message):
        with context(lang, selected):
            if chat not in app.chats.items:
                app.chats.start({"id": chat, "mode": "secretary", "text": message})
            else:
                app.chats.send(chat, {"id": uuid.uuid4().hex, "text": message})
        return wait(chat)

    # 1. Ambiguous: vague habit must ask, never write.
    vague_chat = uuid.uuid4().hex
    vague = "I want to do gym regularly, please handle it." if lang == "en" else "我想规律健身，请安排。"
    status = ask(vague_chat, vague)
    forms = status.get("forms", [])
    assert len(forms) >= 1, "Ambiguous custom request must ask questions first"
    assert custom_rules(runtime) == [], "Ambiguous request must not write any custom rule"
    result["stages"]["ambiguity"] = {"forms": len(forms), "rules": 0,
                                     "assistant_replies": len([m for m in status.get("messages", [])
                                                               if m.get("role") == "assistant" and (m.get("text") or "").strip()])}
    save(target, result)

    # 2. Fully specified in a fresh chat: one save with receipt and exact policy.
    clear_chat = uuid.uuid4().hex
    start = today
    clear = (f"Add a custom gym schedule: every 2 days starting {start}, "
             "restart the 2-day gap from each finish, chase missed days daily, "
             "stop at 3 per Mon-Sun week counting only my confirmations, "
             "and check every evening even on off days."
             if lang == "en" else
             f"添加特殊健身安排：从{start}起每2天一次，每次完成后重新计算2天，漏掉顺延每天提醒，"
             "每周一到周日经我确认满3次即停，非到期日晚间也照常检查。")
    status = ask(clear_chat, clear)
    rules = custom_rules(runtime)
    assert len(rules) == 1, f"Expected exactly one custom rule, got {len(rules)}"
    policy = rules[0]["policy"]
    assert policy.get("interval_days") == 2, "Saved policy must keep the 2-day gap"
    assert policy.get("anchor") == "last_completion", "Saved policy must restart from each finish"
    assert policy.get("miss_policy") == "chase", "Saved policy must chase missed days"
    assert policy.get("weekly_cap") == 3, "Saved policy must stop at 3 per week"
    assert policy.get("nightly") == "always", "Saved policy must check every evening"
    result["stages"]["save_once"] = {"rules": 1, "policy": policy}
    save(target, result)

    # 3. Briefing rows are code-owned and deterministic.
    from goodmorning.records.custom_store import CustomStore
    store = CustomStore(runtime, write=False)
    try:
        gm_rows = store.briefing(today, "gm")
        assert any(r["due"] for r in gm_rows), "Due custom must appear in morning rows"
        assert store.briefing(today, "gm") == gm_rows, "Same inputs must give the same briefing rows"
    finally:
        store.close()
    result["stages"]["briefing_rows"] = {"due": True, "deterministic": True}
    save(target, result)
    result["complete"] = True
    save(target, result)
    bridge.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument("--language", required=True, choices=("en", "zh-CN"))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = {"en": "muse-spark", "zh-CN": "deepseek-flash"}[args.language]
    day = date(2026, 10, 13)
    output.mkdir(parents=True, exist_ok=True)
    with matrix_lock(output):
        source = output / "source"
        if not source.exists():
            trial_engine.copy_release(source, args.source.resolve())
        result = run_case(output, source, args.language, selected, day)
    print(json.dumps({"case": result["case"], "complete": result["complete"],
                      "stages": list(result["stages"]),
                      "tone_review": result["tone_review"]}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
