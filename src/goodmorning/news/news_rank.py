"""Transparent importance proxies, not an objective measure of news importance.

Signals use headlines and short publisher feed excerpts. Coverage/engagement are
weak prominence signals, never independent verification. Political lean is unused.
"""

import re
from datetime import datetime
from urllib.parse import urlsplit

POLICY = "importance-first-v1"


def terms(english, chinese=""):
    """English words need ASCII boundaries: CJK characters count as word characters
    for \\b, so "发布AI模型" would otherwise never match. Chinese terms have no boundaries."""
    pattern = r"(?<![A-Za-z0-9])(?:" + english + r")(?![A-Za-z0-9])"
    return pattern + ("|" + chinese if chinese else "")


AI_PATTERN = re.compile(terms(
    r"AI|artificial intelligence|machine learning|deep learning|LLMs?|"
    r"large language models?|OpenAI|ChatGPT|Anthropic|Claude|DeepSeek|"
    r"GPT[-\s]?\d|generative|neural networks?|Gemini|Llama|Qwen|Mistral|Kimi|"
    r"AlphaFold|reasoning models?|speech recognition|open (?:weights? |source )?models?",
    r"人工智能|机器学习|深度学习|大模型|大语言模型|语言模型|生成式|神经网络|智能体|"
    r"推理模型|语音识别|开源模型|通义千问|文心一言|豆包|智谱|月之暗面"), re.IGNORECASE)


def ai_relevance(story):
    """Conservative text signal, not factual verification or a feed-label shortcut."""
    text = story.get('title', '') + ' ' + story.get('summary', '') + ' ' + ' '.join(
        source.get('summary', '') for source in story.get('sources', []))
    return bool(AI_PATTERN.search(text))


def source_genre(source):
    path = urlsplit(source["url"]).path.casefold()
    if "/opinion/" in path or "/commentisfree/" in path:
        return "opinion"
    if "/sport/" in path or "/sports/" in path:
        return "sport"
    if any(part in path for part in ("/books/", "/music/", "/film/", "/lifeandstyle/", "/fashion/")):
        return "entertainment"
    return "news"


def importance(story):
    title = story["title"].casefold()
    relevant = story['section'] != 'ai' or ai_relevance(story)
    context = title + " " + " ".join(source.get("summary", "") for source in story["sources"])
    reasons, score = [], 0
    def signal(pattern, weight, reason, text=context):
        nonlocal score
        if re.search(pattern, text, re.I):
            headline = bool(re.search(pattern, title, re.I))
            score += weight if weight < 0 or headline else min(weight, 2)
            reasons.append(reason if weight < 0 or headline else "context_" + reason)
            return True
        return False
    if story["section"] == "ai":
        released = re.search(terms(r"launch\w*|releas\w*|introduc\w*|unveil\w*|announc\w*|open[- ]sourc\w*",
                                   r"发布|推出|上线|开源|亮相"), title)
        technical = re.search(terms(r"models?|agents?|APIs?|weights|reasoning|security|scans?|chips?|GPUs?|inference|ASR|speech|robot\w*",
                                    r"模型|智能体|芯片|算力|推理|语音|机器人"), context, re.I)
        if released and technical:
            score += 6
            reasons.append("model_or_tool_release")
        signal(terms(r"research|benchmark\w*|reasoning|scientific|open weights|multimodal|clinical|drug discovery|protein|foundation model",
                     r"研究|基准|多模态|科研|蛋白质|药物研发|基础模型"), 5, "research_or_capability")
        signal(terms(r"safety|security|vulnerabilit\w*|cyberattack\w*|data breach|alignment|misconduct|copyright|lawsuit|antitrust|regulat\w*|export controls?",
                     r"安全|漏洞|网络攻击|数据泄露|对齐|版权|诉讼|反垄断|监管|出口管制"), 7, "safety_security_or_governance")
        signal(terms(r"acquisition|merger|funding|investment|valuation|data centres?|data centers?|chip ban|compute infrastructure",
                     r"收购|并购|融资|投资|估值|数据中心|芯片禁令"), 4, "industry_or_infrastructure")
        signal(terms(r"newsletter|round[- ]?up|the download|weekly digest", r"周报|速览|一周回顾"), -8, "roundup_not_a_specific_development", title)
        signal(terms(r"disrupt \d{4}|buy tickets|pass savings|prices rise|discount|sponsored|campaigns with|creative ideas into campaigns",
                     r"优惠|折扣|限时|购票|赞助"), -12, "promotion", title)
        signal(terms(r"turns? (?:days|creative ideas)|customer stor\w*|case stud\w*", r"客户案例"), -10, "customer_marketing", title)
        signal(r"^show hn\b", -3, "self_promoted_project", title)
    else:
        signal(terms(r"(?<!trade )(?<!trade-)war|invasion|ceasefire|peace deal|missile\w*|airstrikes?|nuclear|hurricane|earthquake|wildfires?|Ebola|pandemic|epidemic|outbreak|famine|mass casualties",
                     r"(?<!贸易)战争|入侵|停火|和平协议|导弹|空袭|核武|核电|飓风|台风|地震|山火|埃博拉|疫情|饥荒|伤亡"), 8, "conflict_disaster_or_public_health")
        signal(terms(r"elections?|by[- ]elections?|government|parliament|prime minister|president|supreme court|international law|sanctions|tariffs?|trade war|budget|tax break|interest rates?|central bank|NHS|healthcare|mental health review|legislation|national security",
                     r"选举|大选|政府|国务院|议会|国会|人大|总理|总统|国家主席|最高法院|国际法|制裁|关税|贸易战|预算|减税|利率|央行|医保|医疗|立法|国家安全"), 7, "public_affairs_or_economic_consequence")
        signal(terms(r"actor|singer|celebrity|prince harry|duke of sussex|memoir|last dancer|punk turns|football|premier league",
                     r"明星|演员|歌手|网红|综艺|足球|英超"), -10, "entertainment_or_personal_story", title)
        signal(terms(r"trespass|shoplift\w*|parking dispute|mother of.*worker|know the truth"), -6, "isolated_incident_or_human_interest", title)
    signal(r"^(?:opinion|comment|why\b)|\b(?:opinion:|editorial:)\b|^(?:评论|社评|社论|观点)[:：]", -2, "background_or_opinion", title)
    genres = {source_genre(source) for source in story["sources"]}
    genre = "news" if "news" in genres else sorted(genres)[0]
    if genre != "news":
        score -= 10
        reasons.append("publisher_" + genre + "_not_straight_news")
    coverage = min(max(story["outlets"] - 1, 0), 3)
    if coverage:
        score += coverage
        reasons.append("multiple_publisher_domains")
    priority = max((source.get("priority", 0) for source in story["sources"]), default=0)
    score += priority
    if priority:
        reasons.append("configured_editorial_priority")
    points = max((source.get("points", 0) for source in story["sources"]), default=0)
    if points >= 100:
        score += 1
        reasons.append("discussion_interest_not_verification")
    if story.get("date_basis", "published") != "published":
        score -= 2
        reasons.append("discovery_or_update_date_not_publication")
    if all(source.get("role") == "primary" for source in story["sources"]):
        if not any(reason in reasons for reason in ("model_or_tool_release", "research_or_capability", "safety_security_or_governance", "industry_or_infrastructure")):
            score -= 4
            reasons.append("first_party_without_substantive_signal")
        reasons.append("first_party_claims")
    if not relevant:
        reasons.append('no_explicit_ai_relevance_in_collected_text')
    return {"policy": POLICY, "score": score, "reasons": reasons or ["no_identified_impact_signal"],
            "eligible": relevant and score >= 5 and genre == "news", "genre": genre,
            **({'ai_relevant':relevant} if story['section'] == 'ai' else {})}


def rank_stories(stories):
    ranked = [{**story, "ranking": importance(story)} for story in stories]
    ranked.sort(key=lambda story: (story["date"], story["section"], -story["ranking"]["score"],
                -max(datetime.fromisoformat(source["published"]).timestamp()
                     for source in story["sources"]), story["title"].casefold()))
    return ranked
