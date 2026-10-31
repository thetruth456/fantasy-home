"""One-off generator for the Best League "Podcast: Power Rankings" tab (static snapshot).

Not run by the update workflow. Writes best-power-data.js (window.POWER.best). Stdlib only.
Usage: python tools/power.py [sims]   (default 10000)
Model (also summarized on the page):
  weekly mean = 50% season points per game (weeks scored so far) + 50% Sleeper's projection for the team's best
  legal lineup from its current roster that week (projections scaled so the league average matches real scoring).
  Long-term injuries come from LONG_TERM in tools/podcast.py; this week's Out/IR/PUP tags count as zero.
  This week (in progress): starters whose NFL game is final keep their real points; open slots use the best lineup
  from players who have not played yet. Weekly noise = the spread of real scores around each team's average.
  Standings: wins (ties = half), then points for. Playoffs: 6 teams, seeds 1-2 bye, fixed bracket.
"""
import json, os, sys, math, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S
import podcast as PC

LEAGUE = PC.LEAGUE
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.environ.get("FH_OUT_DIR") or ROOT, "best-power-data.js")
CACHE = os.environ.get("FH_CACHE_DIR") or os.path.join(ROOT, ".cache")
W_SEASON = 0.5            # weight on season points per game (rest = roster projection)
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


def main():
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

    def pos(pid):
        return (P.get(pid) or {}).get("position") or ""

    def nfl(pid, w):
        e = proj[w].get(pid) or {}
        return e.get("team") or (P.get(pid) or {}).get("team")

    raw = {w: {} for w in range(cur, end + 1)}
    locked, rem = {}, {}
    mcur = {m["roster_id"]: m for m in M[cur]}
    for r in rids:
        for w in range(cur + 1, end + 1):
            raw[w][r] = lineup(slots, [(ppts(p, w), pos(p), p) for p in team[r]["players"]])[0]
        # this week: lock starters whose game is final (or live), refill the rest from players yet to play
        m = mcur[r]
        sp = dict(zip(m.get("starters") or [], m.get("starters_points") or []))
        lk, free = 0.0, list(slots)
        for i, pid in enumerate(m.get("starters") or []):
            if pid and pid != "0" and ((cur, nfl(pid, cur)) in done or (cur, nfl(pid, cur)) in live):
                lk += sp.get(pid) or 0.0
                free.remove(slots[i])
        avail = [(ppts(p, cur), pos(p), p) for p in team[r]["players"]
                 if (cur, nfl(p, cur)) not in done and (cur, nfl(p, cur)) not in live]
        locked[r] = lk
        rem[r] = lineup(free, avail)[0]
        raw[cur][r] = lk + rem[r]
    fut = [w for w in range(cur + 1, reg_end + 1)]
    k = lg_ppg / (sum(raw[w][r] for w in fut for r in rids) / (len(fut) * len(rids)))
    mu = {w: {} for w in range(cur, end + 1)}
    for w in range(cur, end + 1):
        for r in rids:
            mu[w][r] = W_SEASON * ppg[r] + (1 - W_SEASON) * k * raw[w][r]
    sdw = {w: sd for w in mu}
    frac = {}
    for r in rids:  # in-progress week: real points already banked, less noise left
        full = mu[cur][r]
        mu[cur][r] = max(locked[r], full)
        tot = locked[r] + rem[r]
        frac[r] = rem[r] / tot if tot else 1.0
    strength = {r: sum(mu[w][r] for w in fut) / len(fut) for r in rids}
    ap = {r: 100 * sum(phi((mu[w][r] - mu[w][o]) / (sd * math.sqrt(2))) for w in fut for o in rids if o != r) / (len(fut) * (len(rids) - 1)) for r in rids}

    # ---------------- schedule left
    sched_left = {r: [] for r in rids}
    for w in range(cur, reg_end + 1):
        for a, b in pairs(w):
            sched_left[a].append((w, b)); sched_left[b].append((w, a))

    # ---------------- Monte Carlo
    rng = random.Random(20261031)
    seedc = {r: [0] * nplay for r in rids}
    finc = {r: [0] * len(rids) for r in rids}
    title, final, wins_sum = {r: 0 for r in rids}, {r: 0 for r in rids}, {r: 0.0 for r in rids}
    PR = {w: pairs(w) for w in range(cur, reg_end + 1)}
    for _ in range(sims):
        W = {r: rec[r]["w"] + 0.5 * rec[r]["t"] for r in rids}
        F = {r: rec[r]["pf"] for r in rids}
        for w in range(cur, reg_end + 1):
            sc = {r: rng.gauss(mu[w][r], sd * (math.sqrt(frac[r]) if w == cur else 1)) for r in rids}
            for a, b in PR[w]:
                F[a] += sc[a]; F[b] += sc[b]
                if sc[a] > sc[b]: W[a] += 1
                elif sc[b] > sc[a]: W[b] += 1
                else: W[a] += .5; W[b] += .5
        order = sorted(rids, key=lambda r: (-W[r], -F[r]))
        for i, r in enumerate(order):
            finc[r][i] += 1; wins_sum[r] += W[r]
            if i < nplay: seedc[r][i] += 1
        s = order[:nplay]

        def g(a, b, w):
            x, y = rng.gauss(mu[w][a], sd), rng.gauss(mu[w][b], sd)
            return a if x >= y else b
        q1, q2 = g(s[3], s[4], pstart), g(s[2], s[5], pstart)
        f1, f2 = g(s[0], q1, pstart + 1), g(s[1], q2, pstart + 1)
        final[f1] += 1; final[f2] += 1
        title[g(f1, f2, pstart + 2)] += 1
    rows = []
    for r in rids:
        t, R = team[r], rec[r]
        po = sum(seedc[r]) / sims * 100
        rows.append(dict(rid=r, name=t["name"], user=t["user"], w=R["w"], l=R["l"], t=R["t"], pf=round(R["pf"], 1), pa=round(R["pa"], 1),
                         ppg=round(ppg[r], 1), proj=round(k * sum(raw[w][r] for w in fut) / len(fut), 1), strength=round(strength[r], 1), ap=round(ap[r], 1),
                         pwins=round(wins_sum[r] / sims, 2), games=reg_end,
                         playoff=round(po, 1), first=round(seedc[r][0] / sims * 100, 1), bye=round((seedc[r][0] + seedc[r][1]) / sims * 100, 1),
                         final=round(final[r] / sims * 100, 1), title=round(title[r] / sims * 100, 1),
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
    now = datetime.datetime.now(datetime.timezone.utc)
    data = dict(season=season, asof=now.strftime("%Y-%m-%dT%H:%M:%SZ"), last=last, cur=cur, reg_end=reg_end, pstart=pstart, end=end,
                sims=sims, sd=round(sd, 1), k=round(k, 3), w_season=W_SEASON, pw=PW, nplay=nplay,
                locked_games=sorted({tm for (w, tm) in done | live if w == cur}),
                teams=rows)
    with open(OUT, "w") as f:
        f.write("/* Static snapshot generated by tools/power.py. The update workflow does not touch this file. */\n")
        f.write("window.POWER=window.POWER||{};\nwindow.POWER.best=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n")
    S.log("wrote %s (weeks %d-%d left, %d sims, sd %.1f, k %.3f)" % (OUT, cur, reg_end, sims, sd, k))


if __name__ == "__main__":
    main()
