#!/usr/bin/env python3
"""Generate a minimalist static website under site/ from the JSON data.

Produces a small documentation-style HTML site (no JavaScript, no dependencies
beyond the Python standard library):

  site/index.html              tournament overview + group index
  site/group-<a..l>.html       per-group standings + squad tables
  site/team/<slug>.html        per-team page: metadata, squad, fixtures
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
import html
import os
import shutil

from common import (
    CARD_ICON,
    GROUP_LETTERS,
    ROOT,
    STAT_LABELS,
    compute_standings,
    fmt_eur,
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
from odds import as_decimal_odds, build_team_scores, match_odds

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
    nav_items += [("stats.html", "Stats", "stats"),
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
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body>
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


def team_block(slug, by_slug):
    """A team panel for a match card: name, group, squad value and citizens."""
    t = by_slug.get(slug)
    if not t:
        return f'<div class="team"><span class="tname">{esc(slug)}</span></div>'
    name_link = link(f"team/{t['slug']}.html", t["name"])
    return (
        '<div class="team">'
        f'<span class="tname">{name_link}</span>'
        '<dl class="card-stats">'
        f'<div><dt>Squad value</dt><dd>{esc(fmt_eur(squad_value(t)))}</dd></div>'
        f'<div><dt>Citizens</dt><dd>{esc(fmt_pop(t.get("population")))}</dd></div>'
        f'<div><dt>GNP/capita</dt><dd>{esc(fmt_usd(t.get("gnp_per_capita_usd")))}</dd></div>'
        '</dl></div>'
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
        f'{team_block(m["home"], by_slug)}'
        f'<div class="centre">{centre}</div>'
        f'{team_block(m["away"], by_slug)}'
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
    body.append(f'<p>See {link("stats.html", "Stats")} for market-value and economy '
                f'rankings, and {link("results.html", "Results")} for fixtures and '
                f'live standings.</p>')
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

    # "Today" is the build date; SITE_DATE overrides it for deterministic builds.
    today = os.environ.get("SITE_DATE") or datetime.date.today().isoformat()

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
