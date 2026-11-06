"""Focused whole-panel motion, Today badge, hover and gutter-position checks."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from briefing import settle_motion

CENTERED = '''() => {
  const button=document.querySelector('.back-to-top').getBoundingClientRect();
  const edge=document.querySelector('.briefing-section').getBoundingClientRect().right;
  const safe=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--safe-right'))||0;
  return Math.abs(button.x+button.width/2-(edge+document.documentElement.clientWidth-safe)/2)<1;
}'''
# With quick chat shown, the button joins the launcher's row, 10px to its left (#63).
BESIDE_CHAT = '''() => {
  const button=document.querySelector('.back-to-top').getBoundingClientRect();
  const pill=document.querySelector('#quick-chat-launcher').getBoundingClientRect();
  // Stacked above the launcher's right end, so the column reserves only the launcher's width (#284).
  return Math.abs(pill.right-4-button.right)<1&&button.bottom+8<=pill.top;
}'''
# The Today badge's text lines and pill, and the date's text boxes beside it (#258).
BADGE_GLYPHS = '''marker => {
  const boxes=node=>{const range=document.createRange();node.nodeType===3?range.selectNode(node):range.selectNodeContents(node);
    return [...range.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}));};
  const pill=marker.getBoundingClientRect();
  return {lines:boxes(marker),pill:{left:pill.left,right:pill.right,top:pill.top,bottom:pill.bottom},date:[...marker.parentElement.childNodes].filter(n=>n!==marker).flatMap(boxes)};
}'''
# Words of each tile's date label that break across lines, such as 周 and 二 of 周二 (#282).
SPLIT_WORDS = '''picker => [...picker.querySelectorAll('[data-ui-date]')].flatMap(label => {
  const text=label.firstChild, range=document.createRange(), split=[];
  for (const word of text.data.matchAll(/\\S+/g)) {
    const tops=new Set([...word[0]].map((_,i)=>{range.setStart(text,word.index+i);range.setEnd(text,word.index+i+1);return Math.round(range.getBoundingClientRect().top);}));
    if (tops.size>1) split.push(word[0]);
  }
  return split.length?[{label:text.data,split}]:[];
})'''


def set_language(page,language):
    page.locator('#prefs-menu > summary').click()
    page.locator('#website-language').select_option(language)
    expect(page.locator('html')).to_have_attribute('lang',language)
    page.locator('#prefs-menu > summary').click()


def check_today_badge(page):
    """On phones, no date label word wraps, and the badge stays on one line clear of the date, in both languages."""
    try:
        for language in ('zh-CN','en'):
            set_language(page,language)
            # A reload renders the labels on the server, as a saved language does; they are wider than
            # the ones the language switch formats in the page.
            page.reload();page.evaluate('document.fonts.ready')
            for width,height in [(390,844),(320,568)]:
                page.set_viewport_size({'width':width,'height':height})
                page.evaluate("scrollTo({top:0,behavior:'instant'})")
                split=page.locator('.week-picker').evaluate(SPLIT_WORDS)
                assert not split,(language,width,'date label wraps inside a word',split)
                boxes=page.locator('.today-marker').evaluate(BADGE_GLYPHS)
                b,date=boxes['pill'],boxes['date']
                assert len({round(line['top']) for line in boxes['lines']})==1,(language,width,'badge wraps',boxes['lines'])
                # 1px slack: the pill may touch the date's line box, whose top is font ascent space, not ink.
                assert date and not any(b['left']<d['right'] and d['left']<b['right'] and b['top']<d['bottom'] and d['top']<b['bottom']-1
                                        for d in date),(language,width,'badge covers the date',boxes)
    finally:
        # The language is saved to the account, so later checks and reruns need English back.
        if page.evaluate('document.documentElement.lang')!='en':set_language(page,'en')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    parser.add_argument('--artifacts',type=Path)
    args=parser.parse_args()
    if args.artifacts:args.artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    report=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for kind in ('gm','gn'):
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'{args.url}/{kind}')
            page.evaluate('document.fonts.ready')
            expect(page.locator('.today-marker')).to_have_count(1)
            expect(page.locator('.today-marker')).to_have_text('Today')
            expect(page.locator('.today-marker')).to_be_visible()
            settle_motion(page)
            if args.artifacts:page.screenshot(path=str(args.artifacts/f'{kind}-today-desktop.png'))
            # Trigger a section below the initial fold and inspect its actual motion.
            section=page.locator('.briefing-section').nth(2)
            page.evaluate('''() => scrollTo({top:document.querySelectorAll('.briefing-section')[2].offsetTop-innerHeight*.8,behavior:'instant'})''')
            page.wait_for_function('''() => document.querySelectorAll('.briefing-section')[2].getAnimations().some(a=>a.animationName==='arrive'&&a.playState==='running')''')
            section.evaluate('''el => { const a=el.getAnimations().find(a=>a.animationName==='arrive'); a.pause(); a.currentTime=120; }''')
            moving=section.evaluate('''el=>({top:el.getBoundingClientRect().top,
              header:el.querySelector('header').getBoundingClientRect().top,
              body:el.querySelector('.section-body').getBoundingClientRect().top,
              opacity:parseFloat(getComputedStyle(el).opacity),
              transform:getComputedStyle(el).transform,
              titleTransform:getComputedStyle(el.querySelector('h2')).transform})''')
            assert moving['opacity']<.5 and moving['transform']==moving['titleTransform']=='none',moving
            if args.artifacts:page.screenshot(path=str(args.artifacts/f'{kind}-whole-panel-motion.png'))
            # Inspect actual glyph boxes, not just the title/body containers.
            glyphs='''el=>{ const nodes=[el.querySelector('h2'),el.querySelector('.section-body')];
              return nodes.map(node=>{const range=document.createRange();range.selectNodeContents(node);
                return [...range.getClientRects()].map(r=>({x:r.x,y:r.y,width:r.width,height:r.height}));}); }'''
            snapshots=[]
            for time in (0,120,400,750,799):
                section.evaluate("(el,time)=>{el.getAnimations().find(a=>a.animationName==='arrive').currentTime=time;}",time)
                snapshots.append(section.evaluate(glyphs))
            assert all(sample==snapshots[0] for sample in snapshots),'Glyph positions shifted during entrance or settling'
            if args.artifacts:section.locator('h2').screenshot(path=str(args.artifacts/f'{kind}-text-before-settle.png'))
            section.evaluate("el=>el.getAnimations().find(a=>a.animationName==='arrive').finish()")
            if args.artifacts:section.locator('h2').screenshot(path=str(args.artifacts/f'{kind}-text-after-settle.png'))
            assert section.evaluate(glyphs)==snapshots[0],'Glyph positions snapped at animation completion'
            finished=section.evaluate('''el=>({top:el.getBoundingClientRect().top,
              header:el.querySelector('header').getBoundingClientRect().top,
              body:el.querySelector('.section-body').getBoundingClientRect().top})''')
            for child in ('header','body'):
                assert abs((moving[child]-moving['top'])-(finished[child]-finished['top']))<1,'Content animated independently of panel'
            # Hover is decorative only: changed paint, no movement or pointer cursor.
            checked=[]
            for selector in ('.weather-tile','.news-card','.agenda-event','.task-card'):
                if not page.locator(selector).count():continue
                card=page.locator(selector).first
                card.scroll_into_view_if_needed();page.mouse.move(0,0);settle_motion(page)
                read="el=>({background:getComputedStyle(el).backgroundColor,border:getComputedStyle(el).borderColor,shadow:getComputedStyle(el).boxShadow,transform:getComputedStyle(el).transform,cursor:getComputedStyle(el).cursor})"
                before=card.evaluate(read)
                card.hover();settle_motion(page)
                after=card.evaluate(read)
                assert before!=after and after['cursor']=='auto' and before['transform']==after['transform']=='none',(selector,before,after)
                if args.artifacts:card.screenshot(path=str(args.artifacts/f'{kind}-{selector[1:]}-hover.png'))
                checked.append(selector)
            page.mouse.move(0,0)
            page.emulate_media(reduced_motion='reduce')
            for width,height in [(1440,1000),(1920,1080),(390,844),(320,568)]:
                page.set_viewport_size({'width':width,'height':height})
                page.evaluate("scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'})")
                if width<=700:
                    # Phones offer Back to top in the section picker instead of a floating button.
                    expect(page.locator('.back-to-top')).to_be_hidden();continue
                expect(page.locator('#quick-chat-launcher')).to_be_visible()
                page.wait_for_function(BESIDE_CHAT)
                expect(page.locator('.back-to-top')).to_be_visible()
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                assert page.locator('.briefing-section').evaluate_all("els=>els.every(el=>getComputedStyle(el).animationName==='none')")
                if args.artifacts:page.screenshot(path=str(args.artifacts/f'{kind}-corner-button-{width}.png'))
                page.evaluate("scrollTo({top:0,behavior:'instant'})")
                expect(page.locator('.today-marker')).to_be_visible()
                if args.artifacts and width<=390:page.screenshot(path=str(args.artifacts/f'{kind}-today-{width}.png'))
            # Without quick chat, the button centres in the content gutter beside the sections.
            page.locator('#quick-chat-launcher').evaluate('el=>el.hidden=true')
            for width,height in [(1440,1000),(1920,1080)]:
                page.set_viewport_size({'width':width,'height':height})
                page.evaluate("scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'})")
                page.wait_for_function(CENTERED)
                box=page.locator('.back-to-top').bounding_box()
                edge=page.locator('.briefing-section').first.bounding_box()
                assert box['x']>=edge['x']+edge['width']+20
                assert page.evaluate('document.documentElement.clientWidth')-box['x']-box['width']>=27
                if args.artifacts:page.screenshot(path=str(args.artifacts/f'{kind}-centered-button-{width}.png'))
            check_today_badge(page)
            if args.artifacts:page.locator('.week-picker').screenshot(path=str(args.artifacts/f'{kind}-today-badge-320.png'))
            assert not errors,errors
            report.append({'edition':kind,'whole_panel_motion':'stronger fade; stationary glyphs through final frame','hover':checked,'today_badge':'date words unbroken; badge on one line, clear of the date at 390 and 320 px in zh-CN and en','corner_button':'above quick chat and centred without it at two desktop widths; hidden on phones','reduced_motion':'pass'})
            page.close()
        browser.close()
    print(json.dumps(report))


if __name__=='__main__':main()
