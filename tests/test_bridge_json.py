"""Large native tool results must not become website transcripts or queue blockers."""
import io
import itertools
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.bridge_json import read_json
from goodmorning.web.briefing_server import Chamber
from goodmorning.security.briefing_runtime import LocalBridge


class BridgeMessageTests(unittest.TestCase):
    def test_private_subtrees_are_discarded_across_chunk_boundaries(self):
        value = {'data': [{'id': 'msg', 'type': 'assistant', 'metadata': {'private': 'hidden'},
            'providerState': ['private', {'nested': [False, None, 1]}], 'snapshot': None,
            'content': [{'type': 'text', 'text': 'Keep 中文 and "state": {nested} \\'},
                        {'type': 'tool', 'state': {'output': ['private', {'text': 'not a reply'}]}},
                        {'type': 'tool', 'state': 'private'}, {'type': 'tool', 'state': 123},
                        {'type': 'tool', 'state': True}]}], 'cursor': {'next': 'opaque /+'}}
        raw = json.dumps(value).encode()
        for size in range(1, 81):
            chunks = iter(raw[index:index + size] for index in range(0, len(raw), size))
            response = Mock(read=lambda _: next(chunks, b''))
            page = read_json(response, message_data=True)
            entry = page['data'][0]
            self.assertEqual(entry['content'][0], value['data'][0]['content'][0])
            self.assertTrue(all(part['state'] is None for part in entry['content'][1:]))
            self.assertIsNone(entry['metadata'])
            self.assertIsNone(entry['providerState'])
            self.assertEqual(page['cursor'], value['cursor'])

    def test_large_tool_outputs_are_streamed_without_raising_the_visible_limit(self):
        chunks = iter(itertools.chain(
            [b'{"data":[{"id":"reply","type":"assistant","content":[{"type":"tool","state":{"output":"'],
            itertools.repeat(b'x' * 65536, 1100),
            [b'"}},{"type":"text","text":"Visible answer"}]}],"cursor":{"next":null}}']))
        response = Mock(read=lambda _: next(chunks, b''))
        page = read_json(response, limit=250, message_data=True)
        self.assertEqual(page['data'][0]['content'][1]['text'], 'Visible answer')
        self.assertIsNone(page['data'][0]['content'][0]['state'])
        raw = json.dumps({'data': [{'type': 'assistant', 'content': [{'type': 'text', 'text': 'x' * 251}]}]}).encode()
        with self.assertRaisesRegex(ValueError, 'Upstream response exceeds limit'):
            read_json(io.BytesIO(raw), limit=250, message_data=True)
        # Status responses and other API contracts must not lose their state fields.
        self.assertEqual(read_json(io.BytesIO(b'{"state":{"type":"idle"}}')), {'state': {'type': 'idle'}})

    def test_both_bridges_project_native_messages_before_size_check(self):
        value = {'data': [
            {'id': 'a', 'type': 'assistant', 'content': [
                {'type': 'tool', 'state': {'output': 'x' * 3_000_000}},
                {'type': 'text', 'text': 'Visible answer'}]},
            {'id': 'u', 'type': 'user', 'text': 'Prompt', 'files': [{'data': 'x' * 3_000_000}]}],
            'cursor': {'next': None}}
        raw = json.dumps(value).encode()
        for bridge in (Chamber('http://127.0.0.1:1234', '/synthetic'),
                       LocalBridge('http://127.0.0.1:1234', '/synthetic', 'synthetic-password')):
            if isinstance(bridge, LocalBridge):
                target = 'goodmorning.security.briefing_runtime.build_opener'
            else:
                target = 'goodmorning.web.briefing_server.build_opener'
            with patch(target) as opener:
                opener.return_value.open.side_effect = [io.BytesIO(raw), io.BytesIO(b'{"data":{}}')]
                result = bridge.control('session.messages', sessionId='ses_test', limit=100)
            self.assertEqual([entry['text'] for entry in result['messages']], ['Prompt', 'Visible answer'])
            self.assertEqual(result['sessionStatus']['type'], 'idle')

    def test_interrupted_question_becomes_an_expired_message_without_its_private_input(self):
        question = {'type': 'tool', 'id': 'prt_question', 'name': 'question', 'state': {'input': {'questions': ['private']}}}
        value = {'data': [
            {'id': 'later', 'type': 'user', 'text': 'Remind me again'},
            {'id': 'aborted', 'type': 'assistant', 'error': {'type': 'aborted'},
             'content': [{'type': 'text', 'text': 'One thing first.'}, question]},
            {'id': 'answered', 'type': 'assistant', 'content': [{**question, 'id': 'prt_answered'}]},
            {'id': 'u', 'type': 'user', 'text': 'Remind me'}], 'cursor': {'next': None}}
        chamber = Chamber('http://127.0.0.1:1234', '/synthetic')
        with patch('goodmorning.web.briefing_server.build_opener') as opener:
            opener.return_value.open.side_effect = [io.BytesIO(json.dumps(value).encode()), io.BytesIO(b'{"data":{}}')]
            result = chamber.control('session.messages', sessionId='ses_test', limit=100)
        self.assertEqual(result['messages'], [
            {'id': 'u', 'role': 'user', 'text': 'Remind me'},
            {'id': 'aborted', 'role': 'assistant', 'text': 'One thing first.'},
            {'id': 'aborted:expired', 'role': 'assistant', 'text': '', 'kind': 'expired', 'tools': ['prt_question']},
            {'id': 'later', 'role': 'user', 'text': 'Remind me again'}])


if __name__ == '__main__':
    unittest.main()
