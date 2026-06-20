#!/usr/bin/env python3
"""Harvest match-detail JSON for a matchday from ESPN's live JSON API.

SCAFFOLD. This builds schema-valid data/results/matches/<id>.json files from
ESPN's `summary` endpoint -- the fast, fetch-reliable source that is populated
at full time (no waiting hours for Wikipedia). Run it once `poll_ready.py`
signals FIRE for the day:

    python3 scripts/poll_ready.py --date 20260617 && python3 scripts/harvest.py --date 20260617

It reads the day file data/results/<YYYY-MM-DD>.json as the fixture list,
matches each fixture to an ESPN event, writes one match-detail file per
completed match, and -- unless --no-scores is given -- writes the
authoritative final score and status="completed" back into the day file. So
ESPN is the single source of truth for both detail and scores: no separate
manual score entry, and the two can never drift apart. The write-back is
surgical (only the three score/status fields on the matched fixture) and
idempotent; every hand-maintained field (group, venue, note...) is preserved.
A genuine ESPN/day-file score disagreement is reported, not silently applied
without notice.

ESPN coverage (verified 2026-06): lineups w/ shirt numbers + formation,
~28 team stats, minute-stamped goals/cards/subs. Two gaps, both handled
locally:
  * manager  -> filled from data/teams/<slug>.json `coach`
  * xG       -> not in schema's stats block; skip (grab from FotMob if ever added)

Own goals (ESPN credits the beneficiary team; ownGoal flag is null but
type=="own-goal") and second yellows (inferred from a standing yellow, since
ESPN emits only "Red Card") are handled in events(); see its docstring. Always
run scripts/validate.py after.
"""
import argparse
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEAMS_DIR = ROOT / "data" / "teams"
RESULTS_DIR = ROOT / "data" / "results"
SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
              "fifa.world/scoreboard?dates={date}")
SUMMARY = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
           "fifa.world/summary?event={eid}")

# ESPN names that don't normalise to our slug. Extend as new teams appear.
ALIASES = {
    "cape verde": "cabo-verde", "ivory coast": "cote-divoire",
    "cote divoire": "cote-divoire", "congo dr": "dr-congo",
    "dr congo": "dr-congo", "korea republic": "south-korea",
    "south korea": "south-korea", "united states": "usa", "usa": "usa",
    "czech republic": "czechia", "turkey": "turkiye",
    "bosnia and herzegovina": "bosnia-herzegovina",
    "bosnia herzegovina": "bosnia-herzegovina",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").split())


# ESPN's API sits behind Akamai, which 403s plain/datacenter requests (seen
# from the cloud routine runner, though residential IPs pass). A real browser
# User-Agent + Accept/Referer headers and a short retry/backoff clears the bot
# heuristic in most cases.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
}


def get(url, tries=4):
    import time
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
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


# ---- local team metadata -------------------------------------------------

def load_team_index():
    """name/slug -> {slug, coach} so we can resolve ESPN names and fill manager."""
    by_key, coach = {}, {}
    for f in TEAMS_DIR.glob("*.json"):
        d = json.loads(f.read_text())
        slug = d["slug"]
        coach[slug] = d.get("coach")
        by_key[norm(d.get("name", slug))] = slug
        by_key[norm(slug)] = slug
    return by_key, coach


def resolve_slug(name, by_key):
    k = norm(name)
    return ALIASES.get(k) or by_key.get(k)


# ---- field mappers -------------------------------------------------------

def minute(clock):
    # "90'+3'" -> "90+3", "16'" -> "16"
    return (clock or {}).get("displayValue", "").replace("'", "").strip() or None


def position(p):
    nm = (p.get("position") or {}).get("name", "")
    if "Goalkeeper" in nm:
        return "GK"
    if "Back" in nm or "Defender" in nm:
        return "DF"
    if "Midfielder" in nm:
        return "MF"
    if "Forward" in nm or "Striker" in nm or "Wing" in nm:
        return "FW"
    return None


def lineup(roster, coach):
    starting = []
    for p in roster.get("roster", []):
        if not p.get("starter"):
            continue
        num = p.get("jersey")
        starting.append({
            "name": p["athlete"]["displayName"].strip(),
            "position": position(p),
            "number": int(num) if (num or "").isdigit() else None,
        })
    return {"formation": roster.get("formation"), "manager": coach, "starting": starting}


def stat_map(team_boxscore):
    # ESPN statistics items carry only a string `displayValue` ("10", "51.7",
    # "90%") -- no numeric `value`. Parse the leading number off displayValue.
    def num(dv):
        if dv is None:
            return None
        t = "".join(c for c in str(dv) if c.isdigit() or c in ".-")
        try:
            return float(t)
        except ValueError:
            return None

    s = {x["name"]: num(x.get("displayValue")) for x in team_boxscore.get("statistics", [])}

    def i(*names):
        for n in names:
            v = s.get(n)
            if v is not None:
                return int(round(v))
        return None

    acc, tot = s.get("accuratePasses"), s.get("totalPasses")
    pass_acc = int(round(100 * acc / tot)) if acc and tot else None
    return {
        "possession": i("possessionPct"), "shots": i("totalShots"),
        "shots_on_target": i("shotsOnTarget"), "corners": i("wonCorners"),
        "fouls": i("foulsCommitted"), "offsides": i("offsides"),
        "yellow_cards": i("yellowCards"), "red_cards": i("redCards"),
        "saves": i("saves"), "passes": i("totalPasses"),
        "pass_accuracy": pass_acc,
    }


def events(key_events, slug_by_espn_id):
    """Split ESPN keyEvents into goals / cards / substitutions.

    Own goals: ESPN sets ownGoal=None (!) but type.type == "own-goal", and its
    event `team` is already the BENEFICIARY (the side credited) -- which is what
    the schema's goal.team means -- while participant[0] is the own-goalscorer.
    Verified across 5 own goals (USA/Qatar/Belgium/Norway/Austria, 2026-06).

    Second yellows: ESPN has no "second yellow" event text -- it emits plain
    "Red Card" (and "VAR - (Red) Card Upgrade"). We infer a second yellow when a
    red goes to a player who already carries a standing yellow; otherwise it's a
    straight red. Standing yellows are tracked in match order.
    """
    goals, cards, subs = [], [], []
    yellowed, sent_off = set(), set()
    for e in key_events:
        ty = e.get("type") or {}
        text, kind = ty.get("text", ""), ty.get("type", "")
        team = slug_by_espn_id.get((e.get("team") or {}).get("id"))
        parts = [p.get("athlete", {}).get("displayName", "").strip()
                 for p in e.get("participants", [])]
        m = minute(e.get("clock"))
        player = parts[0] if parts else None

        is_own = kind == "own-goal" or "Own Goal" in text
        is_card = "Card" in text and ("Yellow" in text or "Red" in text)
        is_goal = (not is_card) and (e.get("scoringPlay") or is_own
                                     or text.startswith("Goal")
                                     or text == "Penalty - Scored")

        if is_card:
            if "Yellow" in text and "Red" not in text:
                card = "second-yellow" if player in yellowed else "yellow"
                if card == "yellow":
                    yellowed.add(player)
            else:  # "Red Card" / "VAR - (Red) Card Upgrade"
                card = "second-yellow" if player in yellowed else "red"
            if card != "yellow":              # a dismissal
                if player in sent_off:        # dedupe doubled red/2nd-yellow events
                    continue
                sent_off.add(player)
            cards.append({"team": team, "player": player, "minute": m, "card": card})
        elif is_goal:
            if is_own:
                gtype = "own_goal"
            elif e.get("penaltyKick") or "Penalty" in text:
                gtype = "penalty"
            else:
                gtype = "regular"
            goals.append({
                "team": team, "player": player, "minute": m, "type": gtype,
                "assist": parts[1] if (gtype == "regular" and len(parts) > 1) else None,
            })
        elif text == "Substitution":
            # participants are [on, off] (verified: Modric off / Kovacic on, 58')
            subs.append({"team": team,
                         "on": parts[0] if parts else None,
                         "off": parts[1] if len(parts) > 1 else None,
                         "minute": m})
    return goals, cards, subs


# ---- per-match build -----------------------------------------------------

def build_detail(fixture, summary, by_key, coach):
    comp = summary["header"]["competitions"][0]
    espn_side = {}        # 'home'/'away' -> espn team id
    score = {}
    for c in comp["competitors"]:
        espn_side[c["homeAway"]] = c["team"]["id"]
        score[c["homeAway"]] = int(c.get("score") or 0)

    # map each ESPN team id -> our slug, via the competitor display names
    slug_by_id = {}
    for c in comp["competitors"]:
        slug_by_id[c["team"]["id"]] = resolve_slug(c["team"]["displayName"], by_key)

    rosters = {t["homeAway"]: t for t in summary.get("rosters", [])}
    boxes = {t["homeAway"]: t for t in summary.get("boxscore", {}).get("teams", [])}
    goals, cards, subs = events(summary.get("keyEvents", []), slug_by_id)
    gi = summary.get("gameInfo", {})
    officials = gi.get("officials", [])

    detail = {
        "id": fixture["id"], "date": fixture["date"],
        "home": fixture["home"], "away": fixture["away"],
        "home_score": score.get("home", fixture.get("home_score", 0)),
        "away_score": score.get("away", fixture.get("away_score", 0)),
        "attendance": gi.get("attendance"),
        "referee": officials[0]["displayName"] if officials else None,
        "sources": [SUMMARY.format(eid=fixture["_eid"])],
        "goals": goals, "cards": cards, "substitutions": subs,
        "lineups": {}, "stats": {},
    }
    for side in ("home", "away"):
        slug = fixture[side]
        r = rosters.get(side)
        if r:
            detail["lineups"][side] = lineup(r, coach.get(slug))
        b = boxes.get(side)
        if b:
            detail["stats"][side] = stat_map(b)
    return detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYYMMDD or YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true",
                    help="Build and validate in memory; don't write files.")
    ap.add_argument("--no-scores", action="store_true",
                    help="Build detail only; don't write scores/status back to day files.")
    args = ap.parse_args()

    iso = args.date if "-" in args.date else \
        f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"
    compact = iso.replace("-", "")

    # ESPN groups by UTC date, so a late kickoff can land on the neighbouring
    # day's board (e.g. 04:00Z Austria-Jordan shows under 06-17 but we file it
    # under 06-16). Index fixtures from this day file plus its neighbours; each
    # fixture keeps its own date/id, so the right file is written either way.
    from datetime import date, timedelta
    y, mo, da = int(iso[:4]), int(iso[5:7]), int(iso[8:])
    fixtures = {}
    day_files = {}  # d_iso -> {"path", "data", "dirty"}; lets us write scores back
    for delta in (-1, 0, 1):
        d_iso = (date(y, mo, da) + timedelta(days=delta)).isoformat()
        df = RESULTS_DIR / f"{d_iso}.json"
        if not df.exists():
            continue
        data = json.loads(df.read_text())
        day_files[d_iso] = {"path": df, "data": data, "dirty": False}
        for m in data["matches"]:
            # 'date'/'_eid' are transient working keys, stripped before write-back.
            m["date"] = d_iso
            fixtures.setdefault(frozenset((m["home"], m["away"])), m)
    if not fixtures:
        print(f"no day file for {iso} or neighbours; add fixtures first", file=sys.stderr)
        return 2

    by_key, coach = load_team_index()
    board = get(SCOREBOARD.format(date=compact))

    written, problems, skipped, corrections = 0, [], [], []
    for e in board.get("events", []):
        comp = e["competitions"][0]
        slugs = [resolve_slug(c["team"]["displayName"], by_key)
                 for c in comp["competitors"]]
        if None in slugs:
            problems.append(f"unresolved ESPN team in '{e.get('name')}' -> {slugs}")
            continue
        fx = fixtures.get(frozenset(slugs))
        if not fx:
            problems.append(f"no fixture matches ESPN '{e.get('name')}' ({slugs})")
            continue
        if not (e.get("status", {}).get("type", {}).get("completed")):
            skipped.append(f"{fx['id']} not final yet")  # normal, not a failure
            continue

        fx["_eid"] = e["id"]
        detail = build_detail(fx, get(SUMMARY.format(eid=e["id"])), by_key, coach)
        out = RESULTS_DIR / "matches" / f"{fx['id']}.json"
        if args.dry_run:
            print(f"[dry-run] {fx['id']}: {len(detail['goals'])} goals, "
                  f"{len(detail['cards'])} cards, {len(detail['substitutions'])} subs")
        else:
            out.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n")
            print(f"wrote {out.relative_to(ROOT)}")
        written += 1

        # Single-writer: push ESPN's authoritative final score + status back into
        # the day file. fx is the same dict held in day_files[...]["data"], so
        # mutating it here updates that loaded day file in place.
        if not args.no_scores:
            new_h, new_a = detail["home_score"], detail["away_score"]
            old_h, old_a = fx.get("home_score"), fx.get("away_score")
            if old_h is not None and old_a is not None and (old_h, old_a) != (new_h, new_a):
                corrections.append(
                    f"{fx['id']}: day-file score {old_h}-{old_a} -> ESPN {new_h}-{new_a}")
            if (old_h, old_a, fx.get("status")) != (new_h, new_a, "completed"):
                fx["home_score"], fx["away_score"], fx["status"] = new_h, new_a, "completed"
                day = day_files.get(fx["date"])
                if day:
                    day["dirty"] = True

    day_updates = 0
    if not args.no_scores:
        for day in day_files.values():
            if not day["dirty"]:
                continue
            if args.dry_run:
                print(f"[dry-run] would update {day['path'].relative_to(ROOT)} "
                      "(scores/status)")
            else:
                for m in day["data"]["matches"]:
                    m.pop("date", None)   # transient working keys, not part of
                    m.pop("_eid", None)   # the day-file schema
                day["path"].write_text(
                    json.dumps(day["data"], ensure_ascii=False, indent=2) + "\n")
                print(f"updated {day['path'].relative_to(ROOT)} (scores/status)")
            day_updates += 1

    for s in skipped:
        print("  . " + s + "; skipped")
    for c in corrections:
        print("  ~ " + c, file=sys.stderr)
    for p in problems:
        print("  ! " + p, file=sys.stderr)
    print(f"{'validated' if args.dry_run else 'wrote'} {written} match file(s); "
          f"{day_updates} day file(s) updated; "
          f"{len(skipped)} not-final skipped; {len(problems)} issue(s)")
    return 1 if problems else 0  # in-progress skips are NOT failures


if __name__ == "__main__":
    sys.exit(main())
