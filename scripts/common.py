"""Shared helpers for the World Cup 2026 data scripts (standard library only)."""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TEAMS_DIR = os.path.join(DATA_DIR, "teams")
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


def fmt_eur(value):
    """Format an integer euro amount as e.g. €18.0m / €450k / €0."""
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"€{value / 1_000:.0f}k"
    return f"€{value}"
