"""Secretary calls viewed from the website. Read-only scan; explicit approved writes."""
import re

from goodmorning.records.calls_store import CallsStore, scan

SESSION_LABEL = "website-calls"
CALL_ID = re.compile(r"call_[0-9a-f]{16}")


def _store(app, write=False):
    try:
        return CallsStore(app.runtime, write=write)
    except ValueError as error:
        if not write and "setup_required" in str(error):
            return None
        raise


def listing(app, status=""):
    store = _store(app)
    if store is None:
        return {"calls": [], "total": 0, "open": 0}
    try:
        items = store.all(status)
    finally:
        store.close()
    public = [{key: item[key] for key in ("id", "revision", "created_at", "updated_at", "title",
                                          "reason", "question", "kind", "target_type",
                                          "target_id", "target_revision", "chat_id", "status")}
              for item in items]
    return {"calls": public, "total": len(public),
            "open": sum(1 for item in public if item["status"] == "open")}


def candidates(app):
    found = scan(app.runtime)
    return {"candidates": found, "total": len(found)}


def create(app, body):
    if not isinstance(body, dict) or set(body) != {"item"} or not isinstance(body["item"], dict):
        raise ValueError("Invalid call request")
    item = body["item"]
    for field in ("title", "reason", "question", "kind", "target_type", "target_id"):
        if not isinstance(item.get(field), str) or not item[field]:
            raise ValueError("Invalid call request")
    if type(item.get("target_revision")) is not int:
        raise ValueError("Invalid call request")
    key = f"web-call:{item['target_type']}:{item['target_id']}:{item.get('target_revision', 0)}:{item['kind']}"
    store = CallsStore(app.runtime, write=True)
    try:
        from goodmorning.records.inbox_store import stamp
        return store.add(item, SESSION_LABEL, key, stamp(app.runtime))
    finally:
        store.close()


def close(app, call_id, action, body):
    if not CALL_ID.fullmatch(call_id) or action not in ("resolve", "dismiss"):
        raise ValueError("Unknown secretary call")
    if not isinstance(body, dict) or set(body) - {"target_new_revision", "note"}:
        raise ValueError("Invalid call request")
    store = CallsStore(app.runtime, write=True)
    try:
        current = store.show(call_id)
        from goodmorning.records.inbox_store import stamp
        key = f"web-{action}:{call_id}:{current['revision']}"
        if action == "resolve":
            return store.resolve(call_id, current["revision"], body, SESSION_LABEL, key, stamp(app.runtime))
        return store.dismiss(call_id, current["revision"], body, SESSION_LABEL, key, stamp(app.runtime))
    finally:
        store.close()

