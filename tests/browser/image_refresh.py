"""Late cached images refresh an existing news preview without rewriting its text."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from goodmorning.briefings.briefing_stream import publish
from goodmorning.runtime_files import atomic_text


def main():
    results=[]
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-image-refresh-') as directory:
        runtime=Path(directory)
        (runtime/'profile.md').write_text('timezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (runtime/'daily').mkdir()
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('stream.py')),'--serve',directory],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(address+'/gm.html');page.locator('#generate').click()
                expect(page.get_by_role('heading',name='How did today go?')).to_be_visible()
                job=next(iter(json.loads((runtime/'browser-jobs/jobs.json').read_text()).values()))
                from datetime import date,timedelta
                yesterday=(date.fromisoformat(job['date'])-timedelta(days=1)).isoformat()
                plan=[['news','News — '+yesterday],['schedule','Schedule']]
                document={'v':1,'greeting':'Morning.','opening':'One section at a time.','sections':[]}
                publish(runtime,job['id'],document,plan)
                url='https://example.org/story'
                document=deepcopy(document)
                document['sections']=[['news',[['news','World',[['Synthetic headline','A sourced synthetic summary.',[['Publisher',url]]]]]]]]
                publish(runtime,job['id'],document)
                expect(page.locator('#section-1')).not_to_have_attribute('data-pending','true')
                expect(page.locator('#section-1 img')).to_have_count(0)
                before=(runtime/'browser-jobs'/(job['id']+'.preview.json')).read_bytes()
                page.evaluate('window.savedNewsNode=document.querySelector("#section-1"); window.savedNewsText=savedNewsNode.querySelector(".news-copy").innerText')
                # Fixed, valid 64x48 WebP; no network request or optional Python image dependency.
                image=bytes.fromhex('524946464c0000005745425056503820400000005003009d012a400030003e6d369849242322a122a800800d8967000013f193db5f0fc000fefa68abfffe849fffc4d9fff49b3e115fd25d2e34d7a3c710000000')
                digest=hashlib.sha256(image).hexdigest();cache=runtime/'browser-images'/job['date'];cache.mkdir(parents=True)
                (cache/(digest+'.webp')).write_bytes(image)
                atomic_text(cache/'manifest.json',json.dumps({url:{'status':'cached','file':digest+'.webp','sha256':digest,'alt':'Synthetic publisher preview'}}))
                page.evaluate('void poll()')
                expect(page.locator('#section-1 img')).to_have_count(1)
                expect(page.locator('#section-1 img')).to_have_attribute('src','/media/'+digest+'.webp')
                page.locator('#section-1 img').scroll_into_view_if_needed()
                expect(page.locator('#section-1 img')).to_have_js_property('naturalWidth',64)
                assert page.evaluate('savedNewsNode===document.querySelector("#section-1") && savedNewsText===savedNewsNode.querySelector(".news-copy").innerText')
                expect(page.locator('#section-1')).not_to_have_class(re.compile(r'\barriving\b'))
                expect(page.locator('#section-2')).to_have_attribute('data-pending','true')
                assert before==(runtime/'browser-jobs'/(job['id']+'.preview.json')).read_bytes()
                assert not list((runtime/'daily').iterdir()) and not errors
                page.reload();expect(page.locator('#section-1 img')).to_have_count(1)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                results.append({'lateImage':'appears without page reload','textAndCheckpoint':'unchanged','laterSection':'queued','refresh':'image retained','pageErrors':0})
                browser.close()
        finally:
            process.terminate();process.communicate(timeout=5)
    print(json.dumps({'modelCalls':0,'agent':'synthetic','checks':results}))


if __name__=='__main__':main()
