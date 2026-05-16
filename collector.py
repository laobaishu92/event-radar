#!/usr/bin/env python3
# =============================================================================
#  EVENT RADAR — COLLECTOR
# -----------------------------------------------------------------------------
#  Reads sources.yaml, pulls each institution (RSS or scrape), normalises every
#  event into a common schema, keyword-tags it, remembers when each was first
#  seen, and renders a self-contained dashboard (index.html).
#
#  Run:  python collector.py
#  Output:  events.json   (the data record)
#           index.html    (the dashboard, data baked in)
# =============================================================================
import yaml, json, re, sys, hashlib, datetime, pathlib, traceback
import requests, feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dateutil import parser as dtparse

ROOT      = pathlib.Path(__file__).parent
TODAY     = datetime.date.today()
# events dated before this are dropped at collection time (2-day grace window)
PAST_CUTOFF = (TODAY - datetime.timedelta(days=2)).isoformat()
UA        = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS   = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}
MAX_PER_SOURCE = 120         # safety cap (past-dated events trimmed afterwards)
TIMEOUT   = 25

# -----------------------------------------------------------------------------
#  TOPIC TAGGING  — keyword rules. An event can carry several tags. These drive
#  the dashboard filter chips; nothing is ever hidden, so over-tagging is fine.
#  Edit freely: add a topic, add keywords.
# -----------------------------------------------------------------------------
TOPIC_RULES = {
    "China":                 ["china", "chinese", "beijing", "prc", "xi jinping", "ccp",
                               "people's republic", "sino"],
    "Taiwan":                ["taiwan", "taipei", "cross-strait", "cross strait", "taiwanese"],
    "Japan & Korea":         ["japan", "japanese", "tokyo", "korea", "korean", "seoul",
                              "pyongyang", "dprk"],
    "Russia & Ukraine":      ["russia", "russian", "ukraine", "ukrainian", "moscow",
                              "kremlin", "putin", "donbas"],
    "Indo-Pacific":          ["indo-pacific", "indo pacific", "asia-pacific", "asia pacific",
                              "south china sea", "quad", "aukus", "first island chain"],
    "EU & foreign policy":   ["european union", "brussels", "europe-china", "european commission",
                              "de-risking", "de-risk", "european parliament", "eu's", "eu-china",
                              "eu foreign", "strategic autonomy"],
    "Defence & military":    ["defence", "defense", "military", "rearm", "armament", "warfare",
                              "army", "navy", "air force", "war studies", "battlefield"],
    "Security & intelligence":["security", "intelligence", "espionage", "hybrid threat",
                              "covert", "counter-terror", "terrorism", "political warfare",
                              "disinformation", "subversion"],
    "Economic security":     ["economic security", "supply chain", "critical raw material",
                              "critical minerals", "sanctions", "export control",
                              "investment screening", "semiconductor", "trade war", "tariff"],
    "Nordic & Baltic":       ["nordic", "baltic", "denmark", "danish", "sweden", "swedish",
                              "finland", "finnish", "norway", "norwegian", "scandinav"],
    "NATO & alliances":      ["nato", "transatlantic", "collective defence", "collective defense",
                              "alliance"],
    "Nuclear & arms control":["nuclear", "arms control", "disarmament", "non-proliferation",
                              "nonproliferation", "deterrence", "missile", "warhead"],
    "Climate & security":    ["climate", "energy security", "environmental security",
                              "decarbonis", "decarboniz"],
}

MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
          "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")

# country name -> flag emoji  (extend as you add institutions)
COUNTRY_FLAG = {
    "France":"\U0001F1EB\U0001F1F7", "Germany":"\U0001F1E9\U0001F1EA",
    "Denmark":"\U0001F1E9\U0001F1F0", "Sweden":"\U0001F1F8\U0001F1EA",
    "United Kingdom":"\U0001F1EC\U0001F1E7", "Australia":"\U0001F1E6\U0001F1FA",
    "Norway":"\U0001F1F3\U0001F1F4", "Finland":"\U0001F1EB\U0001F1EE",
    "Netherlands":"\U0001F1F3\U0001F1F1", "Belgium":"\U0001F1E7\U0001F1EA",
    "Italy":"\U0001F1EE\U0001F1F9", "Spain":"\U0001F1EA\U0001F1F8",
    "Switzerland":"\U0001F1E8\U0001F1ED", "Austria":"\U0001F1E6\U0001F1F9",
    "Poland":"\U0001F1F5\U0001F1F1", "United States":"\U0001F1FA\U0001F1F8",
    "Hungary":"\U0001F1ED\U0001F1FA", "Hong Kong":"\U0001F1ED\U0001F1F0",
    "Slovakia":"\U0001F1F8\U0001F1F0",
}
# city -> [lat, lng]  for the map  (extend as you add institutions)
CITY_COORDS = {
    "Paris":[48.857,2.343], "Berlin":[52.520,13.405], "Copenhagen":[55.676,12.568],
    "Stockholm":[59.329,18.069], "London":[51.507,-0.128], "Canberra":[-35.281,149.129],
    "Aarhus":[56.162,10.204], "Oslo":[59.913,10.752], "Helsinki":[60.170,24.941],
    "Brussels":[50.847,4.357], "The Hague":[52.078,4.288], "Vienna":[48.208,16.373],
    "Washington":[38.907,-77.037], "Warsaw":[52.232,21.012], "Hong Kong":[22.319,114.169],
    "Cambridge":[52.205,0.119], "Oxford":[51.755,-1.255], "Tampere":[61.498,23.761],
    "Aalborg":[57.048,9.922], "Bratislava":[48.148,17.107], "Sydney":[-33.869,151.209],
}

# -----------------------------------------------------------------------------
#  HELPERS
# -----------------------------------------------------------------------------
def fetch(url):
    """GET with a browser UA. Returns Response or raises."""
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r

def clean(text):
    # drop soft hyphens / zero-width chars that some CMSs inject for line-breaking
    text = (text or "").replace("\u00ad", "").replace("\u200b", "")
    return " ".join(text.split())

def stable_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def tag_topics(text):
    low = (text or "").lower()
    hits = []
    for topic, kws in TOPIC_RULES.items():
        for kw in kws:
            # word-boundary match so "eu" never fires inside "museum"
            if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", low):
                hits.append(topic)
                break
    return hits

def detect_format(text):
    low = (text or "").lower()
    if any(w in low for w in ("hybrid",)):
        return "hybrid"
    if any(w in low for w in ("online", "webinar", "virtual", "zoom", "livestream",
                              "live stream", "live-stream", "teams meeting")):
        return "online"
    return "in-person"

def extract_dates(text):
    """Best-effort: pull (start_iso, end_iso, time_str) out of free text.
    Handles '26 June 2026', '24-25 June 2026', 'June 26, 2026', ISO, 'Friday 22 May'."""
    if not text:
        return None, None, None
    t = text.replace("\u2013", "-").replace("\u2014", "-").replace("\xa0", " ")
    low = t.lower()
    start = end = None

    # range: "24-25 June 2026"
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+(" + MONTHS + r")\.?\s+(\d{4})", low)
    if m:
        d1, d2, mon, yr = m.groups()
        try:
            start = dtparse.parse(f"{d1} {mon} {yr}").date()
            end   = dtparse.parse(f"{d2} {mon} {yr}").date()
        except Exception:
            pass
    # single: "26 June 2026"  /  "Friday 22 May 2026"
    if not start:
        m = re.search(r"(\d{1,2})\s+(" + MONTHS + r")\.?\s+(\d{4})", low)
        if m:
            try:
                start = dtparse.parse(f"{m.group(1)} {m.group(2)} {m.group(3)}").date()
            except Exception:
                pass
    # "June 26, 2026"
    if not start:
        m = re.search(r"(" + MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})", low)
        if m:
            try:
                start = dtparse.parse(f"{m.group(2)} {m.group(1)} {m.group(3)}").date()
            except Exception:
                pass
    # ISO 2026-06-26
    if not start:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        if m:
            try:
                start = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
    # year-less "22 May" — common on listings; infer the soonest future year
    if not start:
        m = re.search(r"(?<!\d)(\d{1,2})\s+(" + MONTHS + r")\.?(?!\s*\d{4})", low)
        if m:
            try:
                d, mon = int(m.group(1)), m.group(2)
                for yr in (TODAY.year, TODAY.year + 1):
                    cand = dtparse.parse(f"{d} {mon} {yr}").date()
                    if cand >= TODAY:
                        start = cand
                        break
                start = start or dtparse.parse(f"{d} {mon} {TODAY.year}").date()
            except Exception:
                pass
    # time "17:30" or "17.30"
    tm = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", t)
    time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None

    return (start.isoformat() if start else None,
            end.isoformat()   if end   else None,
            time_str)

def find_location(text):
    """Light heuristic for a location string."""
    if not text:
        return None
    for city in ("London", "Cambridge", "Oxford", "Paris", "Berlin", "Brussels",
                 "Stockholm", "Copenhagen", "Aarhus", "Canberra", "Sydney",
                 "Helsinki", "Oslo", "The Hague", "Online", "Webinar"):
        if re.search(r"\b" + re.escape(city) + r"\b", text):
            return city
    return None

def src_geo(src):
    """Resolve a source's country/city into flag + map coordinates."""
    country = src.get("country", "")
    city    = src.get("city", "")
    coord   = CITY_COORDS.get(city)
    return dict(country=country, city=city,
                flag=COUNTRY_FLAG.get(country, "\U0001F3F3"),
                lat=coord[0] if coord else None,
                lng=coord[1] if coord else None)

# -----------------------------------------------------------------------------
#  COLLECTORS
# -----------------------------------------------------------------------------
def collect_rss(src):
    """Generic RSS/Atom handler."""
    r = fetch(src["url"])
    feed = feedparser.parse(r.text)
    out = []
    for e in feed.entries[:MAX_PER_SOURCE]:
        title = clean(e.get("title", ""))
        link  = e.get("link", "")
        if not title or not link:
            continue
        summary = clean(BeautifulSoup(e.get("summary", ""), "lxml").get_text())
        blob    = f"{title} . {summary}"
        # prefer a date written in the text; fall back to the feed's own date
        s, en, tm = extract_dates(blob)
        if not s and e.get("published_parsed"):
            pp = e["published_parsed"]
            s  = datetime.date(pp.tm_year, pp.tm_mon, pp.tm_mday).isoformat()
        out.append(dict(title=title, url=link, summary=summary[:400],
                        date=s, date_end=en, time=tm,
                        location=find_location(blob), fmt=detect_format(blob),
                        date_text=""))
    return out

GENERIC_SLUG = {"", "events", "event", "agenda", "upcoming", "past", "all",
                "calendar", "news", "current"}

def collect_scrape(src):
    """Generic scraper: find anchors pointing at an individual event page,
    climb to the widest container that still describes a single event, and read
    date / title / location off it. Robust across Drupal / WordPress / KCL
    templates without per-site CSS selectors."""
    r = fetch(src["url"])
    soup = BeautifulSoup(r.text, "lxml")
    base = r.url
    seen, out = set(), []

    for a in soup.find_all("a", href=True):
        absu = urljoin(base, a["href"])
        if not absu.startswith("http"):
            continue
        path = urlparse(absu).path.lower().rstrip("/")
        segs = [s for s in path.split("/") if s]
        # the path must reference an event section AND end in a real slug
        if not any(s in ("event", "events", "agenda") for s in segs):
            continue
        slug = segs[-1] if segs else ""
        if slug in GENERIC_SLUG or not ("-" in slug or len(slug) >= 12):
            continue
        if absu in seen:
            continue

        title = clean(a.get_text())
        if len(title) < 8:                       # skip "read more" / icon links
            continue
        # some templates prefix the link text with a UI label
        title = re.sub(r"^\s*(view event|event|read more|details)\s*[:\-\u2013]?\s*",
                       "", title, flags=re.I)

        # climb to the WIDEST container still under the size cap: a single event
        # card is small; once text spills into sibling events it exceeds the cap.
        node, container = a, a
        for _ in range(6):
            node = node.parent
            if node is None:
                break
            if len(clean(node.get_text())) > 900:
                break
            container = node
        ctext = clean(container.get_text(" "))

        # date/time often live in a dedicated element inside the card
        date_bits = [clean(el.get_text(" "))
                     for el in container.select('[class*="date" i], time')]
        date_blob = " . ".join(date_bits) + " . " + ctext

        # a date in the TITLE is the most reliable (e.g. GTI "April 30: ...");
        # try it first, fall back to the card text
        s, en, tm = extract_dates(title)
        if not s:
            s, en, tm = extract_dates(date_blob)

        # tidy the display title: strip leading date / time / punctuation noise.
        # listing cards often prepend "DD Mon YYYY", "16:00-17:30", stray commas.
        disp = title
        for _ in range(4):                       # peel several fragments
            new = disp
            new = re.sub(r"^\s*[,;:.\u2013-]+\s*", "", new)        # leading punct
            new = re.sub(r"^\s*[a-z]{0,3}\.?\s*[-\u2013]\s*", "", new, flags=re.I)  # "t. - "
            new = re.sub(r"^\s*\d{1,2}\s+(" + MONTHS + r")\.?(\s+\d{4})?\s*",
                         "", new, flags=re.I)                       # "29 May 2026"
            new = re.sub(r"^\s*(" + MONTHS + r")\.?\s+\d{1,2},?(\s+\d{4})?\s*",
                         "", new, flags=re.I)                       # "May 29 2026"
            new = re.sub(r"^\s*[0-2]?\d[:.][0-5]\d"
                         r"(?:\s*[-\u2013]\s*[0-2]?\d[:.][0-5]\d)?\s*",
                         "", new)                                   # "16:00-17:30"
            if new == disp:
                break
            disp = new
        m = re.search(r"\d{1,2}\s+(" + MONTHS + r")", disp, flags=re.I)
        if m and m.start() > 10:
            disp = disp[:m.start()]
        disp = clean(disp) or clean(title)

        seen.add(absu)
        out.append(dict(title=disp[:200], url=absu,
                        summary=ctext[:400],
                        date=s, date_end=en, time=tm,
                        location=find_location(ctext), fmt=detect_format(date_blob),
                        date_text=""))
        if len(out) >= MAX_PER_SOURCE:
            break
    return out

COLLECTORS = {"rss": collect_rss, "scrape": collect_scrape}

# -----------------------------------------------------------------------------
#  PIPELINE
# -----------------------------------------------------------------------------
def load_sources():
    """All sources, enabled or not — disabled ones become manual-check cards."""
    with open(ROOT / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_first_seen():
    """Map id -> first_seen date, carried over from the previous run."""
    p = ROOT / "events.json"
    if not p.exists():
        return {}
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
        return {e["id"]: e["first_seen"] for e in prev.get("events", [])}
    except Exception:
        return {}

def run():
    sources    = load_sources()
    first_seen = load_first_seen()
    all_events = []
    report     = []

    for src in sources:
        label = src["short"]
        geo   = src_geo(src)
        base  = dict(short=label, name=src["name"], type=src["type"],
                     region=src["region"],
                     events_page=src.get("events_page", src.get("url", "")),
                     flag=geo["flag"], country=geo["country"], city=geo["city"],
                     lat=geo["lat"], lng=geo["lng"])

        # disabled sources are not collected, but still shown as a manual card
        if not src.get("enabled", True):
            report.append(dict(base, count=0, status="manual",
                                note="not auto-collected — open the site to check"))
            print(f"  [manul] {label:10s}  manual check")
            continue

        try:
            raw = COLLECTORS[src["method"]](src)
        except Exception as ex:
            report.append(dict(base, count=0, status="error",
                                note=f"{type(ex).__name__}: {ex}"))
            print(f"  [ERR ] {label:10s} {type(ex).__name__}: {ex}")
            continue

        kept = 0
        for ev in raw:
            # drop events we can date as clearly in the past — keeps events.json
            # lean and stops a long archive (e.g. GTI) from crowding out the
            # upcoming events. Undated events are always kept.
            if ev["date"] and ev["date"] < PAST_CUTOFF:
                continue
            eid  = stable_id(ev["url"])
            blob = f"{ev['title']} . {ev['summary']}"
            event = dict(
                id=eid, title=ev["title"], url=ev["url"],
                source_key=src["key"], institution=src["short"],
                institution_full=src["name"], type=src["type"], region=src["region"],
                date=ev["date"], date_end=ev["date_end"], time=ev["time"],
                date_text=ev.get("date_text", ""),
                location=ev["location"], format=ev["fmt"],
                topics=tag_topics(blob), summary=ev["summary"],
                first_seen=first_seen.get(eid, TODAY.isoformat()),
                **geo,
            )
            all_events.append(event)
            kept += 1

        status = "ok" if kept else "empty"
        report.append(dict(base, count=kept, status=status, note=""))
        print(f"  [{status:5s}] {label:10s} {kept:3d} events")

    # de-duplicate across sources by URL id
    uniq = {e["id"]: e for e in all_events}
    events = list(uniq.values())

    # sort: dated events ascending, undated last
    events.sort(key=lambda e: (e["date"] is None, e["date"] or "9999-12-31", e["title"]))

    payload = dict(
        generated=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        today=TODAY.isoformat(),
        sources=report,
        events=events,
    )
    (ROOT / "events.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    render(payload)
    live = [r for r in report if r["status"] in ("ok", "empty", "error")]
    ok   = sum(1 for r in report if r["status"] == "ok")
    man  = sum(1 for r in report if r["status"] == "manual")
    print(f"\n  TOTAL: {len(events)} unique events · {ok}/{len(live)} live sources"
          + (f" · {man} manual" if man else ""))
    return payload

def render(payload):
    """Inject the data into the dashboard template -> index.html."""
    tpl = (ROOT / "dashboard.template.html").read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False)
    html = tpl.replace("__PAYLOAD__", blob)
    (ROOT / "index.html").write_text(html, encoding="utf-8")

if __name__ == "__main__":
    print("EVENT RADAR — collecting\n" + "-" * 40)
    run()
