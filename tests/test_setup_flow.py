"""Code-led website setup with synthetic runtimes: consent, steps, quotes, saves and receipts. No model."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning import setup_flow
from goodmorning.runtime_files import profile_fields, set_profile_fields

CHAT, SESSION = 'a' * 32, 'ses_setup'
READY = {'city': 'Edinburgh, UK', 'region': 'global', 'timezone': 'Europe/London', 'news_country': 'GB',
         'secretary_name': 'Pip', 'holiday_countries': 'GB-SCT'}


class SetupFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'browser-chats').mkdir()
        self.said('Call yourself Pip. I am Sam, born 03-14, and I live in Edinburgh, UK.')

    def said(self, *texts, language='en', answers=()):
        turns = [{'id': str(index), 'text': text, 'language': language} for index, text in enumerate(texts)]
        questions = [{'id': 'q' + str(index), 'answer': answer} for index, answer in enumerate(answers)]
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(
            {CHAT: {'id': CHAT, 'mode': 'initialize', 'session': SESSION, 'turns': turns, 'questions': questions}}))

    def ready(self, **fields):
        setup_flow.agree(self.root, CHAT)
        if fields:
            set_profile_fields(self.root, fields)
        return setup_flow.begin(self.root, CHAT)

    def run_command(self, action, payload=None):
        output = io.StringIO()
        with redirect_stdout(output):
            code = setup_flow.command(self.root, SESSION, action, None if payload is None else json.dumps(payload))
        return code, json.loads(output.getvalue())

    def answer(self, step, values=None, quotes=None, **extra):
        return self.run_command('answer', {'step': step, 'values': values or {}, **({'quotes': quotes} if quotes else {}), **extra})

    def test_consent_creates_only_missing_storage_and_keeps_records(self):
        self.assertFalse(setup_flow.consented(self.root))
        (self.root / 'profile.md').write_text('city: Leeds\n')
        self.assertTrue(setup_flow.consented(self.root), 'an existing profile predates the consent record')
        setup_flow.agree(self.root, CHAT)
        self.assertEqual((self.root / 'profile.md').read_text(), 'city: Leeds\n')
        for name in ('projects', 'daily', 'calendar.sqlite', 'inbox.sqlite', 'setup-consent.json'):
            self.assertTrue((self.root / name).exists(), name)

    def test_a_new_setup_walks_every_step_in_order_and_saves_each_one(self):
        self.ready()
        code, receipt = self.run_command('next')
        self.assertEqual((code, receipt['setup']['step'], receipt['setup']['mode']), (0, 'secretary_name', 'new'))
        self.assertIn('read no docs', receipt['contract'])
        self.assertIn('--session ses_setup answer --input-stdin', receipt['next']['answer']['command'])
        _, result = self.answer('secretary_name', {'secretary_name': 'Pip'}, {'secretary_name': 'Call yourself Pip'})
        self.assertEqual((result['changed'], result['setup']['step']), ({'secretary_name': 'Pip'}, 'user_name'))
        self.assertEqual(profile_fields(self.root)['secretary_name'], 'Pip', 'saved at the end of its step')
        # Values the user already gave for later steps are saved now and kept there.
        _, result = self.answer('user_name', {'user_name': 'Sam', 'birthday': '03-14'}, {'user_name': 'I am Sam', 'birthday': 'born 03-14'})
        self.assertEqual(result['setup']['step'], 'birthday')
        self.assertEqual(result['saved'], {'birthday': '03-14'})
        self.answer('birthday', quote='born 03-14')
        _, result = self.answer('location', {'city': 'Edinburgh, UK', 'region': 'global', 'timezone': 'Europe/London'},
                                {'city': 'Edinburgh, UK'})
        self.assertEqual(result['setup']['step'], 'rhythm')
        for step in ('rhythm', 'about'):
            self.answer(step, quote='I am Sam')
        self.answer('news', {'news_country': 'gb'}, {'news_country': 'UK'})
        with patch.object(setup_flow, 'verify', return_value={'weather': {'status': 'verified', 'result': {'aqi': 1}}}) as verify:
            _, result = self.answer('holidays', {'holiday_countries': 'gb-sct'}, {'holiday_countries': 'Edinburgh'})
        verify.assert_called_once()
        self.assertEqual(result['next']['action'], 'finish')
        self.assertEqual(result['next']['checks'], {'weather': {'status': 'verified'}})
        self.assertEqual(result['next']['saved']['holiday_countries'], 'GB-SCT')
        self.assertEqual(self.run_command('next')[1]['next']['action'], 'done')
        self.assertTrue((self.root / 'state.json').exists() or any(self.root.glob('state*')), 'the state index is rebuilt')
        self.assertIn('Secretary chat', setup_flow.hint(self.root, CHAT))
        self.assertIsNone(setup_flow.hint(self.root, CHAT), 'the more-features note appears once')

    def test_values_need_the_users_own_words_and_the_current_step(self):
        self.ready()
        code, result = self.answer('secretary_name', {'secretary_name': 'Nova'}, {'secretary_name': 'Nova'})
        self.assertEqual((code, result['error']), (1, 'unquoted'))
        self.assertEqual(self.answer('user_name', {'user_name': 'Sam'}, {'user_name': 'Sam'})[1]['error'], 'wrong_step')
        self.assertEqual(self.answer('secretary_name')[1]['error'], 'unquoted', 'skipping needs the user\'s words too')
        self.assertEqual(self.answer('secretary_name', {'secretary_name': 'Nova'}, {'secretary_name': 'Pip'})[1]['error'], 'unquoted')
        self.assertEqual(self.answer('secretary_name', {'mood': 'x'}, {'mood': 'Pip'})[1]['error'], 'invalid_field')
        self.assertNotIn('secretary_name', {key for key, value in profile_fields(self.root).items() if value})
        # A form answer counts as the user's words.
        self.said('Hello', answers=[{'secretary_name': 'Nova'}])
        self.assertEqual(self.answer('secretary_name', {'secretary_name': 'Nova'}, {'secretary_name': 'nova'})[0], 0)

    def test_values_follow_each_settings_rules(self):
        self.ready()
        self.said('Name: ' + 'x' * 40, 'birthday 1990-03-14', 'Paris', 'Mars/Base', 'Japan news', 'Narnia holidays')
        cases = [('secretary_name', {'secretary_name': 'x' * 40}, {'secretary_name': 'x' * 40}),
                 ('secretary_name', {'birthday': '1990-03-14'}, {'birthday': '1990-03-14'}),
                 ('secretary_name', {'city': 'Paris', 'region': 'global', 'timezone': 'Mars/Base'}, {'city': 'Paris'}),
                 ('secretary_name', {'news_country': 'JP'}, {'news_country': 'Japan news'}),
                 ('secretary_name', {'holiday_countries': 'NARNIA'}, {'holiday_countries': 'Narnia'})]
        for step, values, quotes in cases:
            with self.subTest(values=values):
                self.assertEqual(self.answer(step, values, quotes)[1]['error'], 'invalid_value')
        self.assertEqual(setup_flow.load(self.root, CHAT)['done'], [])

    def test_required_steps_cannot_be_skipped_and_a_review_can_keep_everything(self):
        self.ready()
        state = setup_flow.load(self.root, CHAT)
        state['done'] = list(setup_flow.STEPS[:3])
        setup_flow.store(self.root, CHAT, state)
        self.assertEqual(self.answer('location', quote='I am Sam')[1]['error'], 'required')
        self.assertEqual(self.answer('location', keep_all=True, quote='I am Sam')[1]['error'], 'invalid_keep_all')

        review = 'b' * 32
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps({review: {
            'id': review, 'mode': 'initialize', 'session': SESSION, 'turns': [{'text': 'Keep it all', 'language': 'en'}]}}))
        set_profile_fields(self.root, READY)
        self.assertEqual(setup_flow.begin(self.root, review)['mode'], 'review')
        before = (self.root / 'profile.md').read_text()
        with patch.object(setup_flow, 'verify') as verify:
            _, result = self.answer('secretary_name', keep_all=True, quote='keep it all')
        verify.assert_not_called()  # Nothing about the place or news changed.
        self.assertEqual((result['next']['action'], result['next']['saved'], result['next']['checks']), ('finish', {}, None))
        self.assertEqual((self.root / 'profile.md').read_text(), before, 'keeping writes nothing')

    def test_a_change_made_elsewhere_after_asking_is_not_overwritten(self):
        self.ready()
        question = setup_flow.fallback(self.root, CHAT, record=False)
        setup_flow.posted(self.root, CHAT, question)
        set_profile_fields(self.root, {'secretary_name': 'Aria'})  # Saved on About me meanwhile.
        _, result = self.answer('secretary_name', {'secretary_name': 'Pip'}, {'secretary_name': 'Pip'})
        self.assertEqual(result['error'], 'changed_elsewhere')
        self.assertEqual(profile_fields(self.root)['secretary_name'], 'Aria')

    def test_forms_are_built_by_code_with_the_secretarys_wording(self):
        self.ready(**READY)
        self.assertEqual(self.run_command('ask', {'step': 'user_name', 'title': 'Hi'})[1]['error'], 'wrong_step')
        self.assertEqual(self.run_command('ask', {'step': 'secretary_name', 'title': ''})[1]['error'], 'invalid_title')
        self.assertEqual(self.run_command('ask', {'step': 'secretary_name', 'title': 'Shall I stay Pip?'})[0], 0)
        form = setup_flow.pending(self.root, CHAT)
        self.assertEqual((form['title'], form['setup']), ('Shall I stay Pip?', 'secretary_name'))
        field, = form['fields']
        self.assertEqual([option['value'] for option in field['options']], ['keep', 'keep_all'])
        self.assertEqual(field['options'][0]['label'], 'Keep “Pip”')
        self.assertTrue(field['custom'] and field['customFirst'])
        # Choices are saved by code without the secretary.
        self.assertTrue(setup_flow.apply_form(self.root, CHAT, {'form': form}, {'secretary_name': 'keep'}))
        self.assertFalse(setup_flow.apply_form(self.root, CHAT, {'form': form}, {'secretary_name': 'keep'}), 'only the current step')
        question = setup_flow.fallback(self.root, CHAT)
        self.assertEqual(question['title'], 'What should I call you?')
        self.assertFalse(setup_flow.apply_form(self.root, CHAT, {'form': question}, {'user_name': 'Sam'}), 'typed words go to the secretary')
        self.assertEqual(setup_flow.load(self.root, CHAT)['fallbacks'], ['user_name'])

    def test_news_and_holiday_choices_list_bundled_countries_and_regions(self):
        self.ready(**READY)
        state = setup_flow.load(self.root, CHAT)
        state['done'] = list(setup_flow.STEPS[:6])
        setup_flow.store(self.root, CHAT, state)
        news = setup_flow.fallback(self.root, CHAT)
        self.assertEqual([option['value'] for option in news['fields'][0]['options']], list(setup_flow.NEWS))
        self.assertEqual(news['fields'][0]['default'], 'GB')
        self.assertTrue(setup_flow.apply_form(self.root, CHAT, {'form': news}, {'news_country': 'CN', 'news_additional_countries': ['CN', 'US']}))
        self.assertEqual((profile_fields(self.root)['news_country'], profile_fields(self.root)['news_additional_countries']), ('CN', 'US'))
        holidays = setup_flow.fallback(self.root, CHAT)
        options = [option['value'] for option in holidays['fields'][0]['options']]
        self.assertEqual((options[0], options[1], options[-1]), ('CN', 'US', 'none'))
        self.assertEqual(holidays['fields'][0]['default'], ['GB-SCT'])
        with setup_flow.speaking('zh-CN'):
            labels = [option['label'] for option in setup_flow.fallback(self.root, CHAT)['fields'][0]['options']]
        self.assertIn('英国 — 苏格兰', labels)

    def test_only_an_initialize_chats_session_runs_setup(self):
        self.assertEqual(self.run_command('next')[1]['error'], 'setup_not_active')
        output = io.StringIO()
        with redirect_stdout(output):
            setup_flow.command(self.root, 'ses_other', 'next', None)
        self.assertEqual(json.loads(output.getvalue())['error'], 'setup_not_active')


if __name__ == '__main__':
    unittest.main()
