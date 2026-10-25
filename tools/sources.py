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


PROJ_POS = "&".join("position%5B%5D=" + p for p in ["QB", "RB", "WR", "TE", "K", "DEF"])


def sleeper_projections(season, week, season_type):
    d = get_json("%s/projections/nfl/%s/%s?season_type=%s&%s" % (SLEEPER, season, week, season_type, PROJ_POS), timeout=120)
    if not isinstance(d, list) or len(d) < 500:
        raise RuntimeError("projections look empty (%s rows)" % (len(d) if isinstance(d, list) else d))
    return d


def sleeper_stats(season, week, season_type):
    d = get_json("%s/stats/nfl/%s/%s?season_type=%s" % (SLEEPER, season, week, season_type), timeout=120)
    return d if isinstance(d, list) else []


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


def fetch_fp(week):
    """Return {page: players} for each ranking page. Pages whose week differs from `week` are rejected."""
    out = {}
    for page, minimum in FP_PAGES.items():
        try:
            html = http_get("https://www.fantasypros.com/nfl/rankings/%s.php" % page, timeout=90)
            i = html.index("var ecrData = ")
            d = json.JSONDecoder().raw_decode(html[i + len("var ecrData = "):])[0]
            players = d.get("players") or []
            if len(players) < minimum:
                raise RuntimeError("only %d players" % len(players))
            if str(d.get("week")) != str(week):
                raise RuntimeError("FantasyPros is on week %s, not %s" % (d.get("week"), week))
            out[page] = players
        except Exception as e:  # noqa: BLE001
            log("  FantasyPros %s unavailable: %s" % (page, e))
    return out


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
