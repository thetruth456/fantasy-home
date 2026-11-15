"""Turns raw source data into report rows, quick-read bullets, league setup text and as-of lines."""
import datetime as dt
import re

from sources import norm, log

SKIP_PROPS = ("Played", "Bye", "IR")
# Same availability screen the waiver list uses. Kickers on waivers use this list too.
HELD_OUT = ("Out", "IR", "PUP", "Sus", "NA", "Doubtful")
KICKER_N = 10
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
        self.kicker_markets = kicker_market_names(fw)

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


def is_kicker_market(m):
    s = (m or "").lower()
    return s.startswith("player_fg") or any(x in s for x in ("kick", "field_goal", "extra_point", "kicking"))


def kicker_market_names(fw):
    """Market ids that belong to kickers. Empty when the prop source has no kicker lines (do not invent any)."""
    found = set()
    for p in fw.get("players") or []:
        cells = p.get("cells") or {}
        if p.get("position") != "K" and not any(is_kicker_market(m) for m in cells):
            continue
        for m in cells:
            if p.get("position") == "K" or is_kicker_market(m):
                found.add(m)
    return sorted(found)


def _num(stats, key):
    v = (stats or {}).get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def score_kicker(S, stats):
    """League kicking score for a Sleeper stat line.

    Sleeper projections publish one 50+ bucket (fgm_50p), not a 50-59 / 60+ split. A league that pays
    extra for 60+ is scored at its 50-59 rate for that combined bucket; the 60+ share is not invented.
    Actuals sometimes repeat the same make as both fgm_50_59 and fgm_50p; it is counted once.
    A total fgm with no distance buckets is not scored (the distance is unknown). Flat fgm / fgmiss
    league keys are used only when that league does not score distance buckets.
    """
    S, stats = S or {}, stats or {}
    total = 0.0
    buckets = ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49")
    has_distance = any(S.get(k) for k in buckets) or any(S.get(k) for k in ("fgm_50p", "fgm_50_59", "fgm_60p"))
    if has_distance:
        for key in buckets:
            if S.get(key):
                total += S[key] * _num(stats, key)
        n59, n60, n50 = _num(stats, "fgm_50_59"), _num(stats, "fgm_60p"), _num(stats, "fgm_50p")
        if n59 or n60:
            if S.get("fgm_50_59") or S.get("fgm_60p"):
                if S.get("fgm_50_59"):
                    total += S["fgm_50_59"] * n59
                elif S.get("fgm_50p"):
                    total += S["fgm_50p"] * n59
                if n60:
                    if S.get("fgm_60p"):
                        total += S["fgm_60p"] * n60
                    elif S.get("fgm_50_59"):
                        total += S["fgm_50_59"] * n60
                    elif S.get("fgm_50p"):
                        total += S["fgm_50p"] * n60
            elif S.get("fgm_50p"):
                total += S["fgm_50p"] * (n59 + n60)
        elif n50:
            if S.get("fgm_50p"):
                total += S["fgm_50p"] * n50
            elif S.get("fgm_50_59"):
                total += S["fgm_50_59"] * n50
            elif S.get("fgm_60p"):
                total += S["fgm_60p"] * n50
    elif S.get("fgm"):
        total += S["fgm"] * (_num(stats, "fgm") or sum(_num(stats, k) for k in buckets))
    if S.get("xpm"):
        total += S["xpm"] * _num(stats, "xpm")
    if S.get("xpmiss"):
        total += S["xpmiss"] * _num(stats, "xpmiss")
    miss_parts = ("fgmiss_0_19", "fgmiss_20_29", "fgmiss_30_39", "fgmiss_40_49")
    m59, m60, m50 = _num(stats, "fgmiss_50_59"), _num(stats, "fgmiss_60p"), _num(stats, "fgmiss_50p")
    miss = sum(_num(stats, k) for k in miss_parts) + ((m59 + m60) if (m59 or m60) else m50)
    if S.get("fgmiss"):
        if not miss:
            miss = _num(stats, "fgmiss")
        total += S["fgmiss"] * miss
    else:
        for key in miss_parts + ("fgmiss_50_59", "fgmiss_60p", "fgmiss_50p"):
            if S.get(key):
                total += S[key] * _num(stats, key)
    return total


def _fg_parts(stats):
    """Sleeper's made-field-goal buckets. A 50-59/60+ split replaces fgm_50p so the same make is not counted twice."""
    stats = stats or {}
    if _num(stats, "fgm_50_59") or _num(stats, "fgm_60p"):
        keys = ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgm_60p")
    else:
        keys = ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50p")
    parts = {k: _num(stats, k) for k in keys}
    return parts, sum(parts.values())


def _flat_fg_rate(S):
    keys = ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50p", "fgm_50_59", "fgm_60p")
    rates = [S[k] for k in keys if S.get(k)]
    if rates and all(r == rates[0] for r in rates):
        return rates[0]
    return None


def kicker_implied(S, stats, fg_line, kp_line):
    """League points from posted kicker over/unders. None when a number would require a guess.

    Kicking points are the usual sportsbook stat: 3 per field goal made plus 1 per extra point.
    When both lines are posted and extra points = kicking points - 3 * field goals is between 0 and 8,
    field goals are scaled onto Sleeper's distance mix and extra points use that identity.
    One line scales Sleeper's field-goal and extra-point shape so the posted stat matches.
    Misses are not in these markets and are not deducted. Sleeper's 50+ bucket stays one bucket.
    """
    if fg_line is None and kp_line is None:
        return None
    S = S or {}
    parts, fg_tot = _fg_parts(stats)
    xp_s = _num(stats, "xpm")

    def finish(scaled, xp):
        scaled = dict(scaled)
        scaled["xpm"] = xp
        return score_kicker(S, scaled)

    if fg_line is not None and kp_line is not None:
        xp = float(kp_line) - 3.0 * float(fg_line)
        if xp < -0.05 or xp > 8.05:
            return None
        xp = max(0.0, xp)
        if float(fg_line) == 0:
            return finish({k: 0.0 for k in parts}, xp)
        if fg_tot > 0:
            factor = float(fg_line) / fg_tot
            return finish({k: v * factor for k, v in parts.items()}, xp)
        rate = _flat_fg_rate(S)
        if rate is None:
            return None
        return rate * float(fg_line) + (S.get("xpm") or 0) * xp
    if fg_line is not None:
        if fg_tot <= 0:
            return None
        factor = float(fg_line) / fg_tot
        return finish({k: v * factor for k, v in parts.items()}, xp_s * factor)
    base = 3.0 * fg_tot + xp_s
    if base <= 0:
        return None
    factor = float(kp_line) / base
    return finish({k: v * factor for k, v in parts.items()}, xp_s * factor)


class KickerProps:
    """Two-way kicker lines keyed by normalized name. lookup returns {fg, kp, team} or None."""

    def __init__(self, rows):
        self.idx = {}
        for r in rows or []:
            self.idx.setdefault(norm(r["name"]), []).append(r)

    def lookup(self, name, team):
        c = self.idx.get(norm(name), [])
        if len(c) > 1:
            same = [p for p in c if team_norm(p.get("team")) == team_norm(team)]
            c = same or c[:1]
        return c[0] if c else None


def def_pp(S, stats, opp_total):
    """Prop-implied DEF points: Sleeper's projected stat line scored with the league settings, with the points-allowed buckets
    swapped for the expected score under the opponent's implied total. Yards-allowed buckets stay as Sleeper projects them."""
    base = sum(S[k] * v for k, v in stats.items()
               if k in S and S[k] and isinstance(v, (int, float)) and not k.startswith("pts_allow"))
    return base + pa_expected(S, opp_total)


# ------------------------------------------------------------------ rows
def weather_cell(ctx, team, opp, prev):
    """Display string for one player. Bye is explicit. None in the weather map means keep the previous cell."""
    if opp == "BYE":
        return "Bye"
    if not team:
        return DASH
    wx = ctx.get("wx") if isinstance(ctx, dict) else None
    if not isinstance(wx, dict):
        return (prev or {}).get("wx") or DASH
    key = team_norm(team)
    if key not in wx or wx.get(key) is None:
        return (prev or {}).get("wx") or DASH
    return wx[key]


def build_league(ctx, bundle, user_id, props, fp, flex_page, prev_rows, prev_def=None, prev_kick=None):
    """ctx: dict(week, players, proj{pid:entry}, stats{pid:stats}, games{team:(game,'vs'|'@',other)}, wx{team:text})."""
    L, R = bundle["league"], bundle["rosters"]
    S = L["scoring_settings"]
    P, proj, STD, games = ctx["players"], ctx["proj"], ctx["stats"], ctx["games"]

    def pts(s, pos=None):
        if pos == "K":
            return score_kicker(S, s or {})
        return sum(S[k] * v for k, v in (s or {}).items() if k in S and S[k] and isinstance(v, (int, float)))

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
        pt = round(pts(x["stats"], pos), 1) if x else 0
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
        fg_txt, kp_txt = DASH, DASH
        if pos == "K" and status not in SKIP_PROPS:
            book = ctx.get("kicker_props") if isinstance(ctx, dict) else None
            old = prev_rows.get((nm, team)) or {}
            if book is None:
                pr = dict(base)
                if old.get("pp") is not None:
                    pr["pp"] = old.get("pp")
                    pr["partial"] = bool(old.get("partial"))
                fg_txt = old.get("fg") or DASH
                kp_txt = old.get("kp") or DASH
            else:
                hit = book.lookup(nm, team) or {}
                fg_line, kp_line = hit.get("fg"), hit.get("kp")
                fg_txt = num(fg_line) if isinstance(fg_line, (int, float)) else DASH
                kp_txt = num(kp_line) if isinstance(kp_line, (int, float)) else DASH
                implied = kicker_implied(S, (x or {}).get("stats") if x else {}, fg_line, kp_line)
                pr = dict(base)
                if implied is not None:
                    pr["pp"] = implied
                    pr["partial"] = fg_line is None or kp_line is None
        elif status in SKIP_PROPS or pos not in ("RB", "WR", "TE"):
            pr = base
        elif props is not None:
            pr = props.get(nm, team)
        else:  # props source unavailable: reuse the previous snapshot for this player (same week only), else dashes
            old = prev_rows.get((nm, team))
            pr = {k: old[k] for k in base} if old else base
        if status == "Played":
            a = STD.get(pid)
            act = round(pts(a, pos), 2) if a else 0
            projs = "%.1f final" % act
        else:
            projs = "%.1f" % pt
        partial = False
        if pos == "K":
            partial = bool(pr.get("partial"))
        elif props is not None and pr.get("pp") is not None and pos in ("RB", "WR", "TE"):
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
        d["wx"] = weather_cell(ctx, team, opp, prev_rows.get((nm, team)))
        if pos == "K":
            d["fg"], d["kp"] = fg_txt, kp_txt
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
        if (q.get("injury_status") or "") in HELD_OUT:
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

    try:
        kickers = build_kickers(ctx, info, row, S, me, rost)
    except Exception as e:  # noqa: BLE001
        log("WARNING: kicker table failed (%s); keeping its previous rows" % e)
        kickers = list(prev_kick or [])

    lineup = lineup_check(st, bn, labels, rp, me["starters"])
    s = me.get("settings", {})
    srt = sorted(R, key=lambda r: (-r["settings"].get("wins", 0), -(r["settings"].get("fpts", 0) + r["settings"].get("fpts_decimal", 0) / 100)))
    rank = [r["roster_id"] for r in srt].index(me["roster_id"]) + 1
    record = "%d-%d%s" % (s.get("wins", 0), s.get("losses", 0), ("-%d" % s["ties"]) if s.get("ties") else "")
    opp_name = opponent_name(bundle, me)
    return dict(STARTERS=st, BENCH=bn, WAIVER=wv, DEFENSE=defense, KICKERS=kickers, meta=dict(
        name=L["name"], league_id=L["league_id"], teams=L["total_rosters"], season=L.get("season"),
        record=record, rank=rank, opponent=opp_name, slots=rp, bn=L["roster_positions"].count("BN"),
        reserve=L["settings"].get("reserve_slots") or 0, scoring=S, lineup=lineup))


# ------------------------------------------------------------------ lineup check (top-of-report banner)
FLEX_OK = {"FLEX": ("RB", "WR", "TE"), "WRRB_FLEX": ("RB", "WR"), "REC_FLEX": ("WR", "TE"),
           "SUPER_FLEX": ("QB", "RB", "WR", "TE"), "IDP_FLEX": ("DL", "LB", "DB")}
NO_PLAY = ("Out", "IR", "Bye", "Suspended", "Sus", "PUP", "NA")


def lineup_check(st, bn, labels, rp, starters):
    """Is the current lineup the best legal one? Best lineup = Sleeper projection (the report's 'Sleeper proj' column).
    A swap is flagged only on the report's own rule: the bench player is ahead on BOTH projection and prop-implied points
    (projection alone when either has no prop line, e.g. QB/K/DEF), or the starter is Out/IR/on bye.
    Starters whose game is already played stay put; empty slots count as not optimal.
    Returns dict(ok, swaps=[text], issues=[text])."""
    by_slot = {r["slot"]: r for r in st}
    val = lambda r: 0.0 if r["status"] in NO_PLAY else r["pn"]  # noqa: E731
    free = []          # (label, base slot type) still changeable
    cur = []           # rows currently in the free slots
    empty = []
    for lab, typ, pid in zip(labels, rp, list(starters) + ["0"] * (len(rp) - len(starters))):
        r = by_slot.get(lab) if pid and pid != "0" else None
        if r is not None and r["status"] == "Played":
            continue
        free.append((lab, typ))
        if r is None:
            empty.append(lab)
        else:
            cur.append(r)
    pool = [r for r in cur + [b for b in bn if b["status"] not in ("Played",)] if r["status"] not in NO_PLAY]
    pool.sort(key=lambda r: -r["pn"])
    used, best = set(), []
    order = sorted(free, key=lambda f: (f[1] in FLEX_OK, len(FLEX_OK.get(f[1], ()))))
    for lab, typ in order:
        ok = FLEX_OK.get(typ, (typ,))
        c = next((r for r in pool if id(r) not in used and r["pos"] in ok), None)
        if c is not None:
            used.add(id(c)); best.append(c)
    cur_tot = sum(val(r) for r in cur)
    best_tot = sum(r["pn"] for r in best)
    ins = [r for r in best if all(r is not x for x in cur)]
    outs = [r for r in cur if all(r is not x for x in best)]
    ins.sort(key=lambda r: -r["pn"]); outs.sort(key=val)
    swaps = []
    if best_tot - cur_tot > 0.05:
        for r in ins:
            o = next((x for x in outs if x["pos"] == r["pos"]), outs[0] if outs else None)
            if o is not None:
                outs.remove(o)
                if o["status"] not in NO_PLAY and not (r["pn"] > o["pn"] and (r["pp"] is None or o["pp"] is None or r["pp"] > o["pp"])):
                    continue  # ahead on projection only: the report's advice keeps the starter
                why = o["status"] if o["status"] in NO_PLAY else "%.1f" % o["pn"]
                swaps.append("start %s (%.1f) over %s (%s)" % (r["name"], r["pn"], o["name"], why))
            else:
                swaps.append("start %s (%.1f) in an empty slot" % (r["name"], r["pn"]))
    issues = []
    for r in cur:
        if r["status"] in NO_PLAY and not any(r is x for x in best) and not any(r["name"] in s_ for s_ in swaps):
            issues.append("%s is %s with no bench replacement" % (r["name"], r["status"]))
    n_empty_left = len(empty) - max(0, len(best) - len(cur))
    if empty and n_empty_left > 0:
        issues.append("%d empty starting slot%s" % (n_empty_left, "" if n_empty_left == 1 else "s"))
    return dict(ok=not swaps and not issues, swaps=swaps, issues=issues)


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


def build_kickers(ctx, info, row, S, me, rost):
    """Your kickers (starter, then bench), then the best available unrostered kickers, up to 10 rows.

    Availability matches the waiver list: has a team, game not yet complete, not Out/IR/Doubtful/PUP/Sus/NA.
    Ranked by this league's kicking score of the Sleeper projection. Rostered kickers stay even on a bye
    or after they have played. The table is shorter when fewer kickers qualify; nobody is invented.
    Prop-implied points stay empty: the prop source does not post kicker markets."""
    proj, games = ctx["proj"], ctx["games"]
    starters = set(me.get("starters") or [])
    mine = []
    for pid in me.get("players") or []:
        q = info(pid)
        if q.get("position") == "K":
            mine.append(row(pid, "K" if pid in starters else "BN"))
    mine.sort(key=lambda r: (r["slot"] != "K", -r["pn"], r.get("sid") or ""))
    cands = []
    for pid, x in proj.items():
        q = info(pid)
        if pid in rost or q.get("position") != "K" or not q.get("team"):
            continue
        g = games.get(q["team"])
        if not g or g[0].get("status") == "complete":
            continue
        if (q.get("injury_status") or "") in HELD_OUT:
            continue
        cands.append((score_kicker(S, x.get("stats") or {}), pid))
    cands.sort(key=lambda t: (-t[0], t[1]))
    room = KICKER_N - len(mine)
    fa = [row(pid, "WAIVER") for _, pid in cands[:room]] if room > 0 else []
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
    base = "The ten highest-projected unrostered RB, WR and TE (Sleeper projection under this league's scoring), sorted by prop-implied points. Weather is the kickoff forecast at the game's actual stadium; data notes explain (dome), (roof ?) and (covered). "
    if len(wv) <= 10:
        return base + "The top ten already include %d WRs and %d RBs, so the list was not extended." % (nwr, nrb)
    return base + "The top ten included %d RB%s and %d WR%s, so the list was extended to %d players to include at least 2 RBs and 2 WRs." % (
        nrb, "" if nrb == 1 else "s", nwr, "" if nwr == 1 else "s", len(wv))


NOTES_STD = ["Projections: Sleeper (Rotowire feed) re-scored to this league's settings.",
             "Props: Fieldwork (DraftKings, FanDuel, BetMGM, BetRivers), cross-checked with Sharp Football Analysis and EVAnalytics. A dash means no line was posted.",
             "Kickers: your kickers, then the best available unrostered kickers, up to 10 (same availability rules as the waiver list). Sleeper proj uses this league's kicking settings. FG made and kicking points are the PrizePicks two-way over/under (standard line only; alternate and over-only prices are ignored). Kicking points mean 3 per field goal and 1 per extra point. When both lines are posted, extra points are kicking points minus 3 times field goals, and field goals are spread with Sleeper's distance mix. One line scales that Sleeper shape so the posted stat matches. Misses are not in the markets and are not deducted. A dash means the line was not posted, or scoring it would require a guess. Sleeper's 50+ makes are one bucket; a league that pays more for 60+ is scored at its 50-59 rate for that bucket.",
             "Game lines (total and spread) for the Defense table: ESPN (DraftKings).",
             "Weather: Open-Meteo hourly forecast at the kickoff hour at the stadium on the ESPN schedule, including neutral and international sites (the home city's weather is not assumed). (dome) is a confirmed fixed roof and is not an outdoor forecast. (roof ?) is a retractable roof; the numbers are outdoor, and the roof may be closed. (covered) is SoFi's fixed canopy: outdoor temperature and wind, and precipitation may not reach the field. (indoor ?) is an unrecognized indoor building, with no outdoor numbers. (final) has been played; (kickoff) is in progress. Bye, no forecast (past the 16-day horizon), no obs, and a dash were not filled in.",
             "Lines and forecasts can move before kickoff; re-check before lock."]


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


def _kicker_bullet(d):
    """One line when the starter kicker is on bye, or a free agent is clearly ahead. No prop is invented."""
    ks = d.get("KICKERS") or []
    sk = next((r for r in ks if r.get("slot") == "K"), None)
    fa = [r for r in ks if r.get("slot") == "WAIVER" and r.get("status") not in ("Played", "Bye")]
    if not sk or not fa:
        return None
    b = max(fa, key=lambda r: (r.get("pn") or 0, r.get("pp") if r.get("pp") is not None else -1))
    if sk.get("status") == "Bye":
        return "Your kicker %s is on bye; the best free-agent kicker is %s (%s proj)." % (sk["name"], b["name"], b["proj"])
    if sk.get("status") == "Played":
        return None
    proj_ahead = (b.get("pn") or 0) >= (sk.get("pn") or 0) + 1.5
    if sk.get("pp") is not None and b.get("pp") is not None:
        if proj_ahead and b["pp"] >= sk["pp"] + 1.5:
            return ("Free-agent kicker %s (%.1f prop-implied, %s proj) is ahead of your %s (%.1f prop-implied, %s proj)."
                    % (b["name"], b["pp"], b["proj"], sk["name"], sk["pp"], sk["proj"]))
        return None
    if proj_ahead and sk.get("pp") is None and b.get("pp") is None:
        return ("Free-agent kicker %s (%s proj) is ahead of your %s (%s proj). No kicker prop was posted."
                % (b["name"], b["proj"], sk["name"], sk["proj"]))
    return None


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
    kick = _kicker_bullet(d)
    if kick:
        out.append(kick)
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
    w = src.get("weather_asof")
    bits.append("weather as of %s UTC" % _fmt(parse_iso(w), "UTC") if w else "weather not available")
    k = src.get("kicker_props_asof")
    bits.append("kicker props as of %s UTC" % _fmt(parse_iso(k), "UTC") if k else "kicker props not available")
    return "; ".join(bits) + "."


# ------------------------------------------------------------------ playoff schedule, trades, waivers
PLAYOFF_WEEKS = (15, 16, 17)
SOS_POS = ("QB", "RB", "WR", "TE", "K", "DEF")
SKILL_POS = ("QB", "RB", "WR", "TE")
SIT_STATUS = {"IR", "PUP", "SUS", "NA"}
SOS_NOTE = ("Playoff SOS is Weeks 15-17 opponent fantasy points allowed to that position, divided by the league average of the same number. "
            "Above 1.00 is an easier slate. A dash means the player's team, a playoff opponent, or the points-allowed baseline was missing.")


def score_stats(S, stats, pos):
    """League points for one stat line. Kickers use the kicking buckets; everyone else uses the scoring keys that are set."""
    if pos == "K":
        return score_kicker(S, stats or {})
    return sum(S[k] * v for k, v in (stats or {}).items() if k in S and S[k] and isinstance(v, (int, float)) and not isinstance(v, bool))


def schedule_complete(schedule, week):
    gs = [g for g in schedule or [] if g.get("week") == week]
    return bool(gs) and all(g.get("status") == "complete" for g in gs)


def week_matchups(schedule):
    """{week: {nfl team: opponent}} using the same team codes as the rest of the report."""
    out = {}
    for g in schedule or []:
        w, h, a = g.get("week"), g.get("home"), g.get("away")
        if w is None or not h or not a:
            continue
        out.setdefault(w, {})
        out[w][team_norm(h)] = team_norm(a)
        out[w][team_norm(a)] = team_norm(h)
    return out


def points_allowed(schedule, week_stats, pos_of, score_fn, weeks):
    """Average fantasy points each NFL team allowed to a position group, per game it played.

    week_stats: {week: [ {player_id, team, stats}, ... ]} for weeks that are already final.
    A position group's points are the sum of every player at that position who faced the team.
    Returns (by_team, league). by_team[team][pos] is that average. league[pos] is the average
    across team-games. A position with no team-game is left out of league.
    """
    opp = week_matchups(schedule)
    tot, games = {}, {}
    for w in weeks:
        pairs = opp.get(w) or {}
        if not pairs:
            continue
        for tm in pairs:
            games[tm] = games.get(tm, 0) + 1
        for e in week_stats.get(w) or []:
            tm = team_norm(e.get("team") or "")
            if not tm or tm not in pairs:
                continue
            pos = pos_of(e.get("player_id"))
            if pos not in SOS_POS:
                continue
            dst = pairs[tm]
            bucket = tot.setdefault(dst, {})
            bucket[pos] = bucket.get(pos, 0.0) + float(score_fn(e.get("stats") or {}, pos) or 0)
    by, league_pts, league_g = {}, {p: 0.0 for p in SOS_POS}, {p: 0 for p in SOS_POS}
    for tm, n in games.items():
        if n <= 0:
            continue
        by[tm] = {}
        for p in SOS_POS:
            pts = (tot.get(tm) or {}).get(p, 0.0)
            by[tm][p] = pts / n
            league_pts[p] += pts
            league_g[p] += n
    league = {p: league_pts[p] / league_g[p] for p in SOS_POS if league_g[p]}
    return by, league


def playoff_index(team, pos, schedule, allowed, league, weeks=PLAYOFF_WEEKS):
    """Mean points the playoff opponents allow to this position, divided by the league average.

    Byes are skipped. None when the team, the position, or every playoff opponent is missing.
    Nothing is filled in from a guess.
    """
    if not team or pos not in SOS_POS or not league or not league.get(pos):
        return None
    opp = week_matchups(schedule)
    vals = []
    for w in weeks:
        other = (opp.get(w) or {}).get(team_norm(team))
        if not other:
            continue
        cell = (allowed.get(other) or {}).get(pos)
        if cell is None:
            continue
        vals.append(cell)
    if not vals:
        return None
    return round((sum(vals) / len(vals)) / league[pos], 2)


def apply_sos(groups, allowed, league, schedule, weeks=PLAYOFF_WEEKS):
    for rows in groups:
        for r in rows or []:
            r["sos"] = playoff_index(r.get("team"), r.get("pos"), schedule, allowed, league, weeks)


def positional_rank(pos, text):
    """Integer rank from a FantasyPros positional label such as 'RB18'. None when the label is a different position."""
    if text is None or not pos:
        return None
    raw = str(text).strip().upper().replace("-", "")
    m = re.match(r"^([A-Z]+)?\s*(\d+)$", raw)
    if not m:
        return None
    prefix, num = m.group(1), int(m.group(2))
    if num < 1:
        return None
    if prefix and prefix != str(pos).upper():
        return None
    return num


def _sitting(status):
    return str(status or "").strip().upper() in SIT_STATUS


def _player_identity(pid, players, proj_row):
    q = dict((players or {}).get(str(pid)) or {})
    pl = (proj_row or {}).get("player") or {}
    if proj_row and proj_row.get("team"):
        q["team"] = proj_row["team"]
    if not q.get("position") and pl.get("position"):
        q["position"] = pl["position"]
    if pl.get("injury_status"):
        q["injury_status"] = pl["injury_status"]
    if not q.get("full_name"):
        q["full_name"] = ((pl.get("first_name") or "") + " " + (pl.get("last_name") or "")).strip()
    pos = q.get("position") or ""
    name = (q.get("full_name") or str(pid)).replace(" Sr.", "").strip() or str(pid)
    if pos == "DEF" and q.get("team"):
        name = q["team"] + " D/ST"
    return name, pos, q.get("team") or "", q.get("injury_status") or ""


def roster_values(rosters, players, lookup, proj_by_pid, score_fn):
    """pid -> {name, pos, team, rank, status, proj}.

    rank is the rest-of-season positional rank when lookup returns one.
    When no rostered player has one, rank is 1..n by full-season projection among
    rostered players at that position (1 = highest). The second return is 'ros',
    'proj', or 'none', so the report can say which one it used.
    """
    ids, seen = [], set()
    for r in rosters or []:
        for bucket in ("players", "reserve", "taxi"):
            for pid in r.get(bucket) or []:
                pid = str(pid)
                if pid and pid != "0" and pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
    values = {}
    for pid in ids:
        proj_row = (proj_by_pid or {}).get(pid)
        name, pos, team, status = _player_identity(pid, players, proj_row)
        rank = None
        if lookup and pos:
            hit = lookup(name, team, pos)
            if hit:
                rank = positional_rank(pos, hit[1] if len(hit) > 1 else None)
        proj = None
        stats = (proj_row or {}).get("stats") if proj_row else None
        if stats and pos and score_fn:
            try:
                proj = float(score_fn(stats, pos))
            except (TypeError, ValueError):
                proj = None
        values[pid] = dict(name=name, pos=pos, team=team, rank=rank, status=status or "", proj=proj)
    if any(isinstance(v.get("rank"), int) and not isinstance(v.get("rank"), bool) for v in values.values()):
        return values, "ros"
    by_pos = {}
    for pid, v in values.items():
        if v.get("pos") and isinstance(v.get("proj"), (int, float)) and not isinstance(v.get("proj"), bool):
            by_pos.setdefault(v["pos"], []).append(pid)
    ranked = False
    for pids in by_pos.values():
        pids.sort(key=lambda pid: (-values[pid]["proj"], values[pid]["name"], pid))
        for i, pid in enumerate(pids, 1):
            values[pid]["rank"] = i
            ranked = True
    return values, ("proj" if ranked else "none")


def _owner_name(users, roster):
    u = next((u for u in users or [] if u.get("user_id") == roster.get("owner_id")), None) or {}
    md = u.get("metadata") or {}
    name = (md.get("team_name") or u.get("display_name") or u.get("username") or "").strip()
    user = (u.get("display_name") or u.get("username") or "").strip()
    return name or ("Team %s" % roster.get("roster_id")), user


def trade_targets(rosters, users, user_id, values, slots, nteams, source):
    """Other teams that are deep where this user's team is thin, and the spare players.

    Starter-quality means a positional rank at or better than one per dedicated starting
    slot across the league (12 teams and 2 RB slots -> RB24 or better). IR, PUP, Sus and
    NA do not count. A team is thin when it has fewer starter-quality players than its
    dedicated slots, and deep when it has more. Candidates are the extras past the
    players that team needs for its own slots, best rank first. The user's own players
    are never candidates.
    """
    slots = [s for s in (slots or []) if s not in ("BN", "IR", "TAXI")]
    dedicated = {p: sum(1 for s in slots if s == p) for p in SKILL_POS}
    me = next((r for r in rosters or [] if str(r.get("owner_id")) == str(user_id)), None)
    label = {"ros": "FantasyPros rest-of-season positional rank",
             "proj": "Sleeper full-season projection (rest-of-season ranks were missing)"}.get(source, source or "")

    def held(r):
        out, seen = [], set()
        for bucket in ("players", "reserve"):
            for pid in r.get(bucket) or []:
                pid = str(pid)
                if pid and pid != "0" and pid not in seen:
                    seen.add(pid)
                    out.append(pid)
        return out

    if me is None:
        return dict(team="", user="", source=label, positions=[], note="Your roster was not in this league, so no trade target was named.")
    my_name, my_user = _owner_name(users, me)
    ranked = [v for v in (values or {}).values() if isinstance(v.get("rank"), int) and not isinstance(v.get("rank"), bool)]
    if not ranked:
        return dict(team=my_name, user=my_user, source=label, positions=[],
                    note="No rest-of-season ranks or projections were available, so no trade target was named.")
    try:
        nteams = int(nteams)
    except (TypeError, ValueError):
        nteams = 0
    if nteams < 1:
        return dict(team=my_name, user=my_user, source=label, positions=[], note="League size was missing, so no trade target was named.")

    def quality(r, pos, bar):
        rows = []
        for pid in held(r):
            v = (values or {}).get(pid) or {}
            if v.get("pos") != pos:
                continue
            rank = v.get("rank")
            rank = rank if isinstance(rank, int) and not isinstance(rank, bool) else None
            ok = rank is not None and 1 <= rank <= bar and not _sitting(v.get("status"))
            rows.append(dict(name=v.get("name") or pid, rank=rank, nfl=v.get("team") or "", startable=bool(ok)))
        rows.sort(key=lambda x: (not x["startable"], x["rank"] is None, x["rank"] if x["rank"] is not None else 10 ** 9, x["name"]))
        return rows

    positions = []
    for pos in SKILL_POS:
        need = dedicated[pos]
        if need <= 0:
            continue
        bar = nteams * need
        mine = quality(me, pos, bar)
        have = sum(1 for x in mine if x["startable"])
        if have >= need:
            continue
        teams = []
        for r in rosters or []:
            if r.get("roster_id") == me.get("roster_id"):
                continue
            theirs = [x for x in quality(r, pos, bar) if x["startable"]]
            if len(theirs) <= need:
                continue
            name, user = _owner_name(users, r)
            teams.append(dict(name=name, user=user, have=len(theirs),
                              candidates=[dict(name=c["name"], rank=c["rank"], nfl=c["nfl"]) for c in theirs[need:need + 3]]))
        teams.sort(key=lambda t: (-t["have"], t["candidates"][0]["rank"] if t["candidates"] else 10 ** 9, t["name"]))
        yours = sorted(mine, key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 10 ** 9, x["name"]))
        positions.append(dict(pos=pos, need=need, have=have, bar=bar,
                              yours=[dict(name=x["name"], rank=x["rank"], nfl=x["nfl"], startable=x["startable"]) for x in yours[:8]],
                              teams=teams[:4]))
    note = "" if positions else "No position is short of starter-quality players."
    return dict(team=my_name, user=my_user, source=label, positions=positions, note=note)


def waiver_snapshot(league, rosters, users, user_id):
    """FAAB remaining, or waiver priority when the league does not use FAAB.

    Sleeper waiver_type 0 is rolling priority even when a budget number is set.
    Remaining is the league budget minus waiver_budget_used. A negative used
    amount is left as Sleeper reported it.
    """
    st = (league or {}).get("settings") or {}
    try:
        wtype = int(st.get("waiver_type") or 0)
    except (TypeError, ValueError):
        wtype = 0
    try:
        budget = int(st.get("waiver_budget") or 0)
    except (TypeError, ValueError):
        budget = 0
    faab = wtype != 0 and budget > 0
    rows = []
    for r in rosters or []:
        s = r.get("settings") or {}
        name, user = _owner_name(users, r)
        you = str(r.get("owner_id")) == str(user_id)
        if faab:
            used = s.get("waiver_budget_used")
            if isinstance(used, bool) or not isinstance(used, (int, float)):
                used_n, rem = None, None
            else:
                used_n = int(used) if float(used) == int(used) else used
                rem = budget - used_n
            rows.append(dict(name=name, user=user, you=you, used=used_n, remaining=rem))
        else:
            pos = s.get("waiver_position")
            pos = None if isinstance(pos, bool) or not isinstance(pos, (int, float)) else int(pos)
            rows.append(dict(name=name, user=user, you=you, priority=pos))
    if faab:
        rows.sort(key=lambda x: (x["remaining"] is None, -(x["remaining"] if x["remaining"] is not None else 0), x["name"]))
        return dict(mode="faab", budget=budget, rows=rows)
    rows.sort(key=lambda x: (x["priority"] is None, x["priority"] if x["priority"] is not None else 10 ** 9, x["name"]))
    return dict(mode="priority", rows=rows)
