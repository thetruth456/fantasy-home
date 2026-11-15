#!/usr/bin/env python3
"""Offline tests for the power, luck, and weekly-report additions.

No network, no passwords, and no writes to the repo data files.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import leagues  # noqa: E402
import podcast  # noqa: E402
import power  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _rec(w=0, l=0, t=0, pf=0.0):
    return dict(w=w, l=l, t=t, pf=pf)


class Stake(unittest.TestCase):
    def test_assigning_the_win_does_not_require_outscoring(self):
        # Team 1 scored 1 and team 2 scored 100. Forcing team 1's win still
        # puts the win on team 1; points for stay with whoever scored them.
        rids = [1, 2, 3, 4]
        rec = {r: _rec() for r in rids}
        pairs = {1: [(1, 2), (3, 4)]}
        draws = [{1: {1: 1.0, 2: 100.0, 3: 50.0, 4: 10.0}}]
        out = power.stake_odds(draws, rec, rids, pairs, 2, 1)
        self.assertEqual(out[1]["opp"], 2)
        self.assertEqual(out[1]["win"], 100.0)
        self.assertEqual(out[1]["loss"], 0.0)
        self.assertEqual(out[2]["win"], 100.0)
        self.assertEqual(out[2]["loss"], 0.0)

    def test_a_clinched_team_has_no_swing(self):
        rec = {1: _rec(6, 0, pf=100), 2: _rec(0, 6, pf=10)}
        draws = [{1: {1: 10.0, 2: 30.0}}]
        out = power.stake_odds(draws, rec, [1, 2], {1: [(1, 2)]}, 1, 1)
        self.assertEqual(out[1]["win"], 100.0)
        self.assertEqual(out[1]["loss"], 100.0)
        self.assertEqual(out[2]["win"], 0.0)
        self.assertEqual(out[2]["loss"], 0.0)

    def test_a_tie_can_be_assigned_either_way(self):
        rec = {1: _rec(), 2: _rec()}
        draws = [{1: {1: 5.0, 2: 5.0}}]
        out = power.stake_odds(draws, rec, [1, 2], {1: [(1, 2)]}, 1, 1)
        self.assertEqual(out[1]["win"], 100.0)
        self.assertEqual(out[1]["loss"], 0.0)
        self.assertEqual(out[2]["win"], 100.0)
        self.assertEqual(out[2]["loss"], 0.0)

    def test_missing_week_is_skipped(self):
        rec = {1: _rec(), 2: _rec()}
        draws = [{1: {1: 5.0, 2: 4.0}}]
        self.assertIsNone(power.stake_odds(draws, rec, [1, 2], {1: [(1, 2)]}, 1, 9))
        self.assertIsNone(power.stake_odds([], rec, [1, 2], {1: [(1, 2)]}, 1, 1))

    def test_best_league_stays_frozen(self):
        self.assertEqual(leagues.FROZEN["best"]["tau0"], 4.6)
        power.set_cal("best")
        self.assertEqual(power.TAU0, 4.6)
        power.set_cal("zbt")
        with open(Path(__file__).resolve().parent / "power_cal.json") as f:
            self.assertEqual(power.TAU0, json.load(f)["use"]["zbt"]["tau0"])
        power.set_cal("best")


class LuckMath(unittest.TestCase):
    def setUp(self):
        self.scores = {1: {1: 10.0, 2: 5.0, 3: 8.0, 4: 7.0}, 2: {1: 3.0, 2: 6.0, 3: 9.0, 4: 4.0}}
        self.pairs = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)]}

    def test_schedule_swap_diagonal_is_the_real_record_and_skips_playing_yourself(self):
        sw = podcast.schedule_swap(self.scores, self.pairs)
        self.assertEqual(sw[1][1], [1, 1, 0])
        # Team 2 played team 1 in week 1, so that week is left out. Week 2, team 1's 3 loses to team 4's 4.
        self.assertEqual(sw[1][2], [0, 1, 0])
        self.assertEqual(sw[2][2], [1, 1, 0])

    def test_allplay_counts_every_opponent_and_only_the_weeks_it_is_given(self):
        one = podcast.allplay({1: self.scores[1]})
        self.assertEqual(one[1], [3, 0, 0])
        self.assertEqual(one[2], [0, 3, 0])
        self.assertEqual(one[3], [2, 1, 0])
        self.assertEqual(one[4], [1, 2, 0])
        both = podcast.allplay(self.scores)
        self.assertEqual(both[1][0] + both[1][1] + both[1][2], 6)

    def test_final_weeks_drop_a_week_that_is_not_over(self):
        sched = [
            dict(week=1, status="complete"),
            dict(week=2, status="complete"),
            dict(week=2, status="pre_game"),
        ]
        self.assertEqual(podcast.final_weeks(sched, [1, 2, 3]), [1])

    def test_bench_gap_respects_flex_and_refuses_a_second_quarterback(self):
        slots = ["QB", "RB", "WR", "FLEX"]
        m = dict(roster_id=1, starters=["qb", "rb", "wr8", "0"], points=23,
                 players=["qb", "rb", "wr8", "wr12"],
                 players_points={"qb": 10, "rb": 5, "wr8": 8, "wr12": 12})
        got = podcast.bench_gap(slots, power.lineup, [m], lambda pid: {"qb": "QB", "rb": "RB", "wr8": "WR", "wr12": "WR"}[pid])
        self.assertAlmostEqual(got[1]["left"], 12)
        self.assertAlmostEqual(got[1]["opt"], 35)
        self.assertAlmostEqual(got[1]["actual"], 23)
        self.assertAlmostEqual(got[1]["gap"], 12)
        m2 = dict(roster_id=2, starters=["qb", "rb", "0"], points=15,
                  players=["qb", "rb", "qb2"], players_points={"qb": 10, "rb": 5, "qb2": 30})
        got2 = podcast.bench_gap(["QB", "RB", "FLEX"], power.lineup, [m2], lambda pid: "QB" if pid.startswith("qb") else "RB")
        self.assertAlmostEqual(got2[2]["opt"], 35)  # QB 30, RB 5; the other QB cannot fill FLEX
        self.assertAlmostEqual(got2[2]["gap"], 20)
        self.assertAlmostEqual(got2[2]["left"], 30)


class Weekly(unittest.TestCase):
    def test_playoff_index_uses_points_allowed_and_skips_a_bye(self):
        sched = [
            dict(week=1, home="AAA", away="BBB", status="complete"),
            dict(week=1, home="DDD", away="EEE", status="complete"),
            dict(week=15, home="CCC", away="BBB"),
            dict(week=16, home="CCC", away="AAA"),
        ]
        rows = {1: [
            dict(player_id="a", team="AAA", stats={"pts": 30}),
            dict(player_id="b", team="BBB", stats={"pts": 10}),
        ]}
        allowed, league = build.points_allowed(sched, rows, lambda pid: "WR", lambda st, pos: st["pts"], [1])
        self.assertAlmostEqual(allowed["BBB"]["WR"], 30)
        self.assertAlmostEqual(allowed["AAA"]["WR"], 10)
        self.assertAlmostEqual(allowed["DDD"]["WR"], 0)
        self.assertAlmostEqual(league["WR"], 10)
        self.assertEqual(build.playoff_index("CCC", "WR", sched, allowed, league), 2.0)
        self.assertIsNone(build.playoff_index("", "WR", sched, allowed, league))
        self.assertIsNone(build.playoff_index("CCC", "QB", sched, allowed, league))

    def test_trade_targets_name_the_surplus_not_the_starters(self):
        def roster(rid, owner, pids):
            return dict(roster_id=rid, owner_id=owner, players=pids, reserve=[])
        rosters = [
            roster(1, "kyle", ["rb40"]),
            roster(2, "deep", ["rb5", "rb10", "rb20", "rb22"]),
            roster(3, "even", ["rb8", "rb12"]),
            roster(4, "hurt", ["rb3", "rb6", "rb9"]),
        ]
        users = [
            dict(user_id="kyle", display_name="kfelder30", metadata=dict(team_name="North")),
            dict(user_id="deep", display_name="deep", metadata=dict(team_name="Deep")),
            dict(user_id="even", display_name="even", metadata=dict(team_name="Even")),
            dict(user_id="hurt", display_name="hurt", metadata=dict(team_name="Hurt")),
        ]
        values = {
            "rb40": dict(name="Thin Back", pos="RB", team="GB", rank=40, status=""),
            "rb5": dict(name="Stud Back", pos="RB", team="DET", rank=5, status=""),
            "rb10": dict(name="Second Back", pos="RB", team="DET", rank=10, status=""),
            "rb20": dict(name="Spare Back", pos="RB", team="PHI", rank=20, status=""),
            "rb22": dict(name="Extra Back", pos="RB", team="PHI", rank=22, status=""),
            "rb8": dict(name="Even One", pos="RB", team="KC", rank=8, status=""),
            "rb12": dict(name="Even Two", pos="RB", team="KC", rank=12, status=""),
            "rb3": dict(name="Hurt Stud", pos="RB", team="SF", rank=3, status="IR"),
            "rb6": dict(name="Hurt Two", pos="RB", team="SF", rank=6, status=""),
            "rb9": dict(name="Hurt Three", pos="RB", team="SF", rank=9, status=""),
        }
        slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
        got = build.trade_targets(rosters, users, "kyle", values, slots, 12, "ros")
        self.assertEqual(got["team"], "North")
        rb = next(p for p in got["positions"] if p["pos"] == "RB")
        self.assertEqual(rb["have"], 0)
        self.assertEqual(rb["need"], 2)
        names = {c["name"] for t in rb["teams"] for c in t["candidates"]}
        self.assertIn("Spare Back", names)
        self.assertIn("Extra Back", names)
        self.assertNotIn("Stud Back", names)
        self.assertNotIn("Second Back", names)
        self.assertNotIn("Even One", names)
        self.assertNotIn("Hurt Stud", names)
        self.assertTrue(all(t["name"] != "North" for t in rb["teams"]))

    def test_no_ranks_names_nobody(self):
        rosters = [dict(roster_id=1, owner_id="kyle", players=["a"], reserve=[])]
        users = [dict(user_id="kyle", display_name="kfelder30", metadata=dict(team_name="North"))]
        values = {"a": dict(name="A", pos="RB", team="GB", rank=None, status="")}
        got = build.trade_targets(rosters, users, "kyle", values, ["RB", "RB"], 12, "none")
        self.assertEqual(got["positions"], [])
        self.assertIn("No rest-of-season", got["note"])

    def test_projection_fallback_ranks_by_points(self):
        rosters = [dict(roster_id=1, owner_id="kyle", players=["a", "b"], reserve=[])]
        values, src = build.roster_values(
            rosters, {}, None,
            {"a": dict(stats={"pts": 10}, player=dict(position="RB", first_name="Low", last_name="Back")),
             "b": dict(stats={"pts": 40}, player=dict(position="RB", first_name="High", last_name="Back"))},
            lambda st, pos: st["pts"])
        self.assertEqual(src, "proj")
        self.assertEqual(values["b"]["rank"], 1)
        self.assertEqual(values["a"]["rank"], 2)
        self.assertIsNone(build.positional_rank("RB", "WR3"))
        self.assertEqual(build.positional_rank("WR", "WR3"), 3)

    def test_faab_remaining_and_priority_when_the_league_does_not_use_it(self):
        users = [dict(user_id="kyle", display_name="kfelder30", metadata=dict(team_name="North")),
                 dict(user_id="other", display_name="other", metadata=dict(team_name="Other"))]
        rosters = [
            dict(roster_id=1, owner_id="kyle", settings=dict(waiver_budget_used=71, waiver_position=9)),
            dict(roster_id=2, owner_id="other", settings=dict(waiver_budget_used=-3, waiver_position=1)),
        ]
        faab = build.waiver_snapshot(dict(settings=dict(waiver_type=2, waiver_budget=100)), rosters, users, "kyle")
        self.assertEqual(faab["mode"], "faab")
        by = {r["name"]: r for r in faab["rows"]}
        self.assertEqual(by["North"]["remaining"], 29)
        self.assertTrue(by["North"]["you"])
        self.assertEqual(by["Other"]["remaining"], 103)
        self.assertEqual(faab["rows"][0]["name"], "Other")
        pri = build.waiver_snapshot(dict(settings=dict(waiver_type=0, waiver_budget=100)), rosters, users, "kyle")
        self.assertEqual(pri["mode"], "priority")
        self.assertNotIn("budget", pri)
        self.assertEqual([r["priority"] for r in pri["rows"]], [1, 9])


class Pages(unittest.TestCase):
    def test_new_sections_are_on_every_league_and_power_luck_do_not_name_kyle(self):
        pages = {"index.html": ["best", "zbt", "oops", "spacex"], "best-league.html": ["best"],
                 "zbt.html": ["zbt"], "oopsilons.html": ["oops"], "spacex-ff.html": ["spacex"]}
        for fn, keys in pages.items():
            text = (ROOT / fn).read_text()
            for k in keys:
                self.assertIn('id="%s-t-trade"' % k, text)
                self.assertIn('id="%s-t-faab"' % k, text)
                self.assertLess(text.find('id="%s-data-notes"' % k), text.find('id="%s-t-trade"' % k))
        for fn in ("power.js", "podcast.js"):
            src = (ROOT / fn).read_text()
            self.assertNotIn("kfelder", src)
            self.assertNotIn("(you)", src)
        self.assertNotIn("odds", (ROOT / "report-core.js").read_text())

    def test_view_script(self):
        import subprocess
        r = subprocess.run(["node", str(ROOT / "tools" / "test_views.js")], cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            self.fail(r.stdout + "\n" + r.stderr)


if __name__ == "__main__":
    unittest.main()
