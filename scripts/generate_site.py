#!/usr/bin/env python3
"""Generate a minimalist static website under site/ from the JSON data.

Produces a small documentation-style HTML site (no JavaScript, no dependencies
beyond the Python standard library):

  site/index.html              tournament overview + group index
  site/group-<a..l>.html       per-group standings + squad tables
  site/team/<slug>.html        per-team page: metadata, squad, fixtures
  site/favourites.html         favourite/underdog odds-model rankings
  site/methodology.html        how the odds models are weighted and computed
  site/stats.html              market-value and economy rankings
  site/results.html            live standings + results by date
  site/day-<date>.html         per-matchday calendar page (cards + date pager)
  site/match/<id>.html         rich per-match detail (goals, lineups, stats)
  site/assets/style.css        the single stylesheet

The JSON under data/ is the source of truth; everything under site/ is
generated. Deployed to GitHub Pages by .github/workflows/pages.yml.

Usage: python3 scripts/generate_site.py
"""

import datetime
import hashlib
import html
import os
import shutil
from zoneinfo import ZoneInfo

from common import (
    CARD_ICON,
    GROUP_LETTERS,
    ROOT,
    STAT_LABELS,
    compute_standings,
    fmt_eur,
    fmt_num,
    fmt_pop,
    fmt_usd,
    load_all_teams,
    load_match_details,
    load_results,
    load_tournament,
    minute_key,
    sorted_squad,
    squad_value,
    team_name,
)
from odds import (
    BEST_FINISH_RANK,
    CONFIG,
    PEAK_AGE_HI,
    PEAK_AGE_LO,
    as_decimal_odds,
    build_team_scores,
    match_odds,
)

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def pretty_date(iso):
    """'2026-06-15' -> '15 June 2026'; pass through anything unparseable."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MONTHS[m]} {y}"
    except (ValueError, AttributeError, IndexError):
        return iso

SITE_DIR = os.path.join(ROOT, "site")
ASSETS_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

with open(os.path.join(ASSETS_SRC, "style.css"), "rb") as _f:
    # Short content hash; appended to the stylesheet URL so browsers fetch a
    # fresh copy whenever the CSS changes instead of serving a stale cache.
    STYLE_VER = hashlib.sha1(_f.read()).hexdigest()[:8]

POSITION_NAMES = {"GK": "Goalkeepers", "DF": "Defenders", "MF": "Midfielders", "FW": "Forwards"}


# --- tiny HTML helpers -------------------------------------------------------

def esc(value):
    """HTML-escape any value (None -> empty string)."""
    return html.escape("" if value is None else str(value))


def rel(depth):
    """Path back to the site root from a page nested `depth` directories deep."""
    return "../" * depth


def page(title, body, depth=0, active=None):
    """Wrap body HTML in the shared site shell. `active` highlights a nav item."""
    root = rel(depth)
    nav_items = [("", "Home", "home")]
    if CALENDAR_HOME:
        nav_items.append((CALENDAR_HOME, "Calendar", "calendar"))
    nav_items += [("favourites.html", "Favourites", "favourites"),
                  ("methodology.html", "Methodology", "methodology"),
                  ("stats.html", "Stats", "stats"),
                  ("results.html", "Results", "results")]
    nav = []
    for href, label, key in nav_items:
        cls = ' class="active"' if key == active else ""
        nav.append(f'<a{cls} href="{root}{href or "index.html"}">{esc(label)}</a>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{root}assets/style.css?v={STYLE_VER}">
</head>
<body>
<a class="site-banner" href="{root}index.html">Pitchonomics</a>
<header class="site-header">
<a class="brand" href="{root}index.html">World Cup 2026</a>
<nav>{''.join(nav)}</nav>
</header>
<main>
{body}
</main>
<footer class="site-footer">
<p>{esc(FOOTER_NOTE)}</p>
<p>Generated from the dataset's JSON source of truth. Not affiliated with FIFA.</p>
</footer>
</body>
</html>
"""


def table(headers, rows, cls=""):
    """Build an HTML table. Header cells are escaped; row cells are raw HTML."""
    thead = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    attr = f' class="{cls}"' if cls else ""
    return (f'<div class="table-wrap"><table{attr}>\n<thead><tr>{thead}</tr></thead>\n'
            f'<tbody>\n' + "\n".join(body) + "\n</tbody></table></div>")


def link(href, text):
    return f'<a href="{href}">{esc(text)}</a>'


def write(relpath, content):
    path = os.path.join(SITE_DIR, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# --- shared fragments --------------------------------------------------------

def club_label(player):
    club = player.get("club", "") or ""
    if player.get("club_country"):
        club += f" ({player['club_country']})"
    return club


def squad_table(team):
    rows = []
    for i, p in enumerate(sorted_squad(team), start=1):
        rows.append([
            str(i),
            esc(p.get("name", "")),
            esc(p.get("position", "")),
            esc(club_label(p)),
            esc(p.get("age")) if p.get("age") is not None else "—",
            esc(fmt_eur(p.get("market_value_eur", 0))),
        ])
    return table(["#", "Player", "Pos", "Club", "Age", "Market value"], rows, cls="squad")


def standings_table(rows):
    out = []
    for r in rows:
        gd = f"{r['gd']:+d}" if r["gd"] != 0 else "0"
        out.append([
            esc(r["name"]), str(r["played"]), str(r["won"]), str(r["drawn"]),
            str(r["lost"]), str(r["gf"]), str(r["ga"]), gd,
            f"<strong>{r['points']}</strong>",
        ])
    return table(["Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"], out, cls="standings")


def match_score_label(m, by_slug, depth, link_detail):
    """One-line 'Home 2–0 Away' fragment, linking to the detail page if present."""
    home, away = team_name(by_slug, m["home"]), team_name(by_slug, m["away"])
    if m.get("status") == "completed":
        text = f"{home} {m['home_score']}–{m['away_score']} {away}"
    else:
        text = f"{home} vs {away}"
    if link_detail:
        href = f"{rel(depth)}match/{esc(m['id'])}.html"
        return f'<a href="{href}">{esc(text)}</a>'
    return esc(text)


# --- featured matches (home page) -------------------------------------------

def select_featured_matches(matches, today):
    """Pick the day's fixtures: today's matches, else the next future matchday.

    Returns (label, iso_date, [match, ...]); ([], None, []) when nothing remains.
    """
    by_date = {}
    for m in matches:
        by_date.setdefault(m["date"], []).append(m)
    if today in by_date:
        return ("Today's matches", today, by_date[today])
    future = sorted(d for d in by_date if d > today)
    if future:
        return ("Next matches", future[0], by_date[future[0]])
    return (None, None, [])


# Stats shown in each match-card team panel:
#   (label, value_fn, fmt_fn, better, title_fn)
# `better` is "high" or "low" — which direction wins the head-to-head highlight.
# `title_fn` adds a <dt> tooltip (e.g. indicator provenance), or is None.
CARD_STATS = [
    ("Squad value", squad_value, fmt_eur, "high", None),
    ("Citizens", lambda t: t.get("population"), fmt_pop, "high", None),
    ("GNP/capita", lambda t: t.get("gnp_per_capita_usd"), fmt_usd, "high", None),
    ("HDI", lambda t: t.get("hdi"), lambda v: fmt_num(v, 3), "high",
     lambda t: ("Human Development Index"
                + (f" ({t['indicators_year']})" if t.get("indicators_year") else ""))),
]


def _leads(self_t, opp_t, value_fn, better):
    """True when self_t beats opp_t on this stat (per `better` direction)."""
    sv, ov = value_fn(self_t), value_fn(opp_t)
    if sv is None or ov is None or sv == ov:
        return False
    return sv > ov if better == "high" else sv < ov


def team_block(slug, by_slug, opponent_slug=None):
    """A team panel for a match card: name plus CARD_STATS.

    When opponent_slug is given, the side leading on a stat gets a `card-fav`
    highlight (the same head-to-head cue used by the odds rows).
    """
    t = by_slug.get(slug)
    if not t:
        return f'<div class="team"><span class="tname">{esc(slug)}</span></div>'
    name_link = link(f"team/{t['slug']}.html", t["name"])
    opp = by_slug.get(opponent_slug) if opponent_slug else None
    rows = []
    for label, value_fn, fmt_fn, better, title_fn in CARD_STATS:
        dd_cls = ' class="card-fav"' if opp and _leads(t, opp, value_fn, better) else ""
        dt_attr = ""
        if title_fn:
            tip = title_fn(t)
            if tip:
                dt_attr = f' title="{esc(tip)}"'
        rows.append(
            f'<div><dt{dt_attr}>{esc(label)}</dt>'
            f'<dd{dd_cls}>{esc(fmt_fn(value_fn(t)))}</dd></div>'
        )
    return (
        '<div class="team">'
        f'<span class="tname">{name_link}</span>'
        f'<dl class="card-stats">{"".join(rows)}</dl>'
        '</div>'
    )


# --- odds (two independent models: football & socio-economic) ----------------

# (model key, display label) — order shown on the site.
ODDS_MODELS = (("football", "Football"), ("socio", "Socio-econ"))


def match_model_odds(m, scores):
    """Both models' {home, draw, away} probabilities for a fixture.

    Returns {'football': {...}, 'socio': {...}} or None if either team is
    missing a score. The home side gets a venue edge only when it is a host.
    """
    h, a = m.get("home"), m.get("away")
    if not scores or h not in scores or a not in scores:
        return None
    host_home = bool(scores[h].get("host"))
    return {
        key: match_odds(scores[h][key], scores[a][key], host_home=host_home)
        for key, _ in ODDS_MODELS
    }


def render_card_odds(m, scores):
    """Compact two-row odds footer for a match card (home / draw / away %)."""
    mo = match_model_odds(m, scores)
    if not mo:
        return ""
    lines = [
        '<div class="mc-odds-line mc-odds-head">'
        '<span class="mco-model"></span>'
        '<span class="mco-h">Home</span><span class="mco-d">Draw</span>'
        '<span class="mco-a">Away</span></div>'
    ]
    for key, label in ODDS_MODELS:
        o = mo[key]
        fav = max(("home", "draw", "away"), key=lambda k: o[k])

        def cell(k, css):
            klass = f"mco-{css}" + (" mco-fav" if k == fav else "")
            return f'<span class="{klass}">{round(o[k] * 100)}%</span>'

        lines.append(
            '<div class="mc-odds-line">'
            f'<span class="mco-model">{esc(label)}</span>'
            f'{cell("home", "h")}{cell("draw", "d")}{cell("away", "a")}'
            '</div>'
        )
    return '<div class="mc-odds">' + "".join(lines) + "</div>"


def render_match_card(m, by_slug, details, scores=None):
    completed = m.get("status") == "completed"
    if completed:
        centre = f'<span class="score">{esc(m["home_score"])}–{esc(m["away_score"])}</span>'
    else:
        centre = '<span class="vs">vs</span>'
    if m.get("id") in details:
        centre = f'<a class="centre-link" href="match/{esc(m["id"])}.html">{centre}</a>'
    grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
    grp_html = f'<div class="mc-group">{esc(grp)}</div>' if grp else ""
    return (
        '<div class="match-card">'
        f'{grp_html}'
        f'{team_block(m["home"], by_slug, m["away"])}'
        f'<div class="centre">{centre}</div>'
        f'{team_block(m["away"], by_slug, m["home"])}'
        f'{render_card_odds(m, scores)}'
        '</div>'
    )


# --- calendar (per-matchday pages) ------------------------------------------

def short_date(iso):
    """'2026-06-15' -> '15 Jun'; pass through anything unparseable."""
    try:
        _, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MONTHS[m][:3]}"
    except (ValueError, IndexError):
        return iso


def render_date_nav(dates, current, counts):
    """Prev/next pager + a clickable strip of every matchday (depth-0 links)."""
    i = dates.index(current)
    prev_d = dates[i - 1] if i > 0 else None
    next_d = dates[i + 1] if i < len(dates) - 1 else None
    prev_html = (f'<a class="pager-link" href="day-{prev_d}.html">&lsaquo; {esc(short_date(prev_d))}</a>'
                 if prev_d else '<span class="pager-link disabled">&lsaquo; Prev</span>')
    next_html = (f'<a class="pager-link" href="day-{next_d}.html">{esc(short_date(next_d))} &rsaquo;</a>'
                 if next_d else '<span class="pager-link disabled">Next &rsaquo;</span>')
    chips = []
    for d in dates:
        cls = "date-chip active" if d == current else "date-chip"
        chips.append(
            f'<a class="{cls}" href="day-{d}.html">'
            f'<span class="dc-date">{esc(short_date(d))}</span>'
            f'<span class="dc-count">{counts.get(d, 0)}</span></a>'
        )
    return (
        '<nav class="date-nav" aria-label="Matchdays">'
        f'<div class="date-pager">{prev_html}{next_html}</div>'
        f'<div class="date-strip">{"".join(chips)}</div>'
        '</nav>'
    )


def render_day(date, dates, day_matches, by_slug, details, scores, counts):
    """One matchday page: date navigator + the day's match cards."""
    body = [f'<h1>Matches <span class="muted">— {esc(pretty_date(date))}</span></h1>']
    body.append(render_date_nav(dates, date, counts))
    body.append('<div class="matchday">')
    for m in day_matches:
        body.append(render_match_card(m, by_slug, details, scores))
    body.append('</div>')
    return page(f"Matches — {pretty_date(date)}", "\n".join(body),
                depth=0, active="calendar")


# --- page renderers ----------------------------------------------------------

def render_index(tournament, by_slug, matches, details, today, scores):
    t = tournament
    body = [f"<h1>{esc(t['name'])}</h1>"]
    hosts = ", ".join(t.get("hosts", []))
    body.append(f'<p class="lead">{esc(hosts)} &middot; '
                f'{esc(t.get("start_date"))} – {esc(t.get("end_date"))}</p>')
    body.append(f"<p>{esc(t.get('format', ''))}</p>")
    if t.get("draw"):
        d = t["draw"]
        body.append(f'<p class="muted">Draw: {esc(d.get("date"))}, {esc(d.get("location"))}</p>')

    label, fdate, featured = select_featured_matches(matches, today)
    if featured:
        body.append(f'<h2>{esc(label)} '
                    f'<span class="muted">— {esc(pretty_date(fdate))}</span></h2>')
        body.append('<div class="matchday">')
        for m in featured:
            body.append(render_match_card(m, by_slug, details, scores))
        body.append('</div>')
        body.append(f'<p>{link(f"day-{fdate}.html", "Browse all matchdays →")}</p>')

    rows = []
    for letter in GROUP_LETTERS:
        slugs = t["groups"].get(letter, [])
        names = []
        for s in slugs:
            tm = by_slug.get(s)
            if tm:
                names.append(link(f"team/{s}.html", tm["name"]))
            else:
                names.append(f"<em>{esc(s)}</em>")
        group_link = link(f"group-{letter.lower()}.html", f"Group {letter}")
        rows.append([group_link, ", ".join(names)])
    body.append("<h2>Groups</h2>")
    body.append(table(["Group", "Teams"], rows))
    body.append(f'<p>See {link("favourites.html", "Favourites")} for the '
                f'odds models, {link("stats.html", "Stats")} for market-value and '
                f'economy rankings, and {link("results.html", "Results")} for '
                f'fixtures and live standings.</p>')
    return page(t["name"], "\n".join(body), depth=0, active="home")


def render_group(letter, slugs, by_slug, standings):
    teams = [by_slug[s] for s in slugs if s in by_slug]
    body = [f"<h1>Group {esc(letter)}</h1>"]

    rows = standings.get(letter, [])
    if rows and any(r["played"] for r in rows):
        body.append("<h2>Standings</h2>")
        body.append(standings_table(rows))

    body.append("<h2>Teams</h2>")
    summary = []
    for t in sorted(teams, key=squad_value, reverse=True):
        summary.append([
            link(f"team/{t['slug']}.html", t["name"]),
            esc(t.get("confederation", "")),
            esc(t.get("fifa_ranking")) if t.get("fifa_ranking") else "—",
            esc(fmt_eur(squad_value(t))),
        ])
    body.append(table(["Team", "Confederation", "FIFA rank", "Squad value"], summary))

    missing = [s for s in slugs if s not in by_slug]
    if missing:
        body.append(f'<p class="muted">Pending data: {esc(", ".join(missing))}</p>')

    for t in teams:
        team_link = link(f"team/{t['slug']}.html", t["name"])
        body.append(f'<h3 id="{esc(t["slug"])}">{team_link}</h3>')
        body.append(squad_table(t))
    return page(f"Group {letter}", "\n".join(body), depth=0)


# Team-page socioeconomic dossier: (group title, [(label, json key, fmt_fn)]).
INDICATOR_GROUPS = [
    ("Economy", [
        ("GDP growth", "gdp_growth_pct", lambda v: fmt_num(v, 1, "%")),
        ("Inflation", "inflation_pct", lambda v: fmt_num(v, 1, "%")),
        ("Unemployment", "unemployment_pct", lambda v: fmt_num(v, 1, "%")),
    ]),
    ("Development", [
        ("Human Development Index", "hdi", lambda v: fmt_num(v, 3)),
        ("Gini index", "gini_index", lambda v: fmt_num(v, 1)),
        ("Median age", "median_age_years", lambda v: fmt_num(v, 1, " yrs")),
    ]),
    ("Governance", [
        ("Democracy index", "democracy_index", lambda v: fmt_num(v, 2)),
        ("Corruption Perceptions Index", "corruption_perceptions_index", lambda v: fmt_num(v, 0)),
        ("Political stability", "political_stability", lambda v: fmt_num(v, 2)),
        ("Government effectiveness", "government_effectiveness", lambda v: fmt_num(v, 2)),
    ]),
    ("Society", [
        ("Press freedom", "press_freedom_score", lambda v: fmt_num(v, 1)),
        ("Global Peace Index", "global_peace_index", lambda v: fmt_num(v, 2)),
        ("Military spend", "military_expenditure_pct_gdp", lambda v: fmt_num(v, 1, "% GDP")),
    ]),
]


def render_indicators(team):
    """Grouped socioeconomic dossier for a team page; '' when none present."""
    blocks = []
    for title, specs in INDICATOR_GROUPS:
        items = [(label, esc(fmt_fn(team.get(key))))
                 for label, key, fmt_fn in specs if team.get(key) is not None]
        if not items:
            continue
        rows = "".join(f"<dt>{esc(label)}</dt><dd>{val}</dd>" for label, val in items)
        blocks.append(f'<div class="ind-group"><h3>{esc(title)}</h3>'
                      f'<dl class="meta">{rows}</dl></div>')
    if not blocks:
        return ""
    yr = team.get("indicators_year")
    sub = f' <span class="muted">— {esc(yr)}</span>' if yr else ""
    return (f"<h2>Indicators{sub}</h2>"
            '<div class="ind-grid">' + "".join(blocks) + "</div>")


def render_team(team, by_slug, matches, details):
    body = [f"<h1>{esc(team['name'])}</h1>"]
    meta = []
    if team.get("group"):
        meta.append(("Group", link(f"{rel(1)}group-{team['group'].lower()}.html",
                                    f"Group {team['group']}")))
    if team.get("confederation"):
        meta.append(("Confederation", esc(team["confederation"])))
    if team.get("fifa_ranking"):
        meta.append(("FIFA ranking", esc(team["fifa_ranking"])))
    if team.get("coach"):
        meta.append(("Coach", esc(team["coach"])))
    meta.append(("Squad value", esc(fmt_eur(squad_value(team)))))
    if team.get("gnp_usd") is not None:
        yr = f" ({team['gnp_year']})" if team.get("gnp_year") else ""
        meta.append(("GNP", esc(fmt_usd(team["gnp_usd"])) + esc(yr)))
    if team.get("gnp_per_capita_usd") is not None:
        meta.append(("GNP per capita", esc(fmt_usd(team["gnp_per_capita_usd"]))))
    if team.get("population") is not None:
        meta.append(("Population", esc(f"{team['population']:,}")))
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in meta)
    body.append(f'<dl class="meta">{dl}</dl>')

    body.append(render_indicators(team))

    # Fixtures for this team.
    team_matches = [m for m in matches
                    if team["slug"] in (m.get("home"), m.get("away"))]
    if team_matches:
        body.append("<h2>Fixtures</h2>")
        rows = []
        for m in team_matches:
            has_detail = m.get("id") in details
            grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
            rows.append([
                esc(m.get("date", "")),
                esc(grp),
                match_score_label(m, by_slug, depth=1, link_detail=has_detail),
                esc("completed" if m.get("status") == "completed" else "scheduled"),
            ])
        body.append(table(["Date", "Stage", "Match", "Status"], rows))

    body.append("<h2>Squad</h2>")
    body.append(squad_table(team))
    return page(team["name"], "\n".join(body), depth=1)


def render_stats(teams):
    body = ["<h1>Statistics</h1>",
            f'<p class="muted">Based on {len(teams)} teams with data.</p>']

    ranked = sorted(teams, key=squad_value, reverse=True)
    body.append("<h2>Most valuable squads</h2>")
    rows = [[str(i), link(f"team/{t['slug']}.html", t["name"]),
             esc(t.get("group", "")), esc(fmt_eur(squad_value(t)))]
            for i, t in enumerate(ranked, 1)]
    body.append(table(["Rank", "Team", "Group", "Squad value"], rows))

    body.append("<h2>Total value by group</h2>")
    by_group = {}
    for t in teams:
        by_group.setdefault(t.get("group"), []).append(t)
    rows = []
    for letter in GROUP_LETTERS:
        grp = by_group.get(letter, [])
        if grp:
            total = sum(squad_value(t) for t in grp)
            rows.append([link(f"group-{letter.lower()}.html", f"Group {letter}"),
                         str(len(grp)), esc(fmt_eur(total))])
    body.append(table(["Group", "Teams", "Total value"], rows))

    players = []
    for t in teams:
        for p in t.get("squad", []):
            players.append((p, t))
    players.sort(key=lambda pt: pt[0].get("market_value_eur", 0), reverse=True)
    body.append("<h2>Top 25 most valuable players</h2>")
    rows = [[str(i), esc(p.get("name", "")),
             link(f"team/{t['slug']}.html", t["name"]),
             esc(p.get("club", "")), esc(fmt_eur(p.get("market_value_eur", 0)))]
            for i, (p, t) in enumerate(players[:25], 1)]
    body.append(table(["Rank", "Player", "Team", "Club", "Market value"], rows))

    total_all = sum(squad_value(t) for t in teams)
    n_players = len(players)
    avg = total_all // n_players if n_players else 0
    body.append("<h2>Summary</h2>")
    body.append(f"<ul><li>Total market value of all squads: <strong>{esc(fmt_eur(total_all))}</strong></li>"
                f"<li>Players counted: <strong>{n_players}</strong></li>"
                f"<li>Average player value: <strong>{esc(fmt_eur(avg))}</strong></li></ul>")

    econ = [t for t in teams if t.get("gnp_usd") is not None]
    if econ:
        body.append("<h2>Economy (GNP)</h2>")
        body.append('<p class="muted">Gross National Product (World Bank GNI). '
                    'See the README for sources and caveats.</p>')
        body.append("<h3>By total GNP</h3>")
        rows = [[str(i), link(f"team/{t['slug']}.html", t["name"]),
                 esc(t.get("group", "")), esc(fmt_usd(t["gnp_usd"])),
                 esc(t.get("gnp_year", ""))]
                for i, t in enumerate(sorted(econ, key=lambda x: x["gnp_usd"], reverse=True), 1)]
        body.append(table(["Rank", "Team", "Group", "GNP", "Year"], rows))

        pc = [t for t in econ if t.get("gnp_per_capita_usd") is not None]
        body.append("<h3>By GNP per capita</h3>")
        rows = [[str(i), link(f"team/{t['slug']}.html", t["name"]),
                 esc(t.get("group", "")), esc(fmt_usd(t["gnp_per_capita_usd"])),
                 esc(t.get("gnp_year", ""))]
                for i, t in enumerate(sorted(pc, key=lambda x: x["gnp_per_capita_usd"], reverse=True), 1)]
        body.append(table(["Rank", "Team", "Group", "GNP per capita", "Year"], rows))

    return page("Statistics", "\n".join(body), depth=0, active="stats")


def _fav_table(order, ranks, model, by_slug):
    """Ranked table (Rank, Team, Group, Score) for one model."""
    rows = []
    for slug, sc in order:
        grp = (by_slug.get(slug) or {}).get("group", "")
        host = ' <span class="muted">(host)</span>' if sc.get("host") else ""
        rows.append([str(ranks[slug]),
                     link(f"team/{slug}.html", sc["name"]) + host,
                     esc(grp), esc(f"{sc[model]:.1f}")])
    return table(["#", "Team", "Grp", "Score"], rows, cls="fav-rank")


def render_favourites(teams, scores, by_slug):
    body = ["<h1>Favourites</h1>",
            '<p class="lead">Two independent toy models rate every team 0–100.</p>',
            '<p class="muted">The <strong>football</strong> model weighs squad '
            'market value, FIFA ranking, World Cup pedigree and squad age/depth. '
            'The <strong>socio-economic</strong> model weighs wealth (GNP per '
            'capita), population, total GNP, the share of the squad playing abroad '
            'and in the big-5 leagues, plus a host bump. They are never blended — '
            'the gaps between them are the interesting part. Estimates only, not '
            'betting advice.</p>',
            '<p class="muted">See <a href="methodology.html">Methodology</a> for '
            'the full weighting and how scores become match odds.</p>']

    fb_order = sorted(scores.items(), key=lambda kv: -kv[1]["football"])
    so_order = sorted(scores.items(), key=lambda kv: -kv[1]["socio"])
    fb_rank = {s: i for i, (s, _) in enumerate(fb_order, 1)}
    so_rank = {s: i for i, (s, _) in enumerate(so_order, 1)}

    body.append('<div class="fav-cols">')
    body.append('<div><h2>Football favourites</h2>'
                + _fav_table(fb_order, fb_rank, "football", by_slug) + "</div>")
    body.append('<div><h2>Socio-economic favourites</h2>'
                + _fav_table(so_order, so_rank, "socio", by_slug) + "</div>")
    body.append("</div>")

    # Overachievers: football rank far better than socio-economic rank.
    climbs = sorted(scores, key=lambda s: so_rank[s] - fb_rank[s], reverse=True)
    rows = []
    for slug in climbs:
        gap = so_rank[slug] - fb_rank[slug]
        if gap <= 0:
            break
        rows.append([link(f"team/{slug}.html", scores[slug]["name"]),
                     f"#{fb_rank[slug]}", f"#{so_rank[slug]}",
                     f'<strong>+{gap}</strong>'])
    body.append("<h2>Punching above their weight</h2>")
    body.append('<p class="muted">Teams ranked far higher by football than by '
                'socio-economics — overachievers relative to their resources.</p>')
    body.append(table(["Team", "Football", "Socio-econ", "Climb"], rows[:8]))

    # Talent density: squad value per citizen.
    dens = [(s, sc) for s, sc in scores.items()
            if sc["density"].get("value_per_capita") is not None]
    dens.sort(key=lambda kv: kv[1]["density"]["value_per_capita"], reverse=True)
    rows = []
    for slug, sc in dens[:10]:
        t = by_slug.get(slug, {})
        vpc = sc["density"]["value_per_capita"]
        rows.append([link(f"team/{slug}.html", sc["name"]),
                     esc(fmt_eur(squad_value(t))) if t else "—",
                     esc(fmt_pop(t.get("population"))) if t else "—",
                     f"€{round(vpc):,}"])
    body.append("<h2>Most squad value per citizen</h2>")
    body.append('<p class="muted">Squad market value spread across the '
                'population — a talent-density read on the small nations.</p>')
    body.append(table(["Team", "Squad value", "Citizens", "€ / citizen"], rows))

    return page("Favourites", "\n".join(body), depth=0, active="favourites")


# Human-readable labels + descriptions for each tunable weight, keyed to CONFIG.
# Kept here (not in CONFIG) so the page reads well; the numbers come from CONFIG
# so retuning the engine updates this page automatically.
FOOTBALL_WEIGHT_INFO = {
    "value": ("Squad market value",
              "Combined Transfermarkt value of the 26-man squad (log-scaled). "
              "The single strongest signal of strength."),
    "fifa": ("FIFA ranking",
             "The official world ranking, inverted so that #1 counts as best."),
    "pedigree": ("World Cup pedigree",
                 "Historical record through 2022 — titles, appearances and best "
                 "finish (see the pedigree breakdown below)."),
    "experience": ("Peak-age share",
                   f"Share of the squad in the {PEAK_AGE_LO}–{PEAK_AGE_HI} prime "
                   "age window."),
    "depth": ("Squad depth",
              "Value of the top-16 players as a share of the whole squad — "
              "rewards strength beyond the first XI."),
}

SOCIO_WEIGHT_INFO = {
    "wealth": ("Wealth — GNP per capita",
               "National income per person (log-scaled)."),
    "pool": ("Talent pool — population",
             "Total population, a proxy for how many players a nation can draw "
             "on (log-scaled)."),
    "economy": ("Economy — total GNP",
                "Total national income (log-scaled)."),
    "legion": ("Legionnaires",
               "Share of the squad playing their club football abroad."),
    "big5": ("Big-5 league share",
             "Share of the squad at clubs in England, Spain, Italy, Germany or "
             "France — the five strongest leagues."),
}

PEDIGREE_INFO = {
    "titles": ("World Cup titles", "Number of tournaments won."),
    "appearances": ("Tournament appearances", "Number of finals reached."),
    "best_finish": ("Best finish", "Furthest the nation has ever progressed."),
}


def _weight_table(config_block, info):
    """Render a weight table (Factor / Weight / What it measures) from CONFIG."""
    rows = []
    for key, weight in sorted(config_block.items(), key=lambda kv: -kv[1]):
        label, desc = info[key]
        rows.append([f"<strong>{esc(label)}</strong>",
                     f"{round(weight * 100)}%", esc(desc)])
    return table(["Factor", "Weight", "What it measures"], rows)


def render_methodology(scores):
    odds_cfg = CONFIG["odds"]
    body = [
        "<h1>How the models work</h1>",
        '<p class="lead">The favourite/underdog read comes from two independent '
        'toy models. Each rates every team on a 0–100 scale; a pair of scores is '
        'then turned into home / draw / away odds for a fixture.</p>',
        '<p class="muted">Everything here is illustrative — built from public '
        'data and a fixed set of weights, not from betting markets or match '
        'simulation. It is not betting advice.</p>',

        "<h2>Reading the numbers</h2>",
        "<ul>",
        "<li>A team's <strong>score is relative, not absolute</strong>: each "
        "input is rescaled to 0–1 by its position between the field's lowest and "
        "highest value (some inputs log-scaled first), so a score answers “how "
        "does this team compare to the field,” not “how good are they in the "
        "abstract.”</li>",
        "<li>The <strong>two models are never blended.</strong> The gap between "
        "them is the interesting part — a talented squad from a poorer nation "
        "scores high on football and low on socio-economics, and vice versa.</li>",
        "<li>Match <strong>odds are probabilities</strong> (home / draw / away) "
        "that sum to 100%, shown alongside fair decimal odds.</li>",
        "</ul>",

        "<h2>The football model</h2>",
        "<p>Weights are applied to normalised (0–1) metrics and sum to 100%.</p>",
        _weight_table(CONFIG["football"], FOOTBALL_WEIGHT_INFO),
        "<h3>Inside the pedigree term</h3>",
        "<p>World Cup pedigree is itself a weighted blend, then normalised across "
        "the field:</p>",
        _weight_table(CONFIG["pedigree"], PEDIGREE_INFO),
        '<p class="muted">Best finish is scored on an ordinal scale from '
        f'winners ({BEST_FINISH_RANK["winners"]}) down to never-qualified '
        f'({BEST_FINISH_RANK["never-qualified"]}). Predecessor states are folded '
        "into today's nations (e.g. West Germany → Germany).</p>",

        "<h2>The socio-economic model</h2>",
        "<p>A deliberately different lens — wealth, people and where the players "
        "ply their trade, rather than squad value. Weights sum to 100%.</p>",
        _weight_table(CONFIG["socio"], SOCIO_WEIGHT_INFO),
        '<p class="muted">On top of the weighted score, each '
        f'<strong>host nation</strong> (Canada, Mexico, USA) gets a flat '
        f'+{round(CONFIG["host_bonus"])}-point bump for home advantage across '
        "the tournament.</p>",

        "<h2>From scores to match odds</h2>",
        "<p>Two team scores become a result probability with an Elo-style "
        "expected-score curve, with a draw carved out around even matchups:</p>",
        "<ul>",
        f"<li>The score gap drives an expected result via an Elo curve "
        f"(<code>elo_scale = {odds_cfg['elo_scale']:g}</code>): roughly a "
        "20-point gap converts to about a 76% expected score for the stronger "
        "side.</li>",
        f"<li>A draw is most likely when teams are level — peaking at "
        f"<strong>{round(odds_cfg['draw_max'] * 100)}%</strong> — and fades as "
        f"the gap grows (<code>draw_sigma = {odds_cfg['draw_sigma']:g}</code>).</li>",
        f"<li>When a host plays at home it gets a small venue edge of "
        f"<strong>+{round(odds_cfg['home_advantage'])} points</strong> before "
        "the curve is applied.</li>",
        "</ul>",

        "<h2>Where the inputs come from</h2>",
        "<ul>",
        "<li><strong>Squad market value &amp; age</strong> — Transfermarkt "
        "valuations (June 2026), covering ~96% of players at high confidence; "
        "the rest are best-effort estimates (accurate in scale, not "
        "authoritative).</li>",
        "<li><strong>GNP, GNP per capita &amp; population</strong> — World Bank "
        "figures (mostly 2024), with ONS estimates for England and Scotland.</li>",
        "<li><strong>FIFA ranking</strong> and <strong>World Cup history</strong> "
        "— official records through 2022.</li>",
        "</ul>",
        '<p class="muted">All weights and constants live in a single '
        "<code>CONFIG</code> block in <code>scripts/odds.py</code>; this page is "
        "generated from that same source, so the numbers above always match the "
        "live model. See the "
        + link("favourites.html", "Favourites") +
        " page for the resulting rankings.</p>",
    ]
    return page("Methodology", "\n".join(body), depth=0, active="methodology")


def render_results(teams, matches, details, by_slug):
    completed = [m for m in matches if m.get("status") == "completed"]
    body = ["<h1>Results</h1>",
            f'<p class="muted">{len(completed)} matches played; {len(details)} with '
            f'full detail (goals, lineups, stats).</p>']

    standings = compute_standings(teams, matches)
    body.append("<h2>Group standings</h2>")
    body.append('<p class="muted">Computed from completed matches only.</p>')
    for letter in GROUP_LETTERS:
        rows = standings.get(letter, [])
        if not rows or all(r["played"] == 0 for r in rows):
            continue
        body.append(f"<h3>Group {esc(letter)}</h3>")
        body.append(standings_table(rows))

    body.append("<h2>Match results</h2>")
    dates = []
    for m in matches:
        if m["date"] not in dates:
            dates.append(m["date"])
    for date in dates:
        body.append(f"<h3>{esc(date)}</h3>")
        rows = []
        for m in [mm for mm in matches if mm["date"] == date]:
            has_detail = m.get("id") in details
            grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
            note = m.get("note") or ""
            rows.append([
                match_score_label(m, by_slug, depth=0, link_detail=has_detail),
                esc(grp),
                esc(m.get("venue") or ""),
                esc(note),
            ])
        body.append(table(["Match", "Stage", "Venue", "Note"], rows, cls="results"))

    return page("Results", "\n".join(body), depth=0, active="results")


def render_goals_block(detail, by_slug):
    goals = sorted(detail.get("goals", []), key=lambda g: minute_key(g.get("minute")))
    if not goals:
        return ""
    items = []
    for g in goals:
        tag = ""
        if g.get("type") == "penalty":
            tag = " (pen)"
        elif g.get("type") == "own_goal":
            tag = " (OG)"
        minute = f"{esc(g['minute'])}'" if g.get("minute") else "?"
        assist = f' <span class="muted">assist {esc(g["assist"])}</span>' if g.get("assist") else ""
        items.append(f"<li>{minute} {esc(g.get('player'))}{esc(tag)} "
                     f"<span class=\"muted\">({esc(team_name(by_slug, g.get('team')))})</span>{assist}</li>")
    return "<h2>Goals</h2><ul class=\"events\">" + "".join(items) + "</ul>"


def render_lineup_block(detail, side_key, slug, by_slug):
    lu = (detail.get("lineups") or {}).get(side_key)
    if not lu:
        return ""
    bits = []
    if lu.get("formation"):
        bits.append(esc(lu["formation"]))
    if lu.get("manager"):
        bits.append(esc(lu["manager"]))
    sub = f' <span class="muted">({" — ".join(bits)})</span>' if bits else ""
    items = []
    for p in lu.get("starting", []):
        num = f"{esc(p['number'])}. " if p.get("number") else ""
        pos = f' <span class="muted">{esc(p.get("position"))}</span>' if p.get("position") else ""
        items.append(f"<li>{num}{esc(p.get('name', ''))}{pos}</li>")
    return (f"<h3>{esc(team_name(by_slug, slug))}{sub}</h3>"
            f'<ol class="lineup">' + "".join(items) + "</ol>")


def render_subs_block(detail, by_slug):
    subs = sorted(detail.get("substitutions", []), key=lambda s: minute_key(s.get("minute")))
    if not subs:
        return ""
    items = []
    for s in subs:
        minute = f"{esc(s['minute'])}'" if s.get("minute") else "?"
        items.append(f"<li>{minute} {esc(s.get('off') or '?')} &rarr; {esc(s.get('on') or '?')} "
                     f"<span class=\"muted\">({esc(team_name(by_slug, s.get('team')))})</span></li>")
    return "<h2>Substitutions</h2><ul class=\"events\">" + "".join(items) + "</ul>"


def render_cards_block(detail, by_slug):
    cards = sorted(detail.get("cards", []), key=lambda c: minute_key(c.get("minute")))
    if not cards:
        return ""
    items = []
    for c in cards:
        icon = CARD_ICON.get(c.get("card"), "")
        minute = f"{esc(c['minute'])}'" if c.get("minute") else "?"
        items.append(f"<li>{esc(icon)} {minute} {esc(c.get('player'))} "
                     f"<span class=\"muted\">({esc(team_name(by_slug, c.get('team')))})</span></li>")
    return "<h2>Cards</h2><ul class=\"events\">" + "".join(items) + "</ul>"


def render_stats_block(detail, home, away, by_slug):
    stats = detail.get("stats") or {}
    hs, as_ = stats.get("home") or {}, stats.get("away") or {}
    rows = []
    for key, label, unit in STAT_LABELS:
        hv, av = hs.get(key), as_.get(key)
        if hv is None and av is None:
            continue
        fmt = lambda v: "—" if v is None else f"{esc(v)}{esc(unit)}"
        rows.append([esc(label), fmt(hv), fmt(av)])
    if not rows:
        return ""
    head = ["Stat", team_name(by_slug, home), team_name(by_slug, away)]
    return "<h2>Team statistics</h2>" + table(head, rows, cls="match-stats")


def render_match_odds_block(m, scores, by_slug):
    """Full two-model odds table for a match-detail page."""
    mo = match_model_odds(m, scores)
    if not mo:
        return ""
    home, away = m["home"], m["away"]
    hn, an = team_name(by_slug, home), team_name(by_slug, away)
    host_home = bool(scores[home].get("host"))

    head = (f'<tr><th>Model</th><th>{esc(hn)}</th><th>Draw</th>'
            f'<th>{esc(an)}</th></tr>')
    rows = []
    for key, label in ODDS_MODELS:
        o = mo[key]
        fav = max(("home", "draw", "away"), key=lambda k: o[k])

        def cell(k):
            inner = f"{round(o[k] * 100)}% <span class=\"muted\">({as_decimal_odds(o[k])})</span>"
            return f'<td class="{"odds-fav" if k == fav else ""}">{inner}</td>'

        rows.append(f'<tr><th>{esc(label)}</th>{cell("home")}{cell("draw")}'
                    f'{cell("away")}</tr>')

    sc = scores
    note = ("Two independent toy models — a football model (rank, squad value, "
            "World Cup pedigree, age) and a socio-economic model (wealth, "
            "population, players abroad, hosts). Estimates only, not betting advice.")
    if host_home:
        note += f" {esc(hn)} carries a host-venue edge."
    scoreline = (
        f'<p class="muted">Strength scores — Football: {esc(hn)} '
        f'{sc[home]["football"]} vs {esc(an)} {sc[away]["football"]} &middot; '
        f'Socio-econ: {esc(hn)} {sc[home]["socio"]} vs {esc(an)} {sc[away]["socio"]}</p>'
    )
    return ("<h2>Model odds</h2>"
            f'<table class="odds-table"><thead>{head}</thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            f"{scoreline}"
            f'<p class="muted odds-note">{note}</p>')


def render_match(m, detail, by_slug, scores=None):
    home, away = m["home"], m["away"]
    grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
    title = (f"{team_name(by_slug, home)} {m['home_score']}–{m['away_score']} "
             f"{team_name(by_slug, away)}")
    body = [f"<h1>{esc(team_name(by_slug, home))} "
            f'<span class="score">{esc(m["home_score"])}–{esc(m["away_score"])}</span> '
            f"{esc(team_name(by_slug, away))}</h1>"]
    meta = [esc(grp), esc(m.get("date", ""))]
    if m.get("venue"):
        meta.append(esc(m["venue"]))
    if detail.get("attendance"):
        meta.append(f"Att: {esc(format(detail['attendance'], ','))}")
    if detail.get("referee"):
        meta.append(f"Referee: {esc(detail['referee'])}")
    body.append(f'<p class="lead">{" &middot; ".join(meta)}</p>')
    body.append(f'<p><a href="{rel(1)}group-{m["group"].lower()}.html">&larr; Group '
                f'{esc(m["group"])}</a></p>' if m.get("group") else "")

    body.append(render_goals_block(detail, by_slug))

    lineups = (detail.get("lineups") or {})
    if lineups.get("home") or lineups.get("away"):
        body.append("<h2>Lineups</h2>")
        body.append('<div class="lineups">')
        body.append(render_lineup_block(detail, "home", home, by_slug))
        body.append(render_lineup_block(detail, "away", away, by_slug))
        body.append("</div>")

    body.append(render_subs_block(detail, by_slug))
    body.append(render_cards_block(detail, by_slug))
    body.append(render_stats_block(detail, home, away, by_slug))
    body.append(render_match_odds_block(m, scores, by_slug))

    sources = detail.get("sources") or []
    if sources:
        items = "".join(
            f'<li><a href="{esc(u)}" rel="nofollow noopener">{esc(u)}</a></li>'
            for u in sources)
        body.append('<h2>Sources</h2><ul class="sources">' + items + "</ul>")

    return page(title, "\n".join(b for b in body if b), depth=1)


# --- driver ------------------------------------------------------------------

FOOTER_NOTE = ""
CALENDAR_HOME = ""  # set in main(): href of the Calendar nav landing day page


def main():
    global FOOTER_NOTE, CALENDAR_HOME
    tournament = load_tournament()
    FOOTER_NOTE = tournament.get("data_disclaimer", "")
    teams = load_all_teams()
    by_slug = {t["slug"]: t for t in teams}
    matches = load_results()
    details = load_match_details()
    scores = build_team_scores(teams, tournament)

    # "Today" is the current date in the tournament's timezone, so the home
    # page's featured matches flip at local midnight rather than at UTC midnight
    # (the build host's clock). SITE_DATE pins it for deterministic builds;
    # SITE_TZ overrides the zone (defaults to the hosts' Eastern time).
    site_tz = os.environ.get("SITE_TZ", "America/New_York")
    today = (os.environ.get("SITE_DATE")
             or datetime.datetime.now(ZoneInfo(site_tz)).date().isoformat())

    # Matchdays for the calendar, and the day the Calendar nav lands on.
    by_date = {}
    for m in matches:
        by_date.setdefault(m["date"], []).append(m)
    dates = sorted(by_date)
    counts = {d: len(by_date[d]) for d in dates}
    _, cal_date, _ = select_featured_matches(matches, today)
    if not cal_date and dates:
        cal_date = dates[-1]
    CALENDAR_HOME = f"day-{cal_date}.html" if cal_date else ""

    # Fresh build: clear previous output (keeps a clean, deterministic tree).
    if os.path.isdir(SITE_DIR):
        shutil.rmtree(SITE_DIR)
    os.makedirs(SITE_DIR, exist_ok=True)

    standings = compute_standings(teams, matches)

    write("index.html",
          render_index(tournament, by_slug, matches, details, today, scores))

    n_groups = 0
    for letter in GROUP_LETTERS:
        slugs = tournament["groups"].get(letter, [])
        write(f"group-{letter.lower()}.html",
              render_group(letter, slugs, by_slug, standings))
        n_groups += 1

    for t in teams:
        write(f"team/{t['slug']}.html", render_team(t, by_slug, matches, details))

    write("favourites.html", render_favourites(teams, scores, by_slug))
    write("methodology.html", render_methodology(scores))
    write("stats.html", render_stats(teams))
    write("results.html", render_results(teams, matches, details, by_slug))

    n_matches = 0
    for m in matches:
        detail = details.get(m.get("id"))
        if m.get("status") == "completed" and detail:
            write(f"match/{m['id']}.html", render_match(m, detail, by_slug, scores))
            n_matches += 1

    for d in dates:
        write(f"day-{d}.html",
              render_day(d, dates, by_date[d], by_slug, details, scores, counts))

    # Copy the stylesheet.
    os.makedirs(os.path.join(SITE_DIR, "assets"), exist_ok=True)
    shutil.copyfile(os.path.join(ASSETS_SRC, "style.css"),
                    os.path.join(SITE_DIR, "assets", "style.css"))

    print(f"Wrote site/: index + {n_groups} group pages, {len(teams)} team pages, "
          f"stats, results, {n_matches} match pages, {len(dates)} day pages.")


if __name__ == "__main__":
    main()
