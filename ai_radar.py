#!/usr/bin/env python3
"""
AI Radar — v1.3
- Loads feeds from OPML if present; falls back to built-ins
- Classifies status (Announced/Shipped/Upgraded/Preview/Deprecated/Delayed)
- Dedupe & append to products.csv
- Emits a daily digest markdown for NEW items **and** STATUS PROMOTIONS
Env (optional):
  AI_RADAR_OPML=ai_radar_sources.opml
  AI_RADAR_DIGEST_DAYS=2
  AI_RADAR_DIGEST_LIMIT=50
  AI_RADAR_SKIP_FIRST_DIGEST=0
"""
import os, re, csv, hashlib, datetime, time, html, xml.etree.ElementTree as ET
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

DEFAULT_FEEDS = {
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
}

STATUS_KEYWORDS = [
    ("Shipped",     r"\b(available\s+now|now\s+available|shipping|ships\s+today|GA\b|general\s+availability|launch(ed|ing)\b|available\s+(globally|in|today))"),
    ("Upgraded",    r"\b(update(d|)\b|v\d+(\.\d+)*\b|performance\s+improv(e|ement)|speedup|latency\s+reduced|quality\s+improved|major\s+update|new\s+version)"),
    ("Announced",   r"\b(announce(d|s|ment)\b|introducing|previewing|coming\s+soon|sneak\s+peek|unveil(ed|s))"),
    ("Preview",     r"\b(beta|preview|limited\s+preview|private\s+preview|public\s+preview|early\s+access)\b"),
    ("Deprecated",  r"\b(deprecat(e|ed|ion)|sunset(ting|)|retire(ment|)|EOL\b|end\s+of\s+life)"),
    ("Delayed",     r"\b(delay|delayed|postpone(d|s))\b"),
]
STATUS_RANK = {"Delayed":0,"Preview":1,"Announced":2,"Upgraded":3,"Shipped":4,"Deprecated":5}

CATEGORY_GUESS = [
    ("Model/API",   r"\b(model|API|endpoint|SDK|inference|fine-?tune|weights|token|embedding|prompt)\b"),
    ("Tooling",     r"\b(tool|IDE|extension|plugin|library|framework|notebook)\b"),
    ("Infra",       r"\b(GPU|cluster|server|cloud|region|availability\s+zone|throughput|deployment|latency)\b"),
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
    return "Announced" if re.search(r"\b(announce|introduc|unveil)\b", t) else "Upgraded"

def guess_category(text):
    t = text.lower()
    for label, pattern in CATEGORY_GUESS:
        if re.search(pattern, t):
            return label
    return "Model/API"


def normalize_summary(summary_text, fallback):
    """Return a cleaned paragraph summary from feed content."""
    if summary_text:
        cleaned = html.unescape(re.sub(r"<[^>]+>", " ", summary_text))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
    else:
        cleaned = ""
    if not cleaned:
        return fallback
    if len(cleaned) <= 500:
        return cleaned
    truncated = cleaned[:500].rstrip()
    last_sentence = max(truncated.rfind(". "), truncated.rfind(".\n"), truncated.rfind(".\t"))
    if last_sentence > 200:
        truncated = truncated[:last_sentence + 1]
    return truncated.strip()

def parse_company(feed_name, link):
    if ":" in feed_name:
        return feed_name.split(":",1)[0]
    host = urlparse(link).netloc
    mapping = {
        "openai.com":"OpenAI","blog.google":"Google","research.google":"Google",
        "ai.meta.com":"Meta","developers.meta.com":"Meta",
        "microsoft.com":"Microsoft","blogs.nvidia.com":"NVIDIA","nvidianews.nvidia.com":"NVIDIA",
        "aws.amazon.com":"AWS","machinelearning.apple.com":"Apple","huggingface.co":"Hugging Face",
    }
    return mapping.get(host, host)

def load_existing():
    if not os.path.exists(OUT_CSV):
        return []
    with open(OUT_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_rows(rows):
    if not rows: return
    headers = rows[0].keys()
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)

def sort_for_output(rows):
    def d(x): return (x or "0000-00-00")
    rows.sort(key=lambda r: (d(r.get("status_date")), d(r.get("last_seen")), r.get("company",""), r.get("product","")),
              reverse=True)

def load_feeds_from_opml(path):
    if not os.path.exists(path): return []
    try:
        tree = ET.parse(path); root = tree.getroot()
    except Exception:
        return []
    feeds = []
    def walk(node, anc):
        label = (node.attrib.get("text") or node.attrib.get("title") or "").strip()
        xmlUrl = node.attrib.get("xmlUrl")
        s = (" ".join(anc+[label])).lower()
        vt = None
        if "robot" in s: vt = "robotics"
        if ("xr" in s) or ("ar/vr" in s) or ((" ar " in f" {s} ") and (" vr " in f" {s} ")): vt = "xr"
        if ("research" in s) or ("arxiv" in s): vt = "research" if vt is None else vt
        if vt is None: vt = "ai"
        if xmlUrl:
            feeds.append({"name": label or xmlUrl, "url": xmlUrl, "vertical": vt})
        for child in node.findall("outline"):
            walk(child, anc+[label])
    for node in root.findall(".//body/outline"):
        walk(node, [])
    out, seen = [], set()
    for f in feeds:
        if f["url"] in seen: continue
        seen.add(f["url"]); out.append(f)
    return out

def iter_feed(name, url, vertical="ai"):
    d = feedparser.parse(url)
    for e in d.entries:
        title = (e.get("title") or "").strip()
        link  = (e.get("link") or "").strip()
        if not title or not link: continue
        date_str = ""
        try:
            if e.get("published_parsed"):
                date_str = time.strftime("%Y-%m-%d", e.published_parsed)
            elif e.get("updated_parsed"):
                date_str = time.strftime("%Y-%m-%d", e.updated_parsed)
        except Exception:
            date_str = ""
        summary_text = (e.get("summary") or "").strip()
        clean_summary = normalize_summary(summary_text, fallback=title)
        text_blob = f"{title}\n{summary_text}"
        company = parse_company(name, link)
        status = classify_status(text_blob)
        category = guess_category(text_blob)
        product = re.split(r"[:–\-]| — ", title)[0][:80].strip()
        rid = hash_id(company, title, date_str or datetime.date.today().isoformat())
        today = datetime.date.today().isoformat()
        yield {
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
            "summary": clean_summary,
            "source_title": title,
            "source_url": link,
            "source_type": "RSS/Blog",
            "source_priority": "official",
            "confidence": "0.6",
            "tags": vertical or "",
            "regions": "global",
            "notes": ""
        }

def upsert(rows, incoming):
    """
    Returns (action, row_dict)
      action ∈ {"added","promoted","updated"}
    """
    by_url = {r["source_url"]: i for i, r in enumerate(rows)}
    url = incoming["source_url"]
    today = datetime.date.today().isoformat()
    if url in by_url:
        i = by_url[url]
        old = rows[i]
        rows[i]["last_seen"] = today
        # detect status promotion
        old_rank = STATUS_RANK.get(old.get("status","Announced"), 2)
        new_rank = STATUS_RANK.get(incoming.get("status","Announced"), 2)
        if new_rank > old_rank:
            rows[i]["status"] = incoming["status"]
            rows[i]["status_date"] = today
            rows[i]["change_type"] = incoming["change_type"]
            rows[i]["version"] = incoming.get("version","") or old.get("version","")
            rows[i]["summary"] = incoming["summary"]
            rows[i]["tags"] = incoming.get("tags", old.get("tags",""))
            return "promoted", rows[i]
        if incoming.get("summary"):
            rows[i]["summary"] = incoming["summary"]
        return "updated", rows[i]
    else:
        rows.append(incoming)
        return "added", incoming

def env_int(name, default=None):
    v = os.environ.get(name)
    if v is None or str(v).strip() == "": return default
    try: return int(v)
    except: return default

def make_digest(rows, items, days=None, limit=None):
    if not items: return None
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days)).isoformat() if isinstance(days, int) else None

    # newest-first
    def key(r):
        return ((r.get("status_date") or "0000-00-00"), (r.get("last_seen") or "0000-00-00"))
    if cutoff:
        items = [r for r in items if (r.get("status_date") or "0000-00-00") >= cutoff]
    items.sort(key=key, reverse=True)
    if isinstance(limit, int):
        items = items[:max(0, limit)]
    if not items: return None

    fn = os.path.join(DIGEST_DIR, f"daily_{today.isoformat()}.md")
    lines = [f"# AI Radar — {today.isoformat()}", ""]

    def digest_summary(row):
        raw = (row.get("summary") or "").strip()
        if raw:
            return raw
        notes = (row.get("notes") or "").strip()
        if notes:
            return notes
        return (row.get("source_title") or "").strip()

    for r in items:
        lines.append(f"## {r['company']}: {r['product']} — **{r['status']}**")
        summary = digest_summary(r)
        if summary:
            lines.append(summary)
        lines.append("")
        lines.append(f"- Category: {r['category']}  |  Change: {r['change_type']}  |  Tags: {r.get('tags','')}")
        lines.append(f"- Source: {r['source_title']} — {r['source_url']}")
        lines.append("")
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return fn

def main():
    first_run = not os.path.exists(OUT_CSV) or os.path.getsize(OUT_CSV) == 0
    rows = load_existing()

    # Feeds (OPML preferred)
    opml_path = os.path.join(BASE, os.environ.get("AI_RADAR_OPML", "ai_radar_sources.opml"))
    feeds = load_feeds_from_opml(opml_path)
    if feeds:
        print(f"[info] Loaded {len(feeds)} feeds from {os.path.basename(opml_path)}")
    else:
        print("[info] No OPML found or empty; using DEFAULT_FEEDS")
        feeds = [{"name": n, "url": u, "vertical": "ai"} for n, u in DEFAULT_FEEDS.items()]

    added_items, promoted_items = [], []
    for f in feeds:
        name, url, vertical = f["name"], f["url"], f.get("vertical","ai")
        try:
            for row in iter_feed(name, url, vertical=vertical):
                action, canonical = upsert(rows, row)
                if action == "added":
                    added_items.append(canonical)
                elif action == "promoted":
                    promoted_items.append(canonical)
        except Exception as e:
            print(f"[WARN] {name}: {e}")

    # Always keep CSV sorted
    sort_for_output(rows)
    save_rows(rows)

    # Digest controls
    skip_first = str(os.environ.get("AI_RADAR_SKIP_FIRST_DIGEST","0")).strip().lower() in ("1","true","yes","on")
    digest_days  = env_int("AI_RADAR_DIGEST_DAYS",  None)
    digest_limit = env_int("AI_RADAR_DIGEST_LIMIT", None)

    if first_run and skip_first:
        print("Seed import complete — skipping first digest.")
        return

    # Create digest for both new and promoted items
    digest_pool = added_items + promoted_items
    if digest_pool:
        digest = make_digest(rows, digest_pool, days=digest_days, limit=digest_limit)
        print(f"Added {len(added_items)} new; Promoted {len(promoted_items)}.")
        if digest:
            print(f"Digest: {digest}")
        else:
            print("No digest generated (filters may have excluded items).")
    else:
        print("No new or promoted items (CSV may have been re-sorted/updated only).")

if __name__ == "__main__":
    main()
