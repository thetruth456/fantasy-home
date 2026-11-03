"""Calibrate the Bayesian constants in tools/power.py from past Best League seasons (stdlib only; prints, writes nothing).

Usage: python tools/power_calibrate.py
Follows previous_league_id back from the current league; for every completed earlier season it measures:
  BETA0      slope of real regular-season PPG (vs league mean) on post-draft value (tools/draftprior.py)
  TAU0       what that leaves unexplained, minus the noise of a 14-week average (weekly sd 22.9)
  pre slope  post-draft value on keeper surplus (seasons with keepers), and SIG_DRAFT = the scatter around it
  beta_t     slope of rest-of-season PPG on the week-t roster model (projection + points per game, G0 blend), and
  C          the best fit of beta_t = 1 - (1 - BETA0) * C / (C + t) (weighted by 1/se^2, t = 0..12)
Everything is printed twice: "healthy" = best lineup with everyone available (the pre-injury-model version), and
"injury" = the same lineup averaged over NP simulated future injury paths (tools/injury.py), which is what power.py uses now.
With injuries simulated explicitly, their randomness no longer belongs in TAU0 or the weekly noise, so the injury TAU0 is
sqrt(s^2 - (22.9^2 - v_within) / 14 - V_season) (v_within / V_season: within-season / season-average variance of the injury paths).
"""
import math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S
import draftprior as DP
import injury as INJ
from power import lineup, G0, LEAGUE

SIG = 22.9
NP = int(os.environ.get("FH_CAL_PATHS", "300"))


def get(path):
    return S.get_json(S.SLEEPER + path)


def reg(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = [y - my - b * (x - mx) for x, y in zip(xs, ys)]
    s = math.sqrt(sum(e * e for e in res) / (len(xs) - 2))
    return b, s, s / math.sqrt(sxx)


def main():
    lid = get("/v1/league/%s" % LEAGUE).get("previous_league_id")
    rng = __import__("random").Random(5)
    X, XI, Y, KP, KX, KXI, BT, BTI, VW, VS = [], [], [], [], [], [], {}, {}, [], []
    while lid and lid != "0":
        L = get("/v1/league/%s" % lid)
        season, Sc = L["season"], L["scoring_settings"]
        slots = [x for x in L["roster_positions"] if x not in ("BN", "IR", "TAXI")]
        fp = lambda s: sum(Sc[k] * v for k, v in s.items() if k in Sc and Sc[k] and isinstance(v, (int, float)))
        d = get("/v1/league/%s/drafts" % lid)[0]
        picks = get("/v1/draft/%s/picks" % d["draft_id"])
        proj = DP.season_projections(season)
        post, pre, keep = DP.values(proj, picks, slots, fp, lineup)
        rids = sorted(post)
        reg_end = int(L["settings"].get("playoff_week_start") or 15) - 1
        PV = DP.player_values(proj, fp)
        dc = DP.rosters(PV, picks)
        fa0 = INJ.fa_floor([(p["v"], p["pos"], pid) for pid, p in PV.items()], {p["player_id"] for p in picks})
        allw = list(range(1, reg_end + 1))
        pinj = {}
        for r in rids:
            mean, paths = INJ.team_paths(slots, lineup, {w: dc[r] for w in allw}, allw, NP, rng, fa0)
            pinj[r] = sum(mean.values()) / len(allw)
            a, b = INJ.path_var(paths, allw); VW.append(a); VS.append(b)
        mpi = st.mean(pinj.values())
        pinj = {r: pinj[r] - mpi for r in rids}
        M = {w: get("/v1/league/%s/matchups/%d" % (lid, w)) for w in range(1, reg_end + 1)}
        sc = {w: {m["roster_id"]: m.get("points") or 0.0 for m in M[w]} for w in M}
        PJ = {w: {e["player_id"]: e for e in S.sleeper_projections(season, w, "regular") if e.get("player_id")} for w in M}
        STS = {w: S.sleeper_stats(season, w, "regular") for w in M}
        pos = {}
        for w in PJ:
            for pid, e in PJ[w].items():
                pos.setdefault(pid, e.get("position") or (e.get("player") or {}).get("position") or "")
        for t in range(0, reg_end):
            ros = {r: sum(sc[w][r] for w in range(t + 1, reg_end + 1)) / (reg_end - t) for r in rids}
            if t == 0:
                D, DI = post, pinj
            else:
                pg = {}
                for w in range(1, t + 1):
                    for e in STS[w]:
                        s_ = e.get("stats") or {}
                        if e.get("player_id") and s_.get("gp"):
                            x = pg.setdefault(e["player_id"], [0, 0.0]); x[0] += 1; x[1] += fp(s_)
                roster = {m["roster_id"]: m.get("players") or [] for m in M[t + 1]}
                D, DI = {}, {}
                fw = list(range(t + 2, reg_end + 1))
                fa = INJ.fa_floor([(fp(e.get("stats") or {}), pos.get(pid, ""), pid) for pid, e in PJ[t + 1].items()], {p for v in roster.values() for p in v})
                for r in rids:
                    c = []
                    for pid in roster[r]:
                        pr = 0.0
                        for w in range(t + 1, 0, -1):
                            e = PJ[w].get(pid)
                            if e and fp(e.get("stats") or {}) > 0:
                                pr = fp(e["stats"]); break
                        if pr <= 0:
                            continue
                        g = pg.get(pid); wt = g[0] / (g[0] + G0) if g else 0.0
                        c.append((wt * g[1] / g[0] + (1 - wt) * pr if wt else pr, pos.get(pid, ""), pid))
                    D[r] = lineup(slots, c)[0]
                    mean = INJ.team_paths(slots, lineup, {w: c for w in fw}, fw, NP, rng, fa)[0] if fw else {}
                    DI[r] = (D[r] + sum(mean.values())) / (1 + len(fw))
            mD, mR, mI = st.mean(D.values()), st.mean(ros.values()), st.mean(DI.values())
            BT.setdefault(t, ([], [])); BTI.setdefault(t, ([], []))
            BT[t][0].extend(D[r] - mD for r in rids); BT[t][1].extend(ros[r] - mR for r in rids)
            BTI[t][0].extend(DI[r] - mI for r in rids); BTI[t][1].extend(ros[r] - mR for r in rids)
        ros_full = {r: sum(sc[w][r] for w in M) / len(M) for r in rids}
        mY = st.mean(ros_full.values())
        for r in rids:
            X.append(post[r]); XI.append(pinj[r]); Y.append(ros_full[r] - mY)
            if any(keep.values()):
                KP.append(pre[r]); KX.append(post[r]); KXI.append(pinj[r])
        print("%s: %d keepers, post-draft value sd %.2f, keeper surplus sd %.2f" % (season, sum(len(v) for v in keep.values()),
              st.stdev(post.values()), st.stdev(pre.values())))
        lid = L.get("previous_league_id")
    vw, vs = st.mean(VW), st.mean(VS)
    print("injury paths: within-season weekly variance %.1f (sd %.1f), season-average variance %.2f (sd %.2f)" % (vw, math.sqrt(vw), vs, math.sqrt(vs)))
    for lab, XX, KK, B in (("healthy", X, KX, BT), ("injury", XI, KXI, BTI)):
        b0, s0, se0 = reg(XX, Y)
        tau0 = math.sqrt(max(0.0, s0 ** 2 - SIG ** 2 / 14))
        if lab == "injury":
            tau0 = math.sqrt(max(0.0, s0 ** 2 - (SIG ** 2 - vw) / 14 - vs))
        bp, sp, _ = reg(KP, KK)
        print("[%s] BETA0 %.2f (se %.2f), residual %.2f, TAU0 %.2f, n %d" % (lab, b0, se0, s0, tau0, len(Y)))
        print("[%s] post-draft on keeper surplus: slope %.2f, SIG_DRAFT %.2f" % (lab, bp, sp))
        bt = {t: reg(*B[t]) for t in B}
        print("[%s] beta_t: %s" % (lab, " ".join("%d:%.2f(%.2f)" % (t, bt[t][0], bt[t][2]) for t in sorted(bt))))
        C = min((sum(((1 - (1 - b0) * c / (c + t)) - bt[t][0]) ** 2 / bt[t][2] ** 2 for t in bt if t <= 12), c) for c in [x / 10 for x in range(1, 400)])[1]
        print("[%s] C %.1f -> beta after week 7 %.2f" % (lab, C, 1 - (1 - b0) * C / (C + 7)))

if __name__ == "__main__":
    main()
