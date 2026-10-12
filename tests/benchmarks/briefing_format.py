"""Equal-content format experiment; optional tiktoken/PyYAML, no model calls."""
import hashlib
import json
import statistics
from datetime import date,timedelta
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))


def dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def fixtures():
    samples=[]
    for language in ('en','zh'):
        for count in (2,8,16):
            for kind in ('gm','gn'):
                greeting=('Good morning.' if kind=='gm' else 'Good evening.') if language=='en' else ('早上好。' if kind=='gm' else '晚上好。')
                opening='Give the important things some room today.' if language=='en' else '今天先给重要的事情留出一点空间。'
                sections=[]
                if kind=='gm':
                    sections.append(['weather','Weather',[['weather',[
                        ['temperature','Temperature','14°C','London; range 9–16°C. Bring a jacket.'],
                        ['precipitation','Precipitation','40%','Rain possible after 15:00.'],
                        ['air','AQI','31','Good air; no special precautions.']]]],'Leave a little extra time if the afternoon turns wet.'])
                    stories=[]
                    for i in range(count):
                        headline=f'Research update {i}' if language=='en' else f'研究进展 {i}'
                        summary='A reported result with an important limitation; independent replication is still needed.' if language=='en' else '研究报告了一个结果，但仍存在重要局限，需要独立重复验证。'
                        stories.append([headline,summary,[[f'Publisher {i}',f'https://example.org/research/{i}?ref=digest']]])
                    sections.append(['news','News — 2034-03-16',[['news','AI',stories]],'Interesting work; the limitation matters as much as the headline.'])
                else:
                    sections.append(['today','Today',[['p','You reported partial progress on the analysis, not completion.']],'The useful next step is now clearer.'])
                columns=['Date','Time','Event','Place','Preparation']
                rows=[[f'2034-03-{17+i//3}',f'{9+i%3:02}:00–{10+i%3:02}:00',f'Review {i}','Room A','Bring notes; timing is confirmed.'] for i in range(count)]
                sections.append(['schedule' if kind=='gm' else 'tomorrow','Schedule' if kind=='gm' else 'Tomorrow',[
                    ['p','Timezone: Europe/London. Only approved events are shown.'],['table',columns,rows]],'Keep the gaps between appointments available.'])
                for section_type,title in ([('must-do','Project steps'),('nice-to-do','Optional project steps')] if kind=='gm' else [('still-open','Still open')]):
                    items=[['open',f'{title}: analysis task {i}','Compare the two validation settings; due 2034-03-20.'] for i in range(count)]
                    sections.append([section_type,title,[['tasks',items]],'Choose one focused block before adding another experiment.'])
                doc={'v':1,'greeting':greeting,'opening':opening,'sections':sections,'closing':'A grounded closing, without inventing progress.'}
                if language=='zh':
                    doc['lang']='zh-CN'
                    translated={'weather':'天气','news':'新闻 — 2034-03-16','today':'今日进展','schedule':'日程',
                                'tomorrow':'明日日程','must-do':'项目推进','nice-to-do':'可选项目推进','still-open':'尚未完成'}
                    for section in sections:
                        section[1]=translated[section[0]]
                        for block in section[2]:
                            if block[0]=='weather':
                                for row,label in zip(block[1],['气温','降水','空气质量']):row[1]=label
                            if block[0]=='table':block[1]=['日期','时间','活动','地点','准备']
                samples.append({'name':f'{language}-{kind}-{count}','date':'2034-03-17','kind':kind,'doc':doc})
    return samples


def links(sources):
    return ' '.join(f'[{label}]({url})' for label,url in sources)


def markdown_pair(sample):
    doc=sample['doc']
    parts=[doc['greeting']+' — '+sample['date']]
    takeaways={}
    for section in doc['sections']:
        kind,title,blocks,*note=section
        body=[]
        for block in blocks:
            tag=block[0]
            if tag=='weather':
                body.extend(f'### {label}\n- '+('' if value is None else value+'; ')+detail for _,label,value,detail in block[1])
            elif tag=='news':
                body.append('### '+block[1])
                body.extend(f'- {headline} — {summary} {links(sources)}' for headline,summary,sources in block[2])
            elif tag=='table':
                columns,rows=block[1:]
                body.append('| '+' | '.join(columns)+' |\n|'+ '|'.join('---' for _ in columns)+'|\n'+'\n'.join('| '+' | '.join(row)+' |' for row in rows))
            elif tag=='tasks':
                body.extend(f'- [{"x" if status=="done" else " "}] **{title}** — {detail}' for status,title,detail in block[1])
            elif tag=='p':body.append(block[1])
        parts.append('## '+title+'\n\n'+'\n\n'.join(body))
        if note:takeaways[kind]=note[0]
    parts.append(doc.get('closing',''))
    source='\n\n---\n\n'.join(parts)+'\n'
    presentation={'greeting':doc['greeting'],'opening':doc['opening'],'takeaways':takeaways}
    return source,presentation


def named(doc):
    converted=[]
    for section in doc['sections']:
        kind,title,blocks,*note=section
        parts=[]
        for block in blocks:
            tag=block[0]
            if tag=='weather':parts.append({'type':tag,'cards':[dict(zip(('type','label','value','detail'),row)) for row in block[1]]})
            elif tag=='news':parts.append({'type':tag,'category':block[1],'stories':[{'headline':h,'summary':s,'sources':[{'label':label,'url':url} for label,url in sources]} for h,s,sources in block[2]]})
            elif tag=='tasks':parts.append({'type':tag,'items':[dict(zip(('status','title','detail'),row)) for row in block[1]]})
            elif tag=='table':parts.append({'type':tag,'columns':block[1],'rows':block[2]})
            else:parts.append({'type':'text','text':block[1]})
        converted.append({'type':kind,'title':title,'blocks':parts,**({'note':note[0]} if note else {})})
    return {**doc,'sections':converted}


def compact(sample):
    """Omit standard UI labels; custom/translated labels remain explicit."""
    defaults={'weather':'Weather','news':'News — '+(date.fromisoformat(sample['date'])-timedelta(days=1)).isoformat(),
              'schedule':'Schedule','tomorrow':'Tomorrow','today':'Today','must-do':'Project steps','nice-to-do':'Optional project steps','still-open':'Still open','reminders':'Reminders','notes':'Notes'}
    sections=[]
    for kind,title,blocks,*note in sample['doc']['sections']:
        native=[]
        for block in blocks:
            if block[0]=='weather':
                labels={'temperature':'Temperature','precipitation':'Precipitation','air':'AQI','warning':'Extreme warning'}
                rows=[]
                for row_type,label,value,detail in block[1]:
                    row=[row_type,value,detail]
                    if label!=labels[row_type]:row.append(label)
                    rows.append(row)
                native.append(['weather',rows])
            elif block[0]=='table' and len(block[1])==5:
                agenda=['agenda',block[2]]
                if block[1]!=['Date','Time','Event','Place','Preparation']:agenda.append(block[1])
                native.append(agenda)
            else:native.append(block)
        section=[kind,native]
        if note or title!=defaults[kind]:section.append(note[0] if note else '')
        if title!=defaults[kind]:section.append(title)
        sections.append(section)
    return {**sample['doc'],'sections':sections}


def main():
    import tiktoken
    import yaml
    from goodmorning.briefings import briefing_document as native
    from goodmorning.briefings import briefing_web as web
    report=[]
    storage={'markdown+presentation':0,'compact-json':0}
    timings={'compact-json':[]}
    sample_data=[]
    for sample in fixtures():
        source,presentation=markdown_pair(sample)
        payload=dump(compact(sample))
        native.parse(payload)
        storage['markdown+presentation']+=len(source.encode())+len(dump({**presentation,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}).encode())
        storage['compact-json']+=len((payload+'\n').encode())
        sample_data.append((sample,source,presentation,payload))
    # Warm imports, then seven paired batches; alternate order to reduce drift.
    names = list(timings)
    for batch in range(8):
        for name in (names if batch % 2 == 0 else names[::-1]):
            start=time.perf_counter()
            for sample,source,presentation,payload in sample_data:
                for _ in range(8):
                    doc=native.parse(payload)
                    web.edition(doc,sample['date'],sample['kind'],{sample['kind']:True})
            timings[name].append((time.perf_counter()-start)*1000/(len(sample_data)*8))
    timings = {name: round(statistics.median(values[1:]), 3) for name, values in timings.items()}
    for encoding_name in ('o200k_base','cl100k_base'):
        encoding=tiktoken.get_encoding(encoding_name)
        totals={name:0 for name in ('markdown+presentation','named-json','compact-json','yaml')}
        changes=[]
        for sample in fixtures():
            source,presentation=markdown_pair(sample)
            alternatives={'markdown+presentation':source+dump(presentation),'named-json':dump(named(sample['doc'])),
                          'compact-json':dump(compact(sample)),'yaml':yaml.safe_dump(named(sample['doc']),allow_unicode=True,sort_keys=False)}
            tokens={name:len(encoding.encode(text)) for name,text in alternatives.items()}
            for name,count in tokens.items():totals[name]+=count
            changes.append((tokens['compact-json']/tokens['markdown+presentation']-1)*100)
        report.append({'encoding':encoding_name,'samples':len(fixtures()),'authored_tokens':totals,
                       'compact_change_percent':round((totals['compact-json']/totals['markdown+presentation']-1)*100,2),
                       'per_case_change_range_percent':[round(min(changes),2),round(max(changes),2)]})
    print(json.dumps({'comparison':report,'stored_bytes':storage,
                      'storage_change_percent':round((storage['compact-json']/storage['markdown+presentation']-1)*100,2),
                      'median_compile_ms_per_edition':timings,
                      'native_contract_input_tokens_o200k':len(tiktoken.get_encoding('o200k_base').encode((ROOT/'docs/briefing-format.md').read_text())),
                      'scope':'Equivalent synthetic content; tokenizers are proxies, not the user’s OpenChamber default model. Authoring counts exclude instructions, tool envelopes and minification commands. Local parse/validate/render only, no filesystem/network/cache. No LLM authoring error rate or paid generations measured.'}))


if __name__=='__main__':main()
