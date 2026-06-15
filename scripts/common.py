"""Shared helpers for the World Cup 2026 data scripts (standard library only)."""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TEAMS_DIR = os.path.join(DATA_DIR, "teams")
RESULTS_DIR = os.path.join(DATA_DIR, "results")
DOCS_DIR = os.path.join(ROOT, "docs")
TOURNAMENT_PATH = os.path.join(DATA_DIR, "tournament.json")

GROUP_LETTERS = [chr(c) for c in range(ord("A"), ord("L") + 1)]  # A..L
POSITIONS = ["GK", "DF", "MF", "FW"]
POSITION_ORDER = {p: i for i, p in enumerate(POSITIONS)}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_tournament():
    return load_json(TOURNAMENT_PATH)


def team_path(slug):
    return os.path.join(TEAMS_DIR, slug + ".json")


def load_team(slug):
    return load_json(team_path(slug))


def load_all_teams():
    """Return list of team dicts ordered by group then group position."""
    tournament = load_tournament()
    teams = []
    for letter in GROUP_LETTERS:
        for slug in tournament["groups"].get(letter, []):
            path = team_path(slug)
            if os.path.exists(path):
                teams.append(load_json(path))
    return teams


def load_results():
    """Return all matches across data/results/*.json, ordered by date then file order.

    Each returned match dict is augmented with a 'date' key from its file.
    Returns an empty list if the results directory does not exist.
    """
    matches = []
    if not os.path.isdir(RESULTS_DIR):
        return matches
    for fname in sorted(f for f in os.listdir(RESULTS_DIR) if f.endswith(".json")):
        day = load_json(os.path.join(RESULTS_DIR, fname))
        for match in day.get("matches", []):
            m = dict(match)
            m.setdefault("date", day.get("date"))
            matches.append(m)
    return matches


def compute_standings(teams, matches):
    """Compute group standings from completed matches.

    Returns {group_letter: [row, ...]} where each row has slug, name, played,
    won, drawn, lost, gf, ga, gd, points, sorted by points, GD, GF, name.
    Only matches with status 'completed' and integer scores are counted.
    """
    by_slug = {t["slug"]: t for t in teams}
    rows = {}
    for t in teams:
        rows[t["slug"]] = {
            "slug": t["slug"], "name": t["name"], "group": t.get("group"),
            "played": 0, "won": 0, "drawn": 0, "lost": 0,
            "gf": 0, "ga": 0, "gd": 0, "points": 0,
        }

    for m in matches:
        if m.get("status") != "completed":
            continue
        h, a = m.get("home"), m.get("away")
        hs, as_ = m.get("home_score"), m.get("away_score")
        if h not in rows or a not in rows:
            continue
        if not isinstance(hs, int) or not isinstance(as_, int):
            continue
        for slug, gf, ga in ((h, hs, as_), (a, as_, hs)):
            r = rows[slug]
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            r["gd"] = r["gf"] - r["ga"]
            if gf > ga:
                r["won"] += 1
                r["points"] += 3
            elif gf == ga:
                r["drawn"] += 1
                r["points"] += 1
            else:
                r["lost"] += 1

    standings = {}
    for letter in GROUP_LETTERS:
        group_rows = [r for r in rows.values() if r["group"] == letter]
        group_rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
        standings[letter] = group_rows
    return standings


def fmt_eur(value):
    """Format an integer euro amount as e.g. €18.0m / €450k / €0."""
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"€{value / 1_000:.0f}k"
    return f"€{value}"
