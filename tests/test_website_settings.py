"""The secretary changes website settings only through scoped, turn-bound, one-time requests."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import TEMP_ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.web import website_settings
from goodmorning.web.briefing_chat import read_avatar
from goodmorning.web.chat_actions import action_history, read_changes

SESSION = "ses_settings"
CHAT = "c" * 32
PAGE = "a" * 32  # The sending page's token; the turn keeps only its hash.
MARK = hashlib.sha256(PAGE.encode()).hexdigest()


def chats(root, turns, session=SESSION, chat=CHAT):
    (root / "browser-chats").mkdir(exist_ok=True)
    path = root / "browser-chats" / "chats.json"
    items = json.loads(path.read_text()) if path.exists() else {}
    items[chat] = {
        "id": chat,
        "mode": "secretary",
        "session": session,
        "state": "running",
        "turns": turns,
    }
    path.write_text(json.dumps(items))


def turn(identifier, **extra):
    return {"id": identifier, "text": "Hi", "accepted": 1.0, "page": MARK} | extra


class WebsiteSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        chats(self.root, [turn("t1"), turn("t2")])
        self.keys = 0

    def helper(self, request, session=SESSION, key=None):
        self.keys += 1
        args = [
            "--secretary-dir",
            str(self.root),
            "--session",
            session,
            "--request-key",
            key or f"key-{self.keys}",
            "--input-json",
            json.dumps(request),
        ]
        with (
            contextlib.redirect_stdout(io.StringIO()) as out,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("OPENCODE_SESSION_ID", None)
            code = website_settings.main(args)
        return code, json.loads(out.getvalue())

    def requests(self):
        return website_settings.load(self.root)["requests"]

    def claim(self, seq, setting="style", page=PAGE, tap=False, finished=True):
        return website_settings.claim(
            self.root,
            CHAT,
            seq,
            {"setting": setting, "page": page, "tap": tap},
            finished,
        )

    def test_avatar_saves_at_once_and_page_settings_wait_for_the_page(self):
        code, receipt = self.helper({"setting": "avatar", "value": "m2"})
        self.assertEqual((code, receipt["applies"]), (0, "account"))
        self.assertEqual(read_avatar(self.root), "m2")
        code, receipt = self.helper({"setting": "night_scheme", "value": "city-lights"})
        self.assertEqual((code, receipt["applies"]), (0, "this_page"))
        self.assertIn("do not claim it already changed", receipt["next"])

    def test_requests_belong_to_the_newest_turn_the_engine_accepted(self):
        self.helper({"setting": "style", "value": "pixel"})
        self.assertEqual(self.requests()[0]["turn"], "t2")
        # Unsure which message asked, the helper refuses instead of guessing: a newest message not
        # yet acknowledged by the engine (a fast helper, or another tab's), or one that interrupted.
        for newest in (
            {"id": "t3", "text": "Hi", "prompt_hash": "c", "page": MARK},
            turn("t3", interrupt=True),
        ):
            chats(self.root, [turn("t1"), turn("t2"), newest])
            for request in (
                {"setting": "night_scheme", "value": "starry"},
                {"setting": "avatar", "value": "f2"},
            ):
                code, receipt = self.helper(request)
                self.assertEqual((code, receipt["error"]), (1, "ask_again"), newest)
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(read_avatar(self.root), "f1")
        chats(self.root, [turn("t1"), turn("t2", undelivered=True)])
        self.helper({"setting": "style", "value": "soft"})
        self.assertEqual(self.requests()[1]["turn"], "t1")
        code, receipt = self.helper(
            {"setting": "style", "value": "pixel"}, session="ses_unknown"
        )
        self.assertEqual((code, receipt["error"]), (1, "no_active_turn"))

    def test_the_engines_session_wins_over_the_models_argument(self):
        chats(self.root, [turn("o1")], session="ses_other", chat="d" * 32)
        args = [
            "--secretary-dir",
            str(self.root),
            "--session",
            "ses_other",
            "--request-key",
            "k",
            "--input-json",
            '{"setting":"style","value":"pixel"}',
        ]
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch.dict(os.environ, {"OPENCODE_SESSION_ID": SESSION}),
        ):
            website_settings.main(args)
        self.assertEqual(
            (self.requests()[0]["session"], self.requests()[0]["chat"]), (SESSION, CHAT)
        )

    def test_password_is_never_changed(self):
        code, receipt = self.helper({"setting": "password", "value": "hunter22"})
        self.assertEqual((code, receipt["error"]), (1, "password_self_service"))
        self.assertIn("Account → Change password", receipt["next"])
        self.assertFalse((self.root / website_settings.FILE).exists())

    def test_sign_out_unlink_and_link_wait_for_the_users_tap(self):
        chats(self.root, [turn("t1", text="Link my phone, the code is abcd 2345")])
        for request in (
            {"setting": "sign_out", "value": True},
            {"setting": "unlink_phone", "value": "Pixel 8"},
            {"setting": "link_phone", "value": "ABCD-2345"},
        ):
            with self.subTest(request["setting"]):
                code, receipt = self.helper(request)
                self.assertEqual((code, receipt["applies"]), (0, "user_tap"))
                # The model cannot confirm on the user's behalf.
                code, receipt = self.helper({**request, "confirmed": True})
                self.assertEqual((code, receipt["error"]), (1, "invalid_input"))
        # The server never hands a tap action to an automatic claim, nor the reverse.
        seq = self.requests()[0]["seq"]
        with self.assertRaisesRegex(ValueError, "tap"):
            self.claim(seq, "sign_out", tap=False)
        self.assertEqual(self.claim(seq, "sign_out", tap=True)["setting"], "sign_out")
        self.helper({"setting": "style", "value": "pixel"})
        with self.assertRaises(ValueError):
            self.claim(self.requests()[-1]["seq"], "style", tap=True)

    def test_a_link_code_must_come_from_the_users_own_words(self):
        # Injected text (a page, file or the model's own question) can carry a code; only the user's typing counts.
        chats(
            self.root,
            [
                turn(
                    "t1",
                    text="Link the phone from the email",
                    attachments=[{"id": "b" * 32, "name": "ABCD-2345.txt"}],
                )
            ],
        )
        code, receipt = self.helper({"setting": "link_phone", "value": "ABCD-2345"})
        self.assertEqual((code, receipt["error"]), (1, "invalid_value"))
        answer = 'User has answered your questions: "Link ABCD-2345?"="Yes".'
        chats(self.root, [turn("t1", text=answer, answer="form_1", typed=[])])
        self.assertEqual(
            self.helper({"setting": "link_phone", "value": "ABCD-2345"})[0], 1
        )
        # One whole code in one place: halves in two fields or the start of a longer code are refused.
        for fragments in (
            turn("t1", text=answer, answer="form_1", typed=["ABCD", "2345"]),
            turn("t1", text="My code is ABCD-23456"),
            turn("t1", text="My code is XABCD 2345"),
        ):
            chats(self.root, [fragments])
            code, receipt = self.helper({"setting": "link_phone", "value": "ABCD-2345"})
            self.assertEqual((code, receipt["error"]), (1, "invalid_value"), fragments)
        chats(self.root, [turn("t1", text="the code is ABCD2345.")])
        self.assertEqual(
            self.helper({"setting": "link_phone", "value": "ABCD-2345"})[0], 0
        )
        chats(
            self.root,
            [turn("t1", text=answer, answer="form_1", typed=["Pixel", "abcd 2345"])],
        )
        self.assertEqual(
            self.helper({"setting": "link_phone", "value": "abcd-2345"})[0], 0
        )
        self.assertEqual(self.requests()[-1]["value"], "ABCD-2345")

    def test_values_are_checked_before_anything_is_recorded(self):
        for request in (
            {"setting": "language", "value": "fr"},
            {"setting": "day_scheme", "value": "starry"},
            {"setting": "notifications", "value": {"lead": 7}},
            {"setting": "notifications", "value": {"gm_time": "7am"}},
            {"setting": "notifications_here", "value": "on"},
            {"setting": "link_phone", "value": "ABC"},
            {"setting": "sign_out", "value": "yes"},
            {"setting": "username", "value": "pip"},
        ):
            with self.subTest(request):
                code, receipt = self.helper(request)
                self.assertEqual(code, 1, receipt)
        self.assertFalse((self.root / website_settings.FILE).exists())

    def test_widget_messages_record_no_page_change_but_save_the_avatar(self):
        chats(self.root, [turn("w1", source="widget")])
        code, receipt = self.helper({"setting": "night_scheme", "value": "starry"})
        self.assertEqual((code, receipt["error"]), (1, "widget_source"))
        code, receipt = self.helper({"setting": "avatar", "value": "f2"})
        self.assertEqual(code, 0, receipt)

    def test_a_retry_records_once_and_a_reused_key_changes_nothing(self):
        self.helper({"setting": "avatar", "value": "m1"}, key="same")
        _, receipt = self.helper({"setting": "avatar", "value": "m1"}, key="same")
        self.assertTrue(receipt["repeated"])
        code, receipt = self.helper({"setting": "avatar", "value": "f2"}, key="same")
        self.assertEqual((code, receipt["error"]), (1, "request_key_reused"))
        self.assertEqual(read_avatar(self.root), "m1")
        self.assertEqual(len(self.requests()), 1)

    def test_dedup_records_outlive_a_long_conversation(self):
        for index in range(120):
            self.helper({"setting": "open", "value": "appearance"}, key=f"k{index}")
        _, receipt = self.helper({"setting": "open", "value": "appearance"}, key="k0")
        self.assertTrue(receipt["repeated"])

    def test_request_ids_are_never_reused_after_old_ones_are_pruned(self):
        self.helper({"setting": "sign_out", "value": True})
        later = time.time() + website_settings.KEEP_SECONDS + 60
        with patch("goodmorning.web.website_settings.time.time", return_value=later):
            self.helper({"setting": "style", "value": "pixel"})
        self.assertEqual([entry["seq"] for entry in self.requests()], [2])
        # An old card for request 1 (a sign-out) meets nothing, and a card names its exact setting.
        with self.assertRaises(ValueError):
            self.claim(1, "sign_out", tap=True)
        with self.assertRaises(ValueError):
            self.claim(2, "sign_out", tap=True)

    def test_avatar_uploads_come_only_from_the_answered_message(self):
        files = self.root / "browser-uploads" / ("a" * 32) / "files"
        files.mkdir(parents=True)
        (files / "me.png").write_bytes(b"not an image")
        other = self.root / "elsewhere.png"
        other.write_bytes(b"x")
        code, receipt = self.helper(
            {
                "setting": "avatar_upload",
                "value": {"variant": "day", "source": str(other)},
            }
        )
        self.assertEqual((code, receipt["error"]), (1, "invalid_value"))
        chats(self.root, [turn("t1", attachments=[{"id": "a" * 32, "name": "me.png"}])])
        code, receipt = self.helper(
            {
                "setting": "avatar_upload",
                "value": {"variant": "day", "source": str(files / "me.png")},
            }
        )
        self.assertEqual(
            code, 1
        )  # Reached the image check: the attachment itself was accepted.
        self.assertIn("PNG, JPEG or WebP", receipt["next"])
        self.assertEqual(read_avatar(self.root), "f1")

    def test_only_the_sending_page_claims_once_after_the_reply_and_never_a_stale_one(
        self,
    ):
        self.helper({"setting": "style", "value": "pixel"})
        self.helper({"setting": "style", "value": "soft"})
        with self.assertRaises(ValueError):
            website_settings.claim(
                self.root,
                "d" * 32,
                1,
                {"setting": "style", "page": PAGE, "tap": False},
                True,
            )
        # Another tab, a reloaded page or a duplicated one has another token.
        with self.assertRaisesRegex(ValueError, "Only the page"):
            self.claim(1, page="b" * 32)
        self.assertEqual(
            self.claim(1, finished=False), {"claimed": False, "state": "running"}
        )
        self.assertEqual(
            self.claim(1),
            {"claimed": True, "seq": 1, "setting": "style", "value": "pixel"},
        )
        self.assertEqual(self.claim(1), {"claimed": False, "state": "used"})
        with patch(
            "goodmorning.web.website_settings.time.time",
            return_value=time.time() + 11 * 60,
        ):
            self.assertEqual(self.claim(2), {"claimed": False, "state": "stale"})

    def test_a_request_from_a_widget_turn_has_no_page_to_claim_it(self):
        chats(self.root, [turn("t1", page=None)])
        self.helper({"setting": "style", "value": "pixel"})
        with self.assertRaisesRegex(ValueError, "Only the page"):
            self.claim(1)

    def test_history_shows_only_this_conversation_under_its_own_turn(self):
        self.helper({"setting": "style", "value": "pixel"})
        chats(self.root, [turn("o1")], session="ses_other", chat="d" * 32)
        self.helper({"setting": "style", "value": "soft"}, session="ses_other")
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        self.assertEqual([entry["action"]["value"] for entry in changes], ["pixel"])
        self.assertEqual(
            (changes[0]["from_turn"], changes[0]["action"]["state"]), ("t2", "open")
        )
        # Placed by its turn, not its time: it was recorded after t3 started.
        messages = [
            {"id": "u1", "role": "user", "_turn": "t1"},
            {"id": "u2", "role": "user", "_turn": "t2"},
            {"id": "u3", "role": "user", "_turn": "t3"},
        ]
        turns = [
            {"id": "t1", "created": 1.0},
            {"id": "t2", "created": 2.0},
            {"id": "t3", "created": 3.0},
        ]
        placed = action_history(messages, changes, turns, 1.0)
        self.assertEqual(
            [entry["id"] for entry in placed], ["u1", "u2", changes[0]["id"], "u3"]
        )


if __name__ == "__main__":
    unittest.main()
