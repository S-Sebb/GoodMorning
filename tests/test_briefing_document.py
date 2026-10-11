"""Native briefing validation, evidence preservation, saving and browser compatibility."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings import briefing_web as web
from goodmorning.records import state
from goodmorning.web.briefing_server import BrowserApp
from benchmarks.briefing_format import compact, fixtures
import test_briefing_server as server_tests

DATE = '2034-03-17'


def document(kind='gm'):
    sample = next(sample for sample in fixtures() if sample['kind'] == kind)
    doc = compact(sample)
    for section in doc['sections']:
        for index, value in enumerate(section[1]):
            if value[0] == 'table':
                section[1][index] = ['agenda', value[2]]
    return doc


class DocumentTests(unittest.TestCase):
    def test_all_equal_content_fixture_shapes_validate(self):
        for sample in fixtures():
            doc = compact(sample)
            self.assertEqual(native.parse(native.encode(doc)), doc)

    def test_all_fixture_facts_notes_and_source_urls_survive_direct_rendering(self):
        for sample in fixtures():
            doc = compact(sample)
            page = web.edition(doc, sample['date'], sample['kind'], {sample['kind']: True})
            expected = [doc['greeting'], doc['opening'], doc['closing']]
            urls = []
            for section in doc['sections']:
                expected.append(native.section_title(section, sample['date']))
                if len(section) >= 3: expected.append(section[2])
                for value in section[1]:
                    tag = value[0]
                    if tag == 'p': expected.append(value[1])
                    elif tag == 'weather':
                        for row in value[1]: expected.extend(item for item in row[1:3] if item is not None)
                    elif tag == 'agenda':
                        for row in value[1]: expected.extend(row)
                    elif tag == 'tasks':
                        for row in value[1]: expected.extend(row[1:])
                    elif tag == 'news':
                        expected.append(value[1])
                        for headline, summary, refs in value[2]:
                            expected.extend([headline, summary] + [label for label, _ in refs])
                            urls.extend(url for _, url in refs)
            for value in expected:
                self.assertIn(native.escaped(value), page, sample['name'])
            for url in urls:
                self.assertIn('href="' + native.escaped(url) + '"', page)

    def test_native_renderer_never_calls_markdown_or_prose_layout_inference(self):
        doc = document()
        self.assertFalse(hasattr(web, 'markdown_html'))
        self.assertFalse(hasattr(web, 'section_layout'))
        page = web.edition(doc, DATE, 'gm', {'gm': True})
        for value in ('weather-tile', 'news-card', 'agenda-event', 'task-card', 'src="briefing.js"'):
            self.assertIn(value, page)

    def test_headlines_with_dashes_and_every_citation_are_preserved(self):
        doc = document()
        news = doc['sections'][1][1][0]
        news[2][0] = ['**Research — with a dash**', 'Facts — not punctuation-defined metadata.', [
            ['Source one', 'https://example.org/a?x=1&y=2'], ['Source two', 'https://example.org/b#evidence']]]
        page = web.edition(doc, DATE, 'gm', {'gm': True})
        self.assertIn('<h4>**Research — with a dash**</h4>', page)
        self.assertIn('Facts — not punctuation-defined metadata.', page)
        for label, url in news[2][0][2]:
            self.assertIn(label, page)
            self.assertIn(url.replace('&', '&amp;'), page)
        self.assertEqual(native.news_urls(doc)[:2], ['https://example.org/a?x=1&y=2', 'https://example.org/b#evidence'])

    def test_translated_headings_do_not_control_components_or_flags(self):
        doc = document()
        doc['lang'] = 'zh-CN'
        for section in doc['sections']:
            section.append('今日安排')
        weather = doc['sections'][0][1][0][1]
        for row, label in zip(weather, ['气温', '降水', '空气质量']):
            row.append(label)
        doc['sections'][1][1][0][1] = '国内'
        doc['sections'][1][1][0].append('CN')
        agenda = doc['sections'][2][1][1]
        agenda.append(['日期', '时间', '活动', '地点', '准备'])
        page = web.edition(doc, DATE, 'gm', {'gm': True})
        for value in ('lang="zh-CN"', 'weather-tile', 'agenda-event', 'country-flag', '气温', '地点', '准备'):
            self.assertIn(value, page)

    def test_same_section_type_notes_are_not_overwritten(self):
        doc = {'v': 1, 'greeting': 'Hello.', 'opening': 'Keep both contexts.', 'sections': [
            ['notes', [['p', 'First context.']], 'First note.', 'First'],
            ['notes', [['p', 'Second context.']], 'Second note.', 'Second']]}
        page = web.edition(doc, DATE, 'gm', {'gm': True})
        self.assertIn('First note.', page)
        self.assertIn('Second note.', page)
        self.assertEqual(page.count('class="scroll-chunk"'), 2)

    def test_done_is_distinct_from_partial_and_blocked(self):
        doc = document('gn')
        doc['sections'][-1][1] = [['tasks', [[status, status + ' task', 'Outcome retained.'] for status in ('open', 'done', 'partial', 'blocked')]]]
        page = web.edition(doc, DATE, 'gn', {'gn': True})
        self.assertEqual(page.count(' aria-label="Completed"'), 1)
        self.assertEqual(page.count(' aria-label="Not completed"'), 3)
        self.assertIn('Partial', page)
        self.assertIn('Blocked', page)

    def test_all_rendered_strings_are_inert_and_internal_ids_hidden(self):
        doc = {'v': 1, 'greeting': 'Hello <script>bad</script>.', 'opening': 'No executable markup.', 'sections': [
            ['notes', [['p', 'literal ## heading\n<script>alert(1)</script> ib_' + 'a' * 24,
                        [['<img src=x onerror=bad>', 'https://example.org/?a=%22&b=%3Cscript%3E']]],
                       ['list', ['Keep this warning.', 'Nested-like text is literal.']],
                       ['table', ['Outcome'], [['<iframe>unsafe</iframe>']]]], 'Separate note.', 'Quoted " heading ses_fixture']],
               'closing': 'Good night <b>literal</b>.'}
        page = web.edition(doc, DATE, 'gn', {'gn': True})
        for tag in ('<script>bad', '<script>alert', '<img src=x', '<iframe>', '<b>literal'):
            self.assertNotIn(tag, page)
        self.assertIn('&lt;script&gt;alert', page)
        self.assertNotIn('ib_' + 'a' * 24, page)
        self.assertNotIn('ses_fixture', page)
        self.assertIn('Good night &lt;b&gt;literal', page)

    def test_invalid_or_unknown_formats_never_silently_drop_content(self):
        bad = []
        base = document()
        for key, value in [('v', 2), ('v', True), ('sections', []), ('greeting', 12), ('greeting', '\ud800'), ('lang', 'en" onclick="bad'), ('extra', 'unrendered')]:
            changed = copy.deepcopy(base); changed[key] = value; bad.append(changed)
        for value in ([['unknown', 'Hidden']], [['p', 'x', []]], [['table', ['One'], [['too', 'many']]]],
                      [['tasks', [['complete', 'Task', 'Not confirmed']]]], [['weather', [['air', '31', 'Good'], ['temperature', '1°C', 'Cold']]]],
                      [['weather', [['air', '31', 'Good'], ['air', '30', 'Duplicate']]]], [['news', 'AI', [['Headline', 'Summary', []]]]],
                      [['agenda', [['', '', '', '', '']]]]):
            changed = copy.deepcopy(base); changed['sections'][0][1] = value; bad.append(changed)
        for changed in bad:
            with self.subTest(changed=str(changed)[:80]), self.assertRaises(ValueError):
                native.parse(json.dumps(changed))
        for raw in ('{"v":1,"v":1}', '{"v":NaN}', '[1,2,3]', '{broken', '[' * 2000 + ']' * 2000):
            with self.assertRaises(ValueError):
                native.parse(raw)

    def test_unsafe_source_schemes_and_malformed_urls_are_rejected(self):
        for url in ('javascript:alert(1)', 'data:text/html,unsafe', 'file:///private', '//example.org/story',
                    'https://[broken', 'https://user:pass@example.org/', 'https://example.org:bad/',
                    'https://example.org/\nattack', 'https://example.org\\evil/'):
            doc = document(); doc['sections'][1][1][0][2][0][2][0][1] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                native.parse(json.dumps(doc))

    def test_size_limits_reject_instead_of_truncating(self):
        doc = document(); doc['opening'] = 'x' * 351
        with self.assertRaises(ValueError): native.parse(json.dumps(doc))
        with self.assertRaises(ValueError): native.parse(' ' * 150001)
        doc = document()
        with patch.object(native, 'MAX_BYTES', len(native.encode(doc).encode()) - 1):
            # A minified input may fit exactly, while the canonical newline does not.
            source = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
            native.parse(source)
            with self.assertRaises(ValueError): native.encode(doc)


class SaveAndViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'daily').mkdir()
        (self.root / 'profile.md').write_text('timezone: Europe/London\n')

    def save(self, doc, kind='gm', *extra):
        out = io.StringIO()
        with patch.object(sys, 'stdin', io.StringIO(json.dumps(doc))), contextlib.redirect_stdout(out):
            code = state.main(['--secretary-dir', str(self.root), '--today', DATE, '--mark-' + kind,
                               '--session', 'ses_fixture', '--answer-stdin', '--json', *extra])
        return code, json.loads(out.getvalue())

    def app(self):
        return BrowserApp(self.root, now=lambda: datetime(2034, 3, 17, 12, tzinfo=timezone.utc))

    def test_save_writes_one_canonical_briefing_and_reuses_state_pipeline(self):
        (self.root / 'daily' / f'{DATE}.md').write_text('# Existing daily work\n\n## must-do\n- [ ] Preserve me\n')
        doc = document()
        code, receipt = self.save(doc)
        self.assertEqual(code, 0)
        self.assertEqual(receipt['answer_file'], f'daily/{DATE}.gm.json')
        self.assertTrue(receipt['ran'])
        saved = self.root / receipt['answer_file']
        self.assertEqual(json.loads(saved.read_text()), doc)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / 'daily' / f'{DATE}.gm.md').exists())
        self.assertFalse((self.root / 'daily' / f'{DATE}.gm.presentation.json').exists())
        self.assertIn('Preserve me', (self.root / 'daily' / f'{DATE}.md').read_text())
        page = self.app().page(DATE, 'gm', True).decode()
        self.assertIn(f'href="/d/{DATE}/gm.json"', page)
        self.assertNotIn('Read original Markdown', page)
        self.assertFalse((self.root / 'browser').exists())
        self.assertEqual(self.save(doc)[1]['error'], 'already_ran')

    def test_validation_failure_does_not_save_or_mark(self):
        doc = document(); doc['v'] = 999
        code, result = self.save(doc)
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'briefing_invalid')
        self.assertIn('v:', result['next'])
        self.assertEqual(list((self.root / 'daily').iterdir()), [])
        self.assertFalse((self.root / 'state.json').exists())

    def test_json_escapes_cannot_hide_boilerplate_from_the_existing_lint(self):
        doc = document(); doc['opening'] = 'Weather retrieval returned\nno warnings.'
        code, result = self.save(doc)
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], 'answer_noncritical_boilerplate')
        self.assertEqual(list((self.root / 'daily').iterdir()), [])

    def test_unrelated_text_is_ignored_and_preserved_even_with_force(self):
        old = self.root / 'daily' / f'{DATE}.gm.md'; old.write_text('Legacy source.')
        code, result = self.save(document(), 'gm', '--force')
        self.assertEqual(code, 0)
        self.assertEqual(old.read_text(), 'Legacy source.')
        self.assertTrue(old.with_suffix('.json').exists())

    def test_native_json_is_readable_without_markdown_installed(self):
        self.save(document())
        with patch.dict(sys.modules, {'markdown': None}):
            files = web.build(self.root, DATE, include_assets=False)
            self.assertIn('gm.html', files)
            self.assertIn('gm.json', files)
            self.assertNotIn('gm.md', files)

    def test_text_editions_are_ignored_and_native_cache_refreshes(self):
        self.save(document())
        (self.root / 'daily' / f'{DATE}.gn.md').write_text('Good evening.\n\n## Today\nAn old snapshot.\n')
        files = web.build(self.root, DATE, include_assets=False)
        self.assertTrue({'gm.html', 'gm.json'} <= files.keys())
        self.assertNotIn('gn.html', files)
        app = self.app()
        self.assertNotIn('An old snapshot.', app.page(DATE, 'gn', True).decode())
        path = self.root / 'daily' / f'{DATE}.gm.json'
        changed = document(); changed['greeting'] = 'Changed greeting.'
        path.write_text(native.encode(changed))
        self.assertIn('Changed greeting.', app.page(DATE, 'gm', True).decode())

    def test_invalid_native_source_never_falls_back_to_legacy(self):
        (self.root / 'daily' / f'{DATE}.gm.json').write_text('{broken')
        (self.root / 'daily' / f'{DATE}.gm.md').write_text('Stale old snapshot.')
        with self.assertRaises(ValueError): self.app().page(DATE, 'gm', True)

    def test_rebuild_recognizes_json_pointer_and_never_opens_external_pointer(self):
        self.save(document())
        rebuilt = state.rebuild_index(str(self.root), state.blank_state(), DATE)
        self.assertEqual(rebuilt['days'][DATE]['gm']['answer_file'], f'daily/{DATE}.gm.json')
        self.assertNotIn('unsafe_answer_pointer', rebuilt['warnings'])
        daily = self.root / 'daily' / f'{DATE}.md'
        daily.write_text('- gm: yes (session ses_fixture) | answer: private.json\n')
        with patch.object(state, 'stat_answer', side_effect=AssertionError('Unsafe read')):
            rebuilt = state.rebuild_index(str(self.root), state.blank_state(), DATE)
        self.assertIn('unsafe_answer_pointer', rebuilt['warnings'])

    def test_generated_invalid_json_is_not_reported_ready(self):
        chamber = server_tests.FakeChamber(); chamber.forms = []; chamber.permissions = []; chamber.busy = False
        app = BrowserApp(self.root, chamber, now=lambda: datetime(2034, 3, 17, 12, tzinfo=timezone.utc))
        job = {'id': 'a' * 32, 'date': DATE, 'kind': 'gm', 'state': 'running', 'session': 'ses_fixture'}
        app.jobs[DATE + '.gm'] = job
        source = self.root / 'daily' / f'{DATE}.gm.json'; source.write_text('{"v":999}')
        self.assertEqual(app.status(job['id'])['state'], 'stopped')
        self.assertEqual(source.read_text(), '{"v":999}')
        source.write_text(native.encode(document()))
        self.assertEqual(app.status(job['id'])['state'], 'ready')

    def test_native_source_symlink_is_refused(self):
        (self.root / 'daily' / f'{DATE}.gm.json').symlink_to(self.root / 'profile.md')
        with self.assertRaises(ValueError): self.app().page(DATE, 'gm', True)

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Optional Pillow dependency')
    def test_native_news_reuses_cached_publisher_images_without_provider_access(self):
        from PIL import Image
        from goodmorning.briefings import briefing_images
        data = io.BytesIO(); Image.new('RGB', (640, 360), 'navy').save(data, format='WEBP')
        payload = data.getvalue(); digest = hashlib.sha256(payload).hexdigest()
        pool = self.root / 'browser-images' / 'objects'; pool.mkdir(parents=True)
        (pool / (digest + '.webp')).write_bytes(payload)
        doc = document(); url = doc['sections'][1][1][0][2][0][2][0][1]
        directory = pool.parent / DATE; directory.mkdir()
        (directory / 'manifest.json').write_text(json.dumps({url: {'status': 'cached', 'file': digest + '.webp', 'sha256': digest, 'alt': 'Cached publisher preview'}}))
        self.save(doc)
        with patch.object(briefing_images, 'fetch_public', side_effect=AssertionError('Page visits must never fetch')):
            page = self.app().page(DATE, 'gm', False).decode()
        self.assertIn('src="/media/' + digest + '.webp"', page)
        self.assertIn('srcset="/media/thumb-v1/' + digest + '.webp', page)
        self.assertIn('Cached publisher preview', page)

    def test_rolling_native_dates_keep_storage_and_caches_bounded(self):
        start = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
        payload = native.encode(document())
        for offset in range(20):
            day = (start + timedelta(days=offset)).date().isoformat()
            for kind in ('gm', 'gn'):
                (self.root / 'daily' / f'{day}.{kind}.json').write_text(payload)
        now = start
        app = BrowserApp(self.root, now=lambda: now)
        before = {p for p in self.root.rglob('*') if p.is_file()}
        with patch.dict(sys.modules, {'markdown': None}):
            for offset in range(20):
                now = start + timedelta(days=offset)
                for kind in ('gm', 'gn'):
                    app.page(now.date().isoformat(), kind, False)
                self.assertLessEqual(len(app.cache.items), 14)
                self.assertLessEqual(app.cache.size, 16 * 1024 * 1024)
        self.assertEqual(before, {p for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse((self.root / 'browser').exists())

    def test_dispatch_requests_native_format_without_overriding_user_model(self):
        app = self.app(); chamber = server_tests.FakeChamber(); app.chamber = chamber
        job = {'id': 'a' * 32, 'date': DATE, 'kind': 'gm', 'state': 'starting'}
        app.jobs[DATE + '.gm'] = job; app.dispatch(job)
        prompt = next(args['prompt'] for action, args in chamber.calls if action == 'session.send')
        self.assertEqual(prompt, f'/gm\nBrowser job: {job["id"]}\nRuntime: {app.runtime}\nWebsite language: en')
        self.assertNotIn('briefing-json', prompt)
        self.assertLess(len(prompt), 250)
        self.assertNotIn('model', chamber.calls[0][1])


class NativeHTTPTests(server_tests.HTTPTests):
    def test_native_download_and_read_only_source_mime(self):
        payload = native.encode(document())
        (self.root / 'daily' / f'{self.date}.gm.json').write_text(payload)
        with urlopen(self.address + '/gm.html') as response:
            self.assertIn('View saved data', response.read().decode())
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with urlopen(self.address + f'/d/{self.date}/gm.json') as response:
            self.assertEqual(response.read(), payload.encode())
            self.assertIn('application/json', response.headers['Content-Type'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.assertRaises(HTTPError) as error:
            urlopen(self.address + f'/d/{self.date}/gm.md')
        self.assertEqual(error.exception.code, 404); error.exception.close()

    def test_damaged_native_source_fails_without_modifying_it(self):
        source = self.root / 'daily' / f'{self.date}.gm.json'; source.write_text('{"v":999}')
        with self.assertRaises(HTTPError) as error: urlopen(self.address + '/gm.html')
        self.assertEqual(error.exception.code, 404); error.exception.close()
        self.assertEqual(source.read_text(), '{"v":999}')


def serve_fixture(directory):
    from goodmorning.web.briefing_server import serve_live
    root = Path(directory); (root / 'daily').mkdir(exist_ok=True)
    (root / 'profile.md').write_text('timezone: Europe/London\n')
    current = datetime(2034, 3, 17, 12, tzinfo=timezone.utc)
    for offset in range(7):
        day = (current - timedelta(days=offset)).date().isoformat()
        for kind in ('gm', 'gn'):
            doc = document(kind)
            if offset == 1:
                doc['lang'] = 'zh-CN'
                doc['greeting'] = '早上好。' if kind == 'gm' else '晚上好。'
                for section in doc['sections']: section.append('今日安排')
            if offset == 2:
                doc['sections'].append(['notes', [['table', ['Outcome', 'Next step'], [['Partial — not done', 'Ask before changing the plan']]]], 'A separate assessment.', 'User-reported progress'])
            if offset == 3:
                doc['sections'] = [['notes', [['p', 'Weather/schedule unavailable; do not invent data.']], '', 'Material gaps']]
            if offset == 4:
                doc['sections'].append(['notes', [['p', '<script>literal text</script> ## not navigation', [['Warning source', 'https://example.org/warning?a=1&b=2']]]], '', 'Literal text'])
            if offset == 5:
                doc['sections'].append(['still-open', [['tasks', [[status, status + ' outcome', 'Actual report only.'] for status in ('open', 'done', 'partial', 'blocked')]]]])
            if offset == 6:
                doc['sections'] = [['notes', [['p', ('Saved detail ' * 30) + str(index)]], '', f'Custom {index}'] for index in range(80)]
            doc['sections'][-1][1].append(['p', f'CONTENT_END_{kind}_{day}'])
            (root / 'daily' / f'{day}.{kind}.json').write_text(native.encode(doc))
    serve_live(BrowserApp(root, now=lambda: current), 0)


if __name__ == '__main__':
    if '--serve-fixture' in sys.argv: serve_fixture(sys.argv[-1])
    else: unittest.main()
