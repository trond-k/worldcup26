#!/usr/bin/env python3
"""Harvest match-detail JSON for a matchday from ESPN's live JSON API.

SCAFFOLD. This builds schema-valid data/results/matches/<id>.json files from
ESPN's `summary` endpoint -- the fast, fetch-reliable source that is populated
at full time (no waiting hours for Wikipedia). Run it once `poll_ready.py`
signals FIRE for the day:

    python3 scripts/poll_ready.py --date 20260617 && python3 scripts/harvest.py --date 20260617

It reads the day file data/results/<YYYY-MM-DD>.json as the fixture list +
score authority, matches each fixture to an ESPN event, and writes one
match-detail file per completed match.

ESPN coverage (verified 2026-06): lineups w/ shirt numbers + formation,
~28 team stats, minute-stamped goals/cards/subs. Two gaps, both handled
locally:
  * manager  -> filled from data/teams/<slug>.json `coach`
  * xG       -> not in schema's stats block; skip (grab from FotMob if ever added)

Caveats worth a human spot-check (marked TODO below): own-goal credited-team
orientation, and second-yellow vs straight-red classification -- ESPN's
keyEvents don't always disambiguate these. Always run scripts/validate.py after.
"""
import argparse
import json
import sys
import unicodedata
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


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "worldcup26-harvest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


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
    """Split ESPN keyEvents into goals / cards / substitutions."""
    goals, cards, subs = [], [], []
    for e in key_events:
        text = (e.get("type") or {}).get("text", "")
        team = slug_by_espn_id.get((e.get("team") or {}).get("id"))
        parts = [p.get("athlete", {}).get("displayName", "").strip()
                 for p in e.get("participants", [])]
        m = minute(e.get("clock"))

        if e.get("scoringPlay") or text.startswith("Goal") or text == "Penalty - Scored":
            if e.get("ownGoal"):
                gtype = "own_goal"  # TODO: confirm ESPN credits beneficiary team here
            elif e.get("penaltyKick") or "Penalty" in text:
                gtype = "penalty"
            else:
                gtype = "regular"
            goals.append({
                "team": team, "player": parts[0] if parts else None, "minute": m,
                "type": gtype,
                "assist": parts[1] if (gtype == "regular" and len(parts) > 1) else None,
            })
        elif "Card" in text:
            if "Second" in text:
                card = "second-yellow"
            elif "Red" in text:
                card = "red"
            else:
                card = "yellow"
            cards.append({"team": team, "player": parts[0] if parts else None,
                          "minute": m, "card": card})
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
    for delta in (-1, 0, 1):
        d_iso = (date(y, mo, da) + timedelta(days=delta)).isoformat()
        df = RESULTS_DIR / f"{d_iso}.json"
        if not df.exists():
            continue
        for m in json.loads(df.read_text())["matches"]:
            m["date"] = d_iso
            fixtures.setdefault(frozenset((m["home"], m["away"])), m)
    if not fixtures:
        print(f"no day file for {iso} or neighbours; add fixtures first", file=sys.stderr)
        return 2

    by_key, coach = load_team_index()
    board = get(SCOREBOARD.format(date=compact))

    written, problems = 0, []
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
            problems.append(f"{fx['id']} not final yet; skipped")
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

    for p in problems:
        print("  ! " + p, file=sys.stderr)
    print(f"{'validated' if args.dry_run else 'wrote'} {written} match file(s); "
          f"{len(problems)} issue(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
