import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import compute_standings, match_winner, resolve_bracket_slots
from odds import _depth_ratio


def team(slug, group="A", rank=50):
    return {"slug": slug, "name": slug.upper(), "group": group,
            "fifa_ranking": rank, "squad": []}


def match(home, away, hs, as_, *, stage="group", group="A", mid=None):
    return {
        "id": mid or f"{home}-{away}", "stage": stage, "group": group,
        "home": home, "away": away, "home_score": hs, "away_score": as_,
        "status": "completed",
    }


class StandingsTests(unittest.TestCase):
    def test_knockout_results_never_change_group_standings(self):
        teams = [team(s) for s in "abcd"]
        group = [match("a", "b", 1, 0)]
        before = compute_standings(teams, group)
        final = match("a", "b", 0, 9, stage="final", group=None, mid="final")
        after = compute_standings(teams, group + [final])
        self.assertEqual(before, after)

    def test_head_to_head_precedes_overall_goal_difference(self):
        teams = [team(s, rank=i) for i, s in enumerate("abcd", 1)]
        matches = [
            match("a", "b", 1, 0),
            match("a", "c", 1, 0),
            match("d", "a", 5, 0),
            match("b", "c", 5, 0),
            match("b", "d", 5, 0),
        ]
        rows = compute_standings(teams, matches)["A"]
        self.assertEqual([r["slug"] for r in rows[:2]], ["a", "b"])
        self.assertLess(rows[0]["gd"], rows[1]["gd"])

    def test_penalty_shootout_determines_winner(self):
        m = match("a", "b", 1, 1, stage="round-of-32", group=None)
        m.update(decision="penalties", home_penalties=5, away_penalties=4)
        self.assertEqual(match_winner(m), "a")

    def test_completed_group_and_match_slots_flow_forward(self):
        teams = [team(s, rank=i) for i, s in enumerate("abcd", 1)]
        group_matches = [
            match("a", "b", 1, 0), match("a", "c", 1, 0),
            match("a", "d", 1, 0), match("b", "c", 1, 0),
            match("b", "d", 1, 0), match("c", "d", 1, 0),
        ]
        r32 = match("winner-group-a", "runner-up-group-a", 2, 1,
                    stage="round-of-32", group=None, mid="2026-06-28-r32-73")
        r32["match_number"] = 73
        r16 = {
            "id": "2026-07-04-r16-90", "match_number": 90,
            "stage": "round-of-16", "group": None,
            "home": "winner-match-73", "away": "winner-match-75",
            "home_score": None, "away_score": None, "status": "scheduled",
        }
        standings = compute_standings(teams, group_matches)
        resolved = {m["id"]: m for m in
                    resolve_bracket_slots(group_matches + [r32, r16], standings)}
        self.assertEqual(resolved[r32["id"]]["home"], "a")
        self.assertEqual(resolved[r32["id"]]["away"], "b")
        self.assertEqual(resolved[r16["id"]]["home"], "a")


class OddsTests(unittest.TestCase):
    def test_depth_rewards_bench_value_not_star_concentration(self):
        even = {"squad": [{"market_value_eur": 10} for _ in range(26)]}
        top_heavy = {"squad": ([{"market_value_eur": 16} for _ in range(16)]
                                + [{"market_value_eur": 0} for _ in range(10)])}
        self.assertGreater(_depth_ratio(even), _depth_ratio(top_heavy))


if __name__ == "__main__":
    unittest.main()
