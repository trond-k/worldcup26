"""Favourite / underdog odds engine for World Cup 2026 (standard library only).

Two independent models score every team 0-100 and turn a pair of team scores
into home/draw/away probabilities for a fixture:

  * football_score  - rank, squad market value, World Cup pedigree, squad age
                      profile and depth.
  * socio_score     - the "creative" set: per-capita wealth, population (talent
                      pool), economic power, legion-abroad ratio, big-5 league
                      concentration, plus a host bump.

The two models are never blended - the contrast between them is the story. All
tunable parameters live in CONFIG; the scoring/odds logic below never hard-codes
a weight.

Run directly for a self-test and a printout of the current favourites:

    python3 scripts/odds.py
"""

import math

from common import load_all_teams, load_tournament, squad_value


# --------------------------------------------------------------------------
# Tunable parameters - retune here without touching the logic below.
# --------------------------------------------------------------------------

CONFIG = {
    # Football model. Weights are over normalised (0-1) metrics and sum to 1.
    "football": {
        "value": 0.35,       # squad market value (log-scaled)
        "elo": 0.20,         # World Football Elo rating (results-based strength)
        "pedigree": 0.18,    # World Cup history (titles / apps / best finish)
        "fifa": 0.13,        # FIFA ranking (inverted: 1 = best)
        "experience": 0.09,  # share of squad in the 25-31 peak window
        "depth": 0.05,       # bottom-ten value as a share of total squad value
    },
    # Socio-economic model. Weights sum to 1; the host bump is added on top.
    "socio": {
        "wealth": 0.28,      # GNP per capita (log-scaled)
        "pool": 0.22,        # population (log-scaled)
        "economy": 0.12,     # total GNP (log-scaled)
        "legion": 0.22,      # share of squad playing abroad
        "big5": 0.16,        # share of squad in England/Spain/Italy/Germany/France
    },
    "host_bonus": 6.0,       # flat score points added to a host nation's socio score
    # Sub-weights for the World Cup pedigree composite (combined then normalised).
    "pedigree": {
        "titles": 0.50,
        "appearances": 0.25,
        "best_finish": 0.25,
    },
    # Match-odds conversion (shared by both models).
    "odds": {
        "elo_scale": 25.0,       # a 20-point gap => ~0.76 expected score
        "draw_max": 0.30,        # peak draw probability when teams are level
        "draw_sigma": 18.0,      # how fast the draw chance falls with the gap
        "home_advantage": 4.0,   # score points added when the home team is a host
    },
}

BIG5_LEAGUE_COUNTRIES = {"England", "Spain", "Italy", "Germany", "France"}

# Ordinal strength of a best World Cup finish (higher = better pedigree).
BEST_FINISH_RANK = {
    "winners": 8,
    "runner-up": 7,
    "third": 6,
    "fourth": 5,
    "semi-final": 4,
    "quarter-final": 3,
    "round-16": 2,
    "round-32": 1,
    "group-stage": 1,
    "never-qualified": 0,
}

PEAK_AGE_LO, PEAK_AGE_HI = 25, 31


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def _normalize(raw_by_slug, log=False):
    """Map {slug: value-or-None} to {slug: 0..1} via (optional log) min-max.

    Missing values fall back to the median of the present ones. A degenerate
    spread (all equal) maps everyone to 0.5.
    """
    def prep(v):
        if v is None:
            return None
        if log:
            return math.log10(v) if v > 0 else None
        return float(v)

    present = sorted(p for p in (prep(v) for v in raw_by_slug.values()) if p is not None)
    if not present:
        return {slug: 0.5 for slug in raw_by_slug}

    n = len(present)
    median = present[n // 2] if n % 2 else (present[n // 2 - 1] + present[n // 2]) / 2
    lo, hi = present[0], present[-1]
    span = hi - lo

    out = {}
    for slug, v in raw_by_slug.items():
        p = prep(v)
        if p is None:
            p = median
        out[slug] = 0.5 if span == 0 else (p - lo) / span
    return out


# --------------------------------------------------------------------------
# Raw per-team metric extractors
# --------------------------------------------------------------------------

def _ages(team):
    return [p.get("age") for p in team.get("squad", []) if isinstance(p.get("age"), int)]


def _peak_share(team):
    squad = team.get("squad", [])
    if not squad:
        return 0.0
    peak = sum(1 for a in _ages(team) if PEAK_AGE_LO <= a <= PEAK_AGE_HI)
    return peak / len(squad)


def _depth_ratio(team):
    """Bench value as a share of total value (higher = genuinely deeper)."""
    total = squad_value(team)
    if total <= 0:
        return 0.0
    vals = sorted((p.get("market_value_eur", 0) or 0)
                  for p in team.get("squad", []))
    # The previous implementation returned top-16 / total and described values
    # near 1 as deep. That is backwards: a top-heavy squad also approaches 1.
    # The bottom ten's share rewards value that remains beyond the likely match
    # squad instead of rewarding concentration among the stars.
    bench = sum(vals[:-16])
    return bench / total


def _abroad_share(team):
    squad = team.get("squad", [])
    if not squad:
        return 0.0
    home = team.get("name")
    abroad = sum(1 for p in squad
                 if p.get("club_country") and p.get("club_country") != home)
    return abroad / len(squad)


def _big5_share(team):
    squad = team.get("squad", [])
    if not squad:
        return 0.0
    n = sum(1 for p in squad if p.get("club_country") in BIG5_LEAGUE_COUNTRIES)
    return n / len(squad)


def _pedigree_raw(team, norm_titles, norm_apps, norm_finish):
    w = CONFIG["pedigree"]
    return (w["titles"] * norm_titles
            + w["appearances"] * norm_apps
            + w["best_finish"] * norm_finish)


# --------------------------------------------------------------------------
# Score assembly
# --------------------------------------------------------------------------

def build_team_scores(teams=None, tournament=None):
    """Compute both models for every team, normalised across the full field.

    Returns {slug: {"name", "football", "socio", "components": {...},
                    "density": {...}, "host": bool}}.
    """
    if teams is None:
        teams = load_all_teams()
    if tournament is None:
        tournament = load_tournament()
    hosts = set(tournament.get("hosts", []))

    by_slug = {t["slug"]: t for t in teams}

    # Raw metric collections keyed by slug.
    value_raw = {s: squad_value(t) for s, t in by_slug.items()}
    fifa_raw = {s: t.get("fifa_ranking") for s, t in by_slug.items()}
    elo_raw = {s: t.get("elo_rating") for s, t in by_slug.items()}
    titles_raw = {s: t.get("wc_titles") for s, t in by_slug.items()}
    apps_raw = {s: t.get("wc_appearances") for s, t in by_slug.items()}
    finish_raw = {s: BEST_FINISH_RANK.get(t.get("wc_best_finish")) for s, t in by_slug.items()}
    exp_raw = {s: _peak_share(t) for s, t in by_slug.items()}
    depth_raw = {s: _depth_ratio(t) for s, t in by_slug.items()}

    wealth_raw = {s: t.get("gnp_per_capita_usd") for s, t in by_slug.items()}
    pool_raw = {s: t.get("population") for s, t in by_slug.items()}
    econ_raw = {s: t.get("gnp_usd") for s, t in by_slug.items()}
    legion_raw = {s: _abroad_share(t) for s, t in by_slug.items()}
    big5_raw = {s: _big5_share(t) for s, t in by_slug.items()}

    # Normalise.
    n_value = _normalize(value_raw, log=True)
    n_fifa_rank = _normalize(fifa_raw)  # lower rank = better, so invert below
    n_elo = _normalize(elo_raw)  # higher rating = stronger
    n_titles = _normalize(titles_raw)
    n_apps = _normalize(apps_raw)
    n_finish = _normalize(finish_raw)
    n_exp = _normalize(exp_raw)
    n_depth = _normalize(depth_raw)

    n_wealth = _normalize(wealth_raw, log=True)
    n_pool = _normalize(pool_raw, log=True)
    n_econ = _normalize(econ_raw, log=True)
    n_legion = _normalize(legion_raw)
    n_big5 = _normalize(big5_raw)

    # Pedigree composite, then normalise it so its weight is comparable.
    ped_raw = {s: _pedigree_raw(by_slug[s], n_titles[s], n_apps[s], n_finish[s])
               for s in by_slug}
    n_ped = _normalize(ped_raw)

    fb = CONFIG["football"]
    sc = CONFIG["socio"]
    scores = {}
    for s, t in by_slug.items():
        n_fifa = 1.0 - n_fifa_rank[s]  # invert so #1 ranked => 1.0
        football = 100.0 * (
            fb["value"] * n_value[s]
            + fb["elo"] * n_elo[s]
            + fb["fifa"] * n_fifa
            + fb["pedigree"] * n_ped[s]
            + fb["experience"] * n_exp[s]
            + fb["depth"] * n_depth[s]
        )
        is_host = t.get("name") in hosts
        socio = 100.0 * (
            sc["wealth"] * n_wealth[s]
            + sc["pool"] * n_pool[s]
            + sc["economy"] * n_econ[s]
            + sc["legion"] * n_legion[s]
            + sc["big5"] * n_big5[s]
        )
        if is_host:
            socio += CONFIG["host_bonus"]
        socio = max(0.0, min(100.0, socio))

        pop = pool_raw[s]
        gnp = econ_raw[s]
        scores[s] = {
            "name": t["name"],
            "football": round(football, 1),
            "socio": round(socio, 1),
            "host": is_host,
            "components": {
                "value": value_raw[s], "fifa": fifa_raw[s],
                "elo": elo_raw[s],
                "pedigree": round(n_ped[s], 3),
                "peak_share": round(exp_raw[s], 3),
                "legion": round(legion_raw[s], 3),
                "big5": round(big5_raw[s], 3),
            },
            "density": {
                # "Punches above its weight": squad value per citizen / per GNP$.
                "value_per_capita": (value_raw[s] / pop) if pop else None,
                "value_per_gnp": (value_raw[s] / gnp) if gnp else None,
            },
        }
    return scores


# --------------------------------------------------------------------------
# Match odds
# --------------------------------------------------------------------------

def match_odds(score_home, score_away, host_home=False):
    """Convert two team scores to {home, draw, away} probabilities (sum 1.0).

    Elo-style expected score splits home vs away; a Gaussian peaked at an even
    matchup carves out the draw. host_home adds a venue advantage in points.
    """
    o = CONFIG["odds"]
    d = score_home - score_away + (o["home_advantage"] if host_home else 0.0)
    e_home = 1.0 / (1.0 + 10.0 ** (-d / o["elo_scale"]))
    p_draw = o["draw_max"] * math.exp(-(d * d) / (2.0 * o["draw_sigma"] ** 2))
    p_home = (1.0 - p_draw) * e_home
    p_away = (1.0 - p_draw) * (1.0 - e_home)
    return {"home": p_home, "draw": p_draw, "away": p_away}


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

def _self_test():
    teams = load_all_teams()
    tournament = load_tournament()
    scores = build_team_scores(teams, tournament)
    assert len(scores) == len(teams), "score count must match team count"

    # 1. Every score within range.
    for s, sc in scores.items():
        assert 0.0 <= sc["football"] <= 100.0, f"{s} football out of range: {sc['football']}"
        assert 0.0 <= sc["socio"] <= 100.0, f"{s} socio out of range: {sc['socio']}"

    # 2. Probabilities sum to 1 and stay in [0,1] across a range of gaps.
    for sh in range(0, 101, 10):
        for sa in range(0, 101, 25):
            o = match_odds(sh, sa)
            total = o["home"] + o["draw"] + o["away"]
            assert abs(total - 1.0) < 1e-9, f"probs sum {total} for {sh}/{sa}"
            assert all(0.0 <= p <= 1.0 for p in o.values()), f"prob out of range {o}"

    # 3. Monotonic: a stronger team must be the favourite.
    o = match_odds(60, 40)
    assert o["home"] > o["away"], "higher score should win more often"
    assert match_odds(70, 30)["home"] > match_odds(55, 45)["home"], "bigger gap => bigger fav"

    # 4. Even matchup => peak draw and home == away.
    even = match_odds(50, 50)
    assert abs(even["home"] - even["away"]) < 1e-9, "even teams symmetric"
    assert even["draw"] >= match_odds(70, 30)["draw"], "draw peaks when level"

    # 5. Host advantage helps the home side.
    assert match_odds(50, 50, host_home=True)["home"] > even["home"], "host edge"

    print("self-test: all assertions passed\n")
    _report(scores, teams, tournament)


def _report(scores, teams, tournament):
    def line(slug, sc, key):
        return f"  {sc[key]:5.1f}  {sc['name']}"

    print("Top 10 - FOOTBALL favourites")
    for s, sc in sorted(scores.items(), key=lambda kv: -kv[1]["football"])[:10]:
        print(line(s, sc, "football"))

    print("\nTop 10 - SOCIO-ECONOMIC favourites")
    for s, sc in sorted(scores.items(), key=lambda kv: -kv[1]["socio"])[:10]:
        host = "  (host)" if sc["host"] else ""
        print(f"  {sc['socio']:5.1f}  {sc['name']}{host}")

    # Biggest disagreement between the two models (rank difference).
    fb_rank = {s: i for i, (s, _) in
               enumerate(sorted(scores.items(), key=lambda kv: -kv[1]["football"]))}
    so_rank = {s: i for i, (s, _) in
               enumerate(sorted(scores.items(), key=lambda kv: -kv[1]["socio"]))}
    disagree = sorted(scores.items(),
                      key=lambda kv: -abs(fb_rank[kv[0]] - so_rank[kv[0]]))[:5]
    print("\nBiggest model disagreements (football rank vs socio rank)")
    for s, sc in disagree:
        print(f"  {sc['name']:20s} football #{fb_rank[s]+1:<3d} socio #{so_rank[s]+1}")

    # Sample fixture: top football team (home, treated as host) vs a low one.
    order = sorted(scores.items(), key=lambda kv: -kv[1]["football"])
    top, bottom = order[0], order[-1]
    print(f"\nSample fixture (football outlook; heuristic shares): "
          f"{top[1]['name']} vs {bottom[1]['name']}")
    o = match_odds(top[1]["football"], bottom[1]["football"])
    print(f"  home {o['home']*100:4.1f}%  draw {o['draw']*100:4.1f}%  "
          f"away {o['away']*100:4.1f}%")

    seeded = sum(1 for t in teams if t.get("wc_titles") is not None)
    tail = ("" if seeded == len(teams)
            else "; pedigree term is ~flat until all are seeded")
    print(f"\nnote: {seeded}/{len(teams)} teams have wc_* data{tail}.")


if __name__ == "__main__":
    _self_test()
