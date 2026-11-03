"""Calibrate the Bayesian constants in tools/power.py from past seasons of each league (stdlib only).

Usage: python tools/power_calibrate.py [--write]
For every league in tools/leagues.py, follows previous_league_id back and, for every completed earlier season, measures
(with that season's own scoring, lineup slots, league size and ADP format):
  BETA0      slope of real regular-season PPG (vs league mean) on post-draft value (tools/draftprior.py)
  TAU0       what that leaves unexplained, minus the noise of a season average (weekly sd measured from that season's scores)
  pre slope  post-draft value on keeper surplus (seasons with keepers), and SIG_DRAFT = the scatter around it
  beta_t     slope of rest-of-season PPG on the week-t roster model (projection + points per game, G0 blend), and
  C          the best fit of beta_t = 1 - (1 - BETA0) * C / (C + t) (weighted by 1/se^2, t = 0..12)
Fits are printed per league and pooled over all leagues. "healthy" = best lineup with everyone available, "injury" = the
same lineup averaged over NP simulated future injury paths (tools/injury.py), which is what power.py uses.
With injuries simulated explicitly, their randomness no longer belongs in TAU0 or the weekly noise, so the injury TAU0 is
sqrt(s^2 - (sd^2 - v_within) / weeks - V_season) (v_within / V_season: within-season / season-average variance of the paths).
--write saves the "injury" fits to tools/power_cal.json: a league with at least MIN_OWN team-seasons of history uses its own
fit, the others the pooled one (power.py reads the file).
"""
import json, math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S
import draftprior as DP
import injury as INJ
import leagues as LG
from power import lineup, G0

NP = int(os.environ.get("FH_CAL_PATHS", "300"))
MIN_OWN = 36
CAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "power_cal.json")


def get(path):
    return S.get_json(S.SLEEPER + path)


def reg(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = [y - my - b * (x - mx) for x, y in zip(xs, ys)]
    s = math.sqrt(sum(e * e for e in res) / (len(xs) - 2))
    return b, s, s / math.sqrt(sxx)


def new_data():
    return dict(X=[], XI=[], Y=[], KP=[], KX=[], KXI=[], BT={}, BTI={}, VW=[], VS=[], NOISE=[], seasons=[])


def merge(a, b):
    for k in ("X", "XI", "Y", "KP", "KX", "KXI", "VW", "VS", "NOISE", "seasons"):
        a[k].extend(b[k])
    for k in ("BT", "BTI"):
        for t, (u, v) in b[k].items():
            a[k].setdefault(t, ([], [])); a[k][t][0].extend(u); a[k][t][1].extend(v)


def collect(league_id, rng):
    """All completed earlier seasons of one league (previous_league_id chain)."""
    DD = new_data()
    X, XI, Y, KP, KX, KXI, BT, BTI, VW, VS = (DD[k] for k in ("X", "XI", "Y", "KP", "KX", "KXI", "BT", "BTI", "VW", "VS"))
    lid = get("/v1/league/%s" % league_id).get("previous_league_id")
    while lid and lid != "0":
        L = get("/v1/league/%s" % lid)
        season, Sc = L["season"], L["scoring_settings"]
        slots = [x for x in L["roster_positions"] if x not in ("BN", "IR", "TAXI")]
        fp = lambda s: sum(Sc[k] * v for k, v in s.items() if k in Sc and Sc[k] and isinstance(v, (int, float)))
        d = get("/v1/league/%s/drafts" % lid)[0]
        picks = get("/v1/draft/%s/picks" % d["draft_id"])
        proj = DP.season_projections(season)
        rids = sorted({p["roster_id"] for p in picks})
        adp = LG.adp_key(Sc)
        post, pre, keep = DP.values(proj, picks, slots, fp, lineup, adp, len(rids))
        reg_end = int(L["settings"].get("playoff_week_start") or 15) - 1
        PV = DP.player_values(proj, fp, adp)
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
        tm = {r: st.mean(sc[w][r] for w in M) for r in rids}   # weekly noise: scores around each team's season average
        DD["NOISE"].append((sum((sc[w][r] - tm[r]) ** 2 for w in M for r in rids) / (len(M) * len(rids) - len(rids)), len(M), len(rids)))
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
        print("  %s %s: %d teams, %d keepers, post-draft value sd %.2f, keeper surplus sd %.2f, weekly sd %.1f" % (L["name"], season, len(rids),
              sum(len(v) for v in keep.values()), st.stdev(post.values()), st.stdev(pre.values()), math.sqrt(DD["NOISE"][-1][0])))
        DD["seasons"].append("%s %s" % (L["name"], season))
        lid = L.get("previous_league_id")
    return DD


def fit(D, label):
    """Fits on one data set; returns the "injury" constants (None when there is no history)."""
    if len(D["Y"]) < 8:
        print("[%s] no usable history" % label)
        return None
    vw, vs = st.mean(D["VW"]), st.mean(D["VS"])
    sig2 = sum(v * n for v, _, n in D["NOISE"]) / sum(n for _, _, n in D["NOISE"])   # team-weighted weekly noise variance
    wks = st.mean(w for _, w, _ in D["NOISE"])
    print("[%s] %d team-seasons (%s); weekly sd %.1f over %.0f weeks; injury paths: within-season var %.1f, season-average var %.2f" % (
        label, len(D["Y"]), ", ".join(D["seasons"]), math.sqrt(sig2), wks, vw, vs))
    out = None
    for lab, XX, KK, B in (("healthy", D["X"], D["KX"], D["BT"]), ("injury", D["XI"], D["KXI"], D["BTI"])):
        b0, s0, se0 = reg(XX, D["Y"])
        tau0 = math.sqrt(max(0.0, s0 ** 2 - sig2 / wks))
        if lab == "injury":
            tau0 = math.sqrt(max(0.0, s0 ** 2 - (sig2 - vw) / wks - vs))
        kp = reg(D["KP"], KK) if len(D["KP"]) >= 8 else None
        print("  [%s] BETA0 %.2f (se %.2f), residual %.2f, TAU0 %.2f" % (lab, b0, se0, s0, tau0))
        if kp:
            print("  [%s] post-draft on keeper surplus: slope %.2f, SIG_DRAFT %.2f (%d team-seasons with keepers)" % (lab, kp[0], kp[1], len(D["KP"])))
        bt = {t: reg(*B[t]) for t in B}
        print("  [%s] beta_t: %s" % (lab, " ".join("%d:%.2f(%.2f)" % (t, bt[t][0], bt[t][2]) for t in sorted(bt))))
        C = min((sum(((1 - (1 - b0) * c / (c + t)) - bt[t][0]) ** 2 / bt[t][2] ** 2 for t in bt if t <= 12), c) for c in [x / 10 for x in range(1, 400)])[1]
        print("  [%s] C %.1f -> beta after week 7 %.2f" % (lab, C, 1 - (1 - b0) * C / (C + 7)))
        if lab == "injury":
            out = dict(beta0=round(b0, 2), beta0_se=round(se0, 2), beta_c=round(C, 1), tau0=round(tau0, 1), v_inj=round(vs, 2),
                       pre_slope=round(kp[0], 2) if kp else None, sig_draft=round(kp[1], 2) if kp else None,
                       n=len(D["Y"]), n_keep=len(D["KP"]), seasons=D["seasons"])
    return out


def main():
    rng = __import__("random").Random(5)
    per, pool = {}, new_data()
    for lg in LG.LEAGUES:
        print(lg["name"])
        D = collect(lg["id"], rng)
        per[lg["key"]] = fit(D, lg["name"])
        merge(pool, D)
    pooled = fit(pool, "pooled")
    out = dict(pooled=pooled, own=per, use={}, min_own=MIN_OWN)
    for lg in LG.LEAGUES:
        o = per[lg["key"]]
        own_ok = o and o["n"] >= MIN_OWN and o["pre_slope"] is not None
        out["use"][lg["key"]] = dict(o if own_ok else pooled, source="own" if own_ok else "pooled")
        print("%s -> %s" % (lg["name"], "own history" if own_ok else "pooled"))
    if "--write" in sys.argv:
        with open(CAL, "w") as f:
            json.dump(out, f, indent=1)
        print("wrote", CAL)


if __name__ == "__main__":
    main()
