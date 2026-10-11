"""Transparent importance proxies, not an objective measure of news importance.

Signals use headlines and short publisher feed excerpts. Coverage/engagement are
weak prominence signals, never independent verification. Political lean is unused.
"""

import re
from datetime import datetime
from urllib.parse import urlsplit

POLICY = "importance-first-v1"
AI_PATTERN = re.compile(
    r"\b(?:AI|artificial intelligence|machine learning|deep learning|LLMs?|"
    r"large language models?|OpenAI|ChatGPT|Anthropic|Claude|DeepSeek|"
    r"GPT[-\s]?\d|generative|neural networks?|Gemini|Llama|Qwen|Mistral|"
    r"AlphaFold|reasoning models?|speech recognition|open (?:weights? |source )?models?)\b", re.IGNORECASE)


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
        released = re.search(r"\b(?:launch\w*|releas\w*|introduc\w*|unveil\w*|announc\w*|open[- ]sourc\w*)\b", title)
        technical = re.search(r"\b(?:models?|agents?|APIs?|weights|reasoning|security|scans?|chips?|GPUs?|inference|ASR|speech|robot\w*)\b", context, re.I)
        if released and technical:
            score += 6
            reasons.append("model_or_tool_release")
        signal(r"\b(?:research|benchmark\w*|reasoning|scientific|open weights|multimodal|clinical|drug discovery|protein|foundation model)\b", 5, "research_or_capability")
        signal(r"\b(?:safety|security|vulnerabilit\w*|cyberattack\w*|data breach|alignment|misconduct|copyright|lawsuit|antitrust|regulat\w*|export controls?)\b", 7, "safety_security_or_governance")
        signal(r"\b(?:acquisition|merger|funding|investment|valuation|data centres?|data centers?|chip ban|compute infrastructure)\b", 4, "industry_or_infrastructure")
        signal(r"\b(?:newsletter|round[- ]?up|the download|weekly digest)\b", -8, "roundup_not_a_specific_development", title)
        signal(r"\b(?:disrupt \d{4}|buy tickets|pass savings|prices rise|discount|sponsored|campaigns with|creative ideas into campaigns)\b", -12, "promotion", title)
        signal(r"\b(?:turns? (?:days|creative ideas)|customer stor\w*|case stud\w*)\b", -10, "customer_marketing", title)
        signal(r"^show hn\b", -3, "self_promoted_project", title)
    else:
        signal(r"\b(?:(?<!trade )(?<!trade-)war|invasion|ceasefire|peace deal|missile\w*|airstrikes?|nuclear|hurricane|earthquake|wildfires?|Ebola|pandemic|epidemic|outbreak|famine|mass casualties)\b", 8, "conflict_disaster_or_public_health")
        signal(r"\b(?:elections?|by[- ]elections?|government|parliament|prime minister|president|supreme court|international law|sanctions|tariffs?|trade war|budget|tax break|interest rates?|central bank|NHS|healthcare|mental health review|legislation|national security)\b", 7, "public_affairs_or_economic_consequence")
        signal(r"\b(?:actor|singer|celebrity|prince harry|duke of sussex|memoir|last dancer|punk turns|football|premier league)\b", -10, "entertainment_or_personal_story", title)
        signal(r"\b(?:trespass|shoplift\w*|parking dispute|mother of.*worker|know the truth)\b", -6, "isolated_incident_or_human_interest", title)
    signal(r"^(?:opinion|comment|why\b)|\b(?:opinion:|editorial:)\b", -2, "background_or_opinion", title)
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
