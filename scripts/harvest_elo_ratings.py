"""Harvest the current World Football Elo Ratings table.

eloratings.net renders its ranking in JavaScript, so there is no HTML table to
scrape. The data is loaded from two flat tab-separated files that the site
itself fetches:

    https://www.eloratings.net/World.tsv      rank / team code / rating (+ history columns)
    https://www.eloratings.net/en.teams.tsv   team code -> display name (+ aliases)

This script joins the two: it reads each ranking row's 2-letter team code from
World.tsv, resolves it to a country name via en.teams.tsv, then maps that name
onto this repository's team slugs. It is intentionally standard-library only,
matching the rest of this repository's script conventions.

Default mode writes only the raw CSV snapshot under data/raw/rankings/:

    python3 scripts/harvest_elo_ratings.py

Use --apply to also seed matched team JSON files with:

    elo_rating
    elo_rank
    elo_source
    elo_harvested_at

The harvester is conservative. If eloratings.net changes the file format or
moves the data, it will fail with a clear message rather than silently writing
guessed values.
"""

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import urllib.request

from common import atomic_write_json, load_all_teams, team_path

# Human-facing site, recorded as the provenance in elo_source.
SOURCE_URL = "https://www.eloratings.net/"
# The flat data files the site loads (no JavaScript needed).
RATINGS_URL = "https://www.eloratings.net/World.tsv"
TEAMS_URL = "https://www.eloratings.net/en.teams.tsv"
OUT_PATH = os.path.join("data", "raw", "rankings", "world_football_elo_snapshot.csv")

# Name harmonisation for this repository's team slugs. The source may use common
# football names rather than the repo's exact display names.
NAME_TO_SLUG_OVERRIDES = {
    "usa": "usa",
    "united states": "usa",
    "united states of america": "usa",
    "u.s.a.": "usa",
    "u.s.a": "usa",
    "south korea": "south-korea",
    "korea republic": "south-korea",
    "republic of korea": "south-korea",
    "czech republic": "czechia",
    "czechia": "czechia",
    "bosnia and herzegovina": "bosnia-herzegovina",
    "bosnia-herzegovina": "bosnia-herzegovina",
    "cote d'ivoire": "cote-divoire",
    "côte d'ivoire": "cote-divoire",
    "ivory coast": "cote-divoire",
    "dr congo": "dr-congo",
    "d.r. congo": "dr-congo",
    "congo dr": "dr-congo",
    "democratic republic of the congo": "dr-congo",
    "cape verde": "cabo-verde",
    "cabo verde": "cabo-verde",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "curacao": "curacao",
    "curaçao": "curacao",
}


def normalize_text(value):
    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def norm_key(value):
    value = normalize_text(value).lower()
    value = value.replace("&", "and")
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9' ]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "worldcup26-elo-harvester/1.0 (+https://github.com/trond-k/worldcup26)",
            "Accept": "text/tab-separated-values,text/plain,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def clean_rating(value):
    m = re.search(r"\b(\d{3,4})\b", str(value).replace(",", ""))
    if not m:
        return None
    rating = int(m.group(1))
    # International Elo ratings usually sit roughly in this range. This filter
    # helps avoid years, match counts, and other non-rating integers.
    if 500 <= rating <= 2600:
        return rating
    return None


def parse_team_names(tsv_text):
    """Map each eloratings team code to its primary display name.

    en.teams.tsv rows are: <code>\t<name>\t<alias>...  -- we keep column 2.
    """
    names = {}
    for line in tsv_text.splitlines():
        cells = line.split("\t")
        if len(cells) >= 2 and cells[0].strip():
            names[cells[0].strip()] = normalize_text(cells[1])
    return names


def parse_world_ratings(tsv_text, code_to_name):
    """Extract rank / code / name / rating rows from World.tsv.

    Columns: [0] rank, [2] team code, [3] rating (later columns are history).
    """
    rows = []
    for line in tsv_text.splitlines():
        cells = line.split("\t")
        if len(cells) < 4:
            continue
        rank_match = re.match(r"^\s*(\d{1,3})\s*$", cells[0])
        if not rank_match:
            continue
        rating = clean_rating(cells[3])
        if rating is None:
            continue
        code = cells[2].strip()
        if not code:
            continue
        rows.append({
            "rank": int(rank_match.group(1)),
            "code": code,
            "team": code_to_name.get(code, code),
            "rating": rating,
            "raw_cells": cells,
        })
    return rows


def build_slug_lookup():
    teams = load_all_teams()
    lookup = dict(NAME_TO_SLUG_OVERRIDES)
    for team in teams:
        lookup[norm_key(team["name"])] = team["slug"]
        lookup[norm_key(team["slug"].replace("-", " "))] = team["slug"]
    return lookup


def attach_slugs(rows):
    lookup = build_slug_lookup()
    for row in rows:
        row["matched_slug"] = lookup.get(norm_key(row["team"]), "")
    return rows


def write_csv(rows, out_path, harvested_at):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "harvested_at_utc",
                "source_url",
                "rank",
                "code",
                "team",
                "rating",
                "matched_slug",
                "raw_cells_json",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "harvested_at_utc": harvested_at,
                "source_url": RATINGS_URL,
                "rank": row["rank"],
                "code": row["code"],
                "team": row["team"],
                "rating": row["rating"],
                "matched_slug": row.get("matched_slug", ""),
                "raw_cells_json": json.dumps(row.get("raw_cells", []), ensure_ascii=False),
            })


def insert_before_squad(team, fields):
    """Return a copy of team with fields inserted just before squad."""
    out = {}
    inserted = False
    for key, value in team.items():
        if key == "squad" and not inserted:
            out.update(fields)
            inserted = True
        out[key] = value
    if not inserted:
        out.update(fields)
    return out


def apply_to_team_files(rows, harvested_at, allow_partial=False):
    by_slug = {r["matched_slug"]: r for r in rows if r.get("matched_slug")}
    expected = {team["slug"] for team in load_all_teams()}
    missing = sorted(expected - set(by_slug))
    if missing and not allow_partial:
        raise RuntimeError(
            "refusing partial Elo apply; unmatched World Cup teams: "
            + ", ".join(missing)
            + " (use --allow-partial only for an intentional partial refresh)"
        )
    updates = []
    written = 0
    for slug, row in by_slug.items():
        path = team_path(slug)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            team = json.load(fh)
        updated = insert_before_squad(team, {
            "elo_rating": row["rating"],
            "elo_rank": row["rank"],
            "elo_source": SOURCE_URL,
            "elo_harvested_at": harvested_at,
        })
        updates.append((path, updated))
        written += 1
    for path, updated in updates:
        atomic_write_json(path, updated)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Harvest World Football Elo ranking table.")
    parser.add_argument("--ratings-url", default=RATINGS_URL, help="World.tsv ratings file URL")
    parser.add_argument("--teams-url", default=TEAMS_URL, help="en.teams.tsv code->name file URL")
    parser.add_argument("--out", default=OUT_PATH, help="CSV output path")
    parser.add_argument("--apply", action="store_true", help="Also write elo_* fields into matched team JSON files")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Allow --apply when one or more tournament teams are unmatched")
    args = parser.parse_args(argv)

    harvested_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    code_to_name = parse_team_names(fetch_text(args.teams_url))
    rows = parse_world_ratings(fetch_text(args.ratings_url), code_to_name)
    if not rows:
        raise SystemExit(
            f"No ranking rows could be parsed from {args.ratings_url}. "
            "The file format may have changed, or the data may have moved."
        )

    rows = attach_slugs(rows)
    write_csv(rows, args.out, harvested_at)

    matched = sum(1 for r in rows if r.get("matched_slug"))
    print(f"Wrote {len(rows)} Elo rows to {args.out}")
    print(f"Matched {matched} rows to current World Cup team slugs")

    if args.apply:
        written = apply_to_team_files(rows, harvested_at, allow_partial=args.allow_partial)
        print(f"Updated {written} team JSON files with elo_* fields")
    else:
        print("Dry team-file mode: pass --apply to update data/teams/*.json")


if __name__ == "__main__":
    main()
