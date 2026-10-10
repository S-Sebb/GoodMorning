"""Render saved text into local editorial cards. Never fetch or mark a run."""
import argparse
import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

WIDTH, MAX_HEIGHT, MAX_CARDS = 1080, 5000, 12
REGULAR = "/usr/local/share/fonts/i/Inter_28pt_Regular.ttf"
BOLD = "/usr/local/share/fonts/i/Inter_28pt_SemiBold.ttf"
SERIF = "/usr/share/fonts/tex-gyre/texgyrepagella-regular.otf"
CJK = Path.home() / ".local/share/fonts/noto-cjk/NotoSansSC-Regular.ttf"
FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Renderer:
    def __init__(self, date, kind, output):
        self.date, self.kind, self.output = date, kind, output
        self.bg, self.card, self.ink, self.muted, self.accent, self.line = (
            ("#101B26", "#1A2937", "#F3EEE5", "#B7C8D5", "#DCC29A", "#344756")
            if kind == "gn" else
            ("#F5F1E8", "#FFFDFA", "#172D2B", "#546660", "#247B68", "#DCDDD3")
        )
        self.images, self.links, self.omitted = [], [], []
        self.trace, self.fonts = [], {}

    def font(self, size, face, text):
        if any(ord(c) > 0x2FFF for c in text):
            face = str(CJK)
            if not Path(face).is_file():
                raise ValueError("CJK font missing; refusing unreadable glyphs")
        elif not Path(face).is_file():
            face = FALLBACK
        key = size, face
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(face, size)
        return self.fonts[key]

    def lines(self, text, width, size=34, face=REGULAR):
        font = self.font(size, face, text)
        lines, current = [], ""
        for word in text.split(" "):
            trial = current + (" " if current else "") + word
            if self.draw.textlength(trial, font=font) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
                current = ""
            for char in word:
                if current and self.draw.textlength(current + char, font=font) > width:
                    lines.append(current)
                    current = ""
                current += char
        if current:
            lines.append(current)
        return lines

    def text(self, text, x, y, width=952, size=34, face=REGULAR, color=None):
        font = self.font(size, face, text)
        for line in self.lines(text, width, size, face):
            box = self.draw.textbbox((x, y), line, font=font, anchor="lt")
            if box[2] > WIDTH - 32 or box[3] >= MAX_HEIGHT:
                raise ValueError("Text exceeds card bounds")
            self.draw.text((x, y), line, font=font, fill=color or self.ink, anchor="lt")
            y += int(size * 1.38)
        return y

    def new_card(self, title, section):
        if len(self.images) >= MAX_CARDS:
            raise ValueError("Briefing exceeds 12 cards; split or revise layout")
        self.title, self.section = title, section
        self.image = Image.new("RGB", (WIDTH, MAX_HEIGHT), self.bg)
        self.draw = ImageDraw.Draw(self.image)
        self.draw.fontmode = "1"
        self.text("GOODNIGHT / EVENING EDITION" if self.kind == "gn" else "GOODMORNING / MORNING EDITION", 64, 42, size=23, color=self.muted)
        self.draw.line((64, 87, 1016, 87), fill=self.line, width=2)
        self.text(self.date + " / SAVED BRIEFING", 64, 116, size=25, color=self.muted)
        self.y = self.text(title, 58, 170, width=950, size=70, face=SERIF) + 42

    def ensure(self, height):
        if height > MAX_HEIGHT - 600:
            raise ValueError("One content block exceeds readable card height")
        if self.y + height + 100 > MAX_HEIGHT:
            title, section = self.title, self.section
            self.save()
            self.new_card(title + " (continued)", section)

    def clean(self, text):
        for phrase, replacement in [("Ten minutes tonight saves a rush.", ""), ("steal an hour for slide-CV", "focus on slide-CV")]:
            if phrase in text:
                text = text.replace(phrase, replacement)
                self.omitted.append(phrase)
        # Explicitly labelled estimates only. Never remove clock times/deadlines.
        text = re.sub(r"\s*\((?:estimate|estimated duration):[^)]*\)", "", text, flags=re.I)
        def citation(match):
            label, url = match.groups()
            if not url.startswith(("https://", "http://")):
                return label
            self.links.append({"id": len(self.links) + 1, "source": label, "url": url})
            return f"[{len(self.links)}] {label}"
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", citation, text)
        return text.replace("**", "").strip()

    def paragraph(self, raw, item=False):
        text = self.clean(raw)
        if not text:
            return
        title, separator, detail = text.partition(" — ") if item else (text, "", "")
        size, face = (40, BOLD) if item else (34, REGULAR)
        height = len(self.lines(title, 890, size, face)) * int(size * 1.38)
        height += len(self.lines(detail, 890)) * 46 + (86 if separator else 66)
        self.ensure(height + 24)
        if item:
            self.draw.rounded_rectangle((64, self.y, 1016, self.y + height), 26, fill=self.card)
        cursor = self.text(title, 94, self.y + 30, width=890, size=size, face=face, color=self.ink if item else self.muted)
        if detail:
            self.text(detail, 94, cursor + 16, width=890, color=self.muted)
        self.y += height + 24
        self.trace.append(raw)

    def schedule(self, cells, header):
        if len(cells) != len(header):
            raise ValueError("Malformed schedule table")
        fields = dict(zip(header, cells))
        if "Time" not in fields or "Event" not in fields:
            # Preserve unfamiliar tables as labelled content, not silent omission.
            return self.paragraph(" · ".join(f"{key}: {value}" for key, value in fields.items()), True)
        time = fields.pop("Time")
        event = fields.pop("Event")
        date = fields.pop("Date", "")
        details = [f"{key}: {value}" for key, value in fields.items()]
        right = [event, *details]
        height = max(sum(len(self.lines(t, 650, 34)) * 46 + 18 for t in right), len(self.lines(time + " " + date, 200, 27)) * 38) + 70
        self.ensure(height + 24)
        self.draw.rounded_rectangle((64, self.y, 1016, self.y + height), 26, fill=self.card)
        self.draw.line((307, self.y + 34, 307, self.y + height - 34), fill=self.line, width=3)
        self.draw.ellipse((300, self.y + 39, 314, self.y + 53), fill=self.accent)
        left = self.text(time, 88, self.y + 35, width=200, size=27, face=BOLD)
        self.text(date, 88, left + 20, width=200, size=25, color=self.muted)
        cursor = self.y + 32
        for index, value in enumerate(right):
            cursor = self.text(value, 334, cursor, width=650, size=34, face=BOLD if index == 0 else REGULAR, color=self.ink if index == 0 else self.muted) + 18
        self.y += height + 24

    def save(self):
        bottom = self.y + 100
        self.draw.line((64, self.y + 12, 1016, self.y + 12), fill=self.line, width=2)
        self.text(f"{self.date} / {len(self.images) + 1:02d} / {self.kind.upper()}", 64, self.y + 35, size=23, color=self.muted)
        image = self.image.crop((0, 0, WIDTH, bottom))
        name = f"{len(self.images) + 1:02d}-card.webp"
        path = self.output / name
        image.save(path, lossless=True, method=6)
        with Image.open(path) as decoded:
            if ImageChops.difference(image, decoded.convert("RGB")).getbbox() is not None:
                raise ValueError("Lossless image round-trip failed")
        data = path.read_bytes()
        self.images.append({"file": name, "width": WIDTH, "height": bottom, "bytes": len(data), "sha256": digest(data), "section": self.section})


def render(runtime, date, kind):
    source = runtime / "daily" / f"{date}.{kind}.md"
    if source.resolve() != source or not source.is_file() or source.stat().st_size > 150_000:
        raise ValueError("Saved source missing, symlinked or too large")
    data = source.read_bytes()
    source_hash = digest(data)
    parent = runtime / "visual" / f"{date}.{kind}"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = parent / source_hash[:16]
    if destination.exists():
        return {"cached": True, "directory": str(destination)}
    text = data.decode("utf-8")
    sections = re.split(r"^## (.+)\n", text, flags=re.M)
    if len(sections) < 3:
        raise ValueError("Briefing needs section headings")
    with tempfile.TemporaryDirectory(prefix=".render-", dir=parent) as temporary:
        output = Path(temporary)
        # Preserve complete text before creating images.
        (output / "source.md").write_bytes(data)
        r = Renderer(date, kind, output)
        pairs = list(zip(sections[1::2], sections[2::2]))
        # Priorities and fixed commitments before news. Preserve all section text.
        if kind == "gm":
            pairs.sort(key=lambda pair: pair[0].startswith("News"))
        for section, body in pairs:
            groups = re.split(r"^### (.+)\n", body, flags=re.M) if section.startswith("News") else [body]
            work = [(section, groups[0])] + list(zip(groups[1::2], groups[2::2]))
            for title, content in work:
                meaningful = [line for line in content.splitlines() if line.strip() and line.strip() != "---"]
                if not meaningful:
                    continue
                r.new_card(title, section)
                table_header = None
                for line in meaningful:
                    if line.startswith("### "):
                        r.ensure(80)
                        r.y = r.text(line[4:], 64, r.y, size=26, face=BOLD, color=r.accent) + 24
                    elif line.startswith("|"):
                        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                            continue
                        if table_header is None:
                            table_header = cells
                        else:
                            r.schedule(cells, table_header)
                    else:
                        table_header = None
                        item = line.startswith(("- ", "* "))
                        raw = re.sub(r"^[-*] (?:\[[ xX]\] )?", "", line)
                        r.paragraph(raw, item)
                r.save()
        (output / "sources.md").write_text("# Clickable sources\n\n" + "\n".join(f"{item['id']}. [{item['source']}]({item['url']})" for item in r.links) + "\n")
        cards = "".join(f'<section><h2>{html.escape(image["section"])}</h2><img alt="{html.escape(image["section"])}" src="{image["file"]}"></section>' for image in r.images)
        (output / "briefing.html").write_text(f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{date} {kind}</title><style>body{{background:{r.bg};color:{r.ink};font-family:system-ui;max-width:1080px;margin:auto;padding:16px}}img{{width:100%;height:auto;border-radius:16px}}</style>{cards}<p><a href="source.md">Complete saved text and citations</a></p>')
        manifest = {"date": date, "kind": kind, "source_sha256": source_hash, "lossless": True, "images": r.images, "omitted_estimate_wording": r.omitted, "renderer": 1}
        (output / "manifest.json").write_text(json.dumps(manifest) + "\n")
        if source.read_bytes() != data:
            raise ValueError("Saved briefing changed while rendering")
        try:
            os.rename(output, destination)
        except FileExistsError:
            pass  # A concurrent identical render won; validation follows in JS.
    return {"cards": len(r.images), "directory": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--kind", choices=["gm", "gn"], required=True)
    args = parser.parse_args()
    from datetime import date as Date
    if Date.fromisoformat(args.date).isoformat() != args.date:
        raise ValueError("Invalid date")
    print(json.dumps(render(args.runtime.resolve(), args.date, args.kind)))
