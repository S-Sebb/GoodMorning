"""Editorial selection uses collected evidence, not fabricated links or scores."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from goodmorning.news import news
from goodmorning.news.news_editorial import candidates, curate, seal
from goodmorning.news.news_reports import ReportStore, context_key


def batch():
    stories=[{"date":"2026-10-08","section":section,"title":title,"outlets":1,
              "links":[{"source":"Synthetic","url":"https://example.invalid/"+section}],
              "ranking":{"eligible":False,"genre":"news","score":0}} for section,title in (
                  ("ai","New open model release"),("major","Drone attack across a national border"),("national","Changes to nationwide school funding"))]
    return seal({"date":"2026-10-08","counts":{"ai":1,"major":1,"national":1},"notes":[],
                 "stories":stories,"candidates":candidates(stories),"max_items":4,
                 "curation":{"required":True,"state":"pending"}})


class EditorialTests(unittest.TestCase):
    def test_review_cannot_override_missing_ai_connection(self):
        value=batch();story=value['stories'][0]
        story['title']='DistroKid removes songs after UMG lawsuit'
        story['ranking']={'ai_relevant':True}
        value['candidates']=candidates(value['stories']);value=seal(value)
        choices=[{'candidate_id':value['candidates'][0]['candidate_id'],'reason':'Copyright has economic consequences.'}]
        with self.assertRaisesRegex(ValueError,'explicit AI connection'):
            curate(value,choices,value['candidate_batch_id'],'ses-test')

    def test_assistant_can_promote_known_consequential_candidates_missed_by_proxy(self):
        value=batch()
        choices=[{"candidate_id":item["candidate_id"],"reason":"A consequential newly reported development, selected after reviewing its source."} for item in value["candidates"]]
        reviewed=curate(value,choices,value["candidate_batch_id"],"ses-test")
        self.assertEqual(reviewed["curation"]["state"],"reviewed")
        self.assertEqual(reviewed["counts"],{"ai":1,"major":1,"national":1})
        self.assertTrue(all("editorial_reason" in item for item in reviewed["stories"]))
        self.assertEqual(value["curation"]["state"],"pending")

    def test_unknown_duplicate_and_unexplained_choices_are_rejected(self):
        value=batch(); key=value["candidates"][0]["candidate_id"]
        cases=[[{"candidate_id":"invented","reason":"unknown"}],
               [{"candidate_id":key,"reason":""}],
               [{"candidate_id":key,"reason":"one"},{"candidate_id":key,"reason":"duplicate"}]]
        for choices in cases:
            with self.assertRaises(ValueError):curate(value,choices,value["candidate_batch_id"],"ses-test")

    def test_modified_evidence_or_stale_batch_id_is_rejected(self):
        value=batch()
        with self.assertRaises(ValueError):curate(value,[],"stale","ses-test")
        expected=value["candidate_batch_id"]
        value["candidates"][0]["links"][0]["url"]="https://example.invalid/fabricated"
        with self.assertRaises(ValueError):curate(value,[],expected,"ses-test")

    def test_pending_editorial_report_cannot_be_acknowledged(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            store=ReportStore(directory,create=True)
            self.addCleanup(store.close)
            value=batch();row=store.save("context",value)
            with self.assertRaisesRegex(ValueError,"editorial_review_required"):
                store.acknowledge("context",value["date"],row["report_id"],"ses-test")

    def test_saved_selection_uses_current_revision_and_keeps_candidate_evidence(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            store=ReportStore(directory,create=True)
            self.addCleanup(store.close)
            value=batch(); row=store.save("context",value)
            choices=[{"candidate_id":item["candidate_id"],"reason":"Reviewed consequence and source."} for item in value["candidates"]]
            reviewed=curate(value,choices,value["candidate_batch_id"],"ses-test")
            with self.assertRaisesRegex(ValueError,"report_conflict"):
                store.save("context",reviewed,expect="stale")
            saved=store.save("context",reviewed,expect=row["report_id"])
            self.assertEqual(len(saved["payload"]["candidates"]),3)
            self.assertEqual(store.acknowledge("context",value["date"],saved["report_id"],"ses-test")["status"],"delivered")

    def test_backfill_prepares_day_specific_candidates_without_calling_an_external_model(self):
        import datetime as dt
        cfg={"feeds":[{"name":"AI","section":"ai","url":"https://ai.invalid/feed","ai_topic":True},
                      {"name":"World","section":"major","url":"https://world.invalid/feed"}],
             "countries":{"GB":[{"name":"UK","section":"national","url":"https://uk.invalid/feed"}]},
             "ranking_policy":"importance-first-v1","editorial_review":True}
        def rss(url,*args):
            title="AI company releases reasoning model" if "ai.invalid" in url else "Government approves NHS budget legislation"
            return [{"title":title,"url":url+str(day),"published":dt.datetime(2026,10,day,12,tzinfo=dt.timezone.utc)} for day in range(2,9)]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            output=io.StringIO()
            with patch.object(news,"load_sources",return_value=cfg),patch.object(news,"fetch_rss",side_effect=rss),contextlib.redirect_stdout(output):
                self.assertEqual(news.main(["--secretary-dir",directory,"--country","GB","--timezone","UTC","--provider","rss","--cache-dir",directory,"--today","2026-10-09","--backfill"]),0)
            data=json.loads(output.getvalue())
            self.assertTrue(all(row["editorial_review_pending"] for row in data["days"]))
            store=ReportStore(directory)
            self.addCleanup(store.close)
            row=store.get(context_key("UTC","GB",cfg),"2026-10-08")
            self.assertTrue(all(item["date"]=="2026-10-08" for item in row["payload"]["candidates"]))

    def test_latest_json_is_sealed_after_rendering_and_can_be_reviewed_without_fetching(self):
        import datetime as dt
        cfg={"feeds":[{"name":"AI","section":"ai","url":"https://ai.invalid/feed","ai_topic":True}],
             "ranking_policy":"importance-first-v1","editorial_review":True}
        today=dt.datetime.now(dt.timezone.utc).date()
        raw=[{"title":"AI company introduces new reasoning model","url":"https://ai.invalid/model",
              "published":dt.datetime.combine(today,dt.time.min,dt.timezone.utc)}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            output=io.StringIO()
            with patch.object(news,"load_sources",return_value=cfg),patch.object(news,"fetch_rss",return_value=raw),contextlib.redirect_stdout(output):
                self.assertEqual(news.main(["--latest","--provider","rss","--timezone","UTC","--cache-dir",directory,"--format","json"]),0)
            data=json.loads(output.getvalue())
            self.assertEqual(seal(data)["candidate_batch_id"],data["candidate_batch_id"])
            source=Path(directory)/"latest.json";source.write_text(json.dumps(data))
            choice=Path(directory)/"choices.json"
            choice.write_text(json.dumps([{"candidate_id":data["candidates"][0]["candidate_id"],"reason":"A concrete model release with developer relevance."}]))
            reviewed=io.StringIO()
            with patch.object(news,"fetch_rss",side_effect=AssertionError("unexpected fetch")),contextlib.redirect_stdout(reviewed):
                self.assertEqual(news.main(["--secretary-dir",directory,"--curate-latest",str(source),"--selection-file",str(choice),"--expect",data["candidate_batch_id"],"--session","ses-test"]),0)
            self.assertEqual(json.loads(reviewed.getvalue())["curation"]["state"],"reviewed")
            self.assertFalse((Path(directory)/"news_reports.sqlite").exists())
            projected=io.StringIO()
            with patch.object(news,"collect",side_effect=AssertionError("unexpected fetch")),contextlib.redirect_stdout(projected):
                self.assertEqual(news.main(["--secretary-dir",directory,"--curate-latest",str(source),"--selection-file",str(choice),
                    "--expect",data["candidate_batch_id"],"--session","ses-test","--view","stories"]),0)
            compact=json.loads(projected.getvalue())
            self.assertEqual(compact["status"],"stateless")
            self.assertEqual(compact["as_of"],data["as_of"])
            self.assertNotIn("candidates",compact)
            self.assertEqual(compact["stories"],json.loads(reviewed.getvalue())["stories"])


if __name__=="__main__":unittest.main()
