#!/usr/bin/env python3
"""
AI Radar — v1.2
- Polls official AI/AR/VR/Robotics feeds (from OPML if present)
- Classifies status (Announced/Shipped/Upgraded/Preview/Deprecated/Delayed)
- Dedupe & append to products.csv
- Emits a daily digest markdown
Requires: feedparser
Optional env:
  AI_RADAR_OPML=ai_radar_sources.opml
  AI_RADAR_DIGEST_DAYS=2        # only include last N days in digest (omit to include all)
  AI_RADAR_DIGEST_LIMIT=50      # cap number of items in digest
  AI_RADAR_SKIP_FIRST_DIGEST=0  # 1 to skip digest on first run (when CSV is first created)
"""
import os, re, csv, hashlib, datetime, time, xml.etree.ElementTree as ET
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

# Fallback feeds if OPML isn't present
DEFAULT_FEEDS = {
    # AI
    "OpenAI:News": "https://openai.com/news/rss.xml",
    "Google:AI": "https://blog.google/technology/ai/rss/",
    "Google:DeepMind": "https://blog.google/technology/google-deepmind/rss/",
    "Google:Research": "https://research.google/blog/rss/",
    "Microsoft:AI": "https://www.microsoft.com/en-us/ai/blog/feed/",
    "NVIDIA:Blog": "https://blogs.nvidia.com/feed/",
    "NVIDIA:Newsroom": "https://nvidianews.nvidia.com/rss",
    "AWS:ML": "https://aws.amazon.com/blogs/machine-learning/feed/",
    "Apple:MLResearch": "https://machinelearning.apple.com/feed.xml",
    "HuggingFace:Blog": "https://huggingface.co/blog/feed.xml",
    # Add more in OPML for XR/Robotics/Research, or extend here if you prefer code config
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
    ("Model/API",   r"\b(model|API|endpoint|SDK|inference|fine-?tune|weights|token|embedding|prompt)\b"),
    ("Tooling",     r"\b(tool|IDE|extension|plugin|library|framework|notebook)\b"),
    ("Infra",       r"\b(GPU|cluster|server|cloud|region|availability\s+zone|throughput|deployment|latency)\b"),
    ("Device/AR",   r"\b(headset|AR|VR|glasses|wearable|Quest|Vision\s+Pro|Ray-?Ban)\b"),
    ("Robotics",    r"\b(robot|manipulation|locomotion|Isaac|ROS|arm|gripper|drone|mobile\s+base)\b"),
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
        return feed_name.split(":", 1)[0]
    host = urlparse(link).netloc
    mapping = {
        "openai.com": "OpenAI",
        "blog.google": "Google",
        "research.google": "Google",
        "ai.meta.com": "Meta",
        "developers.meta.com": "Meta",
        "microsoft.com": "Microsoft",
        "blogs.nvidia.com": "NVIDIA",
        "nvidianews.nvidia.com": "NVIDIA",
        "aws.amazon.com": "AWS",
        "machinelearning.apple.com": "Apple",
        "huggingface.co": "Hugging Face",
        "roadtovr.com": "Road to VR",
        "www.uploadvr.com": "UploadVR",
        "uploadvr.com": "UploadVR",
        "robohub.org": "Robohub",
        "www.therobotreport.com": "The Robot Report",
        "therobotreport.com": "The Robot Report",
        "arxiv.org": "arXiv",
        "www.youtube.com": "YouTube",
        "youtube.com": "YouTube",
    }
    return mapping.get(host, host)

def load_existing():
    rows = []
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows

def save_rows(rows):
    if not rows:
        return
    headers = rows[0].keys()
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def sort_for_output(rows):
    """
    Sort newest first by status_date, then last_seen, then company/product.
    Uses ISO dates (YYYY-MM-DD) so string sort works reliably.
    """
    def d(x): return (x or "0000-00-00")
    rows.sort(
        key=lambda r: (d(r.get("status_date")), d(r.get("last_seen")), r.get("company",""), r.get("product","")),
        reverse=True
    )

def upsert(rows, new):
    # dedupe by (source_url) primarily
    by_url = {r["source_url"]: i for i, r in enumerate(rows)}
    url = new["source_url"]
    today = datetime.date.today().isoformat()
    if url in by_url:
        i = by_url[url]
        # update last_seen, status if stronger
        rows[i]["last_seen"] = today
        rank = {"Deprecated":5,"Shipped":4,"Upgraded":3,"Announced":2,"Preview":1,"Delayed":0}
        if rank.get(new["status"], 0) > rank.get(rows[i]["status"], 0):
            rows[i]["status"] = new["status"]
            rows[i]["status_date"] = today
            rows[i]["change_type"] = new["change_type"]
            rows[i]["version"] = new.get("version","") or rows[i].get("version","")
            rows[i]["summary"] = new["summary"]
        return False
    else:
        rows.append(new)
        return True

def load_feeds_from_opml(path):
    """
    Returns a list of dicts: [{name, url, vertical}], vertical ∈ {ai,xr,robotics,research}.
    Vertical inferred from parent <outline> text labels.
    """
    if not os.path.exists(path):
        return []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return []

    feeds = []
    def walk(node, ancestors):
        label = (node.attrib.get("text") or node.attrib.get("title") or "").strip()
        xmlUrl = node.attrib.get("xmlUrl")
        # derive vertical from ancestors' labels
        anc_text = " / ".join(a for a in ancestors if a)
        vt = None
        s = (anc_text + " " + label).lower()
        if "robot" in s:
            vt = "robotics"
        if "research" in s or "arxiv" in s:
            vt = "research" if vt is None else vt
        if "xr" in s or ("ar/vr" in s) or ((" ar " in f" {s} ") and (" vr " in f" {s} ")):
            vt = "xr"
        if vt is None:
            vt = "ai"
        if xmlUrl:
            feeds.append({"name": label or xmlUrl, "url": xmlUrl, "vertical": vt})
        for child in node.findall("outline"):
            walk(child, ancestors + [label])
    for node in root.findall(".//body/outline"):
        walk(node, [])
    # de-dupe by URL
    seen, out = set(), []
    for f in feeds:
        if f["url"] in seen:
            continue
        seen.add(f["url"])
        out.append(f)
    return out

def iter_feed(name, url, vertical="ai"):
    d = feedparser.parse(url)
    for e in d.entries:
        title = (e.get("title") or "").strip()
        link  = (e.get("link") or "").strip()
        if not title or not link:
            continue
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
        tags = vertical or ""
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
            "tags": tags,
            "regions": "global",
            "notes": ""
        }
        yield row

def env_int(name, default=None):
    val = os.environ.get(name)
    if val is None or str(val).strip()=="":
        return default
    try:
        return int(val)
    except Exception:
        return default

def make_digest(rows, new_ids, days=None, limit=None):
    # If days is None -> include all; else filter by status_date >= cutoff
    if not new_ids:
        return None
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days)).isoformat() if isinstance(days, int) else None

    items = [r for r in rows if r["id"] in new_ids]
    if cutoff:
        items = [r for r in items if (r.get("status_date") or "0000-00-00") >= cutoff]

    # newest-first
    items.sort(key=lambda r: ((r.get("status_date") or "0000-00-00"),
                              (r.get("last_seen") or "0000-00-00")), reverse=True)
    if isinstance(limit, int):
        items = items[:max(0, limit)]

    if not items:
        return None

    fn = os.path.join(DIGEST_DIR, f"daily_{today.isoformat()}.md")
    lines = [f"# AI Radar — {today.isoformat()}", ""]
    for r in items:
        lines.append(f"## {r['company']}: {r['product']} — **{r['status']}**")
        lines.append(f"- {r['summary']}")
        lines.append(f"- Category: {r['category']}  |  Change: {r['change_type']}  |  Tags: {r.get('tags','')}")
        lines.append(f"- Source: {r['source_title']} — {r['source_url']}")
        lines.append("")
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return fn

def main():
    # detect first run (no CSV or empty CSV)
    first_run = not os.path.exists(OUT_CSV) or os.path.getsize(OUT_CSV) == 0

    rows = load_existing()

    # Prefer OPML feeds if present
    opml_path = os.path.join(BASE, os.environ.get("AI_RADAR_OPML", "ai_radar_sources.opml"))
    feeds = load_feeds_from_opml(opml_path)
    if feeds:
        print(f"[info] Loaded {len(feeds)} feeds from {os.path.basename(opml_path)}")
    else:
        print("[info] No OPML found or empty; using DEFAULT_FEEDS")
        feeds = [{"name": n, "url": u, "vertical": "ai"} for n, u in DEFAULT_FEEDS.items()]

    new_ids = []
    for f in feeds:
        name, url, vertical = f["name"], f["url"], f.get("vertical", "ai")
        try:
            for row in iter_feed(name, url, vertical=vertical):
                if upsert(rows, row):
                    new_ids.append(row["id"])
        except Exception as e:
            print(f"[WARN] {name}: {e}")

    # Always keep CSV sorted
    sort_for_output(rows)
    save_rows(rows)

    skip_first = str(os.environ.get("AI_RADAR_SKIP_FIRST_DIGEST", "0")).strip() in ("1","true","yes","on")
    digest_days = env_int("AI_RADAR_DIGEST_DAYS", default=None)
    digest_limit = env_int("AI_RADAR_DIGEST_LIMIT", default=None)

    if first_run and skip_first:
        print("Seed import complete — skipping first digest.")
        return

    if new_ids:
        digest = make_digest(rows, new_ids, days=digest_days, limit=digest_limit)
        print(f"Added {len(new_ids)} new items.")
        if digest:
            print(f"Digest: {digest}")
        else:
            print("No digest generated (filters may have excluded items).")
    else:
        print("No new items (file re-written in sorted order).")

if __name__ == "__main__":
    main()
