"""Model-facing projections of collected news."""

SECTIONS = ("ai", "major", "national")
MORE_PER_SECTION = 6


def compact(story):
    ranking = story.get("ranking", {})
    item = {"title": story["title"], "links": [{"source": link["source"], "url": link["url"]} for link in story["links"]],
            "outlets": story.get("outlets", 1), "score": ranking.get("score"), "eligible": ranking.get("eligible")}
    if story.get("summary"):
        item["summary"] = story["summary"]
    if ranking.get("genre", "news") != "news":
        item["genre"] = ranking["genre"]
    if all(link.get("role") == "primary" for link in story["links"]):
        item["first_party"] = True
    return item


def by_section(payload):
    """Every section at once: provisional picks first, then the strongest other
    candidates. A flat candidate page lists one section before the next, so its
    first page can hide world and national news entirely."""
    result = {}
    for section in SECTIONS:
        picks = [story for story in payload["stories"] if story["section"] == section]
        chosen = {story["links"][0]["url"] for story in picks}
        pool = [story for story in payload.get("candidates", []) if story["section"] == section]
        others = [story for story in pool if story["links"][0]["url"] not in chosen]
        result[section] = {"selected": [compact(story) for story in picks],
                           "more": [compact(story) for story in others[:MORE_PER_SECTION]],
                           "candidates_total": len(pool)}
    return result


def report_view(payload, view="stories", offset=0, limit=10):
    result = {key: payload[key] for key in ("timezone", "country", "scope", "since", "until", "as_of",
                                             "coverage", "failures", "candidates_truncated") if key in payload}
    if view == "stories":
        result["stories"] = payload["stories"]
    elif view == "candidates":
        pool = payload.get("candidates", [])
        result["candidates"] = pool[offset:offset + limit]
        result["candidates_total"] = len(pool)
        result["next_offset"] = offset + limit if offset + limit < len(pool) else None
    elif view == "sections":
        result["sections"] = by_section(payload)
    else:
        raise ValueError("unknown news view")
    return result
