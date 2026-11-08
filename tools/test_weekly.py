#!/usr/bin/env python3
"""Offline tests for kickers, weather, rendering, and the privacy boundary.

Uses a synthetic password and fake names only. Does not read FH_REPORT_PASSWORD,
does not decrypt production reports, and does not write the repo's lock or data files.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import seal  # noqa: E402
import sources  # noqa: E402
import update  # noqa: E402
import weather  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 8, 18, 0, tzinfo=dt.timezone.utc)


def _tracked():
    out = []
    for pat in ("*-report.js", "*-power-data.js", "*-podcast-data.js"):
        out += sorted(ROOT.glob(pat))
    for rel in ("tools/lock.json", "tools/power_cal.json", "tools/overrides.json", "tools/leagues.py"):
        out.append(ROOT / rel)
    return out


BEFORE = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in _tracked()}


def tearDownModule():
    bad = [str(p.relative_to(ROOT)) for p, h in BEFORE.items() if hashlib.sha256(p.read_bytes()).hexdigest() != h]
    if bad:
        raise SystemExit("privacy: test run changed %s" % ", ".join(bad))


SAMPLE = dict(fgm_20_29=0.31, fgm_30_39=0.46, fgm_40_49=0.41, fgm_50p=0.41, fgm=1.59,
              fgmiss_30_39=0.04, fgmiss_40_49=0.04, fgmiss_50p=0.12, xpm=2.71, xpmiss=0.13)
BEST = dict(fgm_0_19=1.5, fgm_20_29=1.5, fgm_30_39=1.5, fgm_40_49=2.0, fgm_50p=2.5, xpm=0.5)
ZBT = dict(fgm_0_19=3, fgm_20_29=3, fgm_30_39=3, fgm_40_49=4, fgm_50_59=5, fgm_60p=6, fgmiss=-1, xpm=1)
OOPS = dict(ZBT, xpmiss=-1)


def _hours(rows):
    times = sorted(rows)
    def col(k):
        return [rows[t].get(k) for t in times]
    return {"hourly": {"time": times, "temperature_2m": col("temp"), "wind_speed_10m": col("wind"),
                       "weather_code": col("code"), "precipitation_probability": col("pop"), "precipitation": col("precip")}}


def _payload(rows, as_list=False):
    item = _hours(rows)
    return json.dumps([item] if as_list else item)


class Scoring(unittest.TestCase):
    def test_best_matches_bucket_overlap_and_ignores_bare_total(self):
        # 0.31*1.5 + 0.46*1.5 + 0.41*2 + 0.41*2.5 + 2.71*0.5; misses and fgm total are not in Best's settings
        self.assertAlmostEqual(build.score_kicker(BEST, SAMPLE), 4.355)

    def test_zbt_scores_50_plus_at_the_50_59_rate_and_counts_misses(self):
        # 60+ rate is 6; it must not be applied to the combined 50+ bucket
        got = build.score_kicker(ZBT, SAMPLE)
        self.assertAlmostEqual(got, 8.51)
        self.assertNotAlmostEqual(got, 8.51 + 0.41)  # would be the 60+ premium on 0.41 makes

    def test_oops_applies_extra_point_misses(self):
        self.assertAlmostEqual(build.score_kicker(OOPS, SAMPLE), 8.38)

    def test_split_actuals_are_not_double_counted(self):
        stats = dict(fgm_50_59=1, fgm_50p=1, xpm=1)
        self.assertAlmostEqual(build.score_kicker(BEST, stats), 2.5 + 0.5)
        self.assertAlmostEqual(build.score_kicker(ZBT, stats), 5 + 1)

    def test_bare_fgm_is_not_turned_into_distance_points(self):
        self.assertEqual(build.score_kicker(BEST, dict(fgm=4, fgm_lng=47, xpm=3)), 1.5)
        self.assertEqual(build.score_kicker(dict(fgm=3, xpm=1), dict(fgm=2, xpm=1)), 7)

    def test_miss_buckets_are_not_double_counted(self):
        stats = dict(fgmiss_40_49=1, fgmiss_50_59=1, fgmiss_50p=1)
        self.assertAlmostEqual(build.score_kicker(ZBT, stats), -2)  # two misses, not three

    def test_both_lines_use_identity_and_ignore_misses(self):
        stats = dict(fgm_20_29=0.4, fgm_40_49=0.6, fgm_50p=0.5, xpm=4, fgmiss_40_49=9, xpmiss=9)
        # scale is 1. XP = 8 - 3*1.5 = 3.5. ZBT: 0.4*3 + 0.6*4 + 0.5*5 + 3.5 = 9.6. Misses are not deducted.
        self.assertAlmostEqual(build.kicker_implied(ZBT, stats, 1.5, 8), 9.6)
        # the same make also listed as fgm_50_59 must not be added on top of fgm_50p
        self.assertAlmostEqual(build.kicker_implied(ZBT, dict(stats, fgm_50_59=0.5), 1.5, 8), 9.6)
        self.assertIsNone(build.kicker_implied(ZBT, stats, 2.5, 6))  # XP = 6 - 7.5 < 0

    def test_one_line_scales_sleeper_shape(self):
        stats = dict(fgm_20_29=1.0, fgm_40_49=1.0, xpm=2.0, fgmiss=4)
        # FG 1.0 on a 2.0 Sleeper mix -> half. XP scales with it: 1.0. ZBT 0.5*3 + 0.5*4 + 1 = 4.5
        self.assertAlmostEqual(build.kicker_implied(ZBT, stats, 1.0, None), 4.5)
        # KP 8 on Sleeper 3*(1+1)+2 = 8, factor 1, so the unscaled line. Double the line -> factor 2.
        self.assertAlmostEqual(build.kicker_implied(ZBT, stats, None, 8), 3 + 4 + 2)
        self.assertAlmostEqual(build.kicker_implied(ZBT, stats, None, 16), 2 * (3 + 4 + 2))
        self.assertIsNone(build.kicker_implied(ZBT, {}, 1.5, None))
        self.assertIsNone(build.kicker_implied(ZBT, {}, None, None))

    def test_prizepicks_parser_keeps_two_way_lines_only(self):
        def proj(stat, line, odds="standard", wager="under_or_over", name="Nick Sample", team="MIN", pos="K", updated="2026-11-07T00:00:00Z"):
            return {
                "attributes": {"odds_type": odds, "allowed_wager_types": wager, "status": "pre_game",
                               "line_score": line, "stat_type": stat, "updated_at": updated},
                "relationships": {
                    "stat_type": {"data": {"type": "stat_type", "id": stat}},
                    "new_player": {"data": {"type": "new_player", "id": name}},
                },
            }
        payload = {
            "data": [
                proj("FG Made", 1.5, updated="2026-11-07T01:00:00Z"),
                proj("FG Made", 2.5, odds="demon"),
                proj("FG Made", 4.5, wager="over"),
                proj("Kicking Points", 7.5),
                proj("Receiving Yards", 70.5, name="Riley Sample", pos="WR"),
                proj("FG Made", 1.5, name="Other Sample", team="GB"),
            ],
            "included": [
                {"type": "stat_type", "id": "FG Made", "attributes": {"name": "FG Made"}},
                {"type": "stat_type", "id": "Kicking Points", "attributes": {"name": "Kicking Points"}},
                {"type": "stat_type", "id": "Receiving Yards", "attributes": {"name": "Receiving Yards"}},
                {"type": "new_player", "id": "Nick Sample", "attributes": {"name": "Nick Sample", "team": "MIN", "position": "K"}},
                {"type": "new_player", "id": "Riley Sample", "attributes": {"name": "Riley Sample", "team": "GB", "position": "WR"}},
                {"type": "new_player", "id": "Other Sample", "attributes": {"name": "Other Sample", "team": "GB", "position": "K"}},
            ],
        }
        rows = {r["name"]: r for r in sources.parse_kicker_props(payload)}
        self.assertEqual(set(rows), {"Nick Sample", "Other Sample"})
        self.assertEqual(rows["Nick Sample"]["fg"], 1.5)
        self.assertEqual(rows["Nick Sample"]["kp"], 7.5)
        self.assertEqual(rows["Other Sample"]["fg"], 1.5)
        self.assertIsNone(rows["Other Sample"]["kp"])
        book = build.KickerProps(rows.values())
        self.assertEqual(book.lookup("Nick Sample", "MIN")["kp"], 7.5)
        self.assertIsNone(book.lookup("Nobody", "MIN"))

    def test_skill_prop_formula_unchanged(self):
        fw = {"players": [{"name": "Pat Skill", "team": "GB", "position": "RB",
                           "cells": {"player_rush_yds": 0, "player_anytime_td": 1}}],
              "cell": [[80, None, None, None, [0]], [None, None, None, None, [1]]],
              "quote": [["dk", 0, 80, 0, 0, 0], ["draftkings", 0, 0, 0, 0, -120]]}
        pr = build.Props(fw, {})
        self.assertEqual(pr.kicker_markets, [])
        got = pr.get("Pat Skill", "GB")
        self.assertAlmostEqual(got["pp"], 80 * 0.1 + 6 * (120 / 220))
        self.assertEqual(got["rush"], "80")


class WeatherFormat(unittest.TestCase):
    def test_roofs_for_every_2026_venue_ignore_espn_indoor_flag(self):
        expect = {
            "3687": "retractable", "3752": "outdoor", "6501": "dome", "3622": "outdoor", "3628": "outdoor",
            "3493": "dome", "3937": "outdoor", "3712": "outdoor", "3727": "dome", "3738": "outdoor",
            "3948": "outdoor", "11938": "outdoor", "3679": "outdoor", "3798": "outdoor", "4738": "outdoor",
            "3806": "outdoor", "3812": "retractable", "3673": "outdoor", "3814": "outdoor", "11931": "outdoor",
            "9119": "outdoor", "5348": "retractable", "3839": "outdoor", "3810": "outdoor", "3719": "outdoor",
            "3874": "outdoor", "3886": "outdoor", "3891": "retractable", "1353": "retractable", "7065": "covered",
            "3933": "outdoor", "1781": "outdoor", "3970": "retractable", "5534": "outdoor", "5239": "dome",
            "2455": "outdoor",
        }
        for vid, roof in expect.items():
            self.assertEqual(weather.locate({"venue_id": vid, "indoor": True}).roof, roof, vid)

    def test_name_fallback_and_unknown_buildings(self):
        self.assertEqual(weather.locate({"venue": "Reliant Stadium", "indoor": False}).roof, "retractable")
        self.assertEqual(weather.locate({"venue": "Santiago Bernabéu", "indoor": True}).roof, "retractable")
        self.assertEqual(weather.locate({"venue_id": "999", "venue": "Mystery Dome", "indoor": True}).roof, "unknown_indoor")
        unk = weather.locate({"venue_id": "999", "venue": "New Ground", "indoor": False})
        self.assertEqual(unk.roof, "outdoor")
        self.assertIsNone(unk.coord)

    def test_markers_do_not_present_outdoor_weather_as_indoor(self):
        obs = {"temp": 48.2, "wind": 10.6, "code": 71, "pop": 80, "precip": 0.08}
        text = weather.format_conditions(obs)
        self.assertEqual(text, "48\u00b0F, 11 mph, Snow 80%, 0.08 in")
        self.assertEqual(weather.decorate(text, "dome", "post", ", Madrid"), "(dome), Madrid")
        self.assertEqual(weather.decorate(text, "unknown_indoor", "pre", ""), "(indoor ?)")
        self.assertEqual(weather.decorate(text, "retractable", "post", ", Madrid"),
                         "48\u00b0F, 11 mph, Snow 80%, 0.08 in (roof ?), Madrid (final)")
        self.assertEqual(weather.decorate(weather.format_conditions({"temp": 72, "wind": 6, "code": 0, "pop": 0, "precip": 0}),
                                          "covered", "in", ""),
                         "72\u00b0F, 6 mph, Clear (covered) (kickoff)")
        self.assertIsNone(weather.format_conditions({"temp": None, "wind": 5, "code": 0}))
        self.assertEqual(weather.format_conditions({"temp": 70.8, "wind": 5, "code": 3, "pop": 20, "precip": 0}),
                         "71\u00b0F, 5 mph, Overcast")

    def test_neutral_site_uses_that_stadium_not_the_home_dome(self):
        calls = []

        venues = {
            "DAL": dict(venue_id="2455", venue="Wembley Stadium", city="London", country="England",
                        indoor=False, neutral=True, kickoff="2026-11-08T14:30:00Z", state="pre"),
            "MIN": dict(venue_id="5239", venue="U.S. Bank Stadium", city="Minneapolis", country="USA",
                        indoor=True, neutral=False, kickoff="2026-11-10T01:15:00Z", state="pre"),
            "ATL": dict(venue_id="1353", venue="Santiago Bernabéu", city="Madrid", country="Spain",
                        indoor=True, neutral=True, kickoff="2026-11-08T14:30:00Z", state="pre"),
            "GB": dict(venue_id="3798", venue="Lambeau Field", city="Green Bay", country="USA",
                       indoor=False, neutral=False, kickoff="2026-11-08T18:00:00Z", state="pre"),
        }
        def getter3(url):
            calls.append(url)
            n = url.split("latitude=")[1].split("&")[0].count(",") + 1
            row = {"temp": 57, "wind": 9, "code": 61, "pop": 40, "precip": 0.01}
            cold = {"temp": 31, "wind": 14, "code": 71, "pop": 70, "precip": 0.2}
            hours = {"2026-11-08T14:00": row, "2026-11-08T18:00": cold}
            items = [_hours(hours) for _ in range(n)]
            return json.dumps(items[0] if n == 1 else items)

        res = weather.build_weather_map(venues, NOW, getter=getter3, geocode=lambda v: None)
        self.assertEqual(res.by_team["MIN"], "(dome)")
        self.assertNotIn("\u00b0F", res.by_team["MIN"])
        self.assertIn("London", res.by_team["DAL"])
        self.assertNotIn("(dome)", res.by_team["DAL"])
        self.assertNotIn("(roof ?)", res.by_team["DAL"])
        self.assertIn("Madrid", res.by_team["ATL"])
        self.assertIn("(roof ?)", res.by_team["ATL"])
        self.assertNotIn("Green Bay", res.by_team["GB"])
        self.assertIn("\u00b0F", res.by_team["GB"])
        blob = " ".join(calls)
        self.assertIn("%.4f" % weather.locate({"venue_id": "2455"}).coord[0], blob)  # Wembley
        self.assertNotIn("%.4f" % weather.locate({"venue_id": "3687"}).coord[0], blob)  # AT&T, not the neutral site
        self.assertNotIn("%.4f" % weather.locate({"venue_id": "5239"}).coord[0], blob)  # dome, no outdoor fetch

    def test_horizon_bye_fallback_and_cache(self):
        calls = {"n": 0}

        def getter(url):
            calls["n"] += 1
            return _payload({"2026-11-08T18:00": {"temp": 50, "wind": 8, "code": 1, "pop": 0, "precip": 0}})

        late = {"GB": dict(venue_id="3798", venue="Lambeau Field", city="Green Bay", country="USA",
                           indoor=False, neutral=False, kickoff="2026-12-31T18:00:00Z", state="pre")}
        old = {"BAL": dict(venue_id="3814", venue="M&T Bank Stadium", city="Baltimore", country="USA",
                           indoor=False, neutral=False, kickoff="2026-10-01T01:00:00Z", state="post")}
        cache = tempfile.mkdtemp()
        try:
            self.assertEqual(weather.build_weather_map(late, NOW, cache_dir=cache, getter=getter).by_team["GB"], "no forecast")
            self.assertEqual(weather.build_weather_map(old, NOW, cache_dir=cache, getter=getter).by_team["BAL"], "no obs")
            home = {"GB": dict(venue_id="3798", venue="Lambeau Field", city="Green Bay", country="USA",
                               indoor=False, neutral=False, kickoff="2026-11-08T18:05:00Z", state="pre")}
            first = weather.build_weather_map(home, NOW, cache_dir=cache, getter=getter, ttl_sec=3600)
            n = calls["n"]
            second = weather.build_weather_map(home, NOW, cache_dir=cache, getter=getter, ttl_sec=3600)
            self.assertEqual(calls["n"], n)  # fresh cache, no second fetch
            self.assertEqual(first.by_team["GB"], second.by_team["GB"])
            self.assertTrue(first.asof)
            def boom(url):
                raise RuntimeError("down")
            stale = weather.build_weather_map(home, NOW + dt.timedelta(hours=5), cache_dir=cache, getter=boom, ttl_sec=1)
            self.assertIn("\u00b0F", stale.by_team["GB"])
            self.assertEqual(stale.asof, first.asof)
        finally:
            shutil.rmtree(cache)

        failed = weather.build_weather_map(
            {"GB": dict(venue_id="3798", venue="Lambeau Field", country="USA", indoor=False, neutral=False,
                        kickoff="2026-11-08T18:00:00Z", state="pre"),
             "MIN": dict(venue_id="5239", venue="U.S. Bank Stadium", country="USA", indoor=True, neutral=False,
                         kickoff="2026-11-10T01:15:00Z", state="pre")},
            NOW, getter=lambda url: (_ for _ in ()).throw(RuntimeError("down")))
        self.assertIsNone(failed.by_team["GB"])
        self.assertEqual(failed.by_team["MIN"], "(dome)")
        self.assertIsNone(failed.asof)


class Venues(unittest.TestCase):
    def test_neutral_and_alias_and_completed(self):
        d = {"week": {"number": 9}, "events": [
            {"date": "2026-11-08T00:00Z", "status": {"type": {"state": "pre", "completed": False}},
             "competitions": [{"neutralSite": True, "startDate": "2026-11-08T14:30Z",
                               "venue": {"id": "1353", "fullName": "Santiago Bernabéu", "indoor": True,
                                         "address": {"city": "Madrid", "country": "Spain"}},
                               "competitors": [{"homeAway": "home", "team": {"abbreviation": "ATL"}},
                                               {"homeAway": "away", "team": {"abbreviation": "CIN"}}]}]},
            {"date": "2026-11-08T18:00Z", "status": {"type": {"state": "pre"}},
             "competitions": [{"neutralSite": False,
                               "venue": {"id": "3719", "fullName": "Northwest Stadium", "indoor": False,
                                         "address": {"city": "Landover", "state": "MD", "country": "USA"}},
                               "competitors": [{"homeAway": "home", "team": {"abbreviation": "WAS"}},
                                               {"homeAway": "away", "team": {"abbreviation": "LAR"}}]}]},
            {"date": "2026-11-06T01:15Z", "status": {"type": {"state": "post", "completed": True}},
             "competitions": [{"neutralSite": False, "startDate": "2026-11-06T01:15Z",
                               "venue": {"id": "3814", "fullName": "M&T Bank Stadium", "indoor": False,
                                         "address": {"city": "Baltimore", "state": "MD", "country": "USA"}},
                               "competitors": [{"homeAway": "home", "team": {"abbreviation": "BAL"}},
                                               {"homeAway": "away", "team": {"abbreviation": "JAC"}}]}]},
        ]}
        v = sources.venues_from_scoreboard(d, 9)
        self.assertEqual(v["ATL"]["venue_id"], "1353")
        self.assertEqual(v["CIN"]["city"], "Madrid")
        self.assertTrue(v["ATL"]["neutral"] and v["CIN"]["neutral"])
        self.assertEqual(v["ATL"]["kickoff"], "2026-11-08T14:30Z")
        self.assertNotIn("WAS", v)
        self.assertEqual(v["WSH"]["venue_id"], "3719")
        self.assertEqual(v["LAR"]["venue_id"], "3719")  # not SoFi
        self.assertEqual(v["JAX"]["state"], "post")
        self.assertEqual(v["BAL"]["kickoff"], "2026-11-06T01:15Z")
        with self.assertRaises(RuntimeError):
            sources.venues_from_scoreboard({"week": {"number": 8}, "events": [{}]}, 9)
        with self.assertRaises(RuntimeError):
            sources.venues_from_scoreboard({"week": {"number": 9}, "events": []}, 9)


def _player(pid, name, pos, team, stats=None, inj=None):
    return pid, dict(full_name=name, position=pos, team=team, injury_status=inj), dict(
        player_id=pid, team=team, stats=stats or {}, player=dict(position=pos, injury_status=inj))


def _league(scoring, starters, players, proj, games, wx, prev=None, extra_roster=None, fp=None, kicker_props=None):
    rp = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    me_players = list(players)
    rost = [dict(owner_id="user", roster_id=1, starters=starters, players=me_players, reserve=[],
                 settings=dict(wins=4, losses=4, fpts=100, fpts_decimal=0))]
    if extra_roster:
        rost.append(dict(owner_id="other", roster_id=2, starters=["0"] * len(rp), players=list(extra_roster), reserve=[],
                         settings=dict(wins=4, losses=4, fpts=90, fpts_decimal=0)))
    else:
        rost.append(dict(owner_id="other", roster_id=2, starters=["0"] * len(rp), players=["zz"], reserve=[],
                         settings=dict(wins=4, losses=4, fpts=90, fpts_decimal=0)))
    bundle = dict(
        league=dict(name="Synthetic", league_id="L", season="2026", total_rosters=12, roster_positions=rp + ["BN"] * 6,
                    scoring_settings=scoring, settings=dict(reserve_slots=1)),
        rosters=rost,
        users=[dict(user_id="user", display_name="Me"), dict(user_id="other", display_name="Them")],
        matchups=[dict(roster_id=1, matchup_id=1), dict(roster_id=2, matchup_id=1)])
    ctx = dict(week=9, players={pid: info for pid, info, _e in proj}, proj={pid: e for pid, _i, e in proj},
               stats={}, games=games, wx=wx, kicker_props=kicker_props)
    if fp is None:
        fp = build.FPRanks({"k": [{"player_name": "Starter Sample", "rank_ecr": 4, "player_team_id": "MIN"}]})
    return build.build_league(ctx, bundle, "user", None, fp, "half-point-ppr-flex", prev or {})


class Kickers(unittest.TestCase):
    def _world(self):
        proj = []
        games = {}
        # starter and bench
        proj.append(_player("k-me", "Starter Sample", "K", "MIN", dict(xpm=3)))
        proj.append(_player("k-bn", "Bench Sample", "K", "TEN", dict(xpm=1)))
        games["MIN"] = ({"status": "pre_game"}, "vs", "BUF", "Mon")
        # excluded
        proj.append(_player("k-other", "Other Roster", "K", "KC", dict(xpm=100)))
        proj.append(_player("k-out", "Out Sample", "K", "GB", dict(xpm=99), "Out"))
        proj.append(_player("k-dbt", "Doubt Sample", "K", "DET", dict(xpm=98), "Doubtful"))
        proj.append(_player("k-done", "Played Sample", "K", "BAL", dict(xpm=97)))
        proj.append(_player("k-bye", "Bye Sample", "K", "PIT", dict(xpm=96)))
        games["KC"] = ({"status": "pre_game"}, "vs", "NYJ", "Sun")
        games["GB"] = ({"status": "pre_game"}, "at", "MIN", "Sun")
        games["DET"] = ({"status": "pre_game"}, "at", "MIA", "Sun")
        games["BAL"] = ({"status": "complete"}, "vs", "JAX", "Thu")
        # 12 available, xpm 20..9
        for i, xp in enumerate(range(20, 8, -1)):
            team = "T%d" % i
            proj.append(_player("k-fa-%d" % xp, "Fa%d Sample" % xp, "K", team, dict(xpm=xp)))
            games[team] = ({"status": "pre_game"}, "vs", "AAA", "Sun")
        # one available whose Sleeper team code is WAS; weather is stored under WSH
        proj.append(_player("k-was", "Was Sample", "K", "WAS", dict(xpm=15.5)))
        games["WAS"] = ({"status": "pre_game"}, "vs", "LAR", "Sun")
        wx = {"MIN": "(dome)", "WSH": "51\u00b0F, 9 mph, Clear", "T0": "40\u00b0F, 12 mph, Snow"}
        starters = ["0", "0", "0", "0", "0", "0", "0", "k-me", "0"]
        players = ["k-me", "k-bn"]
        d = _league(ZBT, starters, players, proj, games, wx, extra_roster=["k-other"])
        return d

    def test_ten_relevant_kickers_and_no_invented_props(self):
        buf = []
        real = sources.log
        sources.log = lambda *a: buf.append(" ".join(str(x) for x in a))
        try:
            d = self._world()
        finally:
            sources.log = real
        text = "\n".join(buf)
        self.assertNotIn("Starter Sample", text)
        self.assertNotIn("Fa20 Sample", text)
        ks = d["KICKERS"]
        self.assertEqual(len(ks), 10)
        self.assertEqual([r["name"] for r in ks], [
            "Starter Sample", "Bench Sample", "Fa20 Sample", "Fa19 Sample", "Fa18 Sample", "Fa17 Sample",
            "Fa16 Sample", "Was Sample", "Fa15 Sample", "Fa14 Sample"])
        banned = {"Other Roster", "Out Sample", "Doubt Sample", "Played Sample", "Bye Sample", "Fa13 Sample", "Fa9 Sample"}
        self.assertTrue(banned.isdisjoint({r["name"] for r in ks}))
        was = next(r for r in ks if r["name"] == "Was Sample")
        self.assertEqual(was["wx"], "51\u00b0F, 9 mph, Clear")
        self.assertNotIn("(dome)", was["wx"])
        self.assertTrue(all(r["pp"] is None for r in ks))
        self.assertTrue(all(r["fg"] == build.DASH and r["kp"] == build.DASH for r in ks))
        self.assertEqual(ks[0]["fp"], "K4")
        self.assertEqual(ks[2]["fp"], build.DASH)
        self.assertEqual(ks[0]["wx"], "(dome)")
        self.assertEqual(ks[1]["status"], "Bye")
        self.assertEqual(ks[1]["wx"], "Bye")
        self.assertAlmostEqual(ks[0]["pn"], 3.0)  # xpm 3 * ZBT xpm 1
        tiny = _league(ZBT, ["0", "0", "0", "0", "0", "0", "0", "0", "0"], [], [
            _player("a", "Only Sample", "K", "GB", dict(xpm=4)),
        ], {"GB": ({"status": "pre_game"}, "vs", "MIN", "Sun")}, {"GB": "40\u00b0F, 5 mph, Clear"})
        self.assertEqual([r["name"] for r in tiny["KICKERS"]], ["Only Sample"])
        empty = build.build_league(
            dict(week=9, players={}, proj={}, stats={}, games={}, wx={}),
            _bundle_empty(), "user", None, None, "ppr-flex", {})
        self.assertEqual(empty["KICKERS"], [])

    def test_previous_weather_kept_only_when_this_fetch_failed(self):
        proj = [_player("k", "Keep Sample", "K", "GB", dict(xpm=4))]
        games = {"GB": ({"status": "pre_game"}, "vs", "MIN", "Sun")}
        prev = {("Keep Sample", "GB"): {"fp": "K9", "wx": "old forecast"}}
        class Down:
            def lookup(self, page, row):
                return None
        kept = _league(ZBT, ["0"] * 8 + ["k"], ["k"], proj, games, {"GB": None}, prev, fp=Down())
        self.assertEqual(kept["KICKERS"][0]["wx"], "old forecast")
        self.assertEqual(kept["KICKERS"][0]["fp"], "K9")
        fresh = _league(ZBT, ["0"] * 8 + ["k"], ["k"], proj, games, {"GB": "no forecast"}, prev)
        self.assertEqual(fresh["KICKERS"][0]["wx"], "no forecast")
        # a failed kicker feed keeps the previous over/under; a live feed with no line does not
        prev_line = {("Keep Sample", "GB"): {"fp": "K9", "wx": "old forecast", "pp": 6.5, "fg": "1.5", "kp": "7.5"}}
        kept_line = _league(ZBT, ["0"] * 8 + ["k"], ["k"], proj, games, {"GB": "40\u00b0F, 5 mph, Clear"}, prev_line)
        self.assertEqual(kept_line["KICKERS"][0]["fg"], "1.5")
        self.assertAlmostEqual(kept_line["KICKERS"][0]["pp"], 6.5)
        stats = dict(fgm_20_29=1.0, fgm_40_49=1.0, xpm=2.0)
        proj[0][2]["stats"] = stats
        book = build.KickerProps([{"name": "Keep Sample", "team": "GB", "fg": 1.0, "kp": 6.0}])
        posted = _league(ZBT, ["0"] * 8 + ["k"], ["k"], proj, games, {"GB": "40\u00b0F, 5 mph, Clear"}, prev_line,
                         kicker_props=book)
        self.assertEqual(posted["KICKERS"][0]["fg"], "1")
        self.assertEqual(posted["KICKERS"][0]["kp"], "6")
        self.assertAlmostEqual(posted["KICKERS"][0]["pp"], build.kicker_implied(ZBT, stats, 1.0, 6.0))
        cleared = _league(ZBT, ["0"] * 8 + ["k"], ["k"], proj, games, {"GB": "40\u00b0F, 5 mph, Clear"}, prev_line,
                          kicker_props=build.KickerProps([]))
        self.assertEqual(cleared["KICKERS"][0]["fg"], build.DASH)
        self.assertIsNone(cleared["KICKERS"][0]["pp"])

    def test_lineup_rule_and_quick_read(self):
        low = _player("k1", "Low Sample", "K", "MIN", dict(xpm=4))
        high = _player("k2", "High Sample", "K", "GB", dict(xpm=8))
        free = _player("k3", "Free Sample", "K", "IND", dict(xpm=9))
        games = {"MIN": ({"status": "pre_game"}, "vs", "BUF", "Mon"),
                 "GB": ({"status": "pre_game"}, "at", "MIN", "Sun"),
                 "IND": ({"status": "pre_game"}, "vs", "DAL", "Sun")}
        d = _league(ZBT, ["0"] * 7 + ["k1", "0"], ["k1", "k2"], [low, high, free], games,
                    {"MIN": "(dome)", "GB": "40\u00b0F, 8 mph, Clear", "IND": "49\u00b0F, 7 mph, Clear (roof ?)"})
        self.assertFalse(d["meta"]["lineup"]["ok"])
        self.assertTrue(any("High Sample" in s and "Low Sample" in s for s in d["meta"]["lineup"]["swaps"]))
        bullet = [b for b in build.quick_read(d) if "kicker" in b.lower()]
        self.assertTrue(bullet and "No kicker prop was posted" in bullet[0] and "Free Sample" in bullet[0])
        for r in d["STARTERS"] + d["BENCH"]:
            if r["name"] == "Low Sample":
                r["pp"] = 10
            if r["name"] == "High Sample":
                r["pp"] = 8
        chk = build.lineup_check(d["STARTERS"], d["BENCH"], ["QB", "RB1", "RB2", "WR1", "WR2", "TE", "FLEX", "K", "DEF"],
                                  ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"], ["0"] * 7 + ["k1", "0"])
        self.assertFalse(any("High Sample" in s for s in chk["swaps"]))


def _bundle_empty():
    rp = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    return dict(
        league=dict(name="Synthetic", league_id="L", season="2026", total_rosters=12, roster_positions=rp + ["BN"],
                    scoring_settings=ZBT, settings=dict(reserve_slots=0)),
        rosters=[dict(owner_id="user", roster_id=1, starters=["0"] * len(rp), players=[], reserve=[],
                      settings=dict(wins=0, losses=0, fpts=0, fpts_decimal=0))],
        users=[dict(user_id="user", display_name="Me")], matchups=[])


class Text(unittest.TestCase):
    def test_notes_asof_caption_and_canon(self):
        notes = " ".join(build.notes_for([], None, 9))
        self.assertIn("Open-Meteo", notes)
        self.assertIn("(dome)", notes)
        self.assertIn("(roof ?)", notes)
        self.assertIn("PrizePicks", notes)
        self.assertIn("two-way over/under", notes)
        self.assertNotIn("Fieldwork does not post kicker props", notes)
        self.assertIn("50-59", notes)
        cap = build.waiver_caption([{"pos": "WR"}, {"pos": "RB"}])
        self.assertIn("Weather is the kickoff forecast", cap)
        self.assertIn("weather as of", build.asof_text({"weather_asof": "2026-11-08T18:00:00Z"}))
        self.assertIn("weather not available", build.asof_text({}))
        d = {"META": {"asof": "a", "generated": "b", "sources": {"weather_asof": "c"}, "week": 9},
             "STARTERS": [], "BENCH": [], "WAIVER": [], "DEFENSE": [], "KICKERS": [{"name": "A", "wx": "(dome)"}]}
        c1 = update.canon(d)
        d["META"]["asof"] = "changed"
        self.assertEqual(update.canon(d), c1)
        d["KICKERS"][0]["wx"] = "Bye"
        self.assertNotEqual(update.canon(d), c1)


class Pages(unittest.TestCase):
    def test_all_four_leagues_main_and_standalone(self):
        pages = {"index.html": ["best", "zbt", "oops", "spacex"], "best-league.html": ["best"],
                 "zbt.html": ["zbt"], "oopsilons.html": ["oops"], "spacex-ff.html": ["spacex"]}
        for fn, keys in pages.items():
            text = (ROOT / fn).read_text()
            for k in keys:
                self.assertIn('id="%s-kickers"' % k, text)
                self.assertIn('id="%s-t-kick"' % k, text)
                self.assertIn('id="%s-view-report" hidden' % k, text)
            self.assertIn("(dome)", text)
            self.assertIn("(roof ?)", text)
        idx = (ROOT / "index.html").read_text()
        i = idx.find('id="best-subtabs"')
        chunk = idx[i:i + 400]
        self.assertLess(chunk.find('data-v="power"'), chunk.find('data-v="podcast"'))
        self.assertLess(chunk.find('data-v="podcast"'), chunk.find('data-v="report"'))
        self.assertIn('data-v="power" aria-selected="true"', chunk)
        js = (ROOT / "report-core.js").read_text()
        self.assertIn("KICKERS", js)
        self.assertIn("Weather", js)
        self.assertNotIn("odds", js)

    def test_render_script(self):
        r = subprocess.run(["node", str(ROOT / "tools" / "test_render.js")], cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            self.fail(r.stdout + "\n" + r.stderr)


class Privacy(unittest.TestCase):
    def test_production_reports_stay_encrypted(self):
        self.assertEqual(seal.main(["seal.py", "verify"]), 0)
        for fn in seal.FILES:
            text = (ROOT / fn).read_text(encoding="utf-8")
            self.assertTrue(seal.is_sealed(text), fn)
            self.assertNotIn("window.REPORTS", text)

    def test_synthetic_password_round_trip_is_not_the_production_lock(self):
        pw = "synthetic-fixture-only"
        ks = os.urandom(16)
        lock = {"ks": seal._s(ks), "iter": seal.ITER}
        key = seal.Key(pw, lock)
        lock["check"] = key.seal_blob("CHECK", "fh-ok")
        key = seal.Key(pw, lock)
        with self.assertRaises(seal.SealError):
            seal.Key("not-the-password", lock)
        obj = {"META": {"week": 9, "title": "Synthetic"}, "STARTERS": [], "BENCH": [], "WAIVER": [], "DEFENSE": [],
               "KICKERS": [{"name": "WaiverTargetZZZ", "team": "GB", "wx": "(dome)", "pp": None}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "best-league-report.js"
            key.write(str(path), "REPORTS.best", obj)
            raw = path.read_bytes()
            self.assertNotIn(b"WaiverTargetZZZ", raw)
            self.assertIn(b"window.LOCKED", raw)
            slot, got = key.open_text(path.read_text(encoding="utf-8"))
            self.assertEqual(slot, "REPORTS.best")
            self.assertEqual(got["KICKERS"][0]["wx"], "(dome)")
        self.assertTrue((ROOT / "tools" / "lock.json").exists())


def write_fixture_page(dest):
    """Standalone synthetic page for a screenshot. Does not load any *-report.js."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "style.css", dest / "style.css")
    shutil.copy(ROOT / "report-core.js", dest / "report-core.js")
    data = json.loads((ROOT / "tools" / "fixtures" / "synthetic_week.json").read_text())
    html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic fixture</title>
<link rel="stylesheet" href="style.css">
</head><body class="theme-best">
<div class="wrap">
<p class="cap" style="font-weight:700">Synthetic fixture only. Not a league report. No real roster or waiver list.</p>
<h1 id="best-title"></h1>
<p class="asof" id="best-asof"></p>
<section class="quick"><h2>Quick read (suggestion only)</h2><ul id="best-quick"></ul></section>
<section id="best-flex-tiebreaker"><h2>Flex tiebreaker</h2>
<div class="ctl"><div class="seg" id="best-seg-view"></div><div class="seg" id="best-seg-sort"></div></div>
<div class="scroll" id="best-t-flex"></div></section>
<section id="best-defense"><h2>Defense</h2><div class="scroll" id="best-t-def"></div></section>
<section id="best-kickers"><h2>Kickers</h2>
<p class="cap">Your kickers first, then available kickers, up to 10. FG made and Kicking pts are the two-way over/under. Prop-implied pts scores those lines with the league's kicking settings. Weather is the kickoff forecast at the actual stadium. (dome) is indoor. (roof ?) is outdoor at a retractable roof. (covered) is a canopy.</p>
<div class="scroll" id="best-t-kick"></div></section>
<section id="best-starters"><h2>Starters</h2><div class="scroll" id="best-t-starters"></div></section>
<section id="best-bench"><h2>Bench</h2><div class="scroll" id="best-t-bench"></div></section>
<section id="best-waivers"><h2>Waiver flex options</h2><p class="cap" id="best-wcap"></p><div class="scroll" id="best-t-waiver"></div></section>
<section id="best-league-setup"><h2>League setup</h2><dl id="best-setup"></dl></section>
<section id="best-data-notes"><h2>Data notes and sources</h2><ul id="best-notes"></ul></section>
<p id="best-week" hidden></p>
</div>
<script src="report-core.js"></script>
<script>
window.REPORTS = %s;
initReport("best");
</script>
</body></html>
""" % json.dumps(data["REPORTS"])
    (dest / "index.html").write_text(html)
    return dest / "index.html"


if __name__ == "__main__":
    if "--page" in sys.argv:
        i = sys.argv.index("--page")
        print(write_fixture_page(sys.argv[i + 1]))
    else:
        unittest.main()
