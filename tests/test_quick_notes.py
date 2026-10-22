"""Quick notes are kept word for word and reach the secretary only when the user sorts them."""
from pathlib import Path
import sys
import tempfile
import time
import unittest

from support import TEMP_ROOT, HTTPFixture
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import language as ui
from goodmorning.web.quick_notes import BATCH_LIMIT, MAX_TEXT, Notes


def note(identifier, text, created=None):
    return {'id': identifier * 32, 'text': text, 'created': created or time.time() * 1000}


class QuickNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.notes = Notes(Path(self.temp.name))
        self.states = {}

    def tearDown(self):
        self.temp.cleanup()

    def listing(self):
        return self.notes.listing(lambda chat: self.states.get(chat, 'idle'))

    def test_saving_is_idempotent_and_empty_text_deletes(self):
        first = note('a', '  Ask the landlord about the boiler  ', 1_789_714_800_000)
        self.notes.save(first)
        self.notes.save(first)  # A retried upload.
        self.notes.save(note('b', 'Oat milk', 1_789_714_860_000))
        listed = self.listing()
        self.assertEqual([item['text'] for item in listed['notes']], ['Oat milk', 'Ask the landlord about the boiler'])
        self.assertEqual((listed['total'], listed['pending'], listed['notes'][1]['created']), (2, 2, 1_789_714_800_000))
        self.assertEqual(self.notes.save(note('b', '   '))['deleted'], True)
        self.assertEqual(self.listing()['total'], 1)
        self.assertEqual((Path(self.temp.name) / 'quick-notes.sqlite').stat().st_mode & 0o777, 0o600)

    def test_invalid_notes_are_refused(self):
        for body in ({'id': 'x', 'text': 'a', 'created': 1}, {**note('a', 'x'), 'extra': 1},
                     note('a', 'x' * (MAX_TEXT + 1)), {**note('a', 'x'), 'created': 'now'},
                     {**note('a', 'x'), 'created': (time.time() + 7 * 86400) * 1000}):
            with self.assertRaises(ValueError):
                self.notes.save(body)

    def test_sorting_marks_notes_and_later_edits_show_as_changed(self):
        self.notes.save(note('a', 'Call the dentist', 1_789_714_800_000))
        self.notes.save(note('b', 'Garden idea', 1_789_714_860_000))
        batch = self.notes.batch('Europe/London')
        self.assertTrue(batch['text'].startswith('Quick notes to sort\n\n'))
        self.assertIn('1. Fri 18 Sep, 08:00\nCall the dentist', batch['text'])
        self.assertIn('2. Fri 18 Sep, 08:01\nGarden idea', batch['text'])
        self.notes.mark({'chat': 'c' * 32, 'notes': batch['notes']})
        self.states['c' * 32] = 'running'
        self.assertEqual({item['state'] for item in self.listing()['notes']}, {'sorting'})
        self.states['c' * 32] = 'waiting'
        self.assertEqual(self.listing()['notes'][0]['state'], 'question')
        self.states['c' * 32] = 'idle'
        self.assertEqual((self.listing()['pending'], self.notes.batch(None)['text']), (0, None))
        self.notes.save(note('a', 'Call the dentist on Monday', 1_789_714_800_000))
        listed = self.listing()
        self.assertEqual(([item['state'] for item in listed['notes']], listed['pending']), (['sorted', 'changed'], 1))
        edited = self.notes.batch('Europe/London')
        self.assertIn('1. Fri 18 Sep, 08:00 · Edited after you sorted it\nNow: Call the dentist on Monday\nBefore: Call the dentist',
                      edited['text'])
        self.assertEqual(edited['notes'], [{'id': 'a' * 32, 'text': 'Call the dentist on Monday'}])

    def test_an_edit_during_sorting_is_still_pending(self):
        self.notes.save(note('a', 'First words'))
        batch = self.notes.batch(None)
        self.notes.save(note('a', 'Second words'))
        self.notes.mark({'chat': 'c' * 32, 'notes': batch['notes']})
        self.assertEqual(self.listing()['notes'][0]['state'], 'changed')

    def test_a_large_batch_fits_one_message_and_leaves_the_rest(self):
        for index, letter in enumerate('abcdef'):
            self.notes.save(note(letter, letter * MAX_TEXT, 1_789_714_800_000 + index))
        batch = self.notes.batch(None)
        self.assertLessEqual(len(batch['text']), 8000)
        self.assertEqual((len(batch['notes']), batch['remaining']), (2, 4))
        self.assertLess(BATCH_LIMIT, 8000)

    def test_chinese_batch(self):
        self.notes.save(note('a', '买牛奶', 1_789_714_800_000))
        token = ui.CURRENT.set('zh-CN')
        try:
            text = self.notes.batch('Asia/Shanghai')['text']
        finally:
            ui.CURRENT.reset(token)
        self.assertFalse(text.startswith('Quick notes'))
        self.assertIn('9月18日 15:00\n买牛奶', text)


class QuickNoteRouteTests(HTTPFixture):
    def test_routes_save_list_compose_and_mark(self):
        self.request('/api/notes', note('a', 'Oat milk', 1_789_714_800_000))
        listed = self.request('/api/notes')
        self.assertEqual((listed['pending'], listed['notes'][0]['state']), (1, 'unsorted'))
        batch = self.request('/api/notes/batch')
        self.assertIn('1. Fri 18 Sep, 08:00\nOat milk', batch['text'])
        self.request('/api/notes/sorted', {'chat': 'c' * 32, 'notes': batch['notes']})
        # The conversation is still waiting in the gateway's line, so the note is being sorted.
        self.assertEqual(self.request('/api/notes')['notes'][0]['state'], 'sorting')


if __name__ == '__main__':
    unittest.main()
