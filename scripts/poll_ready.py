#!/usr/bin/env python3
"""Gate for a scheduled results harvest: is a matchday's data ready to pull?

A scheduled run (cron / routine) fires this repeatedly on a matchday. It asks
ESPN's live scoreboard whether every match for the given date has reached full
time, and only then signals the harvest to run -- so we no longer wait hours
for Wikipedia's group-page template to populate.

ESPN scoreboard:
  https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD
Each event carries status.type.{state,completed} ("post" / true at full time).

Exit codes (so a cron wrapper can branch with && / case $?):
  0   FIRE       -- all matches final (and settle window elapsed): run the harvest
  10  WAIT       -- matches still scheduled/in-play, or settle window not yet elapsed
  20  NO_MATCHES -- ESPN lists no matches for this date: nothing to do
  30  ERROR      -- fetch/parse failed: leave previous state, try again next tick

Usage:
  python3 scripts/poll_ready.py                     # today (UTC), no settle buffer
  python3 scripts/poll_ready.py --date 20260617
  python3 scripts/poll_ready.py --settle-minutes 20 # wait 20 min after the last FT

Typical cron wrapper (fires the harvest exactly once, when ready):
  python3 scripts/poll_ready.py --date "$(date -u +%Y%m%d)" --settle-minutes 20 \
    && python3 scripts/harvest.py --date "$(date -u +%Y%m%d)" \
    && python3 scripts/validate.py \
    && python3 scripts/generate_results.py && python3 scripts/generate_site.py
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
       "fifa.world/scoreboard?dates={date}")

FIRE, WAIT, NO_MATCHES, ERROR = 0, 10, 20, 30

# ESPN/Akamai 403s plain/datacenter requests; a browser UA + headers and a
# short retry/backoff clears the bot heuristic (matches scripts/harvest.py).
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
}


def fetch(date, tries=4):
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(API.format(date=date), headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429, 500, 502, 503, 504) and n < tries - 1:
                time.sleep(1.5 * (n + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            if n < tries - 1:
                time.sleep(1.5 * (n + 1))
                continue
            raise
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y%m%d"),
                    help="Matchday as YYYYMMDD (UTC). Defaults to today.")
    ap.add_argument("--settle-minutes", type=int, default=0,
                    help="Require this many minutes to pass after the LAST match "
                         "goes final before firing (lets live stats stabilise). "
                         "Tracked via a stamp file so it survives across polls.")
    ap.add_argument("--stamp", default=None,
                    help="Path to the settle-timer stamp file "
                         "(default: scripts/.poll-<date>.stamp).")
    args = ap.parse_args()

    try:
        data = fetch(args.date)
    except Exception as e:  # network/parse: don't advance state, retry next tick
        print(f"ERROR  could not fetch ESPN scoreboard for {args.date}: {e}",
              file=sys.stderr)
        return ERROR

    events = data.get("events", [])
    if not events:
        print(f"NO_MATCHES  ESPN lists no fixtures for {args.date}")
        return NO_MATCHES

    pending = []
    for e in events:
        t = (e.get("status") or {}).get("type") or {}
        final = t.get("completed") is True or t.get("state") == "post"
        mark = "FT " if final else "...."
        print(f"  {mark} {e.get('name', e.get('id'))}  [{t.get('detail', '?')}]")
        if not final:
            pending.append(e.get("name", e.get("id")))

    if pending:
        print(f"WAIT  {len(pending)}/{len(events)} not final: "
              f"{', '.join(pending)}")
        return WAIT

    # All matches are final. Apply the optional settle buffer via a stamp file:
    # first all-final poll records 'now'; we only fire once enough time elapses.
    if args.settle_minutes > 0:
        stamp = Path(args.stamp or f"scripts/.poll-{args.date}.stamp")
        now = datetime.now(timezone.utc)
        if not stamp.exists():
            stamp.write_text(now.isoformat())
            print(f"WAIT  all {len(events)} final; starting "
                  f"{args.settle_minutes}m settle timer.")
            return WAIT
        started = datetime.fromisoformat(stamp.read_text().strip())
        elapsed = (now - started).total_seconds() / 60
        if elapsed < args.settle_minutes:
            print(f"WAIT  all final; settle {elapsed:.0f}/"
                  f"{args.settle_minutes}m elapsed.")
            return WAIT

    print(f"FIRE  all {len(events)} matches final for {args.date} -- harvest now.")
    return FIRE


if __name__ == "__main__":
    sys.exit(main())
