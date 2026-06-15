#!/usr/bin/env python3
"""Prototype: refresh market_value_eur / age for one team from the Transfermarkt
community API (transfermarkt-api.fly.dev).

Dry-run by default: prints a comparison table and writes nothing.
Pass --apply to overwrite ONLY market_value_eur / age in the team JSON.

Usage:
    python3 scripts/harvest_market_values.py norway
    python3 scripts/harvest_market_values.py norway --apply

Stdlib only (urllib), to match the rest of scripts/.
"""
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://transfermarkt-api.fly.dev"
TEAMS_DIR = Path(__file__).resolve().parent.parent / "data" / "teams"
TIMEOUT = 20
PAUSE = 0.4  # be polite to a free community API


def _norm(s: str) -> str:
    """Lowercase, strip accents and punctuation for fuzzy comparison."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum() or c.isspace()).strip()


# Connector / legal-form tokens that are noise when comparing club names
# ("Atletico de Madrid" vs "Atletico Madrid", "Rangers FC" vs "Rangers").
_CLUB_STOP = {"fc", "fk", "cf", "sc", "ac", "as", "if", "bk", "de", "the",
              "club", "calcio", "futbol", "football", "united", "city"}


def _club_tokens(name: str) -> set:
    return {t for t in _norm(name).split() if t and t not in _CLUB_STOP}


def _club_match(a: str, b: str) -> int:
    """2 = strong token overlap, 1 = partial, 0 = none."""
    ta, tb = _club_tokens(a), _club_tokens(b)
    if not ta or not tb:
        return 0
    shared = ta & tb
    if not shared:
        return 0
    # strong if all of the smaller token set is covered
    return 2 if shared == ta or shared == tb else 1


def _get(url: str, retries: int = 2):
    """GET with retry on transient errors (5xx / timeout)."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "wc26-harvest/0.1"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:  # 4xx won't get better on retry
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last


def _raw_search(name: str):
    url = f"{API}/players/search/{urllib.parse.quote(name)}?page_number=1"
    return _get(url).get("results", [])


def search(name: str):
    """Search; if a name yields nothing, retry with word order reversed
    (Transfermarkt indexes e.g. Korean names given-name-first)."""
    results = _raw_search(name)
    if not results:
        parts = name.split()
        if len(parts) >= 2:
            time.sleep(PAUSE)
            results = _raw_search(" ".join(reversed(parts)))
    return results


# TM nationality spellings that differ from this dataset's team["name"].
# Keyed by normalized team name -> extra acceptable normalized nationality strings.
# Keyed by _norm(team["name"]) -> extra acceptable normalized nationality strings.
NAT_ALIASES = {
    "czechia": {"czech republic"},
    "cabo verde": {"cape verde"},
    "south korea": {"korea south", "korea republic", "republic of korea"},
    "ir iran": {"iran"},
    "cote divoire": {"ivory coast"},
    "bosnia and herzegovina": {"bosniaherzegovina", "bosnia herzegovina"},
}

HIGH_CONF = 5  # nat (3) + at least partial club (2)


def want_nationalities(team: dict) -> set:
    base = _norm(team["name"])
    return {base} | NAT_ALIASES.get(base, set())


def pick(player: dict, results: list, want_nats: set):
    """Score candidates by nationality match + club token overlap."""
    want_club = player["club"]
    best, best_score, why = None, -1, ""
    for r in results:
        score, reasons = 0, []
        nats = [_norm(n) for n in (r.get("nationalities") or [])]
        if any(n in want_nats for n in nats):
            score += 3
            reasons.append("nat")
        elif not nats:
            reasons.append("nat?")  # candidate has no nationality listed
        cm = _club_match(want_club, (r.get("club") or {}).get("name", ""))
        if cm == 2:
            score += 3
            reasons.append("club=match")
        elif cm == 1:
            score += 2
            reasons.append("club~partial")
        if score > best_score:
            best, best_score, why = r, score, ",".join(reasons) or "name-only"
    return best, best_score, why


def fmt_eur(v):
    if v is None:
        return "—"
    return f"€{v/1_000_000:.1f}m" if v >= 1_000_000 else f"€{v:,}"


def harvest_team(team: dict, *, verbose: bool):
    """Returns (matched_count, flagged rows). Mutates squad in place only if
    caller chooses to write; here we just attach proposed values to each row."""
    squad = team["squad"]
    want_nats = want_nationalities(team)
    matched = 0
    flagged = []  # (name, reason, old_val, new_val, old_age, new_age)

    if verbose:
        print(f"{'PLAYER':<26}{'OLD VAL':>9}{'NEW VAL':>9}  {'AGE':>7}  MATCH")
        print("-" * 78)

    for p in squad:
        old_val, old_age = p.get("market_value_eur"), p.get("age")
        try:
            results = search(p["name"])
        except Exception as e:
            flagged.append((p["name"], f"ERROR: {e}", old_val, None, old_age, None))
            p["_proposed"] = None
            continue
        time.sleep(PAUSE)
        if not results:
            flagged.append((p["name"], "NO RESULTS", old_val, None, old_age, None))
            p["_proposed"] = None
            continue
        cand, score, why = pick(p, results, want_nats)
        new_val, new_age = cand.get("marketValue"), cand.get("age")
        p["_proposed"] = (new_val, new_age, score)

        if score >= HIGH_CONF:
            matched += 1
        else:
            flagged.append((p["name"], f"[{score}] {why}", old_val, new_val,
                            old_age, new_age))

        if verbose:
            age_str = f"{old_age}->{new_age}" if new_age != old_age else f"{old_age}"
            flag = "" if score >= HIGH_CONF else "  ⚠ low-conf"
            print(f"{p['name']:<26}{fmt_eur(old_val):>9}{fmt_eur(new_val):>9}  "
                  f"{age_str:>7}  [{score}] {why}{flag}")

    return matched, flagged


def write_team(path, team):
    for p in team["squad"]:
        proposed = p.pop("_proposed", None)
        if not proposed:
            continue
        new_val, new_age, score = proposed
        if score < HIGH_CONF:
            continue  # never auto-write low-confidence rows
        if new_val is not None:
            p["market_value_eur"] = int(new_val)
        if new_age is not None:
            p["age"] = int(new_age)
    # drop any leftover scratch keys before serializing
    for p in team["squad"]:
        p.pop("_proposed", None)
    path.write_text(json.dumps(team, ensure_ascii=False, indent=2) + "\n")


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    do_all = "--all" in args
    slugs = [a for a in args if not a.startswith("--")]

    if do_all:
        slugs = sorted(p.stem for p in TEAMS_DIR.glob("*.json"))
    if not slugs:
        sys.exit("usage: harvest_market_values.py <slug...> | --all  [--apply]")

    grand_matched = grand_total = 0
    all_flagged = []
    for slug in slugs:
        path = TEAMS_DIR / f"{slug}.json"
        team = json.loads(path.read_text())
        verbose = not do_all  # full table for single team, summary for --all
        matched, flagged = harvest_team(team, verbose=verbose)
        n = len(team["squad"])
        grand_matched += matched
        grand_total += n
        for f in flagged:
            all_flagged.append((slug, *f))

        if do_all:
            mark = "OK " if not flagged else "⚠  "
            print(f"{mark}{slug:<20} matched {matched}/{n}"
                  + (f"   flagged {len(flagged)}" if flagged else ""))
        else:
            print("-" * 78)
            print(f"matched high-conf: {matched}/{n}   flagged: {len(flagged)}")

        if apply:
            write_team(path, team)

    if all_flagged:
        print("\n===== FLAGGED ROWS (review before writing) =====")
        print(f"{'TEAM':<16}{'PLAYER':<24}{'OLD':>9}{'NEW':>9}  REASON")
        for slug, name, reason, ov, nv, oa, na in all_flagged:
            print(f"{slug:<16}{name:<24}{fmt_eur(ov):>9}{fmt_eur(nv):>9}  {reason}")

    print(f"\nTOTAL high-conf: {grand_matched}/{grand_total}   "
          f"flagged: {len(all_flagged)}")
    if apply:
        print("WROTE high-confidence rows only; flagged rows left untouched.")
    else:
        print("(dry run — nothing written)")


if __name__ == "__main__":
    main()
