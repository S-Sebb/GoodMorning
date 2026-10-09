"""Assistant editorial review of collected candidates; no external model calls."""

import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidates(stories):
    return [{"candidate_id": digest(story), **story} for story in stories]


def seal(payload):
    value = {key: item for key, item in payload.items() if key != "candidate_batch_id"}
    return {**value, "candidate_batch_id": digest(value)}


def curate(payload, choices, expected, actor):
    """Choose only exact collected stories; caller supplies reviewed importance reasons."""
    if (not expected or payload.get("candidate_batch_id") != expected
            or seal(payload)["candidate_batch_id"] != expected):
        raise ValueError("candidate_conflict: reread the collected candidate batch")
    if not actor or not all(char.isalnum() or char in "_.:/-" for char in actor):
        raise ValueError("editorial review needs the current session identifier")
    if not isinstance(choices, list) or len(choices) > 30:
        raise ValueError("selection must be a list of at most 30 reviewed choices")
    pool = {}
    for item in payload.get("candidates", []):
        original = {key: value for key, value in item.items() if key != "candidate_id"}
        if item.get("candidate_id") != digest(original) or item["candidate_id"] in pool:
            raise ValueError("invalid or duplicate collected candidate")
        pool[item["candidate_id"]] = original
    selected, seen, counts = [], set(), {"ai": 0, "major": 0, "national": 0}
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {"candidate_id", "reason"}:
            raise ValueError("each choice needs only candidate_id and an editorial reason")
        key, reason = choice["candidate_id"], choice["reason"]
        if not isinstance(key, str) or key not in pool or key in seen or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 600:
            raise ValueError("unknown/duplicate candidate or missing editorial reason")
        story = pool[key]
        section = story.get("section")
        if section not in counts or counts[section] >= payload.get("max_items", 4):
            raise ValueError("selection exceeds the requested section limit")
        if story.get("ranking", {}).get("genre", "news") != "news":
            raise ValueError("opinion or entertainment cannot be approved as straight news")
        if story.get("date") != payload.get("date", payload.get("since")):
            raise ValueError("candidate belongs to a different news date")
        seen.add(key)
        counts[section] += 1
        selected.append({**story, "editorial_reason": reason.strip(),
                         "editorial_override": story.get("ranking", {}).get("eligible") is False})
    value = {**payload, "stories": selected,
             "curation": {"required": True, "state": "reviewed", "session": actor}}
    if "counts" in payload:
        value["counts"] = counts
    else:
        value["coverage"] = {payload["since"]: counts}
    # Keep the unchanged candidate evidence and review choices under a new content ID.
    return seal(value)
