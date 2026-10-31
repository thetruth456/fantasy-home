"""One-off generator for the Best League "Podcast" luck report (static snapshot).

Not run by the update workflow. Writes best-podcast-data.js (window.PODCAST.best).
Usage: python tools/podcast.py [last_week]   (default: Sleeper's last fully scored week)
"""
import json, os, sys, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S

LEAGUE = "1389358450705727488"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.environ.get("FH_OUT_DIR") or ROOT, "best-podcast-data.js")
CACHE = os.environ.get("FH_CACHE_DIR") or os.path.join(ROOT, ".cache")
DECAY = 0.97          # pick value = 100 * DECAY ** (pick - 1)
CLOSE = 10.0          # a "close" game is decided by fewer than this many points
# Misses known not to be injuries, from Sleeper tags seen in an earlier players dump (the dump only keeps the current tag).
KNOWN_NOT_INJURY = {"13288": "Coach's Decision (Sleeper tag on Oct 28)"}  # Nicholas Singleton
NOT_INJURY = {"Coach's Decision", "Suspension", "Personal", "Not Injury Related"}


def get(path):
    return S.get_json(S.SLEEPER + path)


def main():
    L = get("/v1/league/%s" % LEAGUE)
    season = L["season"]
    last = int(sys.argv[1]) if len(sys.argv) > 1 else int(L["settings"].get("last_scored_leg") or 0)
    if last < 1:
        raise SystemExit("no completed weeks yet")
    weeks = list(range(1, last + 1))
    users = {u["user_id"]: u for u in get("/v1/league/%s/users" % LEAGUE)}
    rosters = get("/v1/league/%s/rosters" % LEAGUE)
    team = {}
    for r in rosters:
        u = users.get(r["owner_id"]) or {}
        team[r["roster_id"]] = dict(rid=r["roster_id"], user=u.get("display_name") or "Team %s" % r["roster_id"],
                                    name=((u.get("metadata") or {}).get("team_name") or u.get("display_name") or "Team %s" % r["roster_id"]).strip())
    drafts = [d for d in get("/v1/league/%s/drafts" % LEAGUE) if d.get("status") == "complete"]
    picks = get("/v1/draft/%s/picks" % drafts[0]["draft_id"])
    sched = S.sleeper_schedule(season)
    played = {w: set() for w in weeks}
    for g in sched:
        if g["week"] in played and g.get("status") == "complete":
            played[g["week"]].update([g["home"], g["away"]])
    P = S.sleeper_players(CACHE)
    stats = {w: {e["player_id"]: e for e in S.sleeper_stats(season, w, "regular") if e.get("player_id")} for w in weeks}
    Sc = L["scoring_settings"]

    def fpts(st):
        return sum(Sc[k] * v for k, v in st.items() if k in Sc and Sc[k] and isinstance(v, (int, float)))

    # ---------------- injuries (charged to the team that drafted the player)
    players, inj = [], {rid: dict(games=0, bill=0.0, early=0, worst=None) for rid in team}
    for p in picks:
        pid, md = p["player_id"], p.get("metadata") or {}
        q = P.get(pid) or {}
        name = q.get("full_name") or ("%s %s" % (md.get("first_name", ""), md.get("last_name", ""))).strip()
        pos = q.get("position") or md.get("position")
        missed, gp, pts = [], 0, 0.0
        for w in weeks:
            e = stats[w].get(pid) or {}
            st = e.get("stats") or {}
            nfl = e.get("team") or q.get("team")
            if not nfl or nfl not in played[w]:
                continue  # bye week, or no NFL team
            if st.get("gp"):
                gp += 1
                pts += fpts(st)
            else:
                missed.append(w)
        tag = q.get("injury_status")
        part = q.get("injury_body_part")
        if pid in KNOWN_NOT_INJURY:
            kind, tag, part = "not injury", KNOWN_NOT_INJURY[pid], None
        elif part in NOT_INJURY or tag in ("Sus", "NA"):
            kind = "not injury"
        elif tag or part:
            kind = "injured"
        else:
            kind = "no tag now"
        val = 100 * DECAY ** (p["pick_no"] - 1)
        rec = dict(pick=p["pick_no"], rnd=p["round"], name=name, pos=pos, rid=p["roster_id"], missed=missed,
                   val=round(val, 1), bill=round(val * len(missed), 1), gp=gp, ppg=round(pts / gp, 1) if gp else None,
                   status=" ".join(x for x in (tag, "(" + part + ")" if part else "") if x), kind=kind)
        if missed:
            players.append(rec)
        if missed and kind != "not injury":
            t = inj[p["roster_id"]]
            t["games"] += len(missed)
            t["bill"] += rec["bill"]
            if p["round"] <= 5:
                t["early"] += len(missed)
            if not t["worst"] or rec["bill"] > t["worst"]["bill"]:
                t["worst"] = dict(name=name, pick=p["pick_no"], games=len(missed), bill=rec["bill"])
    players.sort(key=lambda r: -r["bill"])

    # ---------------- matchups
    games, scores = [], {w: {} for w in weeks}
    for w in weeks:
        M = get("/v1/league/%s/matchups/%s" % (LEAGUE, w))
        by = {}
        for m in M:
            scores[w][m["roster_id"]] = float(m.get("points") or 0)
            if m.get("matchup_id"):
                by.setdefault(m["matchup_id"], []).append(m)
        for pair in by.values():
            if len(pair) == 2:
                a, b = pair
                games.append(dict(week=w, a=a["roster_id"], b=b["roster_id"], pa=round(float(a["points"]), 2), pb=round(float(b["points"]), 2)))
    n = len(team)
    T = {rid: dict(w=0, l=0, t=0, pf=0.0, pa=0.0, apw=0, apl=0, apt=0, xw=0.0, cw=0, cl=0, dip=0.0, top=0, bottom=0, hiloss=None, lowin=None) for rid in team}
    avg = {rid: sum(scores[w][rid] for w in weeks) / len(weeks) for rid in team}
    for w in weeks:
        sc = scores[w]
        ranked = sorted(sc.values(), reverse=True)
        for rid, s in sc.items():
            above = sum(1 for o, v in sc.items() if o != rid and s > v)
            ties = sum(1 for o, v in sc.items() if o != rid and s == v)
            t = T[rid]
            t["apw"] += above; t["apt"] += ties; t["apl"] += n - 1 - above - ties
            t["xw"] += (above + 0.5 * ties) / (n - 1)
            if s == ranked[0]: t["top"] += 1
            if s == ranked[-1]: t["bottom"] += 1
    for g in games:
        for me, op, ms, os_ in ((g["a"], g["b"], g["pa"], g["pb"]), (g["b"], g["a"], g["pb"], g["pa"])):
            t = T[me]
            t["pf"] += ms; t["pa"] += os_
            # opponent's score vs you, against that opponent's average in his other weeks
            other = [scores[w][op] for w in weeks if w != g["week"]]
            t["dip"] += (sum(other) / len(other)) - os_ if other else 0
            m = ms - os_
            if m > 0:
                t["w"] += 1
                if m < CLOSE: t["cw"] += 1
                if not t["lowin"] or ms < t["lowin"]["pts"]: t["lowin"] = dict(pts=ms, week=g["week"], opp=op, opp_pts=os_)
            elif m < 0:
                t["l"] += 1
                if -m < CLOSE: t["cl"] += 1
                if not t["hiloss"] or ms > t["hiloss"]["pts"]: t["hiloss"] = dict(pts=ms, week=g["week"], opp=op, opp_pts=os_)
            else:
                t["t"] += 1
    rows = []
    for rid, t in T.items():
        x = dict(team[rid])
        x.update(dict(w=t["w"], l=t["l"], t=t["t"], pf=round(t["pf"], 2), pa=round(t["pa"], 2), apw=t["apw"], apl=t["apl"], apt=t["apt"],
                      xw=round(t["xw"], 2), luck=round(t["w"] + 0.5 * t["t"] - t["xw"], 2), cw=t["cw"], cl=t["cl"],
                      dip=round(t["dip"] / len(weeks), 1), top=t["top"], bottom=t["bottom"], hiloss=t["hiloss"], lowin=t["lowin"],
                      inj_games=inj[rid]["games"], inj_bill=round(inj[rid]["bill"], 1), inj_early=inj[rid]["early"], inj_worst=inj[rid]["worst"]))
        rows.append(x)

    def z(vals):
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) or 1
        return [(v - m) / sd for v in vals]
    zl, zi = z([r["luck"] for r in rows]), z([r["inj_bill"] for r in rows])
    for r, a, b in zip(rows, zl, zi):
        r["idx"] = round((a - b) / 2, 2)   # positive = lucky
    rows.sort(key=lambda r: -r["idx"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    close = sorted(games, key=lambda g: abs(g["pa"] - g["pb"]))[:6]
    now = datetime.datetime.now(datetime.timezone.utc)
    data = dict(season=season, weeks=[weeks[0], weeks[-1]], league=L["name"], asof=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                close_margin=CLOSE, decay=DECAY, teams=rows, players=players, close=close, games=games,
                me=next((r["rid"] for r in rows if r["user"] == "kfelder30"), None))
    with open(OUT, "w") as f:
        f.write("/* Static snapshot generated by tools/podcast.py. The update workflow does not touch this file. */\n")
        f.write("window.PODCAST=window.PODCAST||{};\nwindow.PODCAST.best=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n")
    S.log("wrote %s (weeks %d-%d, %d teams, %d players with misses)" % (OUT, weeks[0], weeks[-1], len(rows), len(players)))


if __name__ == "__main__":
    main()
