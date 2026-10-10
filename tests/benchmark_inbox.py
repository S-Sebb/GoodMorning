"""Synthetic model-visible size experiment; no personal files or providers."""

from pathlib import Path
import sys
import tempfile
import time

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from inbox_store import InboxStore, encode, initialize


def main():
    results = []
    for closed in (10, 1000, 10000):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            initialize(root)
            store = InboxStore(root, write=True)
            try:
                for n in range(3):
                    store.mutate("add", {"kind": "todo", "raw": f"Open task {n}",
                                 "context": "Confirmed constraint; no deadline."},
                                 "synthetic-benchmark", f"active-{n}", "2026-10-10T12:00:00+00:00")
                # Closed synthetic history is deliberately much larger than current state.
                historical = "Previous research result and follow-up. " * 100
                with store.transaction():
                    store.db.executemany("INSERT INTO entries (id,revision,kind,status,project,created_at,updated_at,"
                                         "raw,summary,context,questions) VALUES (?,1,'idea','confirmed','Demo',"
                                         "'2026-10-01','2026-10-01',?,'Closed item',?,'[]')",
                                         ((f"closed-{n}", historical, historical) for n in range(closed)))
                start = time.perf_counter()
                page = store.list()
                list_ms = (time.perf_counter() - start) * 1000
                capture = store.mutate("add", {"kind": "todo", "raw": "New task"},
                                       "synthetic-benchmark", "new-task", "2026-10-10T12:01:00+00:00")
                assert page["total"] == 3 and len(page["items"]) == 3
                assert not any("raw" in item or "context" in item for item in page["items"])
                results.append({"closed_entries": closed, "historical_chars": closed * len(historical),
                                "active_page_chars": len(encode(page)), "capture_receipt_chars": len(encode(capture)),
                                "list_ms": round(list_ms, 2)})
            finally:
                store.close()
    assert len({row["active_page_chars"] for row in results}) == 1
    assert len({row["capture_receipt_chars"] for row in results}) == 1
    print(encode({"synthetic": True, "measures": "output characters, not billed model tokens", "results": results}))


if __name__ == "__main__":
    main()
