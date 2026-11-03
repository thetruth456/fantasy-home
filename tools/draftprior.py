"""Draft-value prior for tools/power.py (stdlib only).

For a season's draft: each drafted player is valued at his Sleeper PRESEASON projection per game (league scoring, season
total / 17). Post-draft team value = best legal lineup from the 15 drafted players. Pre-draft value = keeper surplus only:
for each keeper, his value over replacement at his position minus the average value over replacement of the players whose
overall ADP sits around the pick he was kept with (what an ADP-faithful pick there would have returned). Non-keeper picks are
assumed to be worth the same for everyone before the draft.
"""
import statistics as st
import sources as S

REPL = {"QB": 13, "RB": 30, "WR": 30, "TE": 13, "K": 13, "DEF": 13}   # replacement level = Nth best at the position


def season_projections(season):
    return S.get_json("%s/projections/nfl/%s?season_type=regular&%s&order_by=adp_half_ppr" % (S.SLEEPER, season, S.PROJ_POS), timeout=120)


def rosters(P, picks):
    """{roster_id: [(preseason pts per game, pos, pid), ...]} for the drafted players (keepers included)."""
    out = {}
    for p in picks:
        q = P.get(p["player_id"]) or {}
        out.setdefault(p["roster_id"], []).append((q.get("v", 0.0), q.get("pos") or (p.get("metadata") or {}).get("position") or "", p["player_id"]))
    return out


def player_values(proj, fpts):
    P = {}
    for e in proj:
        pid, s = e.get("player_id"), e.get("stats") or {}
        if not pid:
            continue
        pl = e.get("player") or {}
        P[pid] = dict(v=max(0.0, fpts(s)) / 17.0, pos=e.get("position") or pl.get("position") or "", adp=s.get("adp_half_ppr") or 999,
                      name=("%s %s" % (pl.get("first_name", ""), pl.get("last_name", ""))).strip())
    return P


def values(proj, picks, slots, fpts, lineup):
    """(post-draft value - league mean, keeper surplus - league mean, keepers) by roster_id; also see rosters()."""
    P = player_values(proj, fpts)
    rep = {}
    for q, n in REPL.items():
        vs = sorted((p["v"] for p in P.values() if p["pos"] == q), reverse=True)
        rep[q] = vs[n - 1] if len(vs) >= n else 0.0
    for p in P.values():
        p["vor"] = max(0.0, p["v"] - rep.get(p["pos"], p["v"]))
    byadp = [p for p in sorted(P.values(), key=lambda p: p["adp"]) if p["adp"] < 999]

    def pickval(n):
        return st.mean(p["vor"] for p in byadp[max(0, n - 4):min(len(byadp), n + 3)])
    rids = sorted({p["roster_id"] for p in picks})
    post, pre, keep = {}, {}, {}
    cands = rosters(P, picks)
    for r in rids:
        mine = [p for p in picks if p["roster_id"] == r]
        post[r] = lineup(slots, cands[r])[0]
        ks = []
        for p in mine:
            if p.get("is_keeper"):
                q = P.get(p["player_id"]) or {}
                md = p.get("metadata") or {}
                ks.append(dict(pid=p["player_id"], name=q.get("name") or ("%s %s" % (md.get("first_name", ""), md.get("last_name", ""))).strip(),
                               pos=q.get("pos") or md.get("position"), round=p["round"], pick=p["pick_no"],
                               adp=round(q["adp"], 1) if q.get("adp", 999) < 999 else None, surplus=round(q.get("vor", 0.0) - pickval(p["pick_no"]), 2)))
        keep[r] = ks
        pre[r] = sum(k["surplus"] for k in ks)
    mp, mq = st.mean(post.values()), st.mean(pre.values())
    return {r: post[r] - mp for r in rids}, {r: pre[r] - mq for r in rids}, keep
