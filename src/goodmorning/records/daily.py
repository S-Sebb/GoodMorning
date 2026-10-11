#!/usr/bin/env python3
"""Hash-checked daily amendments. Preserve run lines, completions and unrelated text."""

import argparse
from contextlib import nullcontext
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys

from goodmorning.calendar.calendar_safety import safe_text
from goodmorning.runtime_files import atomic_text, runtime_lock, secretary_path

SECTIONS = ("weather", "news", "schedule", "must-do", "nice-to-do", "feedback", "progress")
TASK_SECTIONS = ("must-do", "nice-to-do")
TASK = re.compile(r"^\s*[-*] \[([ xX])\] (.+?)(?:\r?\n)?$")
REF = re.compile(r"\s*<!-- inbox:(ib_[0-9a-f]{16}) -->$")


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def record_path(directory, date):
    if dt.date.fromisoformat(date).isoformat() != date:
        raise ValueError("invalid_date: use YYYY-MM-DD")
    path = Path(directory) / "daily" / (date + ".md")
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("unsafe_path: daily records must not be symlinks")
    return path


def read_record(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return "", "missing"
    if len(data) > 1024 * 1024:
        raise ValueError("record_too_large: inspect the daily record instead of rewriting it")
    return data.decode("utf-8"), hashlib.sha256(data).hexdigest()


def inspect(text, date):
    """Locate only real headings/tasks, not examples inside code fences."""
    lines, headings, tasks, section, fenced = text.splitlines(keepends=True), {}, [], None, False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.fullmatch(r"##[ \t]+(.+?)\s*", line)
        if heading:
            section = heading[1].casefold()
            if section in headings:
                raise ValueError("ambiguous_record: repeated daily section; reconcile it before amendments")
            headings[section] = index
            continue
        match = TASK.match(line) if section in TASK_SECTIONS else None
        if match:
            body = match[2].rstrip("\r\n")
            ref = REF.search(body)
            content = body[:ref.start()].rstrip() if ref else body
            identifier = hashlib.sha256((date + "\0" + section + "\0" + body).encode()).hexdigest()[:16]
            tasks.append({"id": identifier, "section": section, "text": content,
                          "done": match[1].lower() == "x", "ref": ref[1] if ref else None, "line": index})
    return lines, headings, tasks


def show(directory, date, offset=0, limit=7, section=None, chars=2000, *, full_titles=False):
    text, digest = read_record(record_path(directory, date))
    lines, headings, tasks = inspect(text, date)
    result = {"date": date, "sha256": digest, "sections": [key for key in headings if key in SECTIONS]}
    if set(headings) - set(SECTIONS):
        result["other_sections"] = len(set(headings) - set(SECTIONS))
    if section:
        start = headings.get(section)
        end = next((n for n in sorted(headings.values()) if start is not None and n > start), len(lines))
        body = "".join(lines[start + 1:end]) if start is not None else ""
        result.update(section=section, text=body[offset:offset + chars], total_chars=len(body),
                      next_offset=offset + chars if offset + chars < len(body) else None)
    else:
        items = []
        for task in tasks[offset:offset + limit]:
            item = {k: v for k, v in task.items() if k != "line"}
            if not full_titles and len(item["text"]) > 280:
                item.update(text_chars=len(item["text"]), text_truncated=True)
                item["text"] = item["text"][:280]
            items.append(item)
        result.update(tasks=items,
                      tasks_total=len(tasks), next_offset=offset + limit if offset + limit < len(tasks) else None)
    return result


def one_line(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or "\n" in value or "\r" in value:
        raise ValueError("invalid_input: daily items must be nonempty single-line text, at most 2000 characters")
    if safe_text(value) != value or value.lstrip().startswith(("#", "```", "~~~")):
        raise ValueError("protected_input: remove credentials, headings or fence markers from daily items")
    return value.strip()


def amend(directory, date, expected, payload, *, locked=False, dry_run=False):
    if not isinstance(payload, dict) or not payload or set(payload) - {"append", "replace", "tasks", "complete", "confirmed_completion"}:
        raise ValueError("invalid_input: unsupported daily amendment")
    if payload.get("complete") and payload.get("confirmed_completion") is not True:
        raise ValueError("confirmation_required: only user-confirmed task IDs can be completed")
    for mode in ("append", "replace", "tasks"):
        groups = payload.get(mode, {})
        if not isinstance(groups, dict) or set(groups) - set(TASK_SECTIONS if mode == "tasks" else SECTIONS[:3] + SECTIONS[5:]):
            raise ValueError("invalid_input: unsupported section or task group")
        for values in groups.values():
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("invalid_input: section items must be a list of at most 100 items")
            for value in values:
                if mode == "tasks":
                    if not isinstance(value, dict) or set(value) - {"text", "ref"} or "text" not in value:
                        raise ValueError("invalid_input: tasks need text and optional inbox ref")
                    one_line(value["text"])
                    if "ref" in value and not re.fullmatch(r"ib_[0-9a-f]{16}", value["ref"]):
                        raise ValueError("invalid_input: task ref must be a saved inbox ID")
                else:
                    one_line(value)
    complete = payload.get("complete", [])
    if not isinstance(complete, list) or not all(isinstance(item, str) for item in complete):
        raise ValueError("invalid_input: complete must list exact task IDs")
    if set(payload.get("append", {})) & set(payload.get("replace", {})):
        raise ValueError("invalid_input: choose append or replace for each section")
    path = record_path(directory, date)
    with nullcontext() if locked else runtime_lock(directory, ".state.lock"):
        original, digest = read_record(path)
        if digest != expected:
            raise ValueError("write_conflict: daily record changed; reread and reconcile")
        text = original or f"# {date}\n"
        lines, headings, tasks = inspect(text, date)
        known = {task["id"]: task for task in tasks}
        if len(known) != len(tasks) and complete:
            raise ValueError("ambiguous_record: duplicate task IDs; reconcile before marking completion")
        if set(complete) - set(known):
            raise ValueError("unknown_task: complete only IDs from the current daily page")
        for identifier in complete:
            task = known[identifier]
            if not task["done"]:
                lines[task["line"]] = lines[task["line"]].replace("[ ]", "[x]", 1)
        text = "".join(lines)
        # Exact wording/ref deduplication only; semantic task decisions stay with the agent.
        bodies = {" ".join(task["text"].split()) for task in tasks}
        refs = {task["ref"] for task in tasks if task["ref"]}
        additions = {}
        for section, values in payload.get("tasks", {}).items():
            additions[section] = []
            for value in values:
                body = one_line(value["text"])
                ref = value.get("ref")
                key = " ".join(body.split())
                if key not in bodies and (not ref or ref not in refs):
                    additions[section].append("- [ ] " + body + (f" <!-- inbox:{ref} -->" if ref else ""))
                    bodies.add(key)
                    if ref:
                        refs.add(ref)
        for section in SECTIONS:
            replacing = section in payload.get("replace", {})
            values = additions.get(section, []) if section in TASK_SECTIONS else [
                "- " + one_line(value) for value in payload.get("replace" if replacing else "append", {}).get(section, [])]
            if not values and not replacing:
                continue
            lines, headings, _ = inspect(text, date)
            start = headings.get(section)
            end = next((n for n in sorted(headings.values()) if start is not None and n > start), len(lines))
            if start is None:
                text = text.rstrip("\r\n") + f"\n\n## {section}\n" + "\n".join(values) + "\n"
            elif replacing:
                lines[start + 1:end] = [value + "\n" for value in values] + ["\n"]
                text = "".join(lines)
            else:
                present = {line.strip() for line in lines[start + 1:end]}
                fresh = [value + "\n" for value in values if value not in present]
                if fresh:
                    if end and not lines[end - 1].endswith("\n"):
                        lines[end - 1] += "\n"
                    lines[end:end] = fresh
                    text = "".join(lines)
        if read_record(path)[1] != digest:
            raise ValueError("write_conflict: daily record changed during amendment")
        changed = text != original
        if changed and not dry_run:
            atomic_text(path, text)
        return {"saved": True, "changed": changed, "date": date,
                 "sha256": hashlib.sha256(text.encode()).hexdigest()}


def planned_tasks(document):
    """Persist exactly the visible plan, without turning agent status into completion."""
    groups = {}
    for section in document['sections']:
        if section[0] not in TASK_SECTIONS:
            continue
        items = []
        for block in section[1]:
            if block[0] != 'tasks':
                continue
            for status, title, detail in block[1]:
                if status == 'done':
                    raise ValueError('planned_task_completion: new plans cannot assert completion')
                items.append({'text': one_line(title)})
        if items:
            groups.setdefault(section[0], []).extend(items)
    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secretary-dir")
    parser.add_argument("--date", required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--show", action="store_true")
    actions.add_argument("--amend", action="store_true")
    parser.add_argument("--expect")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-file")
    inputs.add_argument("--input-stdin", action="store_true")
    parser.add_argument("--section", choices=SECTIONS)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=7)
    parser.add_argument("--chars", type=int, default=2000)
    args = parser.parse_args(argv)
    try:
        if args.show and (args.expect or args.input_file or args.input_stdin):
            raise ValueError("invalid_input: reads do not accept amendment payloads")
        if args.amend and (args.section or args.offset):
            raise ValueError("invalid_input: section/offset apply only to reads")
        directory = secretary_path(args.secretary_dir)
        if not directory.is_dir():
            raise ValueError("setup_required: selected runtime does not exist")
        if args.offset < 0 or not 1 <= args.limit <= 30 or not 1 <= args.chars <= 8000:
            raise ValueError("invalid_input: invalid page size or offset")
        if args.amend:
            if not args.expect or not (args.input_file or args.input_stdin):
                raise ValueError("input_required: amendment requires --expect and a JSON payload")
            if args.input_file:
                with open(args.input_file, encoding="utf-8") as stream:
                    text = stream.read(65537)
            else:
                text = sys.stdin.read(65537)
            if len(text) > 65536:
                raise ValueError("input_too_large: split the amendment into focused changes")
            result = amend(directory, args.date, args.expect, json.loads(text))
        else:
            result = show(directory, args.date, args.offset, args.limit, args.section, args.chars)
        print(encode(result))
        return 0
    except (ValueError, OSError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else "daily_unavailable: inspect selected record/input without overwriting it"
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
