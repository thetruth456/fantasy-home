"""Top keepers for next season, Best League and Oopsilons only.

The weekly report is for the current season. This table is the keep decision for the
following season, using current rosters. ZBT and SpaceX are not keeper tables here.

Cost, from this league's most recent completed draft (Sleeper `is_keeper` picks count):
  keep round = draft round - 2, then held to 1 through 9.
  A player with no pick in that draft costs a 9th (waiver, free agency, or any other
  path onto the roster). A trade does not change the round. The current roster only
  decides who holds the player.
  The round is the round on this year's pick, not the original draft round frozen for
  both keeper years. Back-to-back keeper rounds in these leagues usually drop by 2,
  which is the same step. The 9th-round cap is applied even when a draft kept someone later.

Ineligible: `is_keeper` in both of the two seasons before the target season. Those
players are left off the ranking. A name is never hardcoded.

Value (points per game):
  expected = average of
    (1) 2026 points per game, shrunk toward that player's Sleeper season projection
        with weight gp / (gp + 7), the same prior the power model uses, and
    (2) the Sleeper projected points per game of whichever player sits at the same
        FantasyPros rest-of-season overall rank (half-PPR or PPR, matching the league).
  If one side is missing, the other is used and the missing column is left blank.
  Surplus = (expected - replacement at the position) - typical value of the keep round.
  Replacement is the Nth-best projected points per game at the position (tools/draftprior.py).
  The round's value is the mean value-over-replacement of the ADP neighborhood around
  the middle pick of that round, the same window draftprior uses for a single pick.
  ADP value-over-replacement is floored at 0. The player's own surplus is not, so a
  bust can rank below the round. Players with no surplus are omitted, not filled with 0.
"""
import statistics

import build as scoring
import draftprior as DP
import sources as S
from leagues import adp_key

KEYS = ("best", "oops")
TOP_N = 24
COST_MIN = 1
COST_MAX = 9
PRIOR = 7.0  # power.py G0: weight on actual points per game is gp / (gp + PRIOR)
ROS_HALF = "ros-half-point-ppr-overall"
ROS_PPR = "ros-ppr-overall"
DATA_NOTE = (
    "Keepers: the top 24 for next season are listed above the league setup. "
    "Cost is this year's draft round minus 2, never earlier than the 1st or later than the 9th. "
    "A player who was not in this year's draft costs a 9th. "
    "Players kept in both of the previous two seasons are left off. "
    "Value is surplus points per game versus the ADP value of that round, using this year's points and FantasyPros rest-of-season ranks for this league's scoring."
)


def enabled(key):
    return key in KEYS


def extra_note(key):
    return DATA_NOTE if enabled(key) else None


def ros_page(scoring):
    """FantasyPros rest-of-season page for this league's reception scoring. None if we have no page."""
    rec = float((scoring or {}).get("rec") or 0)
    if rec >= 1:
        return ROS_PPR
    if rec <= 0:
        return None
    return ROS_HALF


def keep_cost(draft_round):
    """(cost, how) from a draft round, or (9, 'Waiver') when the player was not drafted.

    A round that is missing or not a positive integer returns (None, None): the cost is
    unknown and is not guessed. Waiver is only the explicit 'not in the draft' case.
    """
    if draft_round is None:
        return COST_MAX, "Waiver"
    try:
        rd = int(draft_round)
    except (TypeError, ValueError):
        return None, None
    if isinstance(draft_round, bool) or rd < 1:
        return None, None
    return max(COST_MIN, min(COST_MAX, rd - 2)), "Rd %d" % rd


def round_anchor(rnd, nteams):
    """1-indexed pick at the middle of a draft round."""
    return (int(rnd) - 1) * int(nteams) + (int(nteams) + 1) // 2


def adp_window(values, pick_no):
    """ADP-ordered values around a 1-indexed pick. Same slice as draftprior.pickval."""
    n = int(pick_no)
    return list(values[max(0, n - 4):min(len(values), n + 3)])


def round_baseline(vor_in_adp_order, nteams, rnd):
    window = adp_window(vor_in_adp_order, round_anchor(rnd, nteams))
    if not window:
        return None
    return statistics.mean(window)


def kept_seasons(drafts, player_id):
    pid = str(player_id)
    years = set()
    for d in drafts or []:
        if any(str(p.get("player_id")) == pid and p.get("is_keeper") for p in d.get("picks") or []):
            try:
                years.add(int(d.get("season")))
            except (TypeError, ValueError):
                continue
    return years


def eligible(seasons, for_season):
    """False when the player was a keeper in both of the two seasons before for_season."""
    try:
        year = int(for_season)
    except (TypeError, ValueError):
        return True
    return not ({year - 1, year - 2} <= set(seasons or []))


def draft_round(drafts, player_id, season):
    """Round on this season's draft pick, or None if the player was not picked.

    Several picks in the same season use the earlier round. A missing round is kept
    as None so the caller does not invent one.
    """
    pid = str(player_id)
    found = []
    saw = False
    for d in drafts or []:
        if str(d.get("season")) != str(season):
            continue
        for p in d.get("picks") or []:
            if str(p.get("player_id")) != pid:
                continue
            saw = True
            rd = p.get("round")
            try:
                if rd is not None and not isinstance(rd, bool):
                    found.append(int(rd))
            except (TypeError, ValueError):
                found.append(None)
    if not saw:
        return None
    nums = [r for r in found if isinstance(r, int) and r >= 1]
    if not nums:
        return "missing"
    return min(nums)


def roster_player_ids(roster):
    out, seen = [], set()
    for bucket in ("players", "reserve", "taxi"):
        for pid in roster.get(bucket) or []:
            pid = str(pid)
            if pid and pid != "0" and pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fantasy_points(S, stats, pos):
    """League points for one Sleeper stat line. None when there is no line to score."""
    if not stats:
        return None
    if pos == "K":
        return scoring.score_kicker(S, stats)
    total = 0.0
    for k, v in stats.items():
        if not _num(v):
            continue
        w = (S or {}).get(k)
        if _num(w) and w:
            total += float(w) * float(v)
    return total


def games_played(stats):
    if not stats:
        return None
    gp = stats.get("gp")
    if not _num(gp) or gp <= 0:
        gp = stats.get("gms_active")
    if not _num(gp) or gp <= 0:
        return None
    return float(gp)


def projection_ppg(S, stats, pos):
    """Per-game rate for a season projection.

    Skill players and kickers publish gp of 17 or 18. Defenses publish a season total
    with gp 1 (a sack total of 50 is not one game). A gp below 10 is not used as the
    divisor; the total is spread over 17 games instead.
    """
    pts = fantasy_points(S, stats, pos)
    if pts is None:
        return None
    gp = (stats or {}).get("gp")
    if not _num(gp) or gp < 10:
        gp = 17.0
    return pts / float(gp)


def blend_expected(perf_ppg, gp, proj_ppg, rank_ppg, prior=PRIOR):
    """Expected points per game. None only when every input is missing."""
    reg = None
    if perf_ppg is not None and gp:
        if proj_ppg is not None:
            reg = (float(gp) * perf_ppg + prior * proj_ppg) / (float(gp) + prior)
        else:
            reg = perf_ppg
    elif proj_ppg is not None:
        reg = proj_ppg
    if reg is not None and rank_ppg is not None:
        return 0.5 * reg + 0.5 * rank_ppg
    if reg is not None:
        return reg
    return rank_ppg


def surplus(expected, repl_ppg, baseline):
    if expected is None or repl_ppg is None or baseline is None:
        return None
    return (expected - repl_ppg) - baseline


def _season_drafts(drafts, season):
    return [d for d in drafts or [] if str(d.get("season")) == str(season)]


def history_notes(drafts, season, settings):
    """League-setting notes with counts and rounds only. No player names."""
    notes = []
    settings = settings or {}
    cur = _season_drafts(drafts, season)
    cur.sort(key=lambda d: len(d.get("picks") or []), reverse=True)
    rounds = cur[0].get("rounds") if cur else None
    setting_rounds = settings.get("draft_rounds")
    try:
        if setting_rounds and rounds and int(setting_rounds) != int(rounds):
            notes.append(
                "Sleeper's league setting draft_rounds is %s. The completed %s draft has %s rounds, and costs use those pick rounds."
                % (setting_rounds, season, rounds))
    except (TypeError, ValueError):
        pass
    if settings.get("max_keepers"):
        notes.append(
            "Sleeper max_keepers is %s per team. That cap is not the two-year limit. A player marked keeper in both of the previous two seasons is left off this list."
            % settings.get("max_keepers"))
    by = {}
    for d in drafts or []:
        try:
            year = int(d.get("season"))
        except (TypeError, ValueError):
            continue
        for p in d.get("picks") or []:
            if p.get("is_keeper") and p.get("round"):
                try:
                    by.setdefault(str(p.get("player_id")), []).append((year, int(p["round"])))
                except (TypeError, ValueError):
                    continue
    deltas = []
    for hist in by.values():
        hist.sort()
        for a, b in zip(hist, hist[1:]):
            if b[0] == a[0] + 1:
                deltas.append(b[1] - a[1])
    if deltas:
        n = sum(1 for x in deltas if x == -2)
        notes.append(
            "In back-to-back seasons the keeper round dropped by 2 in %d of %d cases. Next year's cost is this year's draft round minus 2, then held to rounds 1 through 9."
            % (n, len(deltas)))
    late = []
    for d in cur:
        for p in d.get("picks") or []:
            if not p.get("is_keeper"):
                continue
            try:
                rd = int(p.get("round"))
            except (TypeError, ValueError):
                continue
            if rd > COST_MAX:
                late.append(rd)
    if late:
        notes.append(
            "The %s draft kept players later than round 9 (as late as round %d). Costs here are still capped at 9."
            % (season, max(late)))
    normal = set()
    for d in drafts or []:
        for p in d.get("picks") or []:
            if not p.get("is_keeper"):
                normal.add(str(p.get("player_id")))
    waiver_rounds = set()
    for d in cur:
        for p in d.get("picks") or []:
            if not p.get("is_keeper") or str(p.get("player_id")) in normal:
                continue
            try:
                waiver_rounds.add(int(p.get("round")))
            except (TypeError, ValueError):
                continue
    if waiver_rounds and waiver_rounds != {COST_MAX}:
        shown = ", ".join("round %d" % r for r in sorted(waiver_rounds))
        notes.append(
            "Keepers with no prior draft pick in this league were slotted in %s in %s, not only round 9. A player in this year's draft is priced off that round; a player missing from this year's draft costs a 9th."
            % (shown, season))
    return notes


def _pos_name_team(pid, players, proj, stats):
    q = dict((players or {}).get(pid) or {})
    for src in (proj, stats):
        pl = (src or {}).get("player") or {}
        if not q.get("position") and (pl.get("position") or (src or {}).get("position")):
            q["position"] = pl.get("position") or src.get("position")
        if not q.get("team"):
            q["team"] = (src or {}).get("team") or pl.get("team")
        if not q.get("full_name"):
            q["full_name"] = pl.get("full_name") or ("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip()
    pos = q.get("position") or ""
    team = q.get("team") or ""
    name = (q.get("full_name") or "").strip()
    if not name:
        name = ("%s %s" % (q.get("first_name") or "", q.get("last_name") or "")).strip()
    if pos == "DEF" and team:
        name = team + " D/ST"
    name = (name or str(pid)).replace(" Sr.", "")
    return pos, name, team


class RosIndex:
    def __init__(self, players):
        self.by_name = {}
        for p in players or []:
            self.by_name.setdefault(S.norm(p.get("player_name") or ""), []).append(p)

    def lookup(self, name, team, pos):
        if pos == "DEF" or not name:
            return None
        cands = self.by_name.get(S.norm(name)) or []
        if not cands:
            return None
        tm = scoring.team_norm(team) if team else None
        hit = [p for p in cands if tm and scoring.team_norm(p.get("player_team_id")) == tm]
        use = hit or cands
        try:
            overall = int(use[0].get("rank_ecr"))
        except (TypeError, ValueError):
            return None
        if overall < 1:
            return None
        prosr = use[0].get("pos_rank")
        return overall, (str(prosr) if prosr else None)


def _index_rows(rows):
    out = {}
    for e in rows or []:
        pid = e.get("player_id")
        if pid is None:
            continue
        pid = str(pid)
        prev = out.get(pid)
        if prev is None:
            out[pid] = e
            continue
        if (games_played(e.get("stats")) or 0) >= (games_played(prev.get("stats")) or 0):
            out[pid] = e
    return out


def _adp(stats, scoring):
    key = adp_key(scoring or {})
    v = (stats or {}).get(key)
    if not _num(v) or v <= 0 or v >= 999:
        return None
    return float(v)


def _owner(users, roster):
    u = users.get(roster.get("owner_id")) or {}
    md = u.get("metadata") or {}
    name = (md.get("team_name") or u.get("display_name") or u.get("username") or "").strip()
    return name or ("Team %s" % roster.get("roster_id"))


def _positional_ranks(scored):
    """scored: list of (pid, pos, pts) for players who played. Competition rank on 1-decimal points."""
    grouped = {}
    for pid, pos, pts in scored:
        if not pos or pts is None:
            continue
        grouped.setdefault(pos, []).append((round(float(pts), 1), str(pid)))
    out = {}
    for pos, items in grouped.items():
        items.sort(key=lambda t: (-t[0], t[1]))
        prev = None
        rank = 0
        for i, (pts, pid) in enumerate(items):
            if prev is None or pts != prev:
                rank = i + 1
                prev = pts
            out[pid] = "%s%d" % (pos, rank)
    return out


def _one(v):
    if v is None:
        return None
    v = round(float(v), 1)
    return 0.0 if v == 0 else v


def build(bundle, shared, players, drafts=None):
    """Return {rows, meta} for one league. drafts=None loads Sleeper history.

    Rows are the top 24 eligible players with a real surplus. Ineligible players are
    listed on meta only.
    """
    league = bundle["league"]
    season = str(league.get("season"))
    try:
        for_season = int(season) + 1
    except (TypeError, ValueError):
        for_season = None
    if drafts is None:
        drafts = load_history(league["league_id"])
    scoring = league.get("scoring_settings") or {}
    nteams = int(league.get("total_rosters") or 0)
    page = ros_page(scoring)
    ros_block = (shared.get("ros") or {}).get(page) if page else None
    ros = RosIndex((ros_block or {}).get("players"))
    notes = history_notes(drafts, season, league.get("settings") or {})
    if for_season is None:
        notes.append("The league season was not a year, so the two-year check was skipped and no one was marked ineligible.")
    if not _season_drafts(drafts, season):
        notes.append("No completed draft for %s, so keep costs were not guessed." % season)
        return {"rows": [], "meta": _meta(for_season, scoring, page if ros_block else None, [], notes)}
    if page and not ros_block:
        notes.append("FantasyPros rest-of-season ranks were unavailable, so the ROS column is a dash and value uses this year's scoring and the Sleeper projection only.")
    if not nteams:
        notes.append("League size was missing, so the round values were not guessed.")
        return {"rows": [], "meta": _meta(for_season, scoring, page if ros_block else None, [], notes)}

    proj_rows = _index_rows(shared.get("proj"))
    stat_rows = _index_rows(shared.get("stats"))
    proj_ppg = {}
    by_pos = {}
    adp_rows = []
    for pid, e in proj_rows.items():
        pos, _name, _team = _pos_name_team(pid, players, e, None)
        ppg = projection_ppg(scoring, e.get("stats"), pos)
        if ppg is None or not pos:
            continue
        proj_ppg[pid] = (pos, ppg)
        by_pos.setdefault(pos, []).append(ppg)
        adp = _adp(e.get("stats"), scoring)
        if adp is not None:
            adp_rows.append((adp, pid, pos, ppg))
    repl = {}
    for pos, n in DP.repl(nteams).items():
        vs = sorted(by_pos.get(pos) or [], reverse=True)
        repl[pos] = vs[n - 1] if len(vs) >= n else 0.0
    adp_rows.sort(key=lambda t: (t[0], t[1]))
    vor_order = []
    for _adp_v, pid, pos, ppg in adp_rows:
        if pos not in repl:
            continue
        vor_order.append(max(0.0, ppg - repl[pos]))
    # FantasyPros overall ROS is an offensive list. Defenses and kickers sit on their own
    # projection scale and are not used as the point value of an overall rank.
    curve = sorted((ppg for pos, ppg in proj_ppg.values() if pos in ("QB", "RB", "WR", "TE")), reverse=True)

    played = []
    for pid, e in stat_rows.items():
        pos, _name, _team = _pos_name_team(pid, players, proj_rows.get(pid), e)
        gp = games_played(e.get("stats"))
        pts = fantasy_points(scoring, e.get("stats"), pos)
        if gp and pts is not None and pos:
            played.append((pid, pos, pts))
    pranks = _positional_ranks(played)

    users = {u.get("user_id"): u for u in bundle.get("users") or [] if u.get("user_id")}
    held = {}
    for r in bundle.get("rosters") or []:
        for pid in roster_player_ids(r):
            held.setdefault(pid, r)

    rows = []
    ineligible = []
    for pid, roster in held.items():
        pos, name, team = _pos_name_team(pid, players, proj_rows.get(pid), stat_rows.get(pid))
        years = kept_seasons(drafts, pid)
        owner = _owner(users, roster)
        if for_season is not None and not eligible(years, for_season):
            ineligible.append({
                "name": name, "pos": pos or None, "owner": owner,
                "seasons": sorted(years),
            })
            continue
        rd = draft_round(drafts, pid, season)
        if rd == "missing":
            cost, how = None, None
        else:
            cost, how = keep_cost(None if rd is None else rd)
        if cost is None:
            continue
        st = (stat_rows.get(pid) or {}).get("stats")
        gp = games_played(st)
        pts = fantasy_points(scoring, st, pos) if st else None
        perf = (pts / gp) if (pts is not None and gp) else None
        proj = proj_ppg.get(pid)
        proj_only = proj[1] if proj else None
        hit = ros.lookup(name, team, pos)
        overall, prosr = hit if hit else (None, None)
        rank_ppg = curve[overall - 1] if overall and 1 <= overall <= len(curve) else None
        expected = blend_expected(perf, gp, proj_only, rank_ppg)
        value = surplus(expected, repl.get(pos), round_baseline(vor_order, nteams, cost))
        if value is None:
            continue
        shown_pts = _one(pts) if gp else None
        rows.append({
            "name": name,
            "pos": pos or None,
            "nfl": team or None,
            "owner": owner,
            "cost": int(cost),
            "how": how,
            "ros": overall,
            "prosr": prosr,
            "pts": shown_pts,
            "prank": pranks.get(pid) if shown_pts is not None else None,
            "value": _one(value),
        })
    rows.sort(key=lambda r: (
        -(r["value"] if r["value"] is not None else -10 ** 9),
        r["cost"],
        r["ros"] if isinstance(r.get("ros"), int) else 10 ** 9,
        -(r["pts"] if isinstance(r.get("pts"), (int, float)) else -10 ** 9),
        r["name"] or "",
    ))
    rows = rows[:TOP_N]
    for i, r in enumerate(rows, 1):
        r["rk"] = i
    ineligible.sort(key=lambda p: (p.get("name") or "", p.get("pos") or ""))
    return {"rows": rows, "meta": _meta(for_season, scoring, page if ros_block else None, ineligible, notes)}


def _scoring_label(scoring):
    rec = float((scoring or {}).get("rec") or 0)
    return {0.5: "Half PPR", 1.0: "PPR", 0.0: "Standard"}.get(rec, "%g PPR" % rec)


def _meta(for_season, scoring, page, ineligible, notes):
    return {
        "for_season": for_season,
        "scoring": _scoring_label(scoring),
        "ros_page": page,
        "ineligible": ineligible,
        "notes": notes,
    }


def load_history(league_id):
    """Completed drafts for this league and its previous_league_id chain, newest season last in the list order used by build (any order is fine)."""
    drafts = []
    seen = set()
    lid = str(league_id or "")
    hops = 0
    while lid and lid not in seen and lid != "0" and hops < 8:
        seen.add(lid)
        league = S.get_json("%s/v1/league/%s" % (S.SLEEPER, lid))
        season = str(league.get("season") or "")
        for d in S.get_json("%s/v1/league/%s/drafts" % (S.SLEEPER, lid)) or []:
            if d.get("status") != "complete":
                continue
            picks = S.get_json("%s/v1/draft/%s/picks" % (S.SLEEPER, d["draft_id"])) or []
            drafts.append({
                "season": str(d.get("season") or season),
                "rounds": (d.get("settings") or {}).get("rounds"),
                "picks": [{
                    "player_id": str(p["player_id"]),
                    "round": p.get("round"),
                    "is_keeper": bool(p.get("is_keeper")),
                    "roster_id": p.get("roster_id"),
                } for p in picks if p.get("player_id")],
            })
        lid = str(league.get("previous_league_id") or "")
        hops += 1
    return drafts


def load_shared(season):
    """Season stats, season projections, and both FantasyPros ROS pages. A missing ROS page is omitted, not fatal."""
    stats = S.sleeper_season_stats(season)
    proj = S.sleeper_season_projections(season)
    ros = {}
    for page in (ROS_HALF, ROS_PPR):
        try:
            ros[page] = S.fetch_fp_ros(page, season)
        except Exception as e:  # noqa: BLE001
            S.log("WARNING: FantasyPros %s unavailable: %s" % (page, e))
    return {"stats": stats, "proj": proj, "ros": ros}
