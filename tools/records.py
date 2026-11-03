"""Add week-by-week win-loss records to existing <key>-power-data.js files without rerunning the simulation.

Usage: python tools/records.py [--league KEY|all]   (default all)

Records come from Sleeper matchups for weeks 1..last (the data file's last completed week), counted the same way as
tools/power.py (higher points wins, equal points is a tie). The script checks that the final record matches each team's
w/l/t in the file, then appends one line `window.POWER[key].recs={rid: [[w,l,t] after week 1, ...]};`. Everything
before that line stays byte-for-byte the same, so no odds change (files already carrying recs are left alone)."""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leagues as LG
import podcast as PC
import sources as S

TAG = "/* week-by-week records (tools/records.py) */\n"


def weekly_records(league_id, last, rids):
    rec = {r: [0, 0, 0] for r in rids}
    out = {r: [] for r in rids}
    for w in range(1, last + 1):
        M = S.get_json("%s/v1/league/%s/matchups/%s" % (S.SLEEPER, league_id, w))
        pts = {m["roster_id"]: m.get("points") or 0.0 for m in M}
        by = {}
        for m in M:
            if m.get("matchup_id") is not None:
                by.setdefault(m["matchup_id"], []).append(m["roster_id"])
        for a, b in [tuple(v) for v in by.values() if len(v) == 2]:
            for x, y in ((a, b), (b, a)):
                rec[x][0 if pts[x] > pts[y] else 1 if pts[x] < pts[y] else 2] += 1
        for r in rids:
            out[r].append(list(rec[r]))
    return out


def main():
    for lg in LG.pick(sys.argv[1:] or ["--league", "all"]):
        key = lg["key"]
        path = PC.out_path(key, "power")
        src = open(path, encoding="utf-8").read()
        base = src.split(TAG)[0]
        m = re.search(r"^window\.POWER(?:\.%s|\[\"%s\"\])=(.*);$" % (key, key), base, re.M)
        D = json.loads(m.group(1))
        if "recs" in D:
            print(key, "already has recs"); continue
        rids = [t["rid"] for t in D["teams"]]
        R = weekly_records(lg["id"], D["last"], rids)
        bad = [t["name"] for t in D["teams"] if R[t["rid"]][-1] != [t["w"], t["l"], t["t"]]] if D["last"] else []
        if bad:
            raise SystemExit("%s: records do not match the file for %s" % (key, bad))
        line = "window.POWER[%s].recs=%s;\n" % (json.dumps(key), json.dumps({str(r): R[r] for r in rids}, separators=(",", ":")))
        with open(path, "w", encoding="utf-8") as f:
            f.write(base + TAG + line)
        print("%s: records through week %d added to %s" % (key, D["last"], path))


if __name__ == "__main__":
    main()
