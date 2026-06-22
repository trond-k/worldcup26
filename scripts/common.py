"""Shared helpers for the World Cup 2026 data scripts (standard library only)."""

import json
import os
import re
import tempfile

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


def atomic_write_json(path, data):
    """Write JSON atomically so an interrupted harvester cannot truncate data."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


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


def _add_result(row, gf, ga):
    row["played"] += 1
    row["gf"] += gf
    row["ga"] += ga
    row["gd"] = row["gf"] - row["ga"]
    if gf > ga:
        row["won"] += 1
        row["points"] += 3
    elif gf == ga:
        row["drawn"] += 1
        row["points"] += 1
    else:
        row["lost"] += 1


def _conduct_scores(details, match_ids):
    """Return FIFA-style conduct scores (higher/less negative is better).

    Detail files do not currently record cautions for team officials, so this is
    necessarily provisional. Player cards still provide the correct ordering in
    the common case and FIFA ranking remains the final deterministic fallback.
    """
    scores = {}
    if not details:
        return scores
    for mid in match_ids:
        detail = details.get(mid) or {}
        by_player = {}
        for card in detail.get("cards", []):
            key = (card.get("team"), card.get("player"))
            if all(key):
                by_player.setdefault(key, set()).add(card.get("card"))
        for (slug, _player), cards in by_player.items():
            if "red" in cards and "yellow" in cards:
                penalty = -5
            elif "red" in cards:
                penalty = -4
            elif "second-yellow" in cards:
                penalty = -3
            else:
                penalty = -1
            scores[slug] = scores.get(slug, 0) + penalty
    return scores


def compute_standings(teams, matches, details=None):
    """Compute provisional group standings using the FIFA 2026 tie-break order.

    Only completed *group-stage* matches count. Teams level on points are ordered
    by head-to-head points, head-to-head goal difference, head-to-head goals,
    overall goal difference, overall goals, conduct score, then FIFA ranking.
    """
    by_slug = {t["slug"]: t for t in teams}
    rows = {}
    for t in teams:
        rows[t["slug"]] = {
            "slug": t["slug"], "name": t["name"], "group": t.get("group"),
            "played": 0, "won": 0, "drawn": 0, "lost": 0,
            "gf": 0, "ga": 0, "gd": 0, "points": 0,
        }

    group_matches = []
    for m in matches:
        if m.get("stage") != "group" or m.get("status") != "completed":
            continue
        h, a = m.get("home"), m.get("away")
        hs, as_ = m.get("home_score"), m.get("away_score")
        if h not in rows or a not in rows:
            continue
        if not isinstance(hs, int) or not isinstance(as_, int):
            continue
        group_matches.append(m)
        _add_result(rows[h], hs, as_)
        _add_result(rows[a], as_, hs)

    standings = {}
    for letter in GROUP_LETTERS:
        group_rows = [r for r in rows.values() if r["group"] == letter]
        played = [m for m in group_matches if m.get("group") == letter]
        conduct = _conduct_scores(details, [m.get("id") for m in played if m.get("id")])

        ranked = []
        point_totals = sorted({r["points"] for r in group_rows}, reverse=True)
        for points in point_totals:
            tied = [r for r in group_rows if r["points"] == points]
            mini = {
                r["slug"]: {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                            "gf": 0, "ga": 0, "gd": 0, "points": 0}
                for r in tied
            }
            tied_slugs = set(mini)
            for m in played:
                h, a = m.get("home"), m.get("away")
                if h in tied_slugs and a in tied_slugs:
                    _add_result(mini[h], m["home_score"], m["away_score"])
                    _add_result(mini[a], m["away_score"], m["home_score"])
            for row in tied:
                h2h = mini[row["slug"]]
                row["h2h_points"] = h2h["points"]
                row["h2h_gd"] = h2h["gd"]
                row["h2h_gf"] = h2h["gf"]
                row["conduct_score"] = conduct.get(row["slug"], 0)
                row["fifa_ranking"] = by_slug[row["slug"]].get("fifa_ranking") or 999
            tied.sort(key=lambda r: (
                -r["h2h_points"], -r["h2h_gd"], -r["h2h_gf"],
                -r["gd"], -r["gf"], -r["conduct_score"],
                r["fifa_ranking"], r["name"],
            ))
            ranked.extend(tied)
        standings[letter] = ranked
    return standings


def compute_third_place_table(standings):
    """Return the current third-placed team from each active group, ranked."""
    rows = [dict(standings[letter][2]) for letter in GROUP_LETTERS
            if len(standings.get(letter, [])) >= 3
            and standings[letter][2].get("played", 0) > 0]
    rows.sort(key=lambda r: (
        -r["points"], -r["gd"], -r["gf"], -r.get("conduct_score", 0),
        r.get("fifa_ranking", 999), r["name"],
    ))
    return rows


def match_number(match):
    """Return an explicit match number, with a fallback for knockout IDs."""
    if isinstance(match.get("match_number"), int):
        return match["match_number"]
    if match.get("stage") != "group":
        m = re.search(r"-(\d+)$", match.get("id", ""))
        if m:
            return int(m.group(1))
    return None


def match_winner(match):
    """Return the winning team slug, including penalty shoot-outs, or None."""
    if not match or match.get("status") != "completed":
        return None
    hs, as_ = match.get("home_score"), match.get("away_score")
    if not isinstance(hs, int) or not isinstance(as_, int):
        return None
    if hs != as_:
        return match["home"] if hs > as_ else match["away"]
    hp, ap = match.get("home_penalties"), match.get("away_penalties")
    if isinstance(hp, int) and isinstance(ap, int) and hp != ap:
        return match["home"] if hp > ap else match["away"]
    return None


def resolve_bracket_slots(matches, standings):
    """Resolve group places and prior-match winners/losers in match copies.

    Best-third labels are candidate sets rather than a complete allocation rule;
    those remain visible until the official Round-of-32 assignments are entered.
    """
    resolved = [dict(m) for m in matches]
    knockout = [m for m in resolved if m.get("stage") != "group"]

    groups_complete = {
        letter: bool(standings.get(letter))
        and all(row.get("played") == 3 for row in standings[letter])
        for letter in GROUP_LETTERS
    }
    for match in knockout:
        for side in ("home", "away"):
            slug = match.get(side, "")
            p = _PLACEHOLDER_RE.match(slug)
            if not p:
                continue
            if p.group("grp") and groups_complete.get(p.group("grp").upper()):
                pos = 0 if p.group("wru") == "winner" else 1
                match[side] = standings[p.group("grp").upper()][pos]["slug"]

    by_number = {match_number(m): m for m in knockout if match_number(m) is not None}
    for match in sorted(knockout, key=lambda m: match_number(m) or 999):
        for side in ("home", "away"):
            slug = match.get(side, "")
            p = _PLACEHOLDER_RE.match(slug)
            if not p or not p.group("num"):
                continue
            prior = by_number.get(int(p.group("num")))
            winner = match_winner(prior)
            if not winner:
                continue
            if p.group("wl") == "winner":
                match[side] = winner
            else:
                match[side] = prior["away"] if winner == prior["home"] else prior["home"]
    return resolved


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


_PLACEHOLDER_RE = re.compile(
    r"^(?P<wru>winner|runner-up)-group-(?P<grp>[a-l])$"
    r"|^third-(?P<third>[a-l]{2,})$"
    r"|^(?P<wl>winner|loser)-match-(?P<num>\d+)$"
)


def placeholder_label(slug):
    """Human label for a knockout placeholder slug, or None if not a placeholder.

    The knockout bracket is seeded before the teams are known, so each slot is
    a placeholder slug describing where its occupant comes from:

        winner-group-a    -> 'Winner Group A'
        runner-up-group-b -> 'Runner-up Group B'
        third-cefhi       -> '3rd Place C/E/F/H/I'
        winner-match-73   -> 'Winner Match 73'
        loser-match-101   -> 'Loser Match 101'

    Real team slugs return None so callers fall back to the actual team name.
    """
    m = _PLACEHOLDER_RE.match(slug or "")
    if not m:
        return None
    if m.group("grp"):
        kind = "Winner" if m.group("wru") == "winner" else "Runner-up"
        return f"{kind} Group {m.group('grp').upper()}"
    if m.group("third"):
        return "3rd Place " + "/".join(c.upper() for c in m.group("third"))
    kind = "Winner" if m.group("wl") == "winner" else "Loser"
    return f"{kind} Match {m.group('num')}"


def team_name(by_slug, slug):
    """Display name for a team slug, falling back to a placeholder or the slug."""
    t = by_slug.get(slug)
    if t:
        return t["name"]
    return placeholder_label(slug) or slug


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


def fmt_pop(value):
    """Format a population always in millions so values stay comparable.

    e.g. 525_000 -> '0.52M', 3_400_000 -> '3.4M', 114_500_000 -> '114.5M'.
    Uses 2 decimals below 1M so small nations don't collapse to '0.0M'.
    """
    if value is None:
        return "—"
    m = value / 1_000_000
    return f"{m:.2f}M" if m < 1 else f"{m:.1f}M"


def fmt_num(value, decimals=1, suffix=""):
    """Format a number to fixed decimals with an optional suffix; None -> '—'.

    e.g. fmt_num(0.781, 3) -> '0.781', fmt_num(4.7, 1, '%') -> '4.7%'.
    """
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{suffix}"
