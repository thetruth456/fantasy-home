"""One-off generator for the Best League "Podcast: Power Rankings" tab (static snapshot).

Not run by the update workflow. Writes best-power-data.js (window.POWER.best), encrypted with tools/seal.py
(needs FH_REPORT_PASSWORD and the cryptography package).
Usage: python tools/power.py [sims]   (default 10000)
Model (also summarized on the page):
  each rostered player's weekly value = his own 2026 points per game (weight gp/(gp+G0)) + his Sleeper projection
  for that week (the rest). Each simulated season adds a persistent team-strength offset (see TAU0 / tau_k). Team weekly mean = best legal lineup from the
  CURRENT roster on those values, scaled so the league average matches real scoring. So production by players who
  are now hurt, traded or dropped no longer counts for anyone. A player counts as zero in a week when he has no
  projection (bye, or Sleeper has him out), when LONG_TERM in tools/podcast.py has him out, or (this week only)
  when Sleeper tags him Out/IR/PUP.
  This week (in progress): starters whose NFL game is final keep their real points; open slots use the best lineup
  from players who have not played yet. Weekly noise = the spread of real scores around each team's average (less the part
  future injuries now explain). Future weeks also draw random injuries per player (tools/injury.py); lineups re-form from the bench.
  Standings: wins (ties = half), then points for. Playoffs: 6 teams, seeds 1-2 bye, fixed bracket.
"""
import json, os, sys, math, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S
import seal
import podcast as PC
import draftprior as DP
import injury as INJ

LEAGUE = PC.LEAGUE
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.environ.get("FH_OUT_DIR") or ROOT, "best-power-data.js")
CACHE = os.environ.get("FH_CACHE_DIR") or os.path.join(ROOT, ".cache")
G0 = 7.0                  # player level: weight on his 2026 points per game = gp / (gp + G0), rest = Sleeper projection
                          # (1 game 13%, 4 games 36%, 7 games 50%, 13 games 65%: more projection early, more real points later)
# Bayesian team strength, calibrated on Best League 2022-2025 (48 team-seasons; reproduce with tools/power_calibrate.py):
# * Future injuries are simulated (tools/injury.py): every player can miss games at Sleeper-measured per-game rates, for a
#   drawn number of games, and the best lineup re-forms from the rest of the roster (plus a waiver fill-in). A team's
#   expected value = its lineup averaged over those injury paths, so depth counts; each simulated season then follows one path.
# * Prior = the draft. Post-draft value (tools/draftprior.py, injury-averaged) predicts real season PPG with slope BETA0 = 0.51
#   (se 0.25). What it misses has sd 8.0; after removing week-to-week noise and the injury paths' own spread (the sim adds
#   those explicitly) that leaves TAU0 = 4.6 pts/wk (trades, waivers, breakouts and busts).
# * Pre-draft = keeper surplus only, times PRE_SLOPE = 0.95 (how post-draft value tracked keeper surplus), plus the spread of
#   how drafts deviate from that (SIG_DRAFT = 4.68 pts/wk) and the injury spread (V_INJ = 5.18, its rosters are unknown) as
#   extra uncertainty.
# * In season, the roster model's edge over average is trusted more each week: beta_t = 1 - (1 - BETA0) * C / (C + t),
#   C = 7.6 fitted to how well the week-t model (injury-averaged) predicted rest-of-season PPG in 2022-2025 (0.51 -> 0.74
#   after week 7).
# * Every simulated season draws one persistent offset per team ~ N(0, tau_t), tau_t = 1/sqrt(1/TAU0^2 + t/sd^2)
#   (normal-normal update with weekly noise sd). Weekly noise is reduced to sqrt(sd^2 - injury week-to-week variance) so the
#   total weekly spread still matches real scores.
# (Without the injury model the same calibration gives BETA0 0.49, C 8.3, TAU0 5.1, SIG_DRAFT 4.75, slope 1.04.)
BETA0, BETA_C, SIG_DRAFT, PRE_SLOPE, V_INJ = 0.51, 7.6, 4.68, 0.95, 5.18
TAU0 = float(os.environ.get("FH_POWER_TAU0", "4.6"))
NPATH = int(os.environ.get("FH_POWER_PATHS", "2000"))   # injury paths per team (each simulated season picks one)


def beta_t(t):
    return 1.0 - (1.0 - BETA0) * BETA_C / (BETA_C + max(0, t))


def tau_pre():
    return math.sqrt(TAU0 ** 2 + V_INJ + (BETA0 * SIG_DRAFT) ** 2)


def inj_model(slots, cands, weeks, fa, rids, seed, n=None):
    """Per team: injury paths over weeks. Returns (expected lineup by week/team, paths by team, within-season variance)."""
    rng = random.Random(seed)
    E, PT, vw = {w: {} for w in weeks}, {}, []
    for r in rids:
        mean, paths = INJ.team_paths(slots, lineup, {w: cands[w][r] for w in weeks}, weeks, n or NPATH, rng, fa)
        for w in weeks:
            E[w][r] = mean[w]
        PT[r] = paths
        vw.append(INJ.path_var(paths, weeks)[0])
    return E, PT, (sum(vw) / len(vw) if vw else 0.0)


def blend_w(gp):
    return gp / (gp + G0) if gp and gp > 0 else 0.0


def tau_k(k, sd):
    return 1.0 / math.sqrt(1.0 / TAU0 ** 2 + k / sd ** 2) if TAU0 > 0 else 0.0
# Power score weights (0-100 scale each)
PW = dict(strength=0.40, playoff=0.30, first=0.15, title=0.15)
FLEX = {"FLEX": {"RB", "WR", "TE"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"}, "REC_FLEX": {"WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}}


def get(path):
    return S.get_json(S.SLEEPER + path)


def lineup(slots, cands):
    """Best lineup: fixed slots first, then flex slots. cands: list of (pts, pos, pid). Returns (total, [pid])."""
    pool = sorted(cands, reverse=True)
    used, tot, ids = set(), 0.0, []
    for s in sorted(slots, key=lambda s: s in FLEX):
        ok = FLEX.get(s, {s})
        for c in pool:
            if c[2] not in used and c[1] in ok:
                used.add(c[2]); tot += c[0]; ids.append(c[2])
                break
    return tot, ids


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def history(season, last, reg_end, nplay, slots, fpts, rids, M, pairs, sched, LT, P, sd, sims, prior):
    """Playoff / bye odds as they looked after each completed week t = 0 (preseason) .. last, using only what was known then:
    records and points for through week t, each team's roster going into week t+1 (Sleeper matchup data), player points per
    game through week t (blended with projection by games played), team-strength uncertainty tau_k(t), and Sleeper's week t+1 projection as each
    player's weekly rate for the rest of the season (zero on NFL byes). A player with no week t+1 projection is treated as
    back the next week unless LONG_TERM says the injury runs longer. Same scoring spread, tiebreaks and seeding as the main model."""
    games = {}
    for g in sched:
        games.setdefault(g["week"], set()).update((g["home"], g["away"]))
    pj = {w: {e["player_id"]: e for e in S.sleeper_projections(season, w, "regular") if e.get("player_id")} for w in range(1, last + 2)}
    stats = {w: S.sleeper_stats(season, w, "regular") for w in range(1, last + 1)}
    out = []
    post_dev, pre_dev, paths0, vw0 = prior
    for t in range(-1, last + 1):
        if t <= 0:  # -1 = before the draft (keepers only, rosters and so injuries unknown: in the noise), 0 = after the draft
            pre = t < 0
            out.append(dict(week=t, **sim_odds({w: {r: 100.0 + (BETA0 * PRE_SLOPE * pre_dev[r] if pre else BETA0 * post_dev[r]) for r in rids} for w in range(1, reg_end + 1)},
                                               {r: [0.0, 0.0] for r in rids}, rids, pairs, nplay, sd if pre else math.sqrt(sd ** 2 - vw0),
                                               tau_pre() if pre else TAU0, sims, 1000 + t, None if pre else paths0)))
            S.log("history %s done" % ("pre-draft" if t < 0 else "post-draft"))
            continue
        nxt = t + 1
        pg = {}
        for w in range(1, t + 1):
            for e in stats[w]:
                st_ = e.get("stats") or {}
                if e.get("player_id") and st_.get("gp"):
                    x = pg.setdefault(e["player_id"], [0, 0.0]); x[0] += 1; x[1] += fpts(st_)
        rec = {r: [0.0, 0.0] for r in rids}   # wins (ties .5), points for
        for w in range(1, t + 1):
            pts = {m["roster_id"]: m.get("points") or 0.0 for m in M[w]}
            for a, b in pairs(w):
                rec[a][1] += pts[a]; rec[b][1] += pts[b]
                if pts[a] > pts[b]: rec[a][0] += 1
                elif pts[b] > pts[a]: rec[b][0] += 1
                else: rec[a][0] += .5; rec[b][0] += .5
        roster = {m["roster_id"]: m.get("players") or [] for m in M[nxt]}

        def rate(pid):
            e = pj[nxt].get(pid)
            if not e:
                return None, None
            pr = max(0.0, fpts(e.get("stats") or {}))
            return pr, e.get("team") or (P.get(pid) or {}).get("team")

        def last_rate(pid):  # most recent positive projection up to week t+1 (for players out that week)
            for w in range(nxt, 0, -1):
                e = pj[w].get(pid)
                if e:
                    v = max(0.0, fpts(e.get("stats") or {}))
                    if v > 0:
                        return v, e.get("team")
            return 0.0, (P.get(pid) or {}).get("team")
        weeks = list(range(nxt, reg_end + 1))
        mu, cw = {w: {} for w in weeks}, {}
        for r in rids:
            vals = {}
            for pid in roster.get(r, []):
                pr, tm = rate(pid)
                out_now = not pr
                if out_now:
                    pr, tm = last_rate(pid)
                g = pg.get(pid)
                wt = blend_w(g[0]) if g and pr else 0.0
                v = wt * g[1] / g[0] + (1 - wt) * pr if wt else pr
                lt = LT.get(pid)
                vals[pid] = (v, tm, out_now, lt)
            for w in weeks:
                c = []
                for pid, (v, tm, out_now, lt) in vals.items():
                    if tm not in games.get(w, ()):
                        continue
                    if out_now and (w == nxt or (lt and (lt["back"] == "season" or w < lt["back"]["week"]))):
                        continue
                    c.append((v, (P.get(pid) or {}).get("position") or "", pid))
                cw.setdefault(w, {})[r] = c
                mu[w][r] = lineup(slots, c)[0]
        # future injuries from week t+2 (week t+1's injury report is known); waiver fill-ins from week t+1 projections
        rost = {p for v in roster.values() for p in v}
        fa = INJ.fa_floor([(max(0.0, fpts(e.get("stats") or {})), (P.get(pid) or {}).get("position") or "", pid) for pid, e in pj[nxt].items()], rost)
        fw = weeks[1:]
        E, PT, vw = inj_model(slots, cw, fw, fa, rids, 3000 + t, NPATH // 2)
        for w in fw:
            for r in rids:
                mu[w][r] = E[w][r]
        if t >= 1:  # scale to the league's real scoring level so far
            lg = sum(rec[r][1] for r in rids) / (t * len(rids))
            k = lg / (sum(mu[w][r] for w in weeks for r in rids) / (len(weeks) * len(rids)))
            for w in weeks:
                for r in rids:
                    mu[w][r] *= k
        else:
            k = 1.0
        b = beta_t(t)
        for w in weeks:  # shrink each team's edge over the league toward the prior's trust level
            lw = sum(mu[w].values()) / len(rids)
            for r in rids:
                mu[w][r] = lw + b * (mu[w][r] - lw)
        out.append(dict(week=t, **sim_odds(mu, rec, rids, pairs, nplay, math.sqrt(sd ** 2 - k * k * vw), tau_k(t, sd), sims, 1000 + t, PT, k)))
        S.log("history after week %d done" % t)
    return out


def sim_odds(mu, rec, rids, pairs, nplay, sd, tk, sims, seed, inj=None, k=1.0):
    """inj: {rid: [path {week: lineup change vs expected}]} (one path drawn per team per simulated season), scaled by k."""
    rng, irng = random.Random(seed), random.Random(seed + 77)   # separate stream for injury paths: same scoring draws as without
    weeks = sorted(mu)
    po, bye = {r: 0 for r in rids}, {r: 0 for r in rids}
    PR = {w: pairs(w) for w in weeks}
    for _ in range(sims):
        W = {r: rec[r][0] for r in rids}; F = {r: rec[r][1] for r in rids}
        off = {r: rng.gauss(0, tk) if tk else 0.0 for r in rids}
        ip = {r: inj[r][irng.randrange(len(inj[r]))] for r in rids} if inj else None
        for w in weeks:
            for a, b in PR[w]:
                da, db = (k * ip[a].get(w, 0.0), k * ip[b].get(w, 0.0)) if ip else (0.0, 0.0)
                x, y = rng.gauss(mu[w][a] + off[a] + da, sd), rng.gauss(mu[w][b] + off[b] + db, sd)
                F[a] += x; F[b] += y
                if x > y: W[a] += 1
                elif y > x: W[b] += 1
                else: W[a] += .5; W[b] += .5
        order = sorted(rids, key=lambda r: (-W[r], -F[r]))
        for i, r in enumerate(order[:nplay]):
            po[r] += 1
            if i < 2: bye[r] += 1
    return dict(po={r: round(po[r] / sims * 100, 1) for r in rids}, bye={r: round(bye[r] / sims * 100, 1) for r in rids})


def main():
    K = seal.Key()   # fail closed before any work: needs FH_REPORT_PASSWORD
    sims = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    L = get("/v1/league/%s" % LEAGUE)
    season, st = L["season"], L["settings"]
    last = int(st.get("last_scored_leg") or 0)
    cur = last + 1
    pstart = int(st.get("playoff_week_start") or 15)
    reg_end = pstart - 1
    nplay = int(st.get("playoff_teams") or 6)
    if nplay != 6 or st.get("playoff_round_type") not in (0, None):
        raise SystemExit("bracket model assumes 6 teams, one week per round")
    end = pstart + 2
    Sc = L["scoring_settings"]
    slots = [x for x in L["roster_positions"] if x not in ("BN", "IR", "TAXI")]

    def fpts(s):
        return sum(Sc[k] * v for k, v in s.items() if k in Sc and Sc[k] and isinstance(v, (int, float)))

    users = {u["user_id"]: u for u in get("/v1/league/%s/users" % LEAGUE)}
    rosters = get("/v1/league/%s/rosters" % LEAGUE)
    team = {}
    for r in rosters:
        u = users.get(r["owner_id"]) or {}
        team[r["roster_id"]] = dict(rid=r["roster_id"], user=u.get("display_name") or "Team %s" % r["roster_id"],
                                    name=((u.get("metadata") or {}).get("team_name") or u.get("display_name") or "Team %s" % r["roster_id"]).strip(),
                                    players=sorted(set((r.get("players") or []) + (r.get("reserve") or []))))
    rids = sorted(team)
    M = {w: get("/v1/league/%s/matchups/%s" % (LEAGUE, w)) for w in range(1, reg_end + 1)}

    def pairs(w):
        by = {}
        for m in M[w]:
            if m.get("matchup_id") is not None:
                by.setdefault(m["matchup_id"], []).append(m["roster_id"])
        out = [tuple(v) for v in by.values() if len(v) == 2]
        if len(out) != len(rids) // 2:
            raise SystemExit("week %d schedule is incomplete" % w)
        return out

    # ---------------- season so far
    rec = {r: dict(w=0, l=0, t=0, pf=0.0, pa=0.0, scores=[]) for r in rids}
    for w in range(1, last + 1):
        pts = {m["roster_id"]: m.get("points") or 0.0 for m in M[w]}
        for a, b in pairs(w):
            for x, y in ((a, b), (b, a)):
                rec[x]["pf"] += pts[x]; rec[x]["pa"] += pts[y]; rec[x]["scores"].append(pts[x])
                rec[x]["w" if pts[x] > pts[y] else "l" if pts[x] < pts[y] else "t"] += 1
    ppg = {r: rec[r]["pf"] / last for r in rids}
    lg_ppg = sum(ppg.values()) / len(rids)
    res = [s - ppg[r] for r in rids for s in rec[r]["scores"]]
    sd = math.sqrt(sum(x * x for x in res) / (len(res) - len(rids)))

    # ---------------- projections (current rosters, injuries applied)
    P = S.sleeper_players(CACHE)
    sched = S.sleeper_schedule(season)
    done = {(g["week"], tm) for g in sched if g.get("status") == "complete" for tm in (g["home"], g["away"])}
    live = {(g["week"], tm) for g in sched if g.get("status") == "in_progress" for tm in (g["home"], g["away"])}
    LT = PC.LONG_TERM
    proj = {}
    for w in range(cur, end + 1):
        proj[w] = {e["player_id"]: e for e in S.sleeper_projections(season, w, "regular") if e.get("player_id")}

    def ppts(pid, w):
        e = proj[w].get(pid)
        if not e:
            return 0.0
        lt = LT.get(pid)
        if lt and (lt["back"] == "season" or w < lt["back"]["week"]):
            return 0.0
        if w == cur and (P.get(pid) or {}).get("injury_status") in PC.RULED_OUT:
            return 0.0
        return max(0.0, fpts(e.get("stats") or {}))

    # 2026 points per game played, per player (league scoring)
    pg = {}
    for w in range(1, last + 1):
        for e in S.sleeper_stats(season, w, "regular"):
            st_ = e.get("stats") or {}
            if e.get("player_id") and st_.get("gp"):
                t = pg.setdefault(e["player_id"], [0, 0.0]); t[0] += 1; t[1] += fpts(st_)

    def val(pid, w):
        b = ppts(pid, w)
        if b <= 0:          # no projection (bye / Sleeper has him out), LONG_TERM out, or ruled out this week
            return 0.0
        g = pg.get(pid)
        wt = blend_w(g[0]) if g else 0.0
        return wt * max(0.0, g[1] / g[0]) + (1 - wt) * b if wt else b

    def pos(pid):
        return (P.get(pid) or {}).get("position") or ""

    def nfl(pid, w):
        e = proj[w].get(pid) or {}
        return e.get("team") or (P.get(pid) or {}).get("team")

    raw = {w: {} for w in range(cur, end + 1)}
    locked, rem = {}, {}
    mcur = {m["roster_id"]: m for m in M[cur]}
    allf = list(range(cur + 1, end + 1))
    cw = {w: {r: [c for c in ((val(p, w), pos(p), p) for p in team[r]["players"]) if c[0] > 0] for r in rids} for w in allf}
    rost = {p for r in rids for p in team[r]["players"]}
    fa = {w: INJ.fa_floor([(val(p, w), pos(p), p) for p in proj[w]], rost) for w in allf}
    healthy = {w: {r: lineup(slots, cw[w][r])[0] for r in rids} for w in allf}
    E, PT, vw = inj_model(slots, cw, allf, fa, rids, 20261102)
    for r in rids:
        for w in allf:
            raw[w][r] = E[w][r]
        # this week: lock starters whose game is final (or live), refill the rest from players yet to play
        m = mcur[r]
        sp = dict(zip(m.get("starters") or [], m.get("starters_points") or []))
        lk, free = 0.0, list(slots)
        for i, pid in enumerate(m.get("starters") or []):
            if pid and pid != "0" and ((cur, nfl(pid, cur)) in done or (cur, nfl(pid, cur)) in live):
                lk += sp.get(pid) or 0.0
                free.remove(slots[i])
        avail = [(val(p, cur), pos(p), p) for p in team[r]["players"]
                 if (cur, nfl(p, cur)) not in done and (cur, nfl(p, cur)) not in live]
        locked[r] = lk
        rem[r] = lineup(free, avail)[0]
        raw[cur][r] = lk + rem[r]
    fut = [w for w in range(cur + 1, reg_end + 1)]
    k = lg_ppg / (sum(raw[w][r] for w in fut for r in rids) / (len(fut) * len(rids)))
    mu = {w: {} for w in range(cur, end + 1)}
    for w in range(cur, end + 1):
        for r in rids:
            mu[w][r] = k * raw[w][r]
    # Bayesian shrink of each team's edge (see BETA0 / beta_t): future weeks toward that week's league mean
    B = beta_t(last)
    raw_str = {r: sum(mu[w][r] for w in fut) / len(fut) for r in rids}
    for w in range(cur + 1, end + 1):
        lw = sum(mu[w].values()) / len(rids)
        for r in rids:
            mu[w][r] = lw + B * (mu[w][r] - lw)
    lg_f = sum(raw_str.values()) / len(rids)
    frac = {}
    for r in rids:  # in-progress week: real points already banked, less noise left; the rest shrunk like the team's future weeks
        rs = k * rem[r] * ((lg_f + B * (raw_str[r] - lg_f)) / raw_str[r] if raw_str[r] else 1.0)
        mu[cur][r] = locked[r] + rs
        frac[r] = rs / mu[cur][r] if mu[cur][r] else 1.0
    strength = {r: sum(mu[w][r] for w in fut) / len(fut) for r in rids}
    inj_cost = {r: k * sum(healthy[w][r] - E[w][r] for w in fut) / len(fut) for r in rids}
    inj_sd = {r: k * math.sqrt(INJ.path_var(PT[r], fut)[1]) for r in rids}
    sd_e = math.sqrt(sd ** 2 - k * k * vw)   # weekly noise left once injuries are simulated explicitly
    ap = {r: 100 * sum(phi((mu[w][r] - mu[w][o]) / (sd * math.sqrt(2))) for w in fut for o in rids if o != r) / (len(fut) * (len(rids) - 1)) for r in rids}

    # ---------------- schedule left
    sched_left = {r: [] for r in rids}
    for w in range(cur, reg_end + 1):
        for a, b in pairs(w):
            sched_left[a].append((w, b)); sched_left[b].append((w, a))

    # ---------------- Monte Carlo
    PR = {w: pairs(w) for w in range(cur, reg_end + 1)}
    TK = tau_k(last, sd)

    def simulate(rng, pairfn, n, playoffs):
        irng = random.Random(rng.random())   # injury-path picks on their own stream
        seedc = {r: [0] * nplay for r in rids}
        finc = {r: [0] * len(rids) for r in rids}
        title, final, wins_sum = {r: 0 for r in rids}, {r: 0 for r in rids}, {r: 0.0 for r in rids}
        for _ in range(n):
            W = {r: rec[r]["w"] + 0.5 * rec[r]["t"] for r in rids}
            F = {r: rec[r]["pf"] for r in rids}
            off = {r: rng.gauss(0, TK) if TK else 0.0 for r in rids}
            ip = {r: PT[r][irng.randrange(len(PT[r]))] for r in rids}
            for w in range(cur, reg_end + 1):
                sc = {r: rng.gauss(mu[w][r] + (off[r] + k * ip[r][w] if w > cur else frac[r] * off[r]), sd_e * (math.sqrt(frac[r]) if w == cur else 1)) for r in rids}
                for a, b in pairfn(w):
                    F[a] += sc[a]; F[b] += sc[b]
                    if sc[a] > sc[b]: W[a] += 1
                    elif sc[b] > sc[a]: W[b] += 1
                    else: W[a] += .5; W[b] += .5
            order = sorted(rids, key=lambda r: (-W[r], -F[r]))
            for i, r in enumerate(order):
                finc[r][i] += 1; wins_sum[r] += W[r]
                if i < nplay: seedc[r][i] += 1
            if not playoffs:
                continue
            s_ = order[:nplay]

            def g(a, b, w):
                x, y = rng.gauss(mu[w][a] + off[a] + k * ip[a][w], sd_e), rng.gauss(mu[w][b] + off[b] + k * ip[b][w], sd_e)
                return a if x >= y else b
            # Sleeper's winners bracket (fixed, no reseeding): 4v5 and 3v6, then 1 v (4/5) and 2 v (3/6)
            q1, q2 = g(s_[3], s_[4], pstart), g(s_[2], s_[5], pstart)
            f1, f2 = g(s_[0], q1, pstart + 1), g(s_[1], q2, pstart + 1)
            final[f1] += 1; final[f2] += 1
            title[g(f1, f2, pstart + 2)] += 1
        return seedc, finc, title, final, wins_sum
    seedc, finc, title, final, wins_sum = simulate(random.Random(20261031), lambda w: PR[w], sims, True)

    # same model on a neutral schedule (random opponents every remaining week) -> schedule effect
    nrng = random.Random(7)

    def rand_pairs(w):
        o = rids[:]; nrng.shuffle(o)
        return [(o[i], o[i + 1]) for i in range(0, len(o), 2)]
    nseed = simulate(random.Random(20261101), rand_pairs, sims, False)[0]
    rows = []
    for r in rids:
        t, R = team[r], rec[r]
        po = sum(seedc[r]) / sims * 100
        rows.append(dict(rid=r, name=t["name"], user=t["user"], w=R["w"], l=R["l"], t=R["t"], pf=round(R["pf"], 1), pa=round(R["pa"], 1),
                         ppg=round(ppg[r], 1), proj=round(sum(lineup(slots, [(ppts(p, w), pos(p), p) for p in team[r]["players"]])[0] for w in fut) / len(fut), 1), strength=round(strength[r], 1), ap=round(ap[r], 1),
                         pwins=round(wins_sum[r] / sims, 2), games=reg_end,
                         playoff=round(po, 1), first=round(seedc[r][0] / sims * 100, 1), bye=round((seedc[r][0] + seedc[r][1]) / sims * 100, 1),
                         final=round(final[r] / sims * 100, 1),
                         po_neutral=round(sum(nseed[r]) / sims * 100, 1), first_neutral=round(nseed[r][0] / sims * 100, 1), title=round(title[r] / sims * 100, 1),
                         seeds=[round(c / sims * 100, 1) for c in seedc[r]], finish=[round(c / sims * 100, 1) for c in finc[r]],
                         avgfin=round(sum((i + 1) * c for i, c in enumerate(finc[r])) / sims, 2),
                         wk=dict(locked=round(locked[r], 1), mu=round(mu[cur][r], 1)),
                         left=[dict(week=w, opp=o, mu=round(mu[w][o], 1)) for w, o in sched_left[r]]))
    for x in rows:
        x["power"] = round(PW["strength"] * x["ap"] + PW["playoff"] * x["playoff"] + PW["first"] * x["first"] + PW["title"] * x["title"], 1)
        opp = [l["mu"] for l in x["left"]]
        x["sos"] = round(sum(opp) / len(opp), 1)
        ow = sum(rec[l["opp"]]["w"] + .5 * rec[l["opp"]]["t"] for l in x["left"])
        x["opp_w"], x["opp_l"] = ow, sum(last for _ in x["left"]) - ow
    rows.sort(key=lambda x: (-x["power"], -x["ap"]))
    for i, x in enumerate(rows):
        x["rank"] = i + 1
    for i, x in enumerate(sorted(rows, key=lambda x: x["sos"])):
        x["sos_rank"] = i + 1
    for i, x in enumerate(sorted(rows, key=lambda x: -x["strength"])):
        x["str_rank"] = i + 1
    # draft-value prior (keepers, post-draft value)
    drafts = get("/v1/league/%s/drafts" % LEAGUE)
    picks = get("/v1/draft/%s/picks" % drafts[0]["draft_id"])
    sproj = DP.season_projections(season)
    post_dev, pre_dev, keep = DP.values(sproj, picks, slots, fpts, lineup)
    PV = DP.player_values(sproj, fpts)
    dc = DP.rosters(PV, picks)
    allw = list(range(1, reg_end + 1))
    E0, PT0, vw0 = inj_model(slots, {w: dc for w in allw}, allw, INJ.fa_floor([(q["v"], q["pos"], pid) for pid, q in PV.items()], {p["player_id"] for p in picks}), rids, 999)
    e0 = {r: sum(E0[w][r] for w in allw) / len(allw) for r in rids}
    m0 = sum(e0.values()) / len(rids)
    inj_dev = {r: e0[r] - m0 for r in rids}
    for x in rows:
        x["keepers"] = keep.get(x["rid"], [])
        x["draft_dev"], x["keeper_dev"], x["draft_inj_dev"] = round(post_dev[x["rid"]], 1), round(pre_dev[x["rid"]], 1), round(inj_dev[x["rid"]], 1)
        x["inj_cost"], x["inj_sd"] = round(inj_cost[x["rid"]], 1), round(inj_sd[x["rid"]], 1)
    hist = [] if os.environ.get("FH_POWER_NO_HISTORY") else history(season, last, reg_end, nplay, slots, fpts, rids, M, pairs, sched, LT, P, sd, sims, (inj_dev, pre_dev, PT0, vw0))
    by_r = {x["rid"]: x for x in rows}
    hist.append(dict(week=cur, live=True, po={r: by_r[r]["playoff"] for r in rids}, bye={r: by_r[r]["bye"] for r in rids}))
    now = datetime.datetime.now(datetime.timezone.utc)
    data = dict(hist=hist, season=season, asof=now.strftime("%Y-%m-%dT%H:%M:%SZ"), last=last, cur=cur, reg_end=reg_end, pstart=pstart, end=end,
                sims=sims, sd=round(sd, 1), k=round(k, 3), g0=G0, w_now=round(blend_w(last), 2), tau0=TAU0, tau_now=round(TK, 1), tau_pre=round(tau_pre(), 1), beta0=BETA0, sd_noise=round(sd_e, 1), npath=NPATH, inj_hazard=INJ.HAZARD, beta_now=round(B, 2), draft_type=drafts[0].get("type"), pw=PW, nplay=nplay,
                locked_games=sorted({tm for (w, tm) in done | live if w == cur}),
                teams=rows)
    K.write(OUT, "POWER.best", data)   # encrypted (tools/seal.py); fails without FH_REPORT_PASSWORD
    S.log("wrote %s (weeks %d-%d left, %d sims, sd %.1f -> %.1f with injuries, k %.3f, tau %.1f)" % (OUT, cur, reg_end, sims, sd, sd_e, k, TK))


if __name__ == "__main__":
    main()
