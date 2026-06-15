"""Shared helpers for the World Cup 2026 data scripts (standard library only)."""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TEAMS_DIR = os.path.join(DATA_DIR, "teams")
RESULTS_DIR = os.path.join(DATA_DIR, "results")
MATCHES_DIR = os.path.join(RESULTS_DIR, "matches")
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


def load_match_details():
    """Return {match_id: detail_dict} from data/results/matches/*.json."""
    details = {}
    if not os.path.isdir(MATCHES_DIR):
        return details
    for fname in sorted(f for f in os.listdir(MATCHES_DIR) if f.endswith(".json")):
        d = load_json(os.path.join(MATCHES_DIR, fname))
        if d.get("id"):
            details[d["id"]] = d
    return details


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


def squad_value(team):
    """Total market value (EUR) of a team's squad."""
    return sum(p.get("market_value_eur", 0) for p in team.get("squad", []))


def sorted_squad(team):
    """Squad ordered by position (GK, DF, MF, FW) then descending market value."""
    return sorted(
        team.get("squad", []),
        key=lambda p: (
            POSITION_ORDER.get(p.get("position"), 9),
            -p.get("market_value_eur", 0),
        ),
    )


def team_name(by_slug, slug):
    """Display name for a team slug, falling back to the slug itself."""
    t = by_slug.get(slug)
    return t["name"] if t else slug


def minute_key(minute):
    """Sort key for a match minute like '45+5' -> (45, 5); None sorts last."""
    if minute is None:
        return (999, 0)
    s = str(minute)
    if "+" in s:
        base, extra = s.split("+", 1)
        return (int(base), int(extra))
    return (int(s), 0)


# Per-match team statistics: (json key, display label, unit suffix).
STAT_LABELS = [
    ("possession", "Possession", "%"),
    ("shots", "Shots", ""),
    ("shots_on_target", "Shots on target", ""),
    ("corners", "Corners", ""),
    ("fouls", "Fouls", ""),
    ("offsides", "Offsides", ""),
    ("yellow_cards", "Yellow cards", ""),
    ("red_cards", "Red cards", ""),
    ("saves", "Saves", ""),
    ("passes", "Passes", ""),
    ("pass_accuracy", "Pass accuracy", "%"),
]
CARD_ICON = {"yellow": "🟨", "second-yellow": "🟨🟥", "red": "🟥"}


def fmt_eur(value):
    """Format an integer euro amount as e.g. €18.0m / €450k / €0."""
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"€{value / 1_000:.0f}k"
    return f"€{value}"


def fmt_usd(value):
    """Format an integer US$ amount as e.g. $1.4T / $27.5B / $850M / $11,000."""
    if value is None:
        return "—"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    return f"${value:,}"


def fmt_count(value):
    """Format a plain count (e.g. population) as e.g. 1.4B / 84.5M / 12.3k."""
    if value is None:
        return "—"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value}"
