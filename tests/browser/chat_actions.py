"""Synthetic change cards, question forms, palette contrast and one-shot motion."""

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from chat_markdown import contrast
from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
from support import TEMP_ROOT


def action(identifier, operation, target, text):
    return {
        "id": identifier,
        "role": "assistant",
        "kind": "action",
        "text": text,
        "action": {"operation": operation, "target": target},
    }


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks = []
    with tempfile.TemporaryDirectory(
        dir=TEMP_ROOT, prefix="gm-chat-actions-"
    ) as directory:
        process = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "tests/test_briefing_chat.py"),
                "--serve-fixture",
                directory,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        address = (
            process.stdout.readline().strip().removeprefix("Private live viewer: ")
        )
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                for width in (1440, 390, 320):
                    page = browser.new_page(
                        viewport={"width": width, "height": 1100},
                        reduced_motion="reduce",
                    )
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.clock.set_system_time(
                        datetime.fromisoformat("2026-10-13T10:00:00+00:00")
                    )
                    status = {
                        "mode": "secretary",
                        "state": "idle",
                        "label": "Ready for your reply",
                        "language": "en",
                        "forms": [],
                        "permissions": [],
                        "messages": [
                            {
                                "id": "reply",
                                "role": "assistant",
                                "text": "A little room for your plans.",
                            },
                            {
                                "id": "question",
                                "role": "assistant",
                                "kind": "question",
                                "text": "Which afternoon works for you?",
                            },
                            {
                                "id": "answer",
                                "role": "user",
                                "kind": "answer",
                                "text": "Thursday, after lunch.",
                            },
                            {
                                "id": "expired",
                                "role": "assistant",
                                "kind": "expired",
                                "text": "Should I remind you every evening?",
                            },
                            {
                                "id": "skipped",
                                "role": "assistant",
                                "kind": "skipped",
                                "text": "Which room should I book?",
                            },
                            action(
                                "add",
                                "added",
                                "event",
                                "Tea with Sam · Thursday, 14:00",
                            ),
                            action(
                                "edit", "updated", "task", "Prepare the final slides"
                            ),
                            action("cancel", "cancelled", "event", "Friday check-in"),
                            action(
                                "done", "completed", "task", "Pick up the library books"
                            ),
                            action("approve", "approved", "event", "Team lunch"),
                            action(
                                "decline", "declined", "event", "Duplicate invitation"
                            ),
                            action(
                                "idea", "added", "idea", "A tiny garden on the balcony"
                            ),
                            action(
                                "draft",
                                "added",
                                "draft",
                                "Weekend walk · time to confirm",
                            ),
                            action(
                                "unsafe",
                                "updated",
                                "record",
                                '<img src=x onerror="window.executed=true">',
                            ),
                            action("memory", "updated", "memory", ""),
                        ],
                    }
                    page.route(
                        "**/api/chats/*", lambda route: route.fulfill(json=status)
                    )
                    page.goto(address + "/chat?id=" + "f" * 32)
                    expect(page.locator('[data-special="action"]')).to_have_count(10)
                    expect(page.locator(".chat-special-icon svg")).to_have_count(14)
                    # The memory marker only links to the note on About me.
                    expect(
                        page.get_by_role(
                            "link", name="Jotted down a little note about you"
                        )
                    ).to_have_attribute("href", "/about-me#about-memory")
                    expect(
                        page.locator('[data-special="skipped"] .chat-special-label')
                    ).to_have_text("Question skipped")
                    expect(
                        page.locator('[data-message="unsafe"] .message-text img')
                    ).to_have_count(0)
                    assert page.evaluate("window.executed !== true")
                    assert page.locator(".message-enter").count() == 0
                    for edition, scheme in (
                        ("gm", "classic"),
                        ("gm", "warm"),
                        ("gn", "classic"),
                        ("gn", "starry"),
                        ("gn", "city-lights"),
                        ("gn", "midnight-violet"),
                    ):
                        for language in ("en", "zh-CN"):
                            page.evaluate(
                                """([edition, scheme, language]) => {
                                document.documentElement.dataset.edition = edition;
                                document.documentElement.dataset[edition === 'gm' ? 'dayScheme' : 'nightScheme'] = scheme;
                                applyWebsiteLanguage(language);
                            }""",
                                [edition, scheme, language],
                            )
                            expect(
                                page.locator('[data-message="add"] .chat-special-label')
                            ).to_have_text(
                                "Event added" if language == "en" else "已添加事项"
                            )
                            expect(
                                page.locator(
                                    '[data-message="memory"] .chat-special-label'
                                )
                            ).to_have_text(
                                "Jotted down a little note about you"
                                if language == "en"
                                else "记下了一条关于你的小笔记"
                            )
                            ratios = page.locator(
                                "#chat-messages [data-special]"
                            ).evaluate_all("""nodes => nodes.flatMap(node => {
                                const background = getComputedStyle(node).backgroundColor;
                                return ['.message-text', '.chat-special-label'].map(selector => ({
                                    foreground: getComputedStyle(node.querySelector(selector)).color, background,
                                    selector, id: node.dataset.message}));
                            })""")
                            minimum = min(
                                contrast(entry["foreground"], entry["background"])
                                for entry in ratios
                            )
                            assert minimum >= 4.5, (
                                edition,
                                scheme,
                                width,
                                language,
                                minimum,
                                min(
                                    ratios,
                                    key=lambda entry: contrast(
                                        entry["foreground"], entry["background"]
                                    ),
                                ),
                            )
                            assert not page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth"
                            )
                            assert page.locator(
                                "#chat-messages [data-special]"
                            ).evaluate_all("""nodes => nodes.every(node =>
                                node.scrollWidth <= node.clientWidth + 1)""")
                            checks.append(
                                {
                                    "width": width,
                                    "edition": edition,
                                    "scheme": scheme,
                                    "language": language,
                                    "minimumTextContrast": round(minimum, 2),
                                }
                            )
                        if width in (1440, 390):
                            page.evaluate(
                                "applyWebsiteLanguage('en'); document.querySelector('#chat-scroll').scrollTop = 0"
                            )
                            page.screenshot(
                                path=str(
                                    artifacts
                                    / f"actions-{edition}-{scheme}-{width}.png"
                                ),
                                full_page=True,
                            )
                    # Keep typed answers when an unrelated permission arrives. Both get a clear badge.
                    status["forms"] = [
                        {
                            "id": "when",
                            "title": "Make a little space",
                            "fields": [
                                {
                                    "key": "day",
                                    "title": "What day suits you?",
                                    "type": "string",
                                    "required": True,
                                }
                            ],
                        }
                    ]
                    status["state"] = "waiting"
                    page.evaluate("pollChat()")
                    answer = page.get_by_role("textbox", name="What day suits you?")
                    expect(answer).to_be_visible()
                    answer.fill("Thursday afternoon")
                    status["permissions"] = [
                        {
                            "id": "permission",
                            "action": "Save the confirmed event",
                            "resources": ["Synthetic event only"],
                        }
                    ]
                    page.evaluate("pollChat()")
                    expect(page.locator('[data-special="permission"]')).to_be_visible()
                    expect(answer).to_have_value("Thursday afternoon")
                    expect(page.locator(".message-enter")).to_have_count(0)
                    # Choices stay compact: descriptions align under their label, short choices share a row when there is room.
                    status["permissions"] = []
                    status["forms"] = [
                        {
                            "id": "choose",
                            "title": "Pick",
                            "fields": [
                                {
                                    "key": "tone",
                                    "title": "Tone",
                                    "type": "string",
                                    "options": [
                                        {
                                            "value": "warm",
                                            "label": "Warm",
                                            "description": "Friendly and clear.",
                                        },
                                        {
                                            "value": "formal",
                                            "label": "Formal",
                                            "description": "Polite and brief.",
                                        },
                                    ],
                                },
                                {
                                    "key": "parts",
                                    "title": "Parts",
                                    "type": "multiselect",
                                    "options": [
                                        {"value": "a", "label": "News"},
                                        {"value": "b", "label": "Weather"},
                                    ],
                                },
                            ],
                        }
                    ]
                    page.evaluate("pollChat()")
                    expect(page.get_by_role("checkbox", name="Weather")).to_be_visible()
                    layout = page.evaluate("""() => {
                        const box = selector => document.querySelector(selector).getBoundingClientRect();
                        const label = '#chat-questions .answer-option:has(small)';
                        const short = [...document.querySelectorAll('#chat-questions .answer-option:not(:has(small))')];
                        const note = document.querySelector(label + ' small');
                        return {indent: box(label + ' small').left + parseFloat(getComputedStyle(note).paddingLeft) - box(label + ' span').left,
                                sameRow: short[0].getBoundingClientRect().top === short[1].getBoundingClientRect().top,
                                optionHeight: box(label).height};
                    }""")
                    assert abs(layout["indent"]) <= 1 and layout["optionHeight"] < 56, (
                        width,
                        layout,
                    )
                    assert layout["sameRow"] or width < 390, (width, layout)
                    assert not errors, errors
                    page.close()

                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                status = {
                    "mode": "secretary",
                    "state": "idle",
                    "label": "Ready for your reply",
                    "language": "en",
                    "forms": [],
                    "permissions": [],
                    "messages": [],
                }
                page.route("**/api/chats/*", lambda route: route.fulfill(json=status))
                page.goto(address + "/chat?id=" + "e" * 32)
                expect(page.locator("#chat-status")).to_contain_text(
                    "Ready for your reply"
                )
                status["messages"].append(
                    action("new", "added", "task", "Prepare slides")
                )
                page.evaluate("pollChat()")
                card = page.locator('[data-message="new"]')
                expect(card).to_have_class(re.compile("message-enter"))
                assert card.evaluate(
                    "node => node.getAnimations({subtree:true}).every(animation => animation.effect.getTiming().iterations === 1)"
                )
                expect(card).not_to_have_class(re.compile("message-enter"))
                page.evaluate("pollChat()")
                expect(card).not_to_have_class(re.compile("message-enter"))
                # Reload and reduced motion must never replay the entrance.
                page.reload()
                expect(card).to_be_visible()
                expect(card).not_to_have_class(re.compile("message-enter"))
                status["state"] = "waiting"
                status["forms"] = [
                    {
                        "id": "new-question",
                        "title": "A quick check",
                        "fields": [
                            {"key": "day", "title": "Which day?", "type": "string"}
                        ],
                    }
                ]
                page.evaluate("pollChat()")
                question = page.locator('#chat-questions [data-special="question"]')
                expect(question).to_have_class(re.compile("message-enter"))
                expect(question).not_to_have_class(re.compile("message-enter"))
                page.evaluate("pollChat()")
                expect(question).not_to_have_class(re.compile("message-enter"))
                page.emulate_media(reduced_motion="reduce")
                status["messages"].append(
                    action("reduced", "updated", "event", "Tea at 15:00")
                )
                page.evaluate("pollChat()")
                expect(page.locator('[data-message="reduced"]')).to_be_visible()
                expect(page.locator(".message-enter")).to_have_count(0)
                # UI labels change locally even if the transcript connection fails.
                page.route("**/api/chats/*", lambda route: route.abort())
                page.evaluate("applyWebsiteLanguage('zh-CN')")
                expect(card.locator(".chat-special-label")).to_have_text("已添加待办")
                expect(question.locator(".chat-special-label")).to_have_text("想问问你")
                # Settings the secretary prepared apply on the page that sent (or answered) their turn,
                # in order, once the reply ends; other turns' requests and script clicks change nothing.
                page = browser.new_page(viewport={"width": 1000, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def setting(seq, turn, name, value):
                    return {
                        "id": f"action:setting:{seq}",
                        "role": "assistant",
                        "kind": "action",
                        "text": "",
                        "from_turn": turn,
                        "action": {
                            "operation": "requested",
                            "target": "setting",
                            "setting": name,
                            "value": value,
                            "seq": seq,
                            "state": "open",
                        },
                    }

                status = {
                    "mode": "secretary",
                    "state": "waiting",
                    "label": "Ready for your reply",
                    "language": "en",
                    "forms": [
                        {
                            "id": "pick",
                            "title": "Which colors?",
                            "fields": [
                                {
                                    "key": "colors",
                                    "title": "Night colors",
                                    "type": "string",
                                }
                            ],
                        }
                    ],
                    "permissions": [],
                    "messages": [],
                }
                claims, token = [], {}

                def claim(route):
                    seq = int(route.request.url.split("/settings/")[1].split("/")[0])
                    claims.append(seq)
                    entry = next(
                        item["action"]
                        for item in status["messages"]
                        if item["action"]["seq"] == seq
                    )
                    sent = json.loads(route.request.post_data)
                    # Each claim names its exact request and carries this page's token.
                    assert sent == {
                        "setting": entry["setting"],
                        "page": token["page"],
                        "tap": entry["setting"] == "sign_out",
                    }, sent
                    # Request 5's claim answers with another action, which the page refuses.
                    granted = (
                        {"setting": "sign_out", "value": True}
                        if seq == 5
                        else {"setting": entry["setting"], "value": entry["value"]}
                    )
                    route.fulfill(json={"claimed": True, "seq": seq} | granted)

                page.route("**/api/chats/*", lambda route: route.fulfill(json=status))
                page.route("**/settings/*/claim", claim)
                answers = []

                def answered(route):
                    answers.append(json.loads(route.request.post_data))
                    route.fulfill(
                        json={"answered": True, "turn": "answer-turn", "owner": True}
                    )

                page.route("**/form/pick/reply", answered)
                page.goto(address + "/chat?id=" + "d" * 32)
                token["page"] = page.evaluate("goodmorningSettings.page")
                question = page.locator("#chat-questions .agent-form")
                expect(question).to_be_visible()
                question.locator("input, textarea").first.fill("City Lights")
                question.locator("button[type=submit]").click()
                status.update(
                    state="running",
                    forms=[],
                    messages=[
                        setting(1, "answer-turn", "night_scheme", "city-lights"),
                        setting(2, "answer-turn", "style", "pixel"),
                        setting(3, "elsewhere", "day_scheme", "warm"),
                        setting(4, "answer-turn", "sign_out", True),
                        setting(5, "answer-turn", "day_scheme", "picnic"),
                        setting(6, "elsewhere", "sign_out", True),
                    ],
                )
                # The answer carries this page's token, so the server binds its turn to this page.
                assert answers[0]["page"] == token["page"], answers
                page.evaluate("pollChat()")
                page.wait_for_timeout(500)
                assert claims == [], claims
                # Paused on a question or permission is not finished: still nothing runs.
                status["state"] = "waiting"
                page.evaluate("pollChat()")
                page.wait_for_timeout(500)
                assert claims == [], claims
                card = lambda seq: page.locator(
                    f'[data-message="action:setting:{seq}"] .chat-setting'
                )
                # No tap button before the reply ends, and never for another page's request.
                expect(card(4).locator(".chat-setting-confirm")).to_be_hidden()
                status["state"] = "idle"
                page.evaluate("pollChat()")
                for seq in (1, 2):
                    expect(card(seq).locator(".chat-setting-result")).to_have_text(
                        "Done on this device."
                    )
                assert page.evaluate(
                    "[document.documentElement.dataset.nightScheme, document.documentElement.dataset.style]"
                ) == ["city-lights", "pixel"]
                expect(card(3).locator(".chat-setting-result")).to_have_text(
                    "Not changed. Ask again here, or use the pop-up."
                )
                assert (
                    page.evaluate("document.documentElement.dataset.dayScheme")
                    != "warm"
                )
                expect(card(1).locator(".chat-setting-title")).to_have_text(
                    "Night color scheme → City Lights"
                )
                expect(card(5).locator(".chat-setting-result")).to_have_text(
                    "Couldn’t change it: Not changed. Ask again here, or use the pop-up."
                )
                assert (
                    page.evaluate("document.documentElement.dataset.dayScheme")
                    != "picnic"
                )
                expect(card(6).locator(".chat-setting-confirm")).to_be_hidden()
                expect(card(6).locator(".chat-setting-result")).to_have_text(
                    "Not changed. Ask again here, or use the pop-up."
                )
                card(4).locator(".chat-setting-confirm").evaluate(
                    "button => button.click()"
                )
                page.wait_for_timeout(300)
                assert claims == [1, 2, 5], claims
                # The local viewer has no sign-out; a real tap says so instead of pretending.
                card(4).locator(".chat-setting-confirm").click()
                expect(card(4).locator(".chat-setting-result")).to_have_text(
                    "Couldn’t change it: This setting isn’t available on this page."
                )
                # A reload shows the outcomes without applying anything again.
                page.reload()
                expect(card(1).locator(".chat-setting-result")).to_have_text(
                    "Done on this device."
                )
                page.wait_for_timeout(500)
                assert claims == [1, 2, 5, 4], claims
                # A reloaded page is another page: it shows outcomes but owns nothing new.
                expect(card(4).locator(".chat-setting-confirm")).to_be_hidden()
                assert not errors, errors
                checks.append("settings applied once, only by the sending page")
                browser.close()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {
        "modelCalls": 0,
        "paletteChecks": checks,
        "motion": "once, never on reload or reduced motion",
        "privateToolOutput": "not requested",
        "pendingDraftPreserved": True,
    }
    (artifacts / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
