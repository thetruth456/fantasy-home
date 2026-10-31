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

RULED_OUT = {"Out", "IR", "PUP"}   # Sleeper tags that count as a miss for a game not played yet (Questionable/Doubtful do not)

# Long-term absences, from news reports (checked Oct 31, 2026). back = first date he is expected to be able to play:
#   "season" = every remaining game; {"week": n} = first week he can play. A reported range of N weeks uses the
#   midpoint, counted in weeks after the week he got hurt (so he misses Weeks inj+1 .. inj+N, minus byes).
# Every row needs a source; no reported timeline -> no row (Sleeper's tag covers this week only).
LONG_TERM = {
    "9226": dict(back="season", injury="Torn ACL (Week 3, Sep 27)", timeline="Out for the 2026 season", basis="Season-ending",
                 sources=["https://www.nfl.com/news/dolphins-rb-devon-achane-miss-2026-season-acl-tear",
                          "https://www.cbssports.com/nfl/news/devon-achane-knee-injury-dolphins-chiefs-2026/"]),
    "5927": dict(back="season", injury="Torn patellar tendon (Oct 19), surgery Oct 30", timeline="Out for the 2026 season", basis="Season-ending",
                 sources=["https://www.nfl.com/news/commanders-wr-terry-mclaurin-out-rest-of-season-torn-patellar-tendon",
                          "https://www.commanders.com/news/commanders-terry-mclaurin-injured-reserve-jer-zhan-newton"]),
    "10222": dict(back="season", injury="Neck surgery (IR Sep 30)", timeline="Out for the 2026 season", basis="Season-ending",
                  sources=["https://www.nfl.com/news/packers-wr-jayden-reed-to-undergo-neck-surgery-miss-rest-of-2026-season"]),
    "12508": dict(back="season", injury="Knee surgery: meniscus, MCL/PCL (Sep 25)", timeline="4–6 months; out for the rest of the regular season", basis="Season-ending",
                  sources=["https://www.giants.com/news/jaxson-dart-to-miss-rest-of-regular-season-jameis-winston-to-start-quarterback-injury-john-harbaugh",
                           "https://giantswire.usatoday.com/story/sports/nfl/giants/2026/10/01/timeline-giants-jaxson-dart-return-revealed-surgery-went-well/92030077007/"]),
    "6904": dict(back="season", injury="Blood clots in leg and lungs (IR Oct 17)", timeline="Likely out for the rest of 2026", basis="Season-ending",
                 sources=["https://www.nfl.com/news/eagles-qb-jalen-hurts-out-2026-season-blood-clots",
                          "https://www.philadelphiaeagles.com/news/eagles-place-jalen-hurts-on-injured-reserve-sign-rb-jaydon-blue-to-the-active-roster-2026-nfl-week-6-panthers"]),
    "8205": dict(back={"week": 16}, injury="Back surgery (IR)", timeline="Lions hope for a late-December return", basis="Late December: back Week 16 (Dec 28)",
                 sources=["https://sports.yahoo.com/articles/isiah-pacheco-injury-dan-campbell-172500189.html",
                          "https://www.cbssports.com/fantasy/football/news/lions-isiah-pacheco-still-targeting-december-return/"]),
    "2133": dict(back={"week": 15}, injury="Ruptured hamstring (Week 6, Oct 18), surgery Oct 28", timeline="6–10 weeks (McVay hopes for the short end)",
                 basis="Midpoint 8 weeks after Week 6: misses Weeks 7–14",
                 sources=["https://www.cbssports.com/fantasy/football/news/rams-davante-adams-undergoes-hamstring-surgery/",
                          "https://www.nbcsports.com/fantasy/football/player-news/2026-10-28/mcvay-optimistic-on-adams-hammy-return-post-op"]),
    "13417": dict(back={"week": 13}, injury="Ankle (Week 1), surgery Sep 16", timeline="About 10 weeks; team says on track for December", basis="Latest report: first December game, Week 13",
                  sources=["https://www.espn.co.uk/nfl/story/_/id/49960208/49ers-dezhaun-stribling-surgery-miss-10-weeks",
                           "https://www.cbssports.com/fantasy/football/news/49ers-dezhaun-stribling-remains-on-track-for-december-return/"]),
    "11655": dict(back={"week": 13}, injury="Hamstring strain (Week 7), IR", timeline="IR; earliest return Week 13, not season-ending", basis="Earliest return",
                  sources=["https://www.espn.com/nfl/story/_/id/50300226/giants-place-rb-tyrone-tracy-ir-hamstring-injury",
                           "https://www.giants.com/news/tyrone-tracy-jr-injured-reserve-gregory-desrosiers-dean-lowry-practice-squad-roster-moves-bye-week-joe-schoen"]),
    "8121": dict(back={"week": 12}, injury="Shoulder (IR Oct 19)", timeline="IR; earliest return Week 12 (after Week 11 bye), timeline uncertain", basis="Earliest return",
                 sources=["https://apnews.com/article/romeo-doubs-patriots-injured-reserve-41773cdcbdf5fdd693667b3c8c5ac7ce",
                          "https://www.fantasypros.com/nfl/news/614938/romeo-doubs-shoulder-facing-uncertain-timetable-to-retun.php"]),
    "12533": dict(back={"week": 11}, injury="Groin (Week 5), IR Oct 19", timeline="IR; estimated return around Nov 23", basis="Nov 23 is his Week 11 game",
                  sources=["https://www.espn.com/nfl/story/_/id/50221053",
                           "https://www.nbcsports.com/fantasy/football/player-news/2026-10-19/commanders-place-croskey-merritt-groin-on-ir"]),
    "11583": dict(back={"week": 10}, injury="Core muscle (Week 2), surgery Sep 23", timeline="6–8 weeks", basis="Midpoint 7 weeks after Week 2: misses Weeks 3–9",
                  sources=["https://www.nfl.com/news/panthers-rb-jonathon-brooks-surgery-out-six-weeks",
                           "https://www.cbssports.com/fantasy/football/news/panthers-jonathon-brooks-spotted-jogging-thursday/"]),
    "11618": dict(back={"week": 11}, injury="Knee PCL sprain (Week 3, Sep 27), IR", timeline="6–8 weeks; no return date set as of Oct 29", basis="Midpoint 7 weeks after Week 3: misses Weeks 4–10",
                  sources=["https://www.reuters.com/sports/reports-bucs-wr-jalen-mcmillan-knee-out-6-8-weeks--flm-2026-09-29/",
                           "https://www.joebucsfan.com/2026/10/update-on-jalen-mcmillan/"]),
    "9225": dict(back={"week": 11}, injury="Core muscle (Week 4, Oct 4), surgery", timeline="About six weeks or less", basis="6 weeks after Week 4: misses Weeks 5–10",
                 sources=["https://www.cbssports.com/fantasy/football/news/eagles-tank-bigsby-placed-on-ir/",
                          "https://www.philadelphiaeagles.com/news/eagles-place-rb-tank-bigsby-on-injured-reserve-release-lb-anfernee-orji-from-the-practice-squad"]),
    "6819": dict(back={"week": 10}, injury="Plantar fasciitis (short-term IR Oct 10)", timeline="Earliest return Week 10; surgery not ruled out", basis="Earliest return",
                 sources=["https://www.espn.com/nfl/story/_/id/50149634/steelers-placing-wr-pittman-injured-reserve",
                          "https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/steelers-wr-michael-pittman-headed-to-ir"]),
    "12489": dict(back={"week": 13}, injury="Knee (practice, Week 8), short-term IR Oct 31", timeline="IR; eligible to return Week 13", basis="Earliest return",
                  sources=["https://www.denverbroncos.com/news/broncos-promote-s-taylor-rapp-to-active-roster-place-rb-rj-harvey-on-injured-reserve",
                           "https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/broncos-will-put-running-back-r-j-harvey-on-injured-reserve-after-injury-in-practice"]),
    "8142": dict(back={"week": 9}, injury="Heel (IR)", timeline="Expected back Week 9", basis="Reported target",
                 sources=["https://www.rotoballer.com/when-is-alec-pierce-coming-back-week-7-fantasy-football-injury-return-update-2026-2/1970464",
                          "https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/alec-pierce-not-ready-to-return-to-practice-this-week"]),
    "7543": dict(back={"week": 9}, injury="Hamstring (IR Oct 1)", timeline="IR; earliest return Week 9 (Week 8 bye), no firmer date", basis="Earliest return",
                 sources=["https://apnews.com/article/saints-travis-etienne-injured-reserve-a19d20e13c1714fdfdeff81e1cb4dd5f",
                          "https://www.profootballnetwork.com/travis-etienne-jr-injury-update-week-7-2026-saints-steelers-paris/"]),
    "13281": dict(back={"week": 9}, injury="Hamstring (IR)", timeline="No return date; earliest Week 9 (Week 8 bye)", basis="Earliest return",
                  sources=["https://www.usatoday.com/story/sports/nfl/saints/2026/10/25/jordyn-tyson-injury-update-return-saints/92354996007/"]),
}


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

    # ---------------- who held each player each week (trades and waivers move the charge)
    cur = last + 1                                    # the week in progress (not fully scored yet)
    st_ = L["settings"]
    rounds = math.ceil(math.log2(max(2, int(st_.get("playoff_teams") or 6))))
    per = 2 if st_.get("playoff_round_type") == 2 else 1          # 2 = two weeks per round
    end = int(st_.get("playoff_week_start") or 15) + rounds * per - 1 + (1 if st_.get("playoff_round_type") == 1 else 0)  # final fantasy week
    M = {w: get("/v1/league/%s/matchups/%s" % (LEAGUE, w)) for w in range(1, cur + 1)}
    hold = {w: {pid: m["roster_id"] for m in M[w] for pid in (m.get("players") or [])} for w in M}
    now_hold = {pid: r["roster_id"] for r in rosters for pid in (r.get("players") or [])}
    for w in range(cur + 1, end + 1):
        hold[w] = now_hold

    def holder(pid, w, drafted_by):
        for k in range(w, 0, -1):          # the team holding him that week, else the last team that held him
            if pid in hold.get(k, {}):
                return hold[k][pid]
        return drafted_by
    trades = []
    for w in range(1, cur + 1):
        for x in get("/v1/league/%s/transactions/%s" % (LEAGUE, w)):
            if x.get("type") == "trade" and x.get("status") == "complete":
                for pid, to in (x.get("adds") or {}).items():
                    trades.append(dict(week=w, ts=x.get("status_updated"), pid=pid, to=to, frm=(x.get("drops") or {}).get(pid)))

    # games per NFL team: week -> (date, complete)
    tg = {}
    for g in sched:
        for tm in (g["home"], g["away"]):
            tg.setdefault(tm, {})[g["week"]] = (g.get("date") or "", g.get("status") == "complete")
    if cur not in stats:
        stats[cur] = {e["player_id"]: e for e in S.sleeper_stats(season, cur, "regular") if e.get("player_id")}

    def back_week(lt):
        return 99 if lt["back"] == "season" else lt["back"]["week"]

    # ---------------- injuries (charged to whoever held the player that week)
    players, inj = [], {rid: dict(games=0, bill=0.0, games_so=0, bill_so=0.0, games_co=0, bill_co=0.0, early=0, worst=None) for rid in team}
    for p in picks:
        pid, md = p["player_id"], p.get("metadata") or {}
        q = P.get(pid) or {}
        name = q.get("full_name") or ("%s %s" % (md.get("first_name", ""), md.get("last_name", ""))).strip()
        pos = q.get("position") or md.get("position")
        tag = q.get("injury_status")
        part = q.get("injury_body_part")
        lt = LONG_TERM.get(pid)
        missed, coming, gp, pts = [], [], 0, 0.0
        # NFL team by week; a week with no stats row uses the nearest week that has one (players traded between NFL teams)
        seen = {w: stats[w][pid]["team"] for w in weeks + [cur] if (stats[w].get(pid) or {}).get("team")}
        for w in weeks + [cur]:
            e = stats[w].get(pid) or {}
            st = e.get("stats") or {}
            near = sorted(seen, key=lambda k: (abs(k - w), -k))
            nfl = e.get("team") or ((seen[near[0]] if near else q["team"]) if q.get("team") else None)  # released players: skip
            if not nfl or w not in tg.get(nfl, {}):
                continue  # bye week, or no NFL team
            date, done = tg[nfl][w]
            if done:
                if st.get("gp"):
                    if w <= last:
                        gp += 1
                        pts += fpts(st)
                else:
                    missed.append(w)
            elif w == cur and (tag in RULED_OUT or (lt and w < back_week(lt))):
                coming.append(w)   # this week's game not played yet and he is already ruled out
        nfl = q.get("team")
        if lt and nfl:
            for w in range(cur + 1, min(end, back_week(lt) - 1) + 1):
                if w in tg.get(nfl, {}) and not tg[nfl][w][1]:
                    coming.append(w)
        if pid in KNOWN_NOT_INJURY:
            kind, tag, part = "not injury", KNOWN_NOT_INJURY[pid], None
        elif part in NOT_INJURY or tag in ("Sus", "NA"):
            kind = "not injury"
        elif tag or part:
            kind = "injured"
        else:
            kind = "no tag now"
        if kind == "not injury":
            coming = []
        val = 100 * DECAY ** (p["pick_no"] - 1)
        charged = {}
        for w in missed:
            charged.setdefault(holder(pid, w, p["roster_id"]), [0, 0])[0] += 1
        for w in coming:
            charged.setdefault(holder(pid, w, p["roster_id"]), [0, 0])[1] += 1
        now = now_hold.get(pid)
        rec = dict(pid=pid, pick=p["pick_no"], rnd=p["round"], name=name, pos=pos, rid=p["roster_id"], now=now, missed=missed, coming=coming,
                   val=round(val, 1), bill_so=round(val * len(missed), 1), bill_co=round(val * len(coming), 1),
                   bill=round(val * (len(missed) + len(coming)), 1), charged=[[r, a, b] for r, (a, b) in charged.items()],
                   gp=gp, ppg=round(pts / gp, 1) if gp else None,
                   status=" ".join(x for x in (tag, "(" + part + ")" if part else "") if x), kind=kind)
        if lt:
            rec["lt"] = dict(injury=lt["injury"], timeline=lt["timeline"], basis=lt["basis"], sources=lt["sources"],
                             back=back_week(lt))
        if missed or coming:
            players.append(rec)
        if kind == "not injury":
            continue
        for r, (a, b) in charged.items():
            t = inj[r]
            t["games_so"] += a; t["bill_so"] += val * a
            t["games_co"] += b; t["bill_co"] += val * b
            t["games"] += a + b; t["bill"] += val * (a + b)
            if p["round"] <= 5:
                t["early"] += a + b
            share = val * (a + b)
            if not t["worst"] or share > t["worst"]["bill"]:
                t["worst"] = dict(name=name, pick=p["pick_no"], games=a + b, bill=round(share, 1))
    players.sort(key=lambda r: -r["bill"])
    byp = {r["pid"]: r for r in players if r["kind"] != "not injury"}
    trades = [dict(t, name=byp[t["pid"]]["name"], pick=byp[t["pid"]]["pick"]) for t in trades if t["pid"] in byp]
    trades.sort(key=lambda t: (t["ts"] or 0))

    # ---------------- matchups
    games, scores = [], {w: {} for w in weeks}
    for w in weeks:
        by = {}
        for m in M[w]:
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
            # opponent's score vs this team, against that opponent's average in his other weeks
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
                      inj_games=inj[rid]["games"], inj_bill=round(inj[rid]["bill"], 1), inj_early=inj[rid]["early"], inj_worst=inj[rid]["worst"],
                      inj_games_so=inj[rid]["games_so"], inj_bill_so=round(inj[rid]["bill_so"], 1),
                      inj_games_co=inj[rid]["games_co"], inj_bill_co=round(inj[rid]["bill_co"], 1)))
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
                close_margin=CLOSE, decay=DECAY, cur=cur, end=end, teams=rows, players=players, trades=trades, close=close, games=games)
    with open(OUT, "w") as f:
        f.write("/* Static snapshot generated by tools/podcast.py. The update workflow does not touch this file. */\n")
        f.write("window.PODCAST=window.PODCAST||{};\nwindow.PODCAST.best=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n")
    S.log("wrote %s (weeks %d-%d, %d teams, %d players with misses)" % (OUT, weeks[0], weeks[-1], len(rows), len(players)))


if __name__ == "__main__":
    main()
