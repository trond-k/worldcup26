"""Harvest the current World Football Elo Ratings table.

The script fetches https://eloratings.net/, extracts the ranking table, and writes a
raw CSV snapshot under data/raw/rankings/. It is intentionally standard-library
only, matching the rest of this repository's script conventions.

Default mode writes only the raw CSV snapshot:

    python3 scripts/harvest_elo_ratings.py

Use --apply to also seed matched team JSON files with:

    elo_rating
    elo_rank
    elo_source
    elo_harvested_at

The scraper is conservative. If eloratings.net changes its markup or moves the
ranking into JavaScript-only data, it will fail with a clear message rather than
silently writing guessed values.
"""

import argparse
import csv
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import urllib.request

from common import load_all_teams, team_path

SOURCE_URL = "https://eloratings.net/"
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


class TableParser(HTMLParser):
    """Very small HTML table parser for ordinary <table><tr><td> markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._table = []
        self._row = []
        self._cell = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_table and self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._in_table and self._in_row and self._in_cell and tag in {"td", "th"}:
            value = normalize_text("".join(self._cell))
            self._row.append(value)
            self._cell = []
            self._in_cell = False
        elif self._in_table and self._in_row and tag == "tr":
            if any(self._row):
                self._table.append(self._row)
            self._row = []
            self._in_row = False
        elif self._in_table and tag == "table":
            if self._table:
                self.tables.append(self._table)
            self._table = []
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


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


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "worldcup26-elo-harvester/1.0 (+https://github.com/trond-k/worldcup26)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_tables(page_html):
    parser = TableParser()
    parser.feed(page_html)
    return parser.tables


def clean_rating_cell(value):
    m = re.search(r"\b(\d{3,4})\b", value.replace(",", ""))
    if not m:
        return None
    rating = int(m.group(1))
    # International Elo ratings usually sit roughly in this range. This filter
    # helps avoid years, match counts, and other non-rating integers.
    if 500 <= rating <= 2600:
        return rating
    return None


def infer_ranking_rows(tables):
    """Return rows with rank/team/rating inferred from the best-looking table."""
    candidates = []
    for table in tables:
        extracted = []
        for row in table:
            if len(row) < 3:
                continue
            rank_match = re.match(r"^\s*(\d{1,3})\b", row[0])
            if not rank_match:
                continue
            rank = int(rank_match.group(1))

            rating_idx = None
            rating = None
            # Prefer rating-looking cells after the team cell; skip rank cell.
            for idx, cell in enumerate(row[1:], start=1):
                candidate = clean_rating_cell(cell)
                if candidate is not None:
                    rating_idx = idx
                    rating = candidate
                    break
            if rating is None:
                continue

            # Team is usually the text cell between rank and rating. Choose the
            # longest non-numeric text cell before the rating.
            text_cells = [c for c in row[1:rating_idx] if re.search(r"[A-Za-zÀ-ž]", c)]
            if not text_cells:
                continue
            team = max(text_cells, key=len)
            team = re.sub(r"^[↑↓+\-0-9 ]+", "", team).strip()
            if not team:
                continue

            extracted.append({
                "rank": rank,
                "team": team,
                "rating": rating,
                "raw_cells": row,
            })
        if len(extracted) >= 20:
            candidates.append(extracted)

    if not candidates:
        return []
    # Prefer the largest ranking table.
    return max(candidates, key=len)


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
                "source_url": SOURCE_URL,
                "rank": row["rank"],
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


def apply_to_team_files(rows, harvested_at):
    by_slug = {r["matched_slug"]: r for r in rows if r.get("matched_slug")}
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
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(updated, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        written += 1
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Harvest World Football Elo ranking table.")
    parser.add_argument("--url", default=SOURCE_URL, help="Source URL, defaults to https://eloratings.net/")
    parser.add_argument("--out", default=OUT_PATH, help="CSV output path")
    parser.add_argument("--apply", action="store_true", help="Also write elo_* fields into matched team JSON files")
    args = parser.parse_args(argv)

    harvested_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    page = fetch_html(args.url)
    tables = extract_tables(page)
    rows = infer_ranking_rows(tables)
    if not rows:
        raise SystemExit(
            "No ranking table could be extracted from eloratings.net. "
            "The site may have changed markup or moved the table into JavaScript-only data."
        )

    rows = attach_slugs(rows)
    write_csv(rows, args.out, harvested_at)

    matched = sum(1 for r in rows if r.get("matched_slug"))
    print(f"Wrote {len(rows)} Elo rows to {args.out}")
    print(f"Matched {matched} rows to current World Cup team slugs")

    if args.apply:
        written = apply_to_team_files(rows, harvested_at)
        print(f"Updated {written} team JSON files with elo_* fields")
    else:
        print("Dry team-file mode: pass --apply to update data/teams/*.json")


if __name__ == "__main__":
    main()
