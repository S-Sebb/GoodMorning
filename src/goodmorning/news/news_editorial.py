"""Assistant editorial review of collected candidates; no external model calls."""

import hashlib
import json
from .news_rank import ai_relevance


class EditorialError(ValueError):
    """Safe code-authored guidance; never includes provider text or private input."""


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
        raise EditorialError("candidate_conflict: reread the collected candidate batch")
    if not actor or not all(char.isalnum() or char in "_.:/-" for char in actor):
        raise EditorialError("editorial review needs the current session identifier")
    if not isinstance(choices, list) or len(choices) > 30:
        raise EditorialError("selection must be a list of at most 30 reviewed choices")
    pool = {}
    for item in payload.get("candidates", []):
        original = {key: value for key, value in item.items() if key != "candidate_id"}
        if item.get("candidate_id") != digest(original) or item["candidate_id"] in pool:
            raise EditorialError("invalid or duplicate collected candidate")
        pool[item["candidate_id"]] = original
    selected, seen, counts = [], set(), {"ai": 0, "major": 0, "national": 0}
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {"candidate_id", "reason"}:
            raise EditorialError("each choice needs only candidate_id and an editorial reason")
        key, reason = choice["candidate_id"], choice["reason"]
        if not isinstance(key, str) or key not in pool or key in seen or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 600:
            raise EditorialError("unknown/duplicate candidate or missing editorial reason")
        story = pool[key]
        section = story.get("section")
        if section not in counts or counts[section] >= payload.get("max_items", 4):
            raise EditorialError("selection exceeds the requested section limit")
        if story.get("ranking", {}).get("genre", "news") != "news":
            raise EditorialError("opinion or entertainment cannot be approved as straight news")
        if not payload.get("date", payload.get("since")) <= story.get("date", "") <= payload.get("date", payload.get("until")):
            raise EditorialError("candidate belongs to a different news date")
        if section == 'ai' and not ai_relevance(story):
            raise EditorialError('AI selection requires an explicit AI connection in the collected title or publisher excerpt; skip unrelated or ambiguous candidates')
        seen.add(key)
        counts[section] += 1
        selected.append({**story, "editorial_reason": reason.strip(),
                         "editorial_override": story.get("ranking", {}).get("eligible") is False})
    value = {**payload, "stories": selected,
             "curation": {"required": True, "state": "reviewed", "session": actor}}
    if "counts" in payload:
        value["counts"] = counts
    else:
        value["coverage"] = {day: {name: sum(story["date"] == day and story["section"] == name for story in selected) for name in counts}
                             for day in payload["coverage"]}
    # Keep the unchanged candidate evidence and review choices under a new content ID.
    return seal(value)
