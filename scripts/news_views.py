"""Model-facing projections of saved news; evidence and ledgers stay unchanged."""


def report_view(row, view="stories", offset=0, limit=10):
    payload = row["payload"]
    result = {"report_id": row["report_id"], "status": row["status"],
              "collected_at": row["collected_at"],
              **{key: payload[key] for key in ("date", "timezone", "country", "counts", "notes", "curation",
                                             "scope", "since", "until", "as_of", "coverage", "failures",
                                             "candidate_batch_id", "candidates_truncated", "source_status_window") if key in payload}}
    if view == "stories":
        result["stories"] = payload["stories"]
    elif view == "candidates":
        pool = payload.get("candidates", [])
        result["candidates"] = pool[offset:offset + limit]
        result["candidates_total"] = len(pool)
        result["next_offset"] = offset + limit if offset + limit < len(pool) else None
    elif view == "full":
        result.update(payload)
    else:
        raise ValueError("unknown saved news view")
    return result
