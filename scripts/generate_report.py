#!/usr/bin/env python3
"""
generate_report.py
Fetches AI & Robotics RSS feeds, summarizes each article with Gemini,
and outputs a JSON file to be uploaded as a GitHub Release asset.
"""

import os
import json
import time
import argparse
import hashlib
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
from xml.etree import ElementTree as ET

import google.generativeai as genai

# ── Sources ──────────────────────────────────────────────────────────────────

SOURCES = [
    # AI Research
    {"name": "Anthropic Blog",    "url": "https://www.anthropic.com/rss.xml",               "category": "AI Research"},
    {"name": "OpenAI Blog",       "url": "https://openai.com/blog/rss.xml",                 "category": "AI Research"},
    {"name": "DeepMind Blog",     "url": "https://deepmind.google/blog/rss.xml",            "category": "AI Research"},
    {"name": "Google AI Blog",    "url": "https://blog.research.google/feeds/posts/default?alt=rss", "category": "AI Research"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml",            "category": "AI Research"},
    # Robotics
    {"name": "IEEE Spectrum Robotics", "url": "https://spectrum.ieee.org/feeds/topic/robotics.rss", "category": "Robotics"},
    {"name": "The Robot Report",  "url": "https://www.therobotreport.com/feed/",            "category": "Robotics"},
    {"name": "ROS Discourse",     "url": "https://discourse.ros.org/latest.rss",            "category": "Robotics"},
    # Industry & Policy
    {"name": "MIT Tech Review AI","url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "Industry"},
    {"name": "VentureBeat AI",    "url": "https://venturebeat.com/category/ai/feed/",       "category": "Industry"},
    {"name": "The Gradient",      "url": "https://thegradient.pub/rss/",                    "category": "AI Research"},
]

ARTICLES_PER_SOURCE = 2   # Max articles to pull per source
MAX_STORIES = 20          # Hard cap on total stories

# ── RSS Fetcher ───────────────────────────────────────────────────────────────

RSS_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "atom":    "http://www.w3.org/2005/Atom",
}

def fetch_feed(source: dict, max_items: int = ARTICLES_PER_SOURCE) -> list[dict]:
    """Fetch and parse an RSS/Atom feed, return list of raw article dicts."""
    headers = {"User-Agent": "auto-ai-news/1.0 (github.com/merv010/auto-ai-news)"}
    try:
        req = Request(source["url"], headers=headers)
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except URLError as e:
        print(f"  [SKIP] {source['name']}: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  [SKIP] {source['name']}: XML parse error – {e}")
        return []

    items = []

    # Atom feed
    atom_ns = "http://www.w3.org/2005/Atom"
    if root.tag == f"{{{atom_ns}}}feed":
        for entry in root.findall(f"{{{atom_ns}}}entry")[:max_items]:
            title = (entry.findtext(f"{{{atom_ns}}}title") or "").strip()
            link_el = entry.find(f"{{{atom_ns}}}link[@rel='alternate']") or entry.find(f"{{{atom_ns}}}link")
            url = link_el.get("href", "") if link_el is not None else ""
            summary = (
                entry.findtext(f"{{{atom_ns}}}summary") or
                entry.findtext(f"{{{atom_ns}}}content") or ""
            ).strip()
            if title and url:
                items.append({"title": title, "url": url, "raw_summary": summary[:600]})
        return items

    # RSS 2.0
    for item in root.findall(".//item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        url   = (item.findtext("link") or "").strip()
        desc  = (
            item.findtext("description") or
            item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        ).strip()
        # Strip HTML tags naively
        import re
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        if title and url:
            items.append({"title": title, "url": url, "raw_summary": desc[:600]})

    return items

# ── Gemini Summarizer ─────────────────────────────────────────────────────────

def build_gemini_model():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")

SUMMARIZE_PROMPT = """You are a concise science journalist. Given the article title and snippet below, write a 3-5 sentence summary that:
- Explains what the development is
- Why it matters for AI or robotics
- Uses clear, jargon-free language

Respond with ONLY a JSON object (no markdown, no backticks) in this exact format:
{{"summary": "...", "deck": "One punchy sentence teaser max 15 words."}}

Title: {title}
Snippet: {snippet}
Source: {source}"""

def summarize(model, article: dict, source_name: str) -> tuple[str, str]:
    """Return (summary, deck) strings from Gemini."""
    prompt = SUMMARIZE_PROMPT.format(
        title=article["title"],
        snippet=article["raw_summary"][:500],
        source=source_name,
    )
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Strip accidental markdown fences
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
        return data.get("summary", article["raw_summary"]), data.get("deck", "")
    except Exception as e:
        print(f"    [GEMINI ERROR] {e}")
        return article["raw_summary"][:300], ""

# ── Main ──────────────────────────────────────────────────────────────────────

def generate(output_path: str):
    print(f"\n{'='*60}")
    print(f"  AI & Robotics Daily — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")

    model = build_gemini_model()
    stories = []
    seen_hashes = set()

    for source in SOURCES:
        print(f"Fetching: {source['name']}")
        articles = fetch_feed(source)
        for article in articles:
            # Deduplicate by URL hash
            url_hash = hashlib.md5(article["url"].encode()).hexdigest()
            if url_hash in seen_hashes:
                continue
            seen_hashes.add(url_hash)

            print(f"  Summarizing: {article['title'][:70]}…")
            summary, deck = summarize(model, article, source["name"])
            time.sleep(0.5)  # gentle rate limiting

            stories.append({
                "title":    article["title"],
                "url":      article["url"],
                "source":   source["name"],
                "category": source["category"],
                "summary":  summary,
                "deck":     deck,
            })

            if len(stories) >= MAX_STORIES:
                break
        if len(stories) >= MAX_STORIES:
            break

    output = {
        "date":       datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated":  datetime.now(timezone.utc).isoformat(),
        "story_count": len(stories),
        "stories":    stories,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {len(stories)} stories written to {output_path}")
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate daily AI & Robotics news digest")
    parser.add_argument("--output", default="daily-ai-news.json", help="Output JSON file path")
    args = parser.parse_args()
    generate(args.output)
