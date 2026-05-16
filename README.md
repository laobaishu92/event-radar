# Event Radar

A personal dashboard that collects upcoming events from strategic-studies,
security and IR institutions into one page, so heavyweight conferences and
seminars don't slip past unnoticed. It refreshes itself on a schedule — no
server, no database, free to run.

---

## How it works

```
sources.yaml   ──►   collector.py   ──►   index.html  (the dashboard)
(you edit this)      (GitHub Actions       events.json (the data record)
                      runs it on a cron)
```

1. `collector.py` reads `sources.yaml`, pulls each institution (RSS feed or
   page scrape), normalises every event into one schema, keyword-tags it by
   topic, and remembers when each event was first seen.
2. It writes `events.json` (the data) and renders `index.html` — a single
   self-contained dashboard file with all event data baked in. (It does load
   map tiles and the map library from a CDN at view time, for the map panel.)
3. A GitHub Actions workflow runs this twice a week and commits the result.
4. GitHub Pages serves `index.html` as a website you visit.

The dashboard itself has: a map of where events are held, a light/dark theme
toggle, full-text search, and filters for topic, format (in-person / online /
hybrid), region, institution type and source — each with "all / none" controls.

Everything is version-controlled, so if a scraper breaks you can see exactly
what changed, and the Action emails you when a run fails.

---

## One-time setup

1. **Create a new GitHub repository** (private is fine) and push these files
   into it, keeping the folder layout:

   ```
   collector.py
   sources.yaml
   dashboard.template.html
   requirements.txt
   index.html              ← generated, but committing one copy seeds Pages
   events.json             ← generated
   .github/workflows/update.yml
   ```

2. **Enable Actions**: repo → *Settings* → *Actions* → *General* → allow
   workflows to run, and under *Workflow permissions* select
   **Read and write permissions**.

3. **Enable Pages**: repo → *Settings* → *Pages* → *Source* = *Deploy from a
   branch*, branch = `main`, folder = `/ (root)`. Your dashboard will be live
   at `https://<your-username>.github.io/<repo-name>/`.

4. **First run**: go to the *Actions* tab → *Update Event Radar* → *Run
   workflow*. After it finishes, the dashboard is live.

That's it. From then on it updates itself every Monday and Thursday.

---

## Adding or removing institutions

Edit **`sources.yaml`** — it is the only file you need to touch.

* **Remove** an institution: delete its block, or set `enabled: false`.
  (A disabled source still appears on the dashboard as a *manual-check card*
  with a link to its events page — that's how IISS is handled.)
* **Add** one with an RSS/iCal feed: copy a block, set `method: rss` and the
  feed `url`. Nothing else needed.
* **Add** one that needs scraping: set `method: scrape` and the events-page
  `url`. The generic scraper handles most university / think-tank event pages
  (it looks for links to individual event pages and reads the date off the
  surrounding card). If a site is unusual, the scraper may need a tweak.

Every block also has a `country` (drives the flag emoji) and a `city` (drives
the map pin). If you add an institution in a *new* city, add that city to
`CITY_COORDS` in `collector.py` — one line, `"City":[lat,lng]`. Without it the
event still appears in the list, just not on the map.

Run `python collector.py` locally to test before pushing.

---

## Running locally

```bash
pip install -r requirements.txt
python collector.py
open index.html
```

---

## Current sources

**Auto-collected** (16 — events pulled automatically):

| Institution | Type | Method |
|---|---|---|
| Sciences Po — CERI | University | RSS |
| ASPI | Think tank | RSS |
| MERICS | Think tank | scrape |
| DIIS | Research institute | scrape |
| KCL — Lau China Institute | University | scrape |
| KCL — War Studies | University | scrape |
| SIPRI | Research institute | scrape |
| Aarhus — Political Science | University | scrape |
| ECFR | Think tank | scrape |
| Cambridge — POLIS | University | scrape |
| Cambridge — Centre for Geopolitics | University | scrape |
| EUISS | Research institute | scrape |
| CSIS | Think tank | scrape |
| Univ. of Copenhagen — Political Science | University | scrape |
| Copenhagen Business School | University | scrape |
| Swedish National China Centre | Research institute | scrape |

**Manual-check cards** (14 — not auto-collected; shown with a "check ↗" link):
IISS, Global Taiwan Institute, CEIAS, FIIA, ISDP, Lowy, Oxford China Centre,
PISM, CEU — Political Science, Aalborg — Politics & Society, FU Berlin —
Indo-Pacific, CFHK Foundation, University of Helsinki, Tampere University.

See *Known limitations* for why each is manual rather than auto-collected.

---

## Known limitations

These are deliberate trade-offs, not bugs:

* **14 institutions are manual-check cards, not auto-collected.** Two reasons:
  (1) some sites render their event list with JavaScript, which the scraper —
  a plain HTML fetcher — cannot see (Lowy, Oxford China Centre, PISM, CEU,
  Aalborg, FU Berlin, Helsinki, Tampere, GTI), or block automated traffic
  (IISS, CFHK); (2) some publish a *news / past-event-recording* feed rather
  than an upcoming-events calendar (CEIAS, FIIA, ISDP), so auto-collecting them
  would just surface stale items. All 14 still appear in the Sources panel with
  a one-click "check ↗" link to their events page. To auto-collect a
  JavaScript site, the collector would need a headless browser (e.g. Playwright)
  instead of a plain fetch — a larger change.
* **EUISS and the Swedish National China Centre may show zero upcoming events.**
  Their scrapers work; those institutes simply hold few public events, or none
  are currently scheduled. A zero there is genuine.
* **SIPRI and Aarhus list few public events.** Same as above — a low count is
  real, not a broken scraper.
* **Dates are best-effort.** The collector reads the date from each event's
  listing card. Where a site only shows the date on the event's own page
  (some SIPRI series pages), the event appears under "Date to be confirmed".
  Events dated clearly in the past are dropped during collection.
* **Topic tagging is keyword-based** and conservative — roughly half of events
  come through untagged (they still show; nothing is hidden). Broadening the
  keyword lists in `collector.py` (`TOPIC_RULES`), or swapping in an LLM
  tagging step, is the obvious next improvement.
* **"New this week"** = an event first appeared in the last 7 days. On the very
  first run everything is new; it settles after that.

---

## Files

| File | Purpose |
|---|---|
| `sources.yaml` | The institution list — **the file you edit** |
| `collector.py` | The pipeline: collect, tag, render |
| `dashboard.template.html` | The dashboard's design/layout |
| `index.html` | Generated dashboard (what Pages serves) |
| `events.json` | Generated data record |
| `requirements.txt` | Python dependencies |
| `.github/workflows/update.yml` | The schedule |
