"""The leagues the podcast pages cover (luck report + power rankings). Order = tab order on the podcast site."""
LEAGUES = [
    dict(key="best", id="1389358450705727488", name="Best League", theme="best"),
    dict(key="zbt", id="1389375330296279040", name="ZBT", theme="zbt"),
    dict(key="oops", id="1389754735367589888", name="Oopsilons", theme="oops"),
    dict(key="spacex", id="1398902725940367360", name="SpaceX FF", theme="spacex"),
]
BY_KEY = {x["key"]: x for x in LEAGUES}
# Leagues whose power/luck model is frozen at the settings that are live on the site (the user asked not to change the
# Best League model until they say so). power.py uses tau0 below instead of tools/power_cal.json's value, and both tools use
# the injury list as checked on Oct 31 (podcast.LONG_TERM_OCT31, no ACTIVATED overrides). Drop the entry to unfreeze.
FROZEN = {"best": dict(tau0=4.6, injuries="oct31")}


def pick(argv):
    """Pop "--league KEY" (or "all") from argv; default best. Returns the list of league dicts."""
    key = "best"
    if "--league" in argv:
        i = argv.index("--league")
        key = argv[i + 1]
        del argv[i:i + 2]
    if key == "all":
        return list(LEAGUES)
    if key not in BY_KEY:
        raise SystemExit("unknown league %r (one of: %s, all)" % (key, ", ".join(BY_KEY)))
    return [BY_KEY[key]]


def adp_key(scoring):
    rec = scoring.get("rec") or 0
    return "adp_ppr" if rec >= 1 else "adp_std" if rec <= 0 else "adp_half_ppr"
