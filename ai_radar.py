#!/usr/bin/env python3
"""
AI Radar — v1
- Polls official AI/AR/VR/Robotics feeds
- Classifies status (Announced/Shipped/Upgraded/Preview/Deprecated/Delayed)
- Dedupe & append to products.csv
- Emits a daily digest markdown
Requires: feedparser, requests (optional), python-dateutil (optional but recommended)
"""
import os, re, csv, json, hashlib, datetime, time
from urllib.parse import urlparse
try:
    import feedparser
except ImportError:
    raise SystemExit("pip install feedparser")

# ---- Config ----
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE, "products.csv")
DIGEST_DIR = os.path.join(BASE, "digests")
os.makedirs(DIGEST_DIR, exist_ok=True)

FEEDS = {
    # AI
    "OpenAI:News":"https://openai.com/news/rss.xml",
    "Google:AI":"https://blog.google/technology/ai/rss/",
    "Google:DeepMind":"https://blog.google/technology/google-deepmind/rss/",
    "Google:Research":"https://research.google/blog/rss/",
    "Microsoft:AI":"https://www.microsoft.com/en-us/ai/blog/feed/",
    "NVIDIA:Blog":"https://blogs.nvidia.com/feed/",
    "NVIDIA:Newsroom":"https://nvidianews.nvidia.com/rss",
    "AWS:ML":"https://aws.amazon.com/blogs/machine-learning/feed/",
    "Apple:MLResearch":"https://machinelearning.apple.com/feed.xml",
    "HuggingFace:Blog":"https://huggingface.co/blog/feed.xml",
    # Add non-RSS via RSSHub (if you run it) or handle separately in a scraper
    # "Meta:AI":"<rsshub meta ai>",
    # "xAI:News":"<rsshub xai>",
}

STATUS_KEYWORDS = [
    ("Shipped",     r"\b(available\s+now|now\s+available|shipping|ships\s+today|GA\b|general\s+availability|launch(ed|ing)\b|available\s+(globally|in|today))"),
    ("Upgraded",    r"\b(update(d|)\b|v\d+(\.\d+)*\b|performance\s+improv(e|ement)|speedup|latency\s+reduced|quality\s+improved|major\s+update|new\s+version)"),
    ("Announced",   r"\b(announce(d|s|ment)\b|introducing|previewing|coming\s+soon|sneak\s+peek|unveil(ed|s))"),
    ("Preview",     r"\b(beta|preview|limited\s+preview|private\s+preview|public\s+preview|early\s+access)\b"),
    ("Deprecated",  r"\b(deprecat(e|ed|ion)|sunset(ting|)|retire(ment|)|EOL\b|end\s+of\s+life)"),
    ("Delayed",     r"\b(delay|delayed|postpone(d|s))\b"),
]

CATEGORY_GUESS = [
    ("Model/API",   r"\b(model|API|endpoint|SDK|inference|fine-tune|weights|token|embedding|prompt)\b"),
    ("Tooling",     r"\b(tool|IDE|extension|plugin|library|framework|notebook)\b"),
    ("Infra",       r"\b(GPU|cluster|server|Cloud|region|availability\s+zone|throughput|deployment)\b"),
    ("Device/AR",   r"\b(headset|AR|VR|glasses|wearable|Quest|Vision\s+Pro|Ray-?Ban)\b"),
    ("Robotics",    r"\b(robot|manipulation|locomotion|Isaac|ROS|arm|gripper|drone)\b"),
]

def hash_id(company, title, date_str):
    base = f"{company}|{title}|{date_str}"
    return re.sub(r"[^a-z0-9_]+", "-", base.lower())[:64]

def classify_status(text):
    t = text.lower()
    for label, pattern in STATUS_KEYWORDS:
        if re.search(pattern, t):
            return label
    # default
    return "Announced" if re.search(r"\b(announce|introduc|unveil)\b", t) else "Upgraded"

def guess_category(text):
    t = text.lower()
    for label, pattern in CATEGORY_GUESS:
        if re.search(pattern, t):
            return label
    return "Model/API"

def parse_company(feed_name, link):
    if ":" in feed_name:
        return feed_name.split(":",1)[0]
    host = urlparse(link).netloc
    mapping = {
        "openai.com":"OpenAI", "blog.google":"Google", "research.google":"Google",
        "ai.meta.com":"Meta", "developers.meta.com":"Meta",
        "microsoft.com":"Microsoft", "blogs.nvidia.com":"NVIDIA", "nvidianews.nvidia.com":"NVIDIA",
        "aws.amazon.com":"AWS", "machinelearning.apple.com":"Apple",
        "huggingface.co":"Hugging Face"
    }
    return mapping.get(host, host)

def load_existing():
    rows = []
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows

def save_rows(rows):
    if not rows: return
    headers = rows[0].keys()
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def upsert(rows, new):
    # dedupe by (source_url) primarily
    by_url = {r["source_url"]: i for i, r in enumerate(rows)}
    url = new["source_url"]
    today = datetime.date.today().isoformat()
    if url in by_url:
        i = by_url[url]
        # update last_seen, status if stronger
        rows[i]["last_seen"] = today
        # If new status is "Shipped" and existing is not, upgrade
        rank = {"Deprecated":5,"Shipped":4,"Upgraded":3,"Announced":2,"Preview":1,"Delayed":0}
        if rank.get(new["status"],0) > rank.get(rows[i]["status"],0):
            rows[i]["status"] = new["status"]
            rows[i]["status_date"] = today
            rows[i]["change_type"] = new["change_type"]
            rows[i]["version"] = new.get("version","") or rows[i].get("version","")
            rows[i]["summary"] = new["summary"]
        return False
    else:
        rows.append(new)
        return True

def iter_feed(name, url):
    d = feedparser.parse(url)
    for e in d.entries:
        title = e.get("title","").strip()
        link  = e.get("link","").strip()
        if not title or not link:
            continue
        published = e.get("published") or e.get("updated") or ""
        date_str = ""
        try:
            if e.get("published_parsed"):
                date_str = time.strftime("%Y-%m-%d", e.published_parsed)
            elif e.get("updated_parsed"):
                date_str = time.strftime("%Y-%m-%d", e.updated_parsed)
        except Exception:
            date_str = ""
        summary_text = (e.get("summary") or "").strip()
        text_blob = f"{title}\n{summary_text}"
        company = parse_company(name, link)
        status = classify_status(text_blob)
        category = guess_category(text_blob)
        # naive product guess from title (before colon or dash)
        product = re.split(r"[:–\-]| — ", title)[0][:80].strip()
        rid = hash_id(company, title, date_str or datetime.date.today().isoformat())
        today = datetime.date.today().isoformat()
        row = {
            "id": rid,
            "company": company,
            "product": product,
            "category": category,
            "status": status,
            "status_date": date_str or today,
            "first_seen": today,
            "last_seen": today,
            "change_type": "New" if status in ("Announced","Preview") else ("Launch" if status=="Shipped" else "Update"),
            "version": "",
            "summary": title,
            "source_title": title,
            "source_url": link,
            "source_type": "RSS/Blog",
            "source_priority": "official",
            "confidence": "0.6",
            "tags": "",
            "regions": "global",
            "notes": ""
        }
        yield row

def make_digest(rows, new_ids):
    if not new_ids: return None
    today = datetime.date.today().isoformat()
    fn = os.path.join(DIGEST_DIR, f"daily_{today}.md")
    lines = [f"# AI Radar — {today}", ""]
    for r in rows:
        if r["id"] in new_ids:
            lines.append(f"## {r['company']}: {r['product']} — **{r['status']}**")
            lines.append(f"- {r['summary']}")
            lines.append(f"- Category: {r['category']}  |  Change: {r['change_type']}")
            lines.append(f"- Source: {r['source_title']} — {r['source_url']}")
            lines.append("")
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return fn

def main():
    rows = load_existing()
    new_ids = []
    for name, url in FEEDS.items():
        try:
            for row in iter_feed(name, url):
                if upsert(rows, row):
                    new_ids.append(row["id"])
        except Exception as e:
            print(f"[WARN] {name}: {e}")
    if new_ids:
        save_rows(rows)
        digest = make_digest(rows, new_ids)
        print(f"Added {len(new_ids)} new items.")
        if digest:
            print(f"Digest: {digest}")
    else:
        print("No new items.")

if __name__ == "__main__":
    main()
