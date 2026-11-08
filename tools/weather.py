"""Kickoff weather for the weekly report.

The stadium is the one hosting that game (ESPN), including neutral and international sites.
Roof class comes from the building, not from ESPN's indoor flag: that flag stays true for
every retractable roof across 2026 weeks 1-9, so it is not a gameday roof decision.

* dome: fixed enclosed roof. The cell is "(dome)" with no outdoor numbers.
* retractable: outdoor forecast plus "(roof ?)". The roof may be open or closed; the numbers are not indoor conditions.
* covered: SoFi's fixed canopy, open sides. Outdoor temperature and wind, precipitation may not reach the field.
* outdoor: the forecast as-is.
* unknown indoor building: "(indoor ?)" and no outdoor numbers. Unknown open-air buildings are geocoded or left blank.

Forecast is the Open-Meteo hourly value at the kickoff hour (temperature F, wind mph, conditions).
Nothing is interpolated from another hour or another city. A miss is an explicit marker.
"""
import datetime as dt
import json
import math
import os
import re
import unicodedata

from sources import http_get, log

DASH = "\u2014"
# Open-Meteo hourly models go out 16 days. Past hours on the same endpoint cover the current week.
PAST_DAYS = 7
FORECAST_DAYS = 16
TTL_SEC = 45 * 60
GEO_TTL_SEC = 24 * 3600

# Roof and building coordinates (OpenStreetMap stadium pins, 2026). U.S. Bank is the building,
# not the light-rail station next to it. ESPN still calls NRG "Reliant Stadium".
_RAW = [
    ("3687", ("AT&T Stadium",), "retractable", 32.74785, -97.09283),
    ("3752", ("Acrisure Stadium",), "outdoor", 40.44672, -80.01572),
    ("6501", ("Allegiant Stadium",), "dome", 36.09074, -115.18333),
    ("3622", ("Arrowhead Stadium",), "outdoor", 39.04894, -94.48400),
    ("3628", ("Bank of America Stadium",), "outdoor", 35.22577, -80.85283),
    ("3493", ("Caesars Superdome",), "dome", 29.95105, -90.08231),
    ("3937", ("Empower Field at Mile High",), "outdoor", 39.74395, -105.01922),
    ("3712", ("EverBank Stadium",), "outdoor", 30.32398, -81.63730),
    ("3727", ("Ford Field",), "dome", 42.33996, -83.04562),
    ("3738", ("Gillette Stadium",), "outdoor", 42.09089, -71.26417),
    ("3948", ("Hard Rock Stadium",), "outdoor", 25.95790, -80.23885),
    ("11938", ("Highmark Stadium",), "outdoor", 42.77303, -78.79219),
    ("3679", ("Huntington Bank Field",), "outdoor", 41.50606, -81.69971),
    ("3798", ("Lambeau Field",), "outdoor", 44.50097, -88.06197),
    ("4738", ("Levi's Stadium",), "outdoor", 37.40299, -121.96965),
    ("3806", ("Lincoln Financial Field",), "outdoor", 39.90091, -75.16749),
    ("3812", ("Lucas Oil Stadium",), "retractable", 39.75906, -86.16384),
    ("3673", ("Lumen Field",), "outdoor", 47.59535, -122.33164),
    ("3814", ("M&T Bank Stadium",), "outdoor", 39.27797, -76.62267),
    ("11931", ("Maracana Stadium", "Maracanã Stadium"), "outdoor", -22.91216, -43.23119),
    ("9119", ("Melbourne Cricket Ground",), "outdoor", -37.81991, 144.98323),
    ("5348", ("Mercedes-Benz Stadium",), "retractable", 33.75541, -84.40085),
    ("3839", ("MetLife Stadium",), "outdoor", 40.81351, -74.07434),
    ("3810", ("Nissan Stadium",), "outdoor", 36.16652, -86.77131),
    ("3719", ("Northwest Stadium",), "outdoor", 38.90767, -76.86453),
    ("3874", ("Paycor Stadium",), "outdoor", 39.09546, -84.51605),
    ("3886", ("Raymond James Stadium",), "outdoor", 27.97598, -82.50335),
    ("3891", ("NRG Stadium", "Reliant Stadium"), "retractable", 29.68486, -95.41080),
    ("1353", ("Santiago Bernabeu", "Santiago Bernabéu"), "retractable", 40.45304, -3.68820),
    ("7065", ("SoFi Stadium",), "covered", 33.95341, -118.33901),
    ("3933", ("Soldier Field",), "outdoor", 41.86234, -87.61765),
    ("1781", ("Stade de France",), "outdoor", 48.92447, 2.36013),
    ("3970", ("State Farm Stadium",), "retractable", 33.52704, -112.26171),
    ("5534", ("Tottenham Hotspur Stadium",), "outdoor", 51.60416, -0.06626),
    ("5239", ("U.S. Bank Stadium", "US Bank Stadium"), "dome", 44.97380, -93.25770),
    ("2455", ("Wembley Stadium",), "outdoor", 51.55607, -0.27960),
]

WMO = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Snow", 73: "Snow", 75: "Heavy snow", 77: "Snow",
    80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}
_US = {"", "USA", "US", "UNITED STATES"}
_ALIAS = {"WAS": "WSH", "JAC": "JAX"}


def _team(t):
    return _ALIAS.get(t, t)


def norm_venue(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _load_table():
    by_id, by_name = {}, {}
    for vid, names, roof, lat, lon in _RAW:
        rec = dict(id=str(vid), roof=roof, lat=lat, lon=lon, name=names[0])
        by_id[str(vid)] = rec
        for n in names:
            by_name[norm_venue(n)] = rec
    return by_id, by_name


BY_ID, BY_NAME = _load_table()


class Place:
    def __init__(self, roof, lat, lon, source):
        self.roof, self.lat, self.lon, self.source = roof, lat, lon, source

    @property
    def coord(self):
        if self.lat is None:
            return None
        return (round(self.lat, 4), round(self.lon, 4))


def locate(venue):
    """Roof and coordinates for one ESPN venue dict. Unknown buildings are not guessed from the home city."""
    venue = venue or {}
    vid = str(venue.get("venue_id") or venue.get("id") or "")
    rec = BY_ID.get(vid) or BY_NAME.get(norm_venue(venue.get("venue") or venue.get("fullName") or ""))
    if rec:
        return Place(rec["roof"], rec["lat"], rec["lon"], "table")
    indoor = venue.get("indoor")
    if indoor is True:
        return Place("unknown_indoor", None, None, "unverified")
    return Place("outdoor", None, None, "unverified")


def _r0(x):
    return int(math.copysign(math.floor(abs(float(x)) + 0.5), float(x)))


def format_conditions(obs):
    """Temp, wind, and precipitation text. None when temperature or wind is missing (do not show a partial)."""
    if not obs or obs.get("temp") is None or obs.get("wind") is None:
        return None
    code = obs.get("code")
    cond = WMO.get(int(code)) if isinstance(code, (int, float)) and not isinstance(code, bool) else None
    bits = ["%d\u00b0F" % _r0(obs["temp"]), "%d mph" % _r0(obs["wind"])]
    pop = obs.get("pop")
    pop_ok = isinstance(pop, (int, float)) and not isinstance(pop, bool) and pop >= 30
    if cond:
        bits.append("%s %d%%" % (cond, _r0(pop)) if pop_ok else cond)
    elif pop_ok:
        bits.append("%d%% precip" % _r0(pop))
    else:
        bits.append(DASH)
    prec = obs.get("precip")
    if isinstance(prec, (int, float)) and not isinstance(prec, bool) and prec >= 0.05:
        bits.append("%.2f in" % (round(float(prec) + 1e-9, 2)))
    return ", ".join(bits)


def _place_suffix(venue):
    country = (venue.get("country") or "").strip().upper()
    city = (venue.get("city") or "").strip()
    if not city:
        return ""
    if venue.get("neutral") or country not in _US:
        return ", " + city
    return ""


def decorate(text, roof, state, place=""):
    """Apply roof and game-state markers. Dome and unverified indoor buildings never carry outdoor numbers."""
    if roof == "dome":
        return "(dome)" + (place or "")
    if roof == "unknown_indoor":
        return "(indoor ?)" + (place or "")
    if not text:
        return None
    if roof == "retractable":
        text += " (roof ?)"
    elif roof == "covered":
        text += " (covered)"
    text += place or ""
    if state == "post":
        text += " (final)"
    elif state == "in":
        text += " (kickoff)"
    return text


def hour_key(iso):
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None
    return d.strftime("%Y-%m-%dT%H:00")


def _missing(hour, state, times):
    if not hour or not times:
        return "no obs" if state in ("post", "in") else "no forecast"
    lo, hi = min(times), max(times)
    if hour > hi:
        return "no forecast"
    if hour < lo or state in ("post", "in"):
        return "no obs"
    return DASH


class WeatherResult:
    def __init__(self, by_team, asof):
        self.by_team = by_team
        self.asof = asof


def _cache_path(cache_dir):
    return os.path.join(cache_dir, "weather-hourly.json") if cache_dir else None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _as_items(payload, n):
    if isinstance(payload, dict) and "hourly" in payload:
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise RuntimeError("unexpected weather payload")
    if len(items) != n:
        raise RuntimeError("weather returned %d locations, expected %d" % (len(items), n))
    return items


def parse_hourly(payload, coords):
    """Map rounded (lat, lon) -> {hour: {temp, wind, code, pop, precip}} in request order."""
    items = _as_items(payload, len(coords))
    out = {}
    for coord, it in zip(coords, items):
        h = it.get("hourly") or {}
        times = h.get("time") or []
        rows = {}
        for i, t in enumerate(times):
            def at(key, i=i):
                seq = h.get(key) or []
                if i >= len(seq):
                    return None
                v = seq[i]
                return None if v is None else v
            rows[t] = dict(temp=at("temperature_2m"), wind=at("wind_speed_10m"), code=at("weather_code"),
                           pop=at("precipitation_probability"), precip=at("precipitation"))
        out[(round(coord[0], 4), round(coord[1], 4))] = rows
    return out


def _fetch_chunk(coords, getter):
    lats = ",".join("%.4f" % c[0] for c in coords)
    lons = ",".join("%.4f" % c[1] for c in coords)
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&hourly=temperature_2m,precipitation,precipitation_probability,weather_code,wind_speed_10m"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
           "&timezone=UTC&past_days=%d&forecast_days=%d") % (lats, lons, PAST_DAYS, FORECAST_DAYS)
    return parse_hourly(json.loads(getter(url)), coords), url


def load_forecast(coords, now, cache_dir=None, getter=None, ttl_sec=TTL_SEC):
    """Return (points, asof_iso). Uses a fresh cache, else Open-Meteo, else a stale cache. (None, None) if nothing."""
    getter = getter or (lambda url: http_get(url, tries=2, timeout=45))
    coords = [(round(c[0], 4), round(c[1], 4)) for c in coords]
    path = _cache_path(cache_dir)
    cached = _read_json(path) if path else None
    fresh = None
    if cached and cached.get("fetched_at"):
        try:
            age = (now - dt.datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            age = ttl_sec + 1
        if age <= ttl_sec:
            fresh = cached
    have = (fresh or {}).get("points") or {}
    if fresh and all(_ck(c) in have for c in coords):
        return _decode_points(have), fresh["fetched_at"]
    try:
        merged = dict(have)
        for i in range(0, len(coords), 10):
            chunk = coords[i:i + 10]
            part, _url = _fetch_chunk(chunk, getter)
            for c, rows in part.items():
                merged[_ck(c)] = rows
        stamp = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": stamp, "points": merged}, f)
            os.replace(tmp, path)
        return _decode_points(merged), stamp
    except Exception as e:  # noqa: BLE001
        log("WARNING: Open-Meteo weather unavailable (%s)" % e)
        stale = (cached or {}).get("points") or {}
        if stale and all(_ck(c) in stale for c in coords):
            log("WARNING: using cached weather from %s" % cached.get("fetched_at"))
            return _decode_points(stale), cached.get("fetched_at")
        return None, None


def _ck(c):
    return "%.4f,%.4f" % (c[0], c[1])


def _decode_points(raw):
    out = {}
    for key, rows in (raw or {}).items():
        lat, lon = key.split(",")
        out[(round(float(lat), 4), round(float(lon), 4))] = rows
    return out


def _geocode(venue, cache_dir, getter):
    name = venue.get("venue") or ""
    city = venue.get("city") or ""
    if not name:
        return None
    key = norm_venue(name + " " + city)
    path = os.path.join(cache_dir, "geocode.json") if cache_dir else None
    cache = _read_json(path) or {}
    hit = cache.get(key)
    if hit and hit.get("at"):
        try:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(hit["at"].replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            age = GEO_TTL_SEC + 1
        if age <= GEO_TTL_SEC:
            return None if hit.get("miss") else (hit.get("lat"), hit.get("lon"))
    q = name if not city else "%s, %s" % (name, city)
    found = None
    try:
        url = "https://nominatim.openstreetmap.org/search?q=%s&format=jsonv2&limit=3" % _urlquote(q)
        data = json.loads(getter(url, headers=True))
        if isinstance(data, dict):
            data = data.get("results") or []
        for item in data or []:
            if _geo_ok(name, item):
                found = (float(item["lat"]), float(item["lon"]))
                break
    except Exception as e:  # noqa: BLE001
        log("WARNING: stadium geocode failed for an unrecognized venue (%s)" % e)
        return None
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache[key] = {"miss": True, "at": stamp} if not found else {"lat": found[0], "lon": found[1], "at": stamp}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    if not found:
        log("WARNING: unrecognized stadium has no stadium geocode; weather left blank")
    return found


def _urlquote(s):
    from urllib.parse import quote
    return quote(s)


def _geo_ok(name, item):
    kind = (item.get("type") or item.get("class") or "").lower()
    if kind not in ("stadium", "pitch", "sports_centre"):
        return False
    disp = norm_venue(item.get("display_name") or "")
    token = norm_venue(name).split(" ")[0] if name else ""
    return bool(token) and token in disp and "lat" in item and "lon" in item


def build_weather_map(venues, now, cache_dir=None, getter=None, geocode=None, ttl_sec=TTL_SEC):
    """team -> display string, or None where the forecast failed and the previous cell should be kept.

    Dome and unverified-indoor labels are set even when the forecast service fails.
    """
    venues = {_team(k): v for k, v in (venues or {}).items()}
    if geocode is None and getter is not None:
        geocode = lambda v: None  # noqa: E731 - tests that inject getter must not hit the network
    places = {}
    for team, v in venues.items():
        p = locate(v)
        if p.roof == "outdoor" and p.coord is None and geocode is not False:
            fn = geocode or (lambda venue: _geocode(venue, cache_dir, _geo_getter(getter)))
            hit = fn(v)
            if hit:
                p = Place("outdoor", hit[0], hit[1], "geocode")
        places[team] = (p, v)
    need = []
    for p, _v in places.values():
        if p.roof in ("dome", "unknown_indoor") or not p.coord:
            continue
        c = p.coord
        if c not in need:
            need.append(c)
    points, stamp = (None, None)
    if need:
        points, stamp = load_forecast(need, now, cache_dir=cache_dir, getter=getter, ttl_sec=ttl_sec)
    by = {}
    for team, (p, v) in places.items():
        place = _place_suffix(v)
        state = v.get("state") or "pre"
        if p.roof == "dome":
            by[team] = decorate("", "dome", state, place)
            continue
        if p.roof == "unknown_indoor":
            by[team] = decorate("", "unknown_indoor", state, place)
            continue
        if not p.coord:
            by[team] = DASH
            continue
        if points is None:
            by[team] = None
            continue
        rows = points.get(p.coord) or {}
        hk = hour_key(v.get("kickoff"))
        obs = rows.get(hk) if hk else None
        text = format_conditions(obs)
        if text is None:
            by[team] = _missing(hk, state, list(rows))
        else:
            by[team] = decorate(text, p.roof, state, place)
    n_none = sum(1 for x in by.values() if x is None)
    if n_none:
        log("WARNING: outdoor weather missing for %d team(s); those cells keep previous values" % n_none)
    else:
        log("weather: %d teams (%d dome, %d roof-uncertain, %d covered)" % (
            len(by),
            sum(1 for x in by.values() if isinstance(x, str) and x.startswith("(dome)")),
            sum(1 for x in by.values() if isinstance(x, str) and "(roof ?)" in x),
            sum(1 for x in by.values() if isinstance(x, str) and "(covered)" in x)))
    # A failed forecast must not be stamped as fresh. Roofs that did not need a forecast still count as checked.
    if need and points is None:
        asof = None
    elif stamp:
        asof = stamp
    elif n_none == 0:
        asof = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        asof = None
    return WeatherResult(by, asof)


def _geo_getter(getter):
    def g(url, headers=False):
        if getter is None:
            return http_get(url, tries=1, timeout=20)
        return getter(url)
    return g
