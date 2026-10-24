"""
Evidence gathered by code (not by the model) before research:
- AskNews: latest news articles (1 API call per question, free tier allows 1 call per 10s).
- Prediction markets: Kalshi, Polymarket and Manifold prices for matching markets.
- Metaculus main site: community predictions on related questions, when the API shows them.

Every source is optional and failures are swallowed: missing evidence must never
stop a forecast. Using public forecasts from other platforms and from Metaculus
itself is explicitly allowed by the FutureEval rules.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

import requests
from forecasting_tools import MetaculusQuestion, clean_indents

from claude_code_llm import ClaudeCodeLlm

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20
# Bot-only tournaments never show a community prediction, and one of them is
# the question being forecast, so they are excluded from Metaculus lookups.
_BOT_TOURNAMENT_HINTS = ("futureeval", "minibench", "bot-testing", "aib")

_asknews_lock = asyncio.Lock()
_asknews_last_call = 0.0


async def make_search_queries(question: MetaculusQuestion) -> list[str]:
    """Two or three short keyword queries for market and news search."""
    llm = ClaudeCodeLlm(model="haiku", effort=None, purpose="queries", allowed_tries=1)
    prompt = clean_indents(
        f"""
        Write 3 short search queries (2 to 5 words each) that would find prediction markets
        or news about this forecasting question. Use the key entities and the measured quantity.
        Output one query per line and nothing else.

        Question: {question.question_text}
        """
    )
    try:
        text = await llm.invoke(prompt)
        queries = [q.strip(" -*\"'") for q in text.splitlines() if q.strip()]
        return [q for q in queries if 1 <= len(q.split()) <= 8][:3]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Query generation failed, using title words: {e}")
        words = re.findall(r"[A-Za-z0-9$%.]+", question.question_text)
        return [" ".join(words[:6])]


async def asknews_articles(question: MetaculusQuestion) -> str:
    if not os.getenv("ASKNEWS_API_KEY") and not os.getenv("ASKNEWS_CLIENT_ID"):
        return ""
    from asknews_sdk import AsyncAskNewsSDK

    global _asknews_last_call
    async with _asknews_lock:
        wait = 11 - (time.time() - _asknews_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _asknews_last_call = time.time()
        async with AsyncAskNewsSDK(
            api_key=os.getenv("ASKNEWS_API_KEY"),
            client_id=os.getenv("ASKNEWS_CLIENT_ID"),
            client_secret=os.getenv("ASKNEWS_SECRET"),
            scopes={"news"},
        ) as ask:
            response = await ask.news.search_news(
                query=question.question_text,
                n_articles=8,
                return_type="dicts",
                strategy="latest news",
            )
    articles = sorted(response.as_dicts, key=lambda a: a.pub_date, reverse=True)
    lines = [
        f"- {a.pub_date:%Y-%m-%d}: {a.eng_title}. {a.summary[:400]} [source]({a.article_url})"
        for a in articles
    ]
    return "\n".join(lines)


_STOPWORDS = {"will", "what", "when", "price", "2026", "2027", "the", "and", "for", "news", "forecast"}


def _relevant(query: str, title: str) -> bool:
    """Polymarket and Manifold return trending markets when nothing matches."""
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}
    words -= _STOPWORDS
    title = title.lower()
    return any(w in title for w in words)


def _kalshi_price(m: dict) -> str:
    bid, ask = m.get("yes_bid"), m.get("yes_ask")
    if bid and ask:
        return f"{(bid + ask) / 200:.2f}"
    return str(m.get("last_price_dollars") or "n/a")


def _kalshi(query: str) -> list[str]:
    r = requests.get(
        "https://api.elections.kalshi.com/v1/search/series",
        params={"query": query},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for event in r.json().get("current_page", [])[:3]:
        markets = []
        for m in (event.get("markets") or [])[:10]:
            markets.append(f"{m.get('yes_subtitle') or m.get('title')}: {_kalshi_price(m)}")
        feed = (event.get("product_metadata") or {}).get("pyth_symbol")
        settles = f" Settles on the Pyth feed {feed}, which can differ from exchange settlement prices." if feed else ""
        out.append(
            f"- Kalshi: {event.get('event_title')} ({event.get('event_subtitle')}). "
            f"Yes prices: {'; '.join(markets)}.{settles}"
        )
    return out


def _polymarket(query: str) -> list[str]:
    r = requests.get(
        "https://gamma-api.polymarket.com/public-search",
        params={"q": query, "limit_per_type": 3, "events_status": "active"},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for event in r.json().get("events", [])[:3]:
        if not _relevant(query, str(event.get("title"))):
            continue
        markets = []
        for m in (event.get("markets") or [])[:6]:
            markets.append(f"{m.get('groupItemTitle') or m.get('question')}: {m.get('outcomePrices')}")
        out.append(
            f"- Polymarket: {event.get('title')} (ends {str(event.get('endDate'))[:10]}). "
            f"[Yes, No] prices: {'; '.join(markets)}"
        )
    return out


def _manifold(query: str) -> list[str]:
    r = requests.get(
        "https://api.manifold.markets/v0/search-markets",
        params={"term": query, "limit": 4, "filter": "open"},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for m in r.json()[:4]:
        if not _relevant(query, str(m.get("question"))):
            continue
        prob = m.get("probability")
        prob_text = f"{prob:.0%}" if isinstance(prob, (int, float)) else m.get("outcomeType")
        out.append(f"- Manifold: {m.get('question')} ({prob_text}) {m.get('url')}")
    return out


def _metaculus(query: str) -> list[str]:
    token = os.getenv("METACULUS_TOKEN")
    if not token:
        return []
    r = requests.get(
        "https://www.metaculus.com/api/posts/",
        params={"search": query, "statuses": "open", "limit": 8},
        headers={"Authorization": f"Token {token}"},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for post in r.json().get("results", []):
        slugs = " ".join(
            str(t.get("slug", "")) for t in (post.get("projects", {}).get("tournament") or [])
        )
        if any(h in slugs for h in _BOT_TOURNAMENT_HINTS):
            continue
        question = post.get("question") or {}
        aggregations = question.get("aggregations") or {}
        latest = (aggregations.get("recency_weighted") or {}).get("latest") or {}
        centers = latest.get("centers")
        if not centers:
            continue  # without a visible community prediction the title alone adds little
        out.append(
            f"- Metaculus community prediction: {post.get('title')} -> {centers} "
            f"(https://www.metaculus.com/questions/{post['id']}/)"
        )
    return out


async def market_and_metaculus_evidence(queries: list[str]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for fetch in (_kalshi, _polymarket, _manifold, _metaculus):
        for query in queries:
            try:
                for line in await asyncio.to_thread(fetch, query):
                    if line not in seen:
                        seen.add(line)
                        lines.append(line)
            except Exception as e:  # noqa: BLE001
                logger.info(f"{fetch.__name__} lookup failed for '{query}': {e}")
    return "\n".join(lines)


async def gather_evidence(question: MetaculusQuestion) -> tuple[str, str]:
    """Returns (news, markets). Either may be empty."""
    queries = await make_search_queries(question)
    news, markets = await asyncio.gather(
        asknews_articles(question),
        market_and_metaculus_evidence(queries),
        return_exceptions=True,
    )
    if isinstance(news, BaseException):
        logger.warning(f"AskNews failed: {news}")
        news = ""
    if isinstance(markets, BaseException):
        logger.warning(f"Market lookup failed: {markets}")
        markets = ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if markets:
        markets = f"(prices fetched {stamp}; check each market really matches the question)\n{markets}"
    return news, markets
