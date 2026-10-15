"""Bounded, account-owned transcript reads for optional model trials; no model calls."""
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmarks.native_bridge import NativeBridge


class TrialBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge=NativeBridge('/synthetic/source','/synthetic/account')
        self.bridge.sessions['ses_trial']={'idle':True}

    def test_paginated_reads_shrink_truncated_pages_and_keep_visible_order(self):
        calls=[]
        def request(path,body=None):
            self.assertIsNone(body)
            calls.append(path)
            query=parse_qs(urlsplit(path).query)
            if query['limit']==['10']:
                raise json.JSONDecodeError('Truncated CLI output','{',1)
            if 'cursor' not in query:
                return {'data':[{'id':'new','type':'assistant','content':[
                    {'type':'text','text':'Visible reply'}, {'type':'tool','state':{'output':'Not visible'}}]}],
                    'cursor':{'next':'opaque /+'}}
            self.assertEqual(query['cursor'],['opaque /+'])
            self.assertNotIn('order',query)
            return {'data':[{'id':'old','type':'user','text':'Original request'}],'cursor':{}}
        with patch.object(self.bridge,'request',side_effect=request):
            result=self.bridge.control('session.messages',sessionId='ses_trial',limit=100)
        self.assertEqual([item['id'] for item in result['messages']],['old','new'])
        self.assertEqual(result['messages'][-1]['text'],'Visible reply')
        self.assertEqual(len(calls),3)

    def test_single_message_overflow_stops_after_bounded_read_only_attempts(self):
        calls=[]
        def truncated(path,body=None):
            self.assertIsNone(body)
            calls.append(int(parse_qs(urlsplit(path).query)['limit'][0]))
            raise json.JSONDecodeError('Truncated','{',1)
        with patch.object(self.bridge,'request',side_effect=truncated),self.assertRaisesRegex(ValueError,'single native message'):
            self.bridge.control('session.messages',sessionId='ses_trial',limit=100)
        self.assertEqual(calls,[10,5,2,1])

    def test_foreign_session_read_is_rejected_before_any_api_call(self):
        with patch.object(self.bridge,'api') as api,self.assertRaisesRegex(ValueError,'own synthetic sessions'):
            self.bridge.request('/api/session/ses_other/message?limit=1')
        api.assert_not_called()

    def test_experimental_agent_is_pinned_and_verified_before_environment_or_prompt(self):
        bridge=NativeBridge('/synthetic/source','/synthetic/account',agent='build')
        with patch.object(bridge,'api',side_effect=[{'data':{'id':'ses_trial','agent':'build'}},{}]) as api:
            self.assertEqual(bridge.control('session.create')['sessionId'],'ses_trial')
        self.assertEqual(api.call_args_list[0].args[2]['agent'],'build')
        self.assertEqual(api.call_args_list[1].args[1],'/api/session/ses_trial/environment')

    def test_unconfirmed_experimental_agent_stops_before_further_api_calls(self):
        bridge=NativeBridge('/synthetic/source','/synthetic/account',agent='build')
        with patch.object(bridge,'api',return_value={'data':{'id':'ses_trial'}}) as api:
            with self.assertRaisesRegex(ValueError,'before model work'):
                bridge.control('session.create')
        self.assertEqual(api.call_count,1)

    def test_trial_cache_and_temporary_files_stay_in_the_synthetic_account(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            bridge=NativeBridge('/synthetic/source',directory)
            with patch.object(bridge,'api',side_effect=[{'data':{'id':'ses_trial'}},{}]) as api:
                bridge.control('session.create')
            variables=api.call_args_list[1].args[2]['variables']
            self.assertEqual(variables['GM_CACHE_DIR'],str(Path(directory)/'cache'))
            self.assertEqual(variables['TMPDIR'],str(Path(directory)/'tmp'))
            self.assertEqual(variables['CALENDAR_DB_PATH'],str(Path(directory)/'calendar.sqlite'))
            self.assertEqual(variables['BETTERBIRD_PATH'],str(Path(directory)/'unconfigured-betterbird'))
            self.assertTrue((Path(directory)/'tmp').is_dir())


if __name__=='__main__':
    unittest.main()
