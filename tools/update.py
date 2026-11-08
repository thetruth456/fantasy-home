#!/usr/bin/env python3
"""Rebuild the site's data files (*-report.js) from Sleeper, Fieldwork props and FantasyPros ranks.

Run by .github/workflows/update.yml every hour; the schedule gate below decides whether an hourly run does anything.

Environment:
  FORCE=true       skip the time gate and always write (the "Refresh everything" button sets this)
  FH_NOW=<iso>     pretend it is this UTC time (testing the gate)
  FH_OUT_DIR=<dir> write the data files here instead of the repo root (testing)
  FH_CACHE_DIR     where the Sleeper players dump is cached (default <repo>/.cache)
  FH_REPORT_PASSWORD  required: data files are written encrypted (tools/seal.py); without it nothing is written

Weather uses the public Open-Meteo forecast (no key) and the ESPN scoreboard for the real stadium.
"""
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402
import seal  # noqa: E402
import sources as S  # noqa: E402
import weather  # noqa: E402
from sources import log  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_ID = "861321841237696512"  # kfelder30
PT = ZoneInfo("America/Los_Angeles")

# key -> (data file, Sleeper league id, FantasyPros flex ranking page)
LEAGUES = {
    "best": ("best-league-report.js", "1389358450705727488", "half-point-ppr-flex"),
    "zbt": ("zbt-report.js", "1389375330296279040", "ppr-flex"),
    "oops": ("oopsilons-report.js", "1389754735367589888", "ppr-flex"),
    "spacex": ("spacex-report.js", "1398902725940367360", "ppr-flex"),
}
TIME_FIELDS = ("generated", "asof", "sources")
GROUPS = ("STARTERS", "BENCH", "WAIVER", "DEFENSE", "KICKERS")


# ------------------------------------------------------------------ schedule gate
def in_hourly_window(now_pt):
    """Saturday 1:00 PM PT through Sunday 10:59 AM PT (the 10:00 PT run is the last one; cron may start it a bit late)."""
    wd, h = now_pt.weekday(), now_pt.hour
    return (wd == 5 and h >= 13) or (wd == 6 and h <= 10)


def should_run(now_pt, force):
    if force:
        return True, "forced"
    if in_hourly_window(now_pt):
        return True, "inside the Sat 1 PM - Sun 10 AM PT hourly window"
    if now_pt.hour == 9:
        return True, "daily 9 AM PT run"
    return False, "outside the window and not the 9 AM PT daily run"


# ------------------------------------------------------------------ data file io
def read_data(path, key, K):
    return seal.read(path, "REPORTS." + key, K)


def write_data(path, key, d, K):
    """Always encrypted (tools/seal.py); there is no plaintext path."""
    obj = {"META": d["META"]}
    for g in GROUPS:
        obj[g] = d.get(g) or []
    K.write(path, "REPORTS." + key, obj)


def canon(d):
    if not d:
        return None
    m = {k: v for k, v in (d.get("META") or {}).items() if k not in TIME_FIELDS}
    return json.dumps([m] + [d.get(g) or [] for g in GROUPS], sort_keys=True)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ main
def main():
    force = os.environ.get("FORCE", "").strip().lower() in ("1", "true", "yes")
    now = dt.datetime.now(dt.timezone.utc)
    if os.environ.get("FH_NOW"):
        now = dt.datetime.fromisoformat(os.environ["FH_NOW"].replace("Z", "+00:00"))
    now_pt = now.astimezone(PT)
    ok, why = should_run(now_pt, force)
    log("Now %s UTC = %s PT (%s). Run? %s: %s" % (now.strftime("%Y-%m-%d %H:%M"), now_pt.strftime("%a %Y-%m-%d %H:%M %Z"), "forced" if force else "gated", "YES" if ok else "NO", why))
    if not ok:
        return 0
    try:  # fail closed: no password (or the wrong one) -> write nothing
        K = seal.Key()
    except seal.SealError as e:
        log("ERROR: %s" % e)
        return 1
    out_dir = os.environ.get("FH_OUT_DIR") or ROOT
    cache_dir = os.environ.get("FH_CACHE_DIR") or os.path.join(ROOT, ".cache")
    os.makedirs(out_dir, exist_ok=True)

    # --- Sleeper core (everything depends on this)
    try:
        state = S.sleeper_state()
        week, season, stype = int(state["week"]), str(state.get("season") or state.get("league_season")), state.get("season_type", "regular")
        log("Sleeper state: season %s week %s (%s)" % (season, week, stype))
        if stype != "regular":
            log("Not in the regular season; nothing to update.")
            return 0
        sched = S.sleeper_schedule(season)
        projs = S.sleeper_projections(season, week, stype)
        stats = S.sleeper_stats(season, week, stype)
        players = S.sleeper_players(cache_dir)
    except Exception as e:  # noqa: BLE001
        log("ERROR: Sleeper core data unavailable, leaving the site unchanged: %s" % e)
        return 1
    proj_asof = iso(dt.datetime.now(dt.timezone.utc) if not os.environ.get("FH_NOW") else now)
    games = {}
    for g in sched:
        if g.get("week") != week:
            continue
        day = dt.date.fromisoformat(g["date"]).strftime("%a")
        games[g["home"]] = (g, "vs", g["away"], day)
        games[g["away"]] = (g, "@", g["home"], day)
    ctx = dict(week=week, players=players, proj={x["player_id"]: x for x in projs if x.get("player_id")},
               stats={x["player_id"]: x["stats"] for x in stats if x.get("player_id") and x.get("stats")}, games=games)
    log("projections %d, stats %d, games this week %d" % (len(ctx["proj"]), len(ctx["stats"]), len(games) // 2))

    # --- props (Fieldwork)
    overrides = None
    try:
        overrides = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")))
    except Exception:  # noqa: BLE001
        pass
    ovr_players = (overrides or {}).get("players", {}) if str((overrides or {}).get("week")) == str(week) else {}
    props = None
    props_asof = None
    try:
        fw = S.fetch_fieldwork(season, week)
        props = build.Props(fw, ovr_players)
        props_asof = fw.get("lastSuccessAt") or fw.get("collected")
        log("Fieldwork props: %d players (lines collected %s)" % (len(fw["players"]), props_asof))
        if props.kicker_markets:
            log("WARNING: Fieldwork has kicker markets (%s); the kicker table uses PrizePicks over/unders instead" % ", ".join(props.kicker_markets))
    except Exception as e:  # noqa: BLE001
        log("WARNING: Fieldwork props unavailable, keeping the previous props for this week: %s" % e)

    # --- kicker over/unders (PrizePicks). Separate from Fieldwork, which has no kicker markets.
    kicker_props = None
    kicker_props_asof = None
    try:
        kicker_rows = S.fetch_kicker_props()
        kicker_props = build.KickerProps(kicker_rows)
        kicker_props_asof = proj_asof
        n_fg = sum(1 for r in kicker_rows if r.get("fg") is not None)
        n_kp = sum(1 for r in kicker_rows if r.get("kp") is not None)
        n_both = sum(1 for r in kicker_rows if r.get("fg") is not None and r.get("kp") is not None)
        log("kicker O/U: %d players, %d FG lines, %d kicking-point lines, %d with both" % (len(kicker_rows), n_fg, n_kp, n_both))
        if not kicker_rows:
            log("WARNING: PrizePicks has no two-way kicker lines; kicker prop cells stay dashes")
    except Exception as e:  # noqa: BLE001
        log("WARNING: kicker over/unders unavailable, keeping the previous kicker lines for this week: %s" % e)

    # --- FantasyPros ranks
    fp = None
    fp_asof = None
    try:
        pages = S.fetch_fp(week)
        if pages:
            fp = build.FPRanks(pages)
            fp_asof = proj_asof
            log("FantasyPros pages: %s" % ", ".join("%s=%d" % (k, len(v)) for k, v in pages.items()))
            if len(pages) < len(S.FP_PAGES):
                log("WARNING: some FantasyPros pages missing; those ranks keep previous values")
        else:
            log("WARNING: no FantasyPros pages available, keeping the previous ranks for this week")
    except Exception as e:  # noqa: BLE001
        log("WARNING: FantasyPros unavailable: %s" % e)

    # --- game lines (ESPN) for the Defense table
    lines = None
    lines_asof = None
    try:
        lines = S.fetch_game_lines(season, week)
        lines_asof = proj_asof if lines else None
        log("ESPN game lines: %d teams with a total and spread" % len(lines))
        if not lines:
            log("WARNING: ESPN has no posted lines for this week yet; defense line columns show dashes")
    except Exception as e:  # noqa: BLE001
        log("WARNING: ESPN game lines unavailable, keeping the previous lines for this week: %s" % e)

    # --- venues and kickoff weather (actual stadium, including neutral sites)
    venues = None
    try:
        venues = S.fetch_venues(season, week)
        log("ESPN venues: %d teams" % len(venues))
    except Exception as e:  # noqa: BLE001
        log("WARNING: ESPN venues unavailable, weather keeps previous values: %s" % e)
    wx_result = None
    if venues is not None:
        try:
            wx_result = weather.build_weather_map(venues, now, cache_dir=cache_dir)
        except Exception as e:  # noqa: BLE001
            log("WARNING: weather failed (%s); outdoor cells keep previous values" % e)
            wx_result = None
    ctx["wx"] = wx_result.by_team if wx_result is not None else None
    ctx["kicker_props"] = kicker_props
    fresh_weather_asof = wx_result.asof if wx_result is not None else None

    changed, failed = [], []
    for key, (fn, lid, flex_page) in LEAGUES.items():
        path = os.path.join(out_dir, fn)
        prev = read_data(path if os.path.exists(path) else os.path.join(ROOT, fn), key, K)
        pm = (prev or {}).get("META") or {}
        same_week = bool(prev) and str(pm.get("week")) == str(week)
        prev_rows = {}
        prev_lines = {}
        if same_week:
            for g in GROUPS:
                for r in prev.get(g, []):
                    prev_rows[(r["name"], r["team"])] = r
            for r in prev.get("DEFENSE", []):  # last known line per team, used only if ESPN is down
                if r.get("total") is not None and r.get("opptot") is not None:
                    prev_lines[build.team_norm(r["team"])] = dict(total=r["total"], spread=r["spread"], opp_total=r["opptot"], team_total=r["total"] - r["opptot"])
        psrc = pm.get("sources", {}) if same_week else {}
        try:
            bundle = S.sleeper_league_bundle(lid, week)
            ctx["lines"] = lines if lines is not None else prev_lines
            d = build.build_league(ctx, bundle, USER_ID, props, fp, flex_page, prev_rows,
                                    (prev or {}).get("DEFENSE") if same_week else None,
                                    (prev or {}).get("KICKERS") if same_week else None)
        except Exception as e:  # noqa: BLE001
            log("ERROR: league %s failed (%s); keeping its previous data" % (key, e))
            failed.append(key)
            continue
        m = d.pop("meta")
        sources = dict(
            proj_asof=proj_asof,
            props_asof=props_asof if props is not None else psrc.get("props_asof"),
            fp_asof=fp_asof if fp is not None else psrc.get("fp_asof"),
            lines_asof=lines_asof if lines is not None else (psrc.get("lines_asof") if prev_lines else None),
            weather_asof=fresh_weather_asof if fresh_weather_asof else (psrc.get("weather_asof") if same_week else None),
            kicker_props_asof=kicker_props_asof if kicker_props is not None else (psrc.get("kicker_props_asof") if same_week else None))
        META = dict(
            key=key, week=week, season=season, season_type=stype, league_id=m["league_id"], name=m["name"],
            title="%s Week %d: roster, kickers, waiver flex options and prop tiebreakers" % (m["name"], week),
            lineup=m.get("lineup"),
            quick=build.quick_read(d),
            wcap=build.waiver_caption(d["WAIVER"]),
            setup=build.setup_text(m, week),
            notes=build.notes_for(d["STARTERS"] + d["BENCH"] + d["WAIVER"] + d.get("KICKERS", []) + d.get("DEFENSE", []), overrides, week),
            scoring=m["scoring"], fp_page=flex_page, sources=sources,
            asof=build.asof_text(sources), generated=iso(now if os.environ.get("FH_NOW") else dt.datetime.now(dt.timezone.utc)))
        d["META"] = META
        if canon(d) == canon(prev) and not force:
            log("%-7s no substantive change; leaving file as is" % key)
            continue
        if canon(d) == canon(prev):
            log("%-7s unchanged data, rewriting timestamps (forced)" % key)
        else:
            log("%-7s data changed -> %s" % (key, fn))
        write_data(path, key, d, K)
        changed.append(key)
        rows = []
        for g in GROUPS:
            rows.extend(d.get(g) or [])
        unranked = [r for r in rows if r["fp"] == build.DASH and r["status"] in ("Healthy", "Questionable") and r["pos"] in ("RB", "WR", "TE", "QB", "K", "DEF")]
        if unranked:
            log("        no FantasyPros rank for %d player(s) (names not logged: Actions logs are public)" % len(unranked))
        ks = d.get("KICKERS") or []
        log("        kickers: %d (%d rostered)" % (len(ks), sum(1 for r in ks if r.get("slot") != "WAIVER")))
        noprops = [r for r in d["STARTERS"] + d["BENCH"] + d["WAIVER"] if r["pos"] in ("RB", "WR", "TE") and r["status"] not in build.SKIP_PROPS and r["pp"] is None]
        if noprops:
            log("        no prop-implied pts (missing lines) for %d player(s)" % len(noprops))
    log("Done. Changed: %s. Failed: %s." % (", ".join(changed) or "none", ", ".join(failed) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
