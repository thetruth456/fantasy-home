"""Turns raw source data into report rows, quick-read bullets, league setup text and as-of lines."""
import datetime as dt
import re

from sources import norm, log

SKIP_PROPS = ("Played", "Bye", "IR")
DASH = "\u2014"
DAYS = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
TEAM_ALIAS = {"WAS": "WSH", "JAC": "JAX"}


def team_norm(t):
    return TEAM_ALIAS.get(t, t)


def norm_fw(n):
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def imp(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def fmt_odds(o):
    return ("+%d" % o) if o > 0 else str(o)


def num(x):
    return "%g" % x


def ordn(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


# ------------------------------------------------------------------ props (Fieldwork)
class Props:
    def __init__(self, fw, overrides):
        self.fw = fw
        self.ovr = overrides or {}
        self.idx = {}
        for p in fw["players"]:
            self.idx.setdefault(norm_fw(p["name"]), []).append(p)

    def find(self, name, team):
        c = self.idx.get(norm_fw(name), [])
        if len(c) > 1:
            c = [p for p in c if p["team"] == team] or c[:1]
        return c[0] if c else None

    def get(self, name, team):
        cell, quote = self.fw["cell"], self.fw["quote"]
        o = self.ovr.get(name, {})
        p = self.find(o.get("fwname", name), team)
        out = dict(rush=DASH, rec=DASH, recs=DASH, atd=DASH, atdr="", pp=None, partial=False)
        rn = yn = cn = None
        if not p:
            return out
        def line(m):
            if m not in p["cells"]:
                return None, ""
            c = cell[p["cells"][m]]
            if c[0] is None:
                return None, ""
            qs = [quote[q] for q in c[4]]
            ls = sorted(set(q[2] for q in qs))
            return c[0], (num(ls[0]) if len(ls) == 1 else num(ls[0]) + "\u2013" + num(ls[-1]))
        vals = {}
        for k, m, key in [("rush", "player_rush_yds", "rn"), ("rec", "player_reception_yds", "yn"), ("recs", "player_receptions", "cn")]:
            v, r = line(m)
            vals[key] = v
            if v is not None:
                out[k] = num(v) + (" (" + r + ")" if "\u2013" in r else "")
        rn, yn, cn = vals["rn"], vals["yn"], vals["cn"]
        if yn is None and "yn" in o:
            yn = o["yn"]; out["rec"] = num(yn)
        if rn is None and "rn" in o:
            rn = o["rn"]; out["rush"] = num(rn)
        if cn is None and "cn" in o:
            cn = o["cn"]; out["recs"] = num(cn)
        ip = None
        if "player_anytime_td" in p["cells"]:
            c = cell[p["cells"]["player_anytime_td"]]
            prices = {quote[q][0]: quote[q][5] for q in c[4]}
            if prices:
                vs = list(prices.values())
                dec = lambda n: (1 + n / 100) if n > 0 else (1 + 100 / -n)  # noqa: E731
                sv = sorted(vs, key=dec)
                out["atd"] = fmt_odds(prices["draftkings"]) if "draftkings" in prices else fmt_odds(sv[0])
                out["atdr"] = (fmt_odds(sv[0]) + " to " + fmt_odds(sv[-1])) if sv[0] != sv[-1] else ""
                ip = sum(imp(v) for v in vs) / len(vs)
                if rn is not None or yn is not None:
                    out["pp"] = (rn or 0) * .1 + (yn or 0) * .1 + (cn or 0) + 6 * ip
        out["_yn"], out["_cn"], out["_rn"] = yn, cn, rn
        return out


# ------------------------------------------------------------------ FantasyPros matching
class FPRanks:
    def __init__(self, pages):
        self.pages = pages
        self.idx = {}
        for k, pl in pages.items():
            d = {}
            for x in pl:
                d.setdefault(norm(x["player_name"]), []).append(x)
            self.idx[k] = d

    def lookup(self, flex_page, r):
        """Return the FP rank string for a row dict, or None when that page is unavailable. Dash when unranked."""
        pos = r["pos"]
        if pos in ("RB", "WR", "TE"):
            if flex_page not in self.idx:
                return None
            c = self.idx[flex_page].get(norm(r["name"]), [])
            c = [x for x in c if team_norm(x["player_team_id"]) == team_norm(r["team"])] or c
            return str(c[0]["rank_ecr"]) if c else DASH
        if pos in ("QB", "K"):
            pg = pos.lower()
            if pg not in self.idx:
                return None
            c = self.idx[pg].get(norm(r["name"]), [])
            return "%s%s" % (pos, c[0]["rank_ecr"]) if c else DASH
        if pos == "DEF":
            if "dst" not in self.pages:
                return None
            c = [x for x in self.pages["dst"] if team_norm(x["player_team_id"]) == team_norm(r["team"])]
            return "DEF%s" % c[0]["rank_ecr"] if c else DASH
        return DASH


# ------------------------------------------------------------------ defense: expected points-allowed score
PA_BUCKETS = [("pts_allow_0", 0, 0), ("pts_allow_1_6", 1, 6), ("pts_allow_7_13", 7, 13), ("pts_allow_14_20", 14, 20),
              ("pts_allow_21_27", 21, 27), ("pts_allow_28_34", 28, 34), ("pts_allow_35p", 35, 10 ** 6)]
_DIST = {}


def score_dist(total, drives=14, td_share=0.77):
    """Distribution of an offense's points when it is expected to score `total`.
    14 independent scoring chances; each is a TD (7 pts) or a field goal (3 pts) or nothing. 77% of the expected points
    come from TDs and 23% from field goals. This gives lumpy football scores with a standard deviation of about 10 at a
    22-point total (the NFL norm), which a plain Poisson overstates. Returns a list p[points] up to 98+ (cap folded into the last cell)."""
    key = round(total, 2)
    if key in _DIST:
        return _DIST[key]
    a = td_share * total / (7.0 * drives)
    b = (1 - td_share) * total / (3.0 * drives)
    cap = 7 * drives
    d = [1.0] + [0.0] * cap
    for _ in range(drives):
        n = [0.0] * (cap + 1)
        for i, x in enumerate(d):
            if x:
                n[i] += x * (1 - a - b)
                n[min(i + 7, cap)] += x * a
                n[min(i + 3, cap)] += x * b
        d = n
    _DIST[key] = d
    return d


def pa_expected(S, opp_total):
    """Expected points-allowed fantasy score for a defense whose opponent is expected to score opp_total, under scoring settings S."""
    d = score_dist(max(5.0, min(60.0, float(opp_total))))
    e = 0.0
    for k, lo, hi in PA_BUCKETS:
        v = S.get(k) or 0
        if v:
            e += v * sum(d[lo:hi + 1])
    if S.get("pts_allow"):
        e += S["pts_allow"] * float(opp_total)
    return e


def def_pp(S, stats, opp_total):
    """Prop-implied DEF points: Sleeper's projected stat line scored with the league settings, with the points-allowed buckets
    swapped for the expected score under the opponent's implied total. Yards-allowed buckets stay as Sleeper projects them."""
    base = sum(S[k] * v for k, v in stats.items()
               if k in S and S[k] and isinstance(v, (int, float)) and not k.startswith("pts_allow"))
    return base + pa_expected(S, opp_total)


# ------------------------------------------------------------------ rows
def build_league(ctx, bundle, user_id, props, fp, flex_page, prev_rows, prev_def=None):
    """ctx: dict(week, players, proj{pid:entry}, stats{pid:stats}, games{team:(game,'vs'|'@',other)})."""
    L, R = bundle["league"], bundle["rosters"]
    S = L["scoring_settings"]
    P, proj, STD, games = ctx["players"], ctx["proj"], ctx["stats"], ctx["games"]

    def pts(s):
        return sum(S[k] * v for k, v in s.items() if k in S and S[k] and isinstance(v, (int, float)))

    def info(pid):
        q = dict(P.get(pid) or {})
        x = proj.get(pid)
        if x:  # projection feed is fresher for team and injury status
            pl = x.get("player") or {}
            if x.get("team"):
                q["team"] = x["team"]
            q["injury_status"] = pl.get("injury_status")
            for k_src, k_dst in (("position", "position"),):
                if not q.get(k_dst) and pl.get(k_src):
                    q[k_dst] = pl[k_src]
            if not q.get("full_name") and pl.get("first_name"):
                q["full_name"] = (pl.get("first_name", "") + " " + pl.get("last_name", "")).strip()
        return q

    me = [r for r in R if r.get("owner_id") == user_id]
    if not me:
        raise RuntimeError("user not found in league %s" % L.get("name"))
    me = me[0]
    rp = [x for x in L["roster_positions"] if x != "BN"]
    cnt = {x: rp.count(x) for x in set(rp)}
    seen = {}
    labels = []
    for x in rp:
        seen[x] = seen.get(x, 0) + 1
        labels.append(x if cnt[x] == 1 else x + str(seen[x]))
    reserve = set(me.get("reserve") or [])
    notes = []

    def row(pid, slot):
        q = info(pid)
        nm = (q.get("full_name") or pid).replace(" Sr.", "")
        pos = q.get("position")
        if pos == "DEF":
            nm = q["team"] + " D/ST"
        x = proj.get(pid)
        pt = round(pts(x["stats"]), 1) if x else 0
        g = games.get(q.get("team"))
        if g:
            opp = "%s %s (%s)" % (g[1], g[2], g[3])
            played = g[0].get("status") == "complete"
        else:
            opp = "BYE" if q.get("team") else DASH
            played = False
        inj = q.get("injury_status") or ""
        if pid in reserve:
            status = "IR"
        elif opp == "BYE":
            status = "Bye"
        elif played:
            status = "Played"
        else:
            status = inj or "Healthy"
        team = q.get("team")
        base = dict(rush=DASH, rec=DASH, recs=DASH, atd=DASH, atdr="", pp=None, partial=False)
        if status in SKIP_PROPS or pos not in ("RB", "WR", "TE"):
            pr = base
        elif props is not None:
            pr = props.get(nm, team)
        else:  # props source unavailable: reuse the previous snapshot for this player (same week only), else dashes
            old = prev_rows.get((nm, team))
            pr = {k: old[k] for k in base} if old else base
        if status == "Played":
            a = STD.get(pid)
            act = round(pts(a), 2) if a else 0
            projs = "%.1f final" % act
        else:
            projs = "%.1f" % pt
        partial = False
        if props is not None and pr.get("pp") is not None and pos in ("RB", "WR", "TE"):
            partial = (pr.get("_yn") is None or pr.get("_cn") is None or (pos == "RB" and pr.get("_rn") is None))
        elif props is None:
            partial = bool(pr.get("partial"))
        d = dict(slot=slot, name=nm, pos=pos, team=team, opp=opp, status=status, proj=projs, pn=pt,
                 rush=pr["rush"], rec=pr["rec"], recs=pr["recs"], atd=pr["atd"], atdr=pr["atdr"],
                 pp=None if pr["pp"] is None else round(pr["pp"], 3), partial=bool(partial))
        f = fp.lookup(flex_page, d) if fp is not None else None
        if f is None:
            old = prev_rows.get((nm, team))
            f = old["fp"] if old and old.get("fp") else DASH
        d["fp"] = f
        d["sid"] = pid
        return d

    st = [row(p, l) for p, l in zip(me["starters"], labels) if p != "0"]
    bn = [row(p, "BN") for p in me["players"] if p not in me["starters"]]
    rost = {p for r in R for p in (r.get("players") or [])}
    cands = []
    for pid, x in proj.items():
        q = info(pid)
        if pid in rost or q.get("position") not in ("RB", "WR", "TE") or not q.get("team"):
            continue
        g = games.get(q["team"])
        if not g or g[0].get("status") == "complete":
            continue
        if (q.get("injury_status") or "") in ("Out", "IR", "PUP", "Sus", "NA", "Doubtful"):
            continue
        cands.append((pts(x["stats"]), pid))
    cands.sort(key=lambda t: (-t[0], t[1]))
    top = cands[:10]

    def need():
        pos = [info(p)["position"] for _, p in top]
        return pos.count("RB") < 2 or pos.count("WR") < 2
    i = 10
    while need() and len(top) < 14 and i < len(cands):
        top.append(cands[i]); i += 1
    wv = [row(p, "WAIVER") for _, p in top]

    try:
        defense = build_defense(ctx, info, row, pts, S, me, rost, labels)
    except Exception as e:  # noqa: BLE001
        log("WARNING: defense table failed (%s); keeping its previous rows" % e)
        defense = list(prev_def or [])

    s = me.get("settings", {})
    srt = sorted(R, key=lambda r: (-r["settings"].get("wins", 0), -(r["settings"].get("fpts", 0) + r["settings"].get("fpts_decimal", 0) / 100)))
    rank = [r["roster_id"] for r in srt].index(me["roster_id"]) + 1
    record = "%d-%d%s" % (s.get("wins", 0), s.get("losses", 0), ("-%d" % s["ties"]) if s.get("ties") else "")
    opp_name = opponent_name(bundle, me)
    return dict(STARTERS=st, BENCH=bn, WAIVER=wv, DEFENSE=defense, meta=dict(
        name=L["name"], league_id=L["league_id"], teams=L["total_rosters"], season=L.get("season"),
        record=record, rank=rank, opponent=opp_name, slots=rp, bn=L["roster_positions"].count("BN"),
        reserve=L["settings"].get("reserve_slots") or 0, scoring=S))


def build_defense(ctx, info, row, pts, S, me, rost, labels_unused):
    """Rows for the Defense table: this user's DEF (starter and bench), then the 8 best unrostered DEF by Sleeper projection.
    Each row is a normal report row plus total (game O/U), spread (this team's own line, negative = favorite) and opptot
    (the opponent's implied team total). pp stays None (dash) when there is no line, the game was played, or the team is on bye."""
    proj, games = ctx["proj"], ctx["games"]
    lines = ctx.get("lines") or {}

    def make(pid, slot):
        d = row(pid, slot)
        d["total"] = d["spread"] = d["opptot"] = None
        d["pp"] = None
        ln = lines.get(team_norm(d["team"] or ""))
        if ln and d["status"] not in ("Played", "Bye", "IR"):
            x = proj.get(pid)
            d["total"], d["spread"], d["opptot"] = ln["total"], ln["spread"], round(ln["opp_total"], 2)
            if x:
                d["pp"] = round(def_pp(S, x["stats"], ln["opp_total"]), 3)
        return d

    starters = set(me["starters"])
    mine = []
    for pid in me["players"]:
        q = info(pid)
        if q.get("position") == "DEF":
            mine.append(make(pid, "DEF" if pid in starters else "BN"))
    key = lambda r: (r["pp"] is None, -(r["pp"] or 0), -r["pn"])  # noqa: E731
    mine.sort(key=key)
    cands = []
    for pid, x in proj.items():
        q = info(pid)
        if pid in rost or q.get("position") != "DEF" or not q.get("team"):
            continue
        g = games.get(q["team"])
        if not g or g[0].get("status") == "complete":  # bye or already played: nothing to pick up
            continue
        cands.append((pts(x["stats"]), pid))
    cands.sort(key=lambda t: (-t[0], t[1]))
    fa = [make(pid, "WAIVER") for _, pid in cands[:8]]
    fa.sort(key=key)
    return mine + fa


def opponent_name(bundle, me):
    mid = None
    for m in bundle["matchups"]:
        if m.get("roster_id") == me["roster_id"]:
            mid = m.get("matchup_id")
    if mid is None:
        return None
    other = [m for m in bundle["matchups"] if m.get("matchup_id") == mid and m.get("roster_id") != me["roster_id"]]
    if not other:
        return None
    rid = other[0]["roster_id"]
    ro = [r for r in bundle["rosters"] if r["roster_id"] == rid]
    if not ro:
        return None
    u = [u for u in bundle["users"] if u.get("user_id") == ro[0].get("owner_id")]
    return (u[0].get("display_name") or u[0].get("username")) if u else None


# ------------------------------------------------------------------ league setup text
def _f(vals, v):
    """Format v like the other values of its group: one decimal if any member is fractional, else %g."""
    return ("%.1f" % v) if any(float(x) != int(x) for x in vals) else ("%g" % v)


def _signed(v):
    return ("+%g" % v) if v > 0 else ("%g" % v)


def setup_text(meta, week):
    S = meta["scoring"]
    g = lambda k, d=0: S.get(k, d) or 0  # noqa: E731
    rec = g("rec")
    label = {0.5: "Half PPR", 1.0: "Full PPR", 0.0: "Standard (no PPR)"}.get(float(rec), "%g PPR" % rec)
    rows = [("League", "%s, %d teams, %s season, Week %s" % (meta["name"], meta["teams"], meta["season"], week), False),
            ("Scoring", label, True)]
    ry, cy = g("rush_yd"), g("rec_yd")
    yd = "%g per rushing or receiving yard" % ry if ry == cy else "%g per rushing yard, %g per receiving yard" % (ry, cy)
    td = "%g per TD" % g("rush_td") if g("rush_td") == g("rec_td") else "%g per rushing TD, %g per receiving TD" % (g("rush_td"), g("rec_td"))
    rows.append(("Reception / yards", "%.1f per reception, %s, %s" % (rec, yd, td), False))
    rows.append(("Passing", "%g per yard, %g per TD, %g per interception" % (g("pass_yd"), g("pass_td"), g("pass_int")), False))
    other = ["%g per fumble lost" % g("fum_lost")]
    if g("rec_2pt"):
        other.append("%g per 2-point conversion" % g("rec_2pt"))
    other.append("TE premium %g per reception" % g("bonus_rec_te") if g("bonus_rec_te") else "no TE premium")
    bonus = [k for k in S if k.startswith("bonus_") and k != "bonus_rec_te" and S[k]]
    other.append("yardage bonuses on" if bonus else "no yardage bonuses")
    rows.append(("Other", ", ".join(other), False))
    # kicker
    kk = []
    if g("xpm"):
        kk.append("%g per extra point%s" % (g("xpm"), (" (%g miss)" % g("xpmiss")) if g("xpmiss") else ""))
    fg_keys = [("fgm_0_19", None), ("fgm_20_29", None), ("fgm_30_39", None), ("fgm_40_49", "40-49"), ("fgm_50_59", "50-59"), ("fgm_60p", "60+"), ("fgm_50p", "50+")]
    fgv = [g(k) for k, _ in fg_keys if g(k)]
    if fgv:
        under = [g("fgm_0_19"), g("fgm_20_29"), g("fgm_30_39")]
        parts = ["%s (under 40 yards)" % _f(fgv, under[2])] if len(set(under)) == 1 and under[0] else \
            ["%s (0-19)" % _f(fgv, under[0]), "%s (20-29)" % _f(fgv, under[1]), "%s (30-39)" % _f(fgv, under[2])]
        for k, lab in fg_keys[3:]:
            if g(k):
                parts.append("%s (%s)" % (_f(fgv, g(k)), lab))
        fgs = "field goals " + ", ".join(parts) + ((", %g per miss" % g("fgmiss")) if g("fgmiss") else "")
        kk.append(fgs)
    if kk:
        rows.append(("Kicker", "; ".join(kk), False))
    # defense
    dd = []
    for k, lab in [("sack", "per sack"), ("int", "per interception"), ("fum_rec", "per fumble recovery"), ("ff", "per forced fumble"),
                   ("safe", "per safety"), ("blk_kick", "per blocked kick"), ("def_td", "per TD")]:
        if g(k):
            dd.append("%g %s" % (g(k), lab))
    pa = [("pts_allow_0", "0"), ("pts_allow_1_6", "1-6"), ("pts_allow_7_13", "7-13"), ("pts_allow_14_20", "14-20"),
          ("pts_allow_21_27", "21-27"), ("pts_allow_28_34", "28-34"), ("pts_allow_35p", "35+")]
    txt = ", ".join(dd)
    if any(g(k) for k, _ in pa):
        txt += "; points allowed: " + ", ".join("%s = %s" % (lab, _signed(g(k))) for k, lab in pa)
    ya = [("yds_allow_0_100", "under 100"), ("yds_allow_100_199", "100-199"), ("yds_allow_200_299", "200-299"), ("yds_allow_300_349", "300-349"),
          ("yds_allow_350_399", "350-399"), ("yds_allow_400_449", "400-449"), ("yds_allow_450_499", "450-499"),
          ("yds_allow_500_549", "500-549"), ("yds_allow_550p", "550+")]
    if any(g(k) for k, _ in ya):
        txt += "; yards allowed: " + ", ".join("%s = %s" % (lab, _signed(g(k))) for k, lab in ya)
    if txt:
        rows.append(("Defense / ST", txt, False))
    slots = ", ".join("FLEX (RB, WR or TE)" if s == "FLEX" else "SUPER_FLEX (QB, RB, WR or TE)" if s == "SUPER_FLEX" else s for s in meta["slots"])
    rows.append(("Starting slots", slots, False))
    ir = meta["reserve"]
    rows.append(("Bench", "%d bench spots%s" % (meta["bn"], (" and %d IR spot%s" % (ir, "" if ir == 1 else "s")) if ir else ""), False))
    rec_txt = "%s, %s of %d" % (meta["record"], ordn(meta["rank"]), meta["teams"])
    if meta.get("opponent"):
        rec_txt += "; Week %s opponent %s" % (week, meta["opponent"])
    rows.append(("Your record", rec_txt, False))
    return [[a, b, c] for a, b, c in rows]


# ------------------------------------------------------------------ waiver caption and notes
def waiver_caption(wv):
    top = wv[:10]
    nrb = sum(r["pos"] == "RB" for r in top)
    nwr = sum(r["pos"] == "WR" for r in top)
    base = "The ten highest-projected unrostered RB, WR and TE (Sleeper projection under this league's scoring), sorted by prop-implied points. "
    if len(wv) <= 10:
        return base + "The top ten already include %d WRs and %d RBs, so the list was not extended." % (nwr, nrb)
    return base + "The top ten included %d RB%s and %d WR%s, so the list was extended to %d players to include at least 2 RBs and 2 WRs." % (
        nrb, "" if nrb == 1 else "s", nwr, "" if nwr == 1 else "s", len(wv))


NOTES_STD = ["Projections: Sleeper (Rotowire feed) re-scored to this league's settings.",
             "Props: Fieldwork (DraftKings, FanDuel, BetMGM, BetRivers), cross-checked with Sharp Football Analysis and EVAnalytics. A dash means no line was posted.",
             "Game lines (total and spread) for the Defense table: ESPN (DraftKings).",
             "Lines can move before kickoff; re-check before lock."]


def notes_for(rows, overrides_doc, week):
    n = list(NOTES_STD)
    if overrides_doc and str(overrides_doc.get("week")) == str(week):
        names = {r["name"] for r in rows}
        extra = [v["note"] for k, v in (overrides_doc.get("players") or {}).items() if k in names and v.get("note")]
        for e in extra:
            n.insert(2, e)
    return n


# ------------------------------------------------------------------ quick read
def _day(r):
    m = re.search(r"\((\w{3})\)", r["opp"] or "")
    return m.group(1) if m else None


def _at(r):
    m = re.match(r"(vs|@)\s+(\S+)", r["opp"] or "")
    if not m:
        return ""
    return (" at " if m.group(1) == "@" else " vs ") + m.group(2)


def _short(r, opp=False):
    head = "%s %s%s" % (r["pos"], r["team"], _at(r) if opp else "")
    extra = []
    if r["status"] in ("Questionable", "Doubtful"):
        extra.append(r["status"])
    extra.append("%s proj" % r["proj"])
    if r["pp"] is not None:
        extra.append("%.1f" % r["pp"])
    return "%s (%s, %s)" % (r["name"], head, ", ".join(extra))


def _short_def(r):
    return "%s (%s, %s proj, %.1f prop-implied)" % (r["name"], (r["opp"] or "").split(" (")[0], r["proj"], r["pp"])


def _long(r):
    head = "%s %s%s" % (r["pos"], r["team"], _at(r))
    extra = ["%s proj" % r["proj"]]
    if r["pp"] is not None:
        extra.append("%.1f prop-implied" % r["pp"])
    d = _day(r)
    if d:
        extra.append("Monday night" if d == "Mon" else DAYS.get(d, d))
    if r["status"] in ("Questionable", "Doubtful"):
        extra.append(r["status"])
    return "%s (%s, %s)" % (r["name"], head, ", ".join(extra))


def _list(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _are(names, what):
    return "%s %s %s" % (_list(names), "is" if len(names) == 1 else "are", what)


def quick_read(d):
    st, bn, wv = d["STARTERS"], d["BENCH"], d["WAIVER"]
    flex = next((r for r in st if r["slot"] == "FLEX"), None)
    usable = lambda r: r["status"] not in ("Played", "Bye", "IR", "Out") and r["pp"] is not None  # noqa: E731
    cand = [("Bench " + r["pos"], r) for r in bn if usable(r)] + [("Free agent", r) for r in wv if usable(r)]
    cand.sort(key=lambda t: -t[1]["pp"])
    out = []
    used = set()
    if flex:
        out.append("Your FLEX is %s." % _long(flex) if flex["status"] != "Played" else
                   "Your FLEX is %s (already played: %s)." % (flex["name"], flex["proj"]))
        fpp = flex["pp"] if flex["pp"] is not None else -1
        f1 = round(fpp, 1)
        both = [t for t in cand if round(t[1]["pp"], 1) > f1 and t[1]["pn"] > flex["pn"]]
        level = [t for t in cand if round(t[1]["pp"], 1) == f1 and t[1]["pn"] > flex["pn"]]
        last = flex["name"].split(" ")[-1]
        if both:
            lab, r = both[0]
            late = {"Mon": "Monday night", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday"}.get(_day(r))
            s = "%s %s is ahead of him on both projection and props" % (lab, _short(r, True))
            if late and _day(r) != _day(flex):
                s += ", but plays " + late
            out.append(s + ".")
            used.add(r["name"])
            more = [t for t in both[1:3]]
            if more:
                out.append("Also ahead on both: %s." % _list(["%s %s" % (l.replace("Free agent", "free agent"), _short(x)) for l, x in more]))
                used.update(x["name"] for _, x in more)
        elif level:
            lab, r = level[0]
            out.append("%s %s is level with him on props and has the better projection." % (lab, _short(r, True)))
            used.add(r["name"])
        else:
            close = [t for t in cand[:2]]
            if close:
                out.append("No bench or free-agent option beats %s on both projection and props; the closest %s %s." % (
                    flex["name"], "is" if len(close) == 1 else "are", _list([_short(x) for _, x in close])))
                used.update(x["name"] for _, x in close)
    rest = [t for t in cand if t[1]["name"] not in used]
    nxt = rest[:3]
    best_bn = next((t for t in rest if t[0].startswith("Bench")), None)
    if nxt:
        s = "Next on props: %s." % _list([_short(x) for _, x in nxt])
        if best_bn and best_bn[1]["name"] not in {x["name"] for _, x in nxt}:
            s += " The best bench option is %s." % _short(best_bn[1])
        elif best_bn:
            s += " %s is your best bench option." % best_bn[1]["name"]
        out.append(s)
    elif best_bn:
        out.append("The best bench option is %s." % _short(best_bn[1]))
    # defense bullet: only when there is a clear upgrade
    dfs = d.get("DEFENSE") or []
    sd = next((r for r in dfs if r["slot"] == "DEF"), None)
    fa_d = [r for r in dfs if r["slot"] == "WAIVER" and r["pp"] is not None]
    if sd and fa_d:
        b = fa_d[0]
        if sd["status"] == "Bye":
            out.append("Your defense %s is on bye; the best free-agent defense is %s." % (sd["name"], _short_def(b)))
        elif sd["pp"] is not None and b["pp"] >= sd["pp"] + 1.5:
            out.append("Free-agent defense %s is well ahead of your %s (%s proj, %.1f prop-implied)." % (_short_def(b), sd["name"], sd["proj"], sd["pp"]))
    # status bullet
    played = [r for r in st + bn if r["status"] == "Played"]
    parts = []
    if played:
        days = {_day(r) for r in played}
        when = (" " + DAYS.get(next(iter(days)), "")) if len(days) == 1 else ""
        names = ["%s (%s)" % (r["name"], r["proj"].replace(" final", "")) for r in played]
        parts.append("%s already played%s." % (_list(names), when))
    clauses = []
    for r in st:
        if r["status"] in ("Out", "Doubtful", "Questionable", "Bye", "IR"):
            w = {"Bye": "on bye", "IR": "on IR"}.get(r["status"], r["status"])
            clauses.append("%s (%s) is %s in your lineup" % (r["name"], r["slot"], w))
    bo = [r["name"] for r in bn if r["status"] == "Out"]
    if bo:
        clauses.append(_are(bo, "Out on your bench"))
    bi = [r["name"] for r in bn if r["status"] == "IR"]
    if bi:
        clauses.append(_are(bi, "on IR"))
    bb = [r["name"] for r in bn if r["status"] == "Bye"]
    if bb:
        clauses.append(_are(bb, "on bye"))
    if clauses:
        s = ", ".join(clauses[:-1]) + (", and " if len(clauses) > 2 else " and ") + clauses[-1] if len(clauses) > 1 else clauses[0]
        parts.append(s[0].upper() + s[1:] + ".")
    if parts:
        out.append(" ".join(parts))
    return out


# ------------------------------------------------------------------ as-of text
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt(d, tzname):
    h = d.hour % 12 or 12
    ap = "AM" if d.hour < 12 else "PM"
    return "%s %d, %d:%02d %s" % (MON[d.month - 1], d.day, h, d.minute, ap) if tzname == "ET" else \
        "%s %d, %02d:%02d" % (MON[d.month - 1], d.day, d.hour, d.minute)


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def asof_text(src):
    from zoneinfo import ZoneInfo
    bits = []
    p = src.get("props_asof")
    if p:
        u = parse_iso(p)
        e = u.astimezone(ZoneInfo("America/New_York"))
        bits.append("Props as of %s ET (%s UTC)" % (_fmt(e, "ET"), _fmt(u, "UTC")))
    else:
        bits.append("Props not available")
    s = src.get("proj_asof")
    bits.append("Sleeper projections as of %s UTC" % _fmt(parse_iso(s), "UTC") if s else "Sleeper projections not available")
    f = src.get("fp_asof")
    bits.append("FantasyPros ranks as of %s UTC" % _fmt(parse_iso(f), "UTC") if f else "FantasyPros ranks not available")
    g = src.get("lines_asof")
    bits.append("game lines as of %s UTC" % _fmt(parse_iso(g), "UTC") if g else "game lines not available")
    return "; ".join(bits) + "."
