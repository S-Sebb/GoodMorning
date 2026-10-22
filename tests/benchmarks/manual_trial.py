"""Manual secretary trials: I supply the brains, the script supplies the plumbing.

Setup once per worktree state:
  python3 tests/benchmarks/manual_trial.py --setup --source /tmp/opencode/manual-src
Per case+model (fresh synthetic runtime, fresh native session, never production):
  python3 tests/benchmarks/manual_trial.py --dir /tmp/opencode/manual-yuka/A-deepseek --model deepseek-flash --language zh-CN --send "11月初提醒我和若熙确定北京行程"
  python3 tests/benchmarks/manual_trial.py --dir ... --reply-form frm_ID '{"q0": "..."}'
  python3 tests/benchmarks/manual_trial.py --dir ... --records
  python3 tests/benchmarks/manual_trial.py --dir ... --messages
"""
import argparse
import json
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from benchmarks.native_bridge import NativeBridge
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language, models


@contextmanager
def context(lang, selected):
    a = language.CURRENT.set(lang)
    b = models.CURRENT.set(selected)
    try:
        yield
    finally:
        language.CURRENT.reset(a)
        models.CURRENT.reset(b)


def load(args):
    directory = Path(args.dir)
    state_file = directory / "chat.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    return directory, state, state_file


def snapshot(app, chat, lang, selected):
    with context(lang, selected):
        return app.chats.status(chat)


def settle(app, chat, lang, selected, label="request"):
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        status = snapshot(app, chat, lang, selected)
        print("state:", status["state"], "| forms:", len(status.get("forms", [])),
              "| permissions:", len(status.get("permissions", [])),
              flush=True)
        if status["state"] in ("idle", "waiting", "uncertain", "unavailable"):
            for form in status.get("forms", []):
                print("FORM", form["id"], "::",
                      json.dumps(form, ensure_ascii=False)[:2000], flush=True)
            if status["state"] in ("uncertain", "unavailable"):
                print("WARNING: delivery uncertain; inspect transcript before retrying",
                      flush=True)
            return status
        time.sleep(5)
    raise TimeoutError(label + " did not settle in seven minutes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--dir")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--language", default="zh-CN", choices=("en", "zh-CN"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--send")
    group.add_argument("--status", action="store_true")
    group.add_argument("--reply-form", nargs=2, metavar=("FORM", "JSON"))
    group.add_argument("--records", action="store_true")
    group.add_argument("--messages", action="store_true")
    args = parser.parse_args()
    if args.setup:
        source = Path(args.source)
        if source.exists():
            shutil.rmtree(source)
        source.mkdir(parents=True, mode=0o700)
        for name in ("src", "scripts", "docs", "templates", "assets", "skill-source", ".opencode"):
            shutil.copytree(ROOT / name, source / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "AGENT-PROMPT-GUIDE.md", "SERVER-USER-GUIDE.md", "SERVER-DATA-GUIDE.md"):
            shutil.copyfile(ROOT / name, source / name)
        shutil.copyfile(ROOT / "skill-source/goodmorning.md", source / "goodmorning.md")
        (source / "opencode.json").write_text(json.dumps({"skills": ["."]}))
        print("source ready:", source)
        return
    directory, state, state_file = load(args)
    runtime = directory / "account"
    source = Path(args.source or "/tmp/opencode/manual-src")
    lang, selected = args.language, args.model
    if args.send and not state:
        runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
        (runtime / "profile.md").write_text(
            "city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\n"
            "secretary_language: Chinese\nsecretary_name: Nora\ncalendar_source: custom\n")
        (runtime / "browser-policy.json").write_text(json.dumps(
            {key: False for key in ("live_project_access", "calendar_sync",
                                    "publisher_images", "news_acknowledgement")}))
        initialize(runtime)
        chat = uuid.uuid4().hex
        state = {"chat": chat, "lang": lang, "model": selected}
        state_file.write_text(json.dumps(state))
    bridge = NativeBridge(source, runtime)
    app = BrowserApp(runtime, bridge)
    chat = state["chat"]
    try:
        existing = (app.chats.get(chat) or {}).get("session")
    except Exception:
        existing = None
    if existing and existing not in bridge.sessions:
        bridge.sessions[existing] = {"idle": True}
    if args.send:
        ask = args.send
        with context(lang, selected):
            if chat not in app.chats.items:
                app.chats.start({"id": chat, "mode": "secretary", "text": ask})
            else:
                app.chats.send(chat, {"id": uuid.uuid4().hex, "text": ask})
        print("sent; chat", chat, flush=True)
        settle(app, chat, lang, selected, "request")
    elif args.status:
        status = snapshot(app, chat, lang, selected)
        print("state:", status["state"], "| forms:", len(status.get("forms", [])),
              "| permissions:", len(status.get("permissions", [])))
        for form in status.get("forms", []):
            print("FORM", form["id"], "::", json.dumps(form, ensure_ascii=False)[:2000])
    elif args.reply_form:
        form_id, values = args.reply_form
        with context(lang, selected):
            receipt = app.chats.reply(chat, "form", form_id, {"answer": json.loads(values)})
        print("replied:", json.dumps(receipt, ensure_ascii=False)[:300], flush=True)
        settle(app, chat, lang, selected, "answer")
    elif args.records:
        from goodmorning.records.inbox_store import InboxStore
        from goodmorning.records.task_store import TaskStore
        inbox = InboxStore(runtime)
        try:
            for task in TaskStore(inbox).all():
                print(task["id"], "rev", task["revision"], "|", task.get("title"), "|",
                      (task.get("detail") or "")[:120], "|", task.get("status"), "|",
                      json.dumps(task.get("repeat"), ensure_ascii=False), "|", task.get("planned_date"),
                      "|", task.get("due_date"))
            print("--- entries ---")
            for entry in inbox.list()["items"]:
                print(entry["id"], entry["kind"], entry["status"], "|", (entry.get("summary") or "")[:80])
        finally:
            inbox.close()
        try:
            from goodmorning.records.custom_store import CustomStore
            store = CustomStore(runtime, write=False)
            try:
                for rule in store.all():
                    print("CUSTOM", rule["id"], "|", rule.get("title"), "|",
                          json.dumps(rule.get("policy"), ensure_ascii=False))
            finally:
                store.close()
        except ValueError as error:
            print("no custom store:", error)
    elif args.messages:
        with context(lang, selected):
            status = app.chats.status(chat)
        for message in status.get("messages", [])[-8:]:
            print(f"[{message.get('role')}]", (message.get("text") or "")[:1200])
            print("---")


if __name__ == "__main__":
    main()
