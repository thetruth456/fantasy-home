"""Data sources for the update pipeline: Sleeper, Fieldwork (props) and FantasyPros (ranks). Stdlib only."""
import json, os, re, time, unicodedata, urllib.request, urllib.error

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
SLEEPER = "https://api.sleeper.app"


def log(*a):
    msg = " ".join(str(x) for x in a)
    # surface problems as annotations on the GitHub Actions run summary page
    if os.environ.get("GITHUB_ACTIONS") == "true" and msg.startswith(("WARNING", "ERROR")):
        print("::%s::%s" % ("warning" if msg.startswith("WARNING") else "error", msg.replace("\n", " ")), flush=True)
    else:
        print(msg, flush=True)


def http_get(url, tries=3, timeout=60):
    """GET with a browser User-Agent and simple retry/backoff. Returns text; raises on failure."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - log and retry
            last = e
            log("  fetch failed (%d/%d) %s: %s" % (i + 1, tries, url[:100], e))
            time.sleep(2 * (i + 1))
    raise RuntimeError("giving up on %s: %s" % (url, last))


def get_json(url, **kw):
    return json.loads(http_get(url, **kw))


# ---------------------------------------------------------------- Sleeper
def sleeper_state():
    s = get_json(SLEEPER + "/v1/state/nfl")
    if not isinstance(s, dict) or "week" not in s:
        raise RuntimeError("unexpected Sleeper state: %r" % (s,))
    return s


def sleeper_schedule(season):
    d = get_json("%s/schedule/nfl/regular/%s" % (SLEEPER, season))
    if not isinstance(d, list) or len(d) < 100:
        raise RuntimeError("schedule looks empty")
    return d


def sleeper_scores(season, week):
    """Live game states for one NFL week (status, quarter_num, time_remaining in metadata). [] if unavailable."""
    try:
        d = get_json("%s/scores/nfl/regular/%s/%s" % (SLEEPER, season, week))
    except Exception:
        return []
    return d if isinstance(d, list) else []


def week_final(season, week):
    """True once every NFL game of that regular-season week is final in Sleeper's scores feed
    (Sleeper's league last_scored_leg only moves the next morning)."""
    g = sleeper_scores(season, week)
    return bool(g) and all(x.get("status") == "complete" or (x.get("metadata") or {}).get("is_over") for x in g)


PROJ_POS = "&".join("position%5B%5D=" + p for p in ["QB", "RB", "WR", "TE", "K", "DEF"])


def sleeper_projections(season, week, season_type):
    d = get_json("%s/projections/nfl/%s/%s?season_type=%s&%s" % (SLEEPER, season, week, season_type, PROJ_POS), timeout=120)
    if not isinstance(d, list) or len(d) < 500:
        raise RuntimeError("projections look empty (%s rows)" % (len(d) if isinstance(d, list) else d))
    return d


def sleeper_stats(season, week, season_type):
    d = get_json("%s/stats/nfl/%s/%s?season_type=%s" % (SLEEPER, season, week, season_type), timeout=120)
    return d if isinstance(d, list) else []


def sleeper_season_stats(season):
    """One season-to-date stat line per player (week is null; gp is games played so far)."""
    d = get_json("%s/stats/nfl/%s?season_type=regular" % (SLEEPER, season), timeout=120)
    if not isinstance(d, list) or len(d) < 1000:
        raise RuntimeError("season stats look empty (%s)" % (len(d) if isinstance(d, list) else d))
    return d


def sleeper_season_projections(season):
    """Full-season stat projections, including ADP. Scored later with each league's settings."""
    d = get_json("%s/projections/nfl/%s?season_type=regular&%s&order_by=adp_half_ppr" % (SLEEPER, season, PROJ_POS), timeout=120)
    if not isinstance(d, list) or len(d) < 500:
        raise RuntimeError("season projections look empty (%s)" % (len(d) if isinstance(d, list) else d))
    return d


def sleeper_players(cache_dir, max_age_h=24):
    """The big players dump. Sleeper asks for at most one call a day, so keep a cache file."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "players.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_h * 3600:
        try:
            d = json.load(open(path))
            if len(d) > 5000:
                log("  players dump: using cache (%d players)" % len(d))
                return d
        except Exception:  # noqa: BLE001
            pass
    try:
        d = get_json(SLEEPER + "/v1/players/nfl", timeout=180)
        if not isinstance(d, dict) or len(d) < 5000:
            raise RuntimeError("players dump looks empty")
        json.dump(d, open(path, "w"))
        log("  players dump: fetched (%d players)" % len(d))
        return d
    except Exception as e:  # noqa: BLE001
        if os.path.exists(path):
            log("  players dump fetch failed (%s); using stale cache" % e)
            return json.load(open(path))
        raise


def sleeper_league_bundle(league_id, week):
    L = get_json("%s/v1/league/%s" % (SLEEPER, league_id))
    R = get_json("%s/v1/league/%s/rosters" % (SLEEPER, league_id))
    U = get_json("%s/v1/league/%s/users" % (SLEEPER, league_id))
    try:
        M = get_json("%s/v1/league/%s/matchups/%s" % (SLEEPER, league_id, week))
    except Exception as e:  # noqa: BLE001
        log("  matchups unavailable for %s: %s" % (league_id, e))
        M = []
    if not isinstance(L, dict) or not L.get("scoring_settings") or not isinstance(R, list) or not R:
        raise RuntimeError("league %s data looks empty" % league_id)
    return dict(league=L, rosters=R, users=U if isinstance(U, list) else [], matchups=M if isinstance(M, list) else [])


# ---------------------------------------------------------------- Fieldwork props
def fetch_fieldwork(season, week):
    html = http_get("https://fieldworklines.com/nfl/%s/week-%s" % (season, week), timeout=90)
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    flight = "".join(json.loads(c) for c in chunks)
    dec = json.JSONDecoder()
    out = {}
    for k, n in [("players", "players"), ("cellPool", "cell"), ("quotePool", "quote")]:
        i = flight.find('"%s":[' % k)
        if i < 0:
            raise RuntimeError("Fieldwork page has no %s" % k)
        out[n] = dec.raw_decode(flight[i + len(k) + 3:])[0]
    m = re.search(r'"lastSuccessAt":"\$?D?([^"]+)"', flight)
    out["lastSuccessAt"] = m.group(1) if m else None
    m = re.search(r'collected: <time dateTime="([^"]+)"', html)
    out["collected"] = m.group(1) if m else None
    if len(out["players"]) < 50 or len(out["cell"]) < 100 or len(out["quote"]) < 100:
        raise RuntimeError("Fieldwork data looks empty (%d players)" % len(out["players"]))
    return out


# ---------------------------------------------------------------- FantasyPros ranks
FP_PAGES = {"half-point-ppr-flex": 100, "ppr-flex": 100, "qb": 20, "k": 15, "dst": 15}


def _ecr(html):
    i = html.index("var ecrData = ")
    return json.JSONDecoder().raw_decode(html[i + len("var ecrData = "):])[0]


def fetch_fp(week):
    """Return {page: players} for each ranking page. Pages whose week differs from `week` are rejected."""
    out = {}
    for page, minimum in FP_PAGES.items():
        try:
            html = http_get("https://www.fantasypros.com/nfl/rankings/%s.php" % page, timeout=90)
            d = _ecr(html)
            players = d.get("players") or []
            if len(players) < minimum:
                raise RuntimeError("only %d players" % len(players))
            if str(d.get("week")) != str(week):
                raise RuntimeError("FantasyPros is on week %s, not %s" % (d.get("week"), week))
            out[page] = players
        except Exception as e:  # noqa: BLE001
            log("  FantasyPros %s unavailable: %s" % (page, e))
    return out


def fetch_fp_ros(page, season):
    """One FantasyPros rest-of-season ranking. Rejects a draft ranking or a different season.

    Returns {players, scoring, updated, year, page}. Week is 0 on these pages and is not checked.
    """
    html = http_get("https://www.fantasypros.com/nfl/rankings/%s.php" % page, timeout=90)
    d = _ecr(html)
    kind = "%s %s" % (d.get("type") or "", d.get("ranking_type_name") or "")
    if "ROS" not in kind.upper():
        raise RuntimeError("not a rest-of-season ranking (%s)" % kind.strip())
    year = d.get("year")
    if year is not None and str(year) != str(season):
        raise RuntimeError("FantasyPros ROS year is %s, not %s" % (year, season))
    players = d.get("players") or []
    if len(players) < 50:
        raise RuntimeError("only %d players" % len(players))
    scoring = str(d.get("scoring") or "").upper()
    if "half" in page and "HALF" not in scoring:
        raise RuntimeError("expected half-PPR, got %s" % (d.get("scoring"),))
    if "half" not in page and "PPR" in scoring and "HALF" in scoring:
        raise RuntimeError("expected PPR, got %s" % (d.get("scoring"),))
    if "half" not in page and "ppr" in page and "PPR" not in scoring:
        raise RuntimeError("expected PPR, got %s" % (d.get("scoring"),))
    return {"players": players, "scoring": d.get("scoring"), "updated": d.get("last_updated"), "year": year, "page": page}


# ---------------------------------------------------------------- game lines (ESPN public scoreboard, DraftKings odds)
ESPN_ALIAS = {"WAS": "WSH", "JAC": "JAX"}


def fetch_game_lines(season, week):
    """Return {team: {total, spread, team_total, opp_total}} for games that have not finished, keyed by ESPN abbreviation
    (WAS and JAC mapped to WSH and JAX). spread is that team's own line (negative = favorite). Games without a posted
    line, or already final, are left out. Raises if ESPN is unreachable or is showing a different week."""
    d = get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week=%s&seasontype=2&dates=%s" % (week, season), timeout=45)
    wk = (d.get("week") or {}).get("number")
    if wk is not None and str(wk) != str(week):
        raise RuntimeError("ESPN scoreboard is on week %s, not %s" % (wk, week))
    events = d.get("events") or []
    if not events:
        raise RuntimeError("ESPN scoreboard has no games")
    out = {}
    for e in events:
        c = (e.get("competitions") or [{}])[0]
        if ((e.get("status") or {}).get("type") or {}).get("completed"):
            continue
        odds = (c.get("odds") or [None])[0]
        if not odds:
            continue
        total = odds.get("overUnder")
        teams = {t["homeAway"]: ESPN_ALIAS.get(t["team"]["abbreviation"], t["team"]["abbreviation"]) for t in c.get("competitors", [])}
        if not isinstance(total, (int, float)) or set(teams) != {"home", "away"}:
            continue
        # margin and favorite: the favorite flags and details text ("KC -1.5") agree; spread is the home team's line
        m = re.match(r"\s*([A-Z]{2,4})\s+(-?\d+(?:\.\d+)?)", odds.get("details") or "")
        fav = None
        if (odds.get("homeTeamOdds") or {}).get("favorite"):
            fav = teams["home"]
        elif (odds.get("awayTeamOdds") or {}).get("favorite"):
            fav = teams["away"]
        if odds.get("details") in ("EVEN", "PK", "Pick", "PICK"):
            margin, fav = 0.0, None
        elif m and isinstance(odds.get("spread"), (int, float)) and abs(abs(odds["spread"]) - abs(float(m.group(2)))) < 1e-6:
            margin = abs(float(m.group(2)))
            fav = ESPN_ALIAS.get(m.group(1), m.group(1))
        elif fav and isinstance(odds.get("spread"), (int, float)):
            margin = abs(odds["spread"])
        else:
            continue
        if not (20 <= total <= 80) or margin > 30 or (margin and fav not in teams.values()):
            log("  ESPN line looks wrong for %s @ %s (total %s, margin %s); skipped" % (teams["away"], teams["home"], total, margin))
            continue
        for side, other in (("home", "away"), ("away", "home")):
            t, o = teams[side], teams[other]
            own = 0.0 if not margin else (-margin if t == fav else margin)
            out[t] = dict(total=float(total), spread=own, team_total=total / 2 - own / 2, opp_total=total / 2 + own / 2)
    return out


def _scoreboard(season, week):
    d = get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week=%s&seasontype=2&dates=%s" % (week, season), timeout=45)
    wk = (d.get("week") or {}).get("number")
    if wk is not None and str(wk) != str(week):
        raise RuntimeError("ESPN scoreboard is on week %s, not %s" % (wk, week))
    return d


def venues_from_scoreboard(d, week):
    """{team: venue} from an ESPN scoreboard payload. Both clubs share that game's actual venue.
    Completed games stay in the map so a played kickoff can still be described. Raises if the week
    does not match or there are no games."""
    wk = (d.get("week") or {}).get("number")
    if wk is not None and str(wk) != str(week):
        raise RuntimeError("ESPN scoreboard is on week %s, not %s" % (wk, week))
    events = d.get("events") or []
    if not events:
        raise RuntimeError("ESPN scoreboard has no games")
    out = {}
    for e in events:
        c = (e.get("competitions") or [{}])[0]
        st = ((e.get("status") or {}).get("type") or {})
        state = st.get("state") or ("post" if st.get("completed") else "pre")
        v = c.get("venue") or {}
        addr = v.get("address") or {}
        kick = c.get("startDate") or e.get("date")
        info = dict(
            venue_id=str(v.get("id") or ""),
            venue=v.get("fullName") or "",
            city=addr.get("city") or "",
            region=addr.get("state") or "",
            country=addr.get("country") or "",
            indoor=bool(v.get("indoor")),
            neutral=bool(c.get("neutralSite")),
            kickoff=kick,
            state=state)
        for t in c.get("competitors") or []:
            ab = ((t.get("team") or {}).get("abbreviation")) or ""
            if not ab:
                continue
            out[ESPN_ALIAS.get(ab, ab)] = info
    return out


def fetch_venues(season, week):
    """Actual stadium and kickoff for every team that plays this week. Raises if ESPN is unreachable or on another week."""
    return venues_from_scoreboard(_scoreboard(season, week), week)


# ---------------------------------------------------------------- kicker over/unders (PrizePicks two-way lines)
# Fieldwork's week page has no kicker markets. PrizePicks posts a standard over/under for
# field goals made and for kicking points (3 per field goal + 1 per extra point). Demon/goblin
# alternates and over-only prices are not an over/under and are left out.
KICKER_OU = {"FG Made": "fg", "Kicking Points": "kp"}


def parse_kicker_props(d):
    """Rows {name, team, fg, kp} from a PrizePicks projections payload. Raises if the payload is not that feed."""
    if not isinstance(d, dict) or not isinstance(d.get("data"), list):
        raise RuntimeError("PrizePicks payload has no projections")
    byid = {}
    for x in d.get("included") or []:
        if isinstance(x, dict):
            byid[(x.get("type"), x.get("id"))] = x
    best = {}  # (player id, stat) -> (updated, line, name, team)
    for p in d["data"]:
        if not isinstance(p, dict):
            continue
        a = p.get("attributes") or {}
        if a.get("odds_type") != "standard" or a.get("allowed_wager_types") != "under_or_over":
            continue
        if a.get("status") not in (None, "pre_game"):
            continue
        rel = p.get("relationships") or {}
        st = ((rel.get("stat_type") or {}).get("data")) or {}
        stat = (byid.get((st.get("type"), st.get("id"))) or {}).get("attributes") or {}
        kind = KICKER_OU.get(stat.get("name") or a.get("stat_type"))
        if not kind:
            continue
        pl = ((rel.get("new_player") or {}).get("data")) or {}
        player = (byid.get((pl.get("type"), pl.get("id"))) or {}).get("attributes") or {}
        if player.get("position") not in (None, "", "K"):
            continue
        name, team = player.get("name") or player.get("display_name"), player.get("team")
        line = a.get("line_score")
        if not name or not isinstance(line, (int, float)) or isinstance(line, bool):
            continue
        pid = pl.get("id") or name
        key = (pid, kind)
        updated = a.get("updated_at") or ""
        prev = best.get(key)
        if prev is None or updated > prev[0]:
            best[key] = (updated, float(line), name, team or "")
    acc = {}
    for (pid, kind), (_u, line, name, team) in best.items():
        row = acc.setdefault(pid, {"name": name, "team": team, "fg": None, "kp": None})
        row[kind] = line
        row["name"], row["team"] = name, team
    return list(acc.values())


def fetch_kicker_props():
    """Current NFL kicker over/unders. Raises if PrizePicks is unreachable or the payload is unusable."""
    d = get_json("https://partner-api.prizepicks.com/projections?league_id=9&per_page=1000", timeout=90)
    return parse_kicker_props(d)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
