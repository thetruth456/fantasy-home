"""Future injury / absence model for tools/power.py (stdlib only).

Rates are estimated from Sleeper game logs, fantasy-relevant players, 2021-2025 regular seasons (2020 left out: COVID absences), weeks 1-17
(reproduce with: python tools/injury.py). A player is "relevant" if his Sleeper preseason projection ranked him in the
top 24 QB / 48 RB / 72 WR / 18 TE / 12 K. Absence = his NFL team played and he did not (gp = 0 or no stat line), so it counts
injuries, illness, suspensions, benchings and releases alike; getting hurt during a game he started is not an absence (that
stays in the weekly scoring noise).
* HAZARD[pos] = P(misses this game | played his team's previous game).
* When a starter is out, the best legal lineup re-forms from the rest of the roster plus two waiver fill-ins per position
  (fa_floor: the 3rd- and 4th-best unrostered players there), so bench depth fills in and an empty slot is not scored as zero.
* DUR = how many team games an absence lasts (Kaplan-Meier over runs, so stints still open at week 17 count as censored);
  "rest" = share that lasts the rest of the season. Pooled over RB/WR/TE/K (too few runs per position); QB separate
  (QB absences include benchings and run longer). Durations count team games, so NFL byes do not use them up.
Defenses never miss games.
"""
import bisect, math, random, collections, sys

HAZARD = {"QB": 0.057, "RB": 0.064, "WR": 0.064, "TE": 0.064, "K": 0.021, "DEF": 0.0}   # n games: 1566 / 3064 / 4551 / 1169 / 817
DUR = {  # games out: probability; "rest" = out for the rest of the season (581 skill stints, 90 QB stints)
    "skill": {1: 0.368, 2: 0.175, 3: 0.111, 4: 0.08, 5: 0.048, 6: 0.022, 7: 0.022, 8: 0.008, 9: 0.006, 10: 0.008, "rest": 0.151},
    "QB": {1: 0.233, 2: 0.172, 3: 0.141, 4: 0.057, 5: 0.047, 6: 0.05, 9: 0.06, "rest": 0.24},
}
TOP = {"QB": 24, "RB": 48, "WR": 72, "TE": 18, "K": 12}


def _cdf(d):
    ks = [k for k in d if k != "rest"]
    ks.sort()
    tot = sum(d.values())
    xs, c = [], 0.0
    for k in ks:
        c += d[k] / tot; xs.append(c)
    return ks, xs
_CDF = {g: _cdf(d) for g, d in DUR.items()}


FA_RANK = 3   # waiver fill-ins = the 3rd- and 4th-best unrostered players at the position (others want the top ones too)


def fa_floor(pool, rostered, rank=FA_RANK):
    """pool: iterable of (pts, pos, pid) for every player. Returns two waiver fill-ins per position as (pts, pos, "FA_<pos><n>"),
    so a hole in the lineup is filled at waiver level instead of zero."""
    by = collections.defaultdict(list)
    for v, q, pid in pool:
        if pid not in rostered and v > 0:
            by[q].append(v)
    out = []
    for q, vs in by.items():
        vs.sort(reverse=True)
        for i in (0, 1):
            if len(vs) >= rank + i:
                out.append((vs[rank - 1 + i], q, "FA_%s%d" % (q, i)))
    return out


def draw_dur(rng, pos):
    ks, xs = _CDF["QB" if pos == "QB" else "skill"]
    i = bisect.bisect_right(xs, rng.random())
    return ks[i] if i < len(ks) else None   # None = rest of season


def _geo(rng, h):
    return int(math.log(1.0 - rng.random()) / math.log(1.0 - h))


def team_paths(slots, lineup, cands, weeks, n, rng, fa=()):
    """cands: {week: [(pts, pos, pid), ...]} = the players available that week (absent = bye or already known out).
    Each path walks every player through his own game weeks: healthy games until an absence starts (prob HAZARD per game),
    then out for a drawn number of his team games, then healthy again. The week's team total = best legal lineup from
    whoever is left plus the waiver fill-ins in fa (a list, or {week: list}). The loss in a week = waiver-filled lineup with everyone minus
    waiver-filled lineup without the absent players, so with nobody hurt the team is exactly its normal best lineup). Returns (mean total by week, [path: {week: total - mean}])."""
    games = collections.defaultdict(list)
    info = {}
    for w in weeks:
        for c in cands.get(w, []):
            if c[0] > 0:
                games[c[2]].append(w); info[c[2]] = c[1]
    faw = fa if isinstance(fa, dict) else {w: list(fa) for w in weeks}
    full = {w: lineup(slots, cands.get(w, []))[0] for w in weeks}
    fullfa = {w: lineup(slots, cands.get(w, []) + faw.get(w, []))[0] for w in weeks}   # same, holes (byes) filled too
    cache, tots = {}, []
    for _ in range(n):
        outs = collections.defaultdict(set)
        for pid, ws in games.items():
            h = HAZARD.get(info[pid], 0.0)
            if h <= 0:
                continue
            i, L = _geo(rng, h), len(ws)
            while i < L:
                d = draw_dur(rng, info[pid])
                e = L if d is None else min(L, i + d)
                for j in range(i, e):
                    outs[ws[j]].add(pid)
                i = e + 1 + _geo(rng, h)
        t = {}
        for w in weeks:
            if not outs[w]:
                t[w] = full[w]; continue
            key = (w, frozenset(outs[w]))
            v = cache.get(key)
            if v is None:
                # loss = how much the waiver-filled lineup drops without the absent players (so a bye hole elsewhere,
                # which the fill-ins would also plug, does not offset it)
                v = cache[key] = full[w] - max(0.0, fullfa[w] - lineup(slots, [c for c in cands.get(w, []) if c[2] not in outs[w]] + faw.get(w, []))[0])
            t[w] = v
        tots.append(t)
    mean = {w: sum(t[w] for t in tots) / n for w in weeks}
    return mean, [{w: t[w] - mean[w] for w in weeks} for t in tots]


def path_var(paths, weeks):
    """(average within-season variance of weekly deviations, variance of the season-average deviation)."""
    if not paths or not weeks:
        return 0.0, 0.0
    n, wv, sm = len(paths), 0.0, []
    for p in paths:
        xs = [p[w] for w in weeks]
        m = sum(xs) / len(xs); sm.append(m)
        wv += sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)
    return wv / n, sum(x * x for x in sm) / n


def estimate(seasons=("2021", "2022", "2023", "2024", "2025")):
    import sources as S, draftprior as DP
    at, on, runs = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    for season in seasons:
        byp = collections.defaultdict(list)
        for e in DP.season_projections(season):
            pl = e.get("player") or {}
            q = e.get("position") or pl.get("position")
            if e.get("player_id") and q in TOP:
                byp[q].append(((e.get("stats") or {}).get("pts_half_ppr") or 0, e["player_id"]))
        pos = {pid: q for q, l in byp.items() for _, pid in sorted(l, reverse=True)[:TOP[q]]}
        gp, team, tplay = {}, {}, {}
        for w in range(1, 18):
            gp[w], team[w], tplay[w] = set(), {}, set()
            for e in S.sleeper_stats(season, w, "regular"):
                s, pid = e.get("stats") or {}, e.get("player_id")
                if s.get("gp"):
                    tplay[w].add(e.get("team"))
                    if pid: gp[w].add(pid)
                if pid: team[w][pid] = e.get("team")
        for pid, q in pos.items():
            last, seq = None, []
            for w in range(1, 18):
                t = team[w].get(pid)
                last = t or last
                if last and last in tplay[w]:
                    seq.append(pid in gp[w])
            for j in range(1, len(seq)):
                if seq[j - 1]:
                    at[q] += 1
                    if not seq[j]:
                        on[q] += 1
                        k = j
                        while k < len(seq) and not seq[k]:
                            k += 1
                        runs["QB" if q == "QB" else "skill"].append((k - j, k == len(seq)))
    for q in at:
        print("%-3s hazard %.3f per game (%d absences in %d games)" % (q, on[q] / at[q], on[q], at[q]))
    for g, rs in runs.items():
        surv, pmf = 1.0, {}
        for d in range(1, 17):
            risk = [r for r in rs if r[0] >= d]
            if not risk:
                break
            h = sum(1 for r in risk if r[0] == d and not r[1]) / len(risk)
            if h:
                pmf[d] = round(surv * h, 3)
            surv *= 1 - h
        pmf["rest"] = round(surv, 3)
        print("%-5s durations (%d stints): %s" % (g, len(rs), pmf))


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    estimate()
