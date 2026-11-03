#!/usr/bin/env python3
"""Encrypt the site's data files so the public repo and site hold only ciphertext.

Every weekly report data file (*-report.js: rosters, lineups, waivers) is written as
(the podcast luck / power rankings files stay plaintext and public on purpose)
    window.LOCKED["REPORTS.best"] = {"v":1, "ks":..., "iter":..., "salt":..., "iv":..., "ct":...}
  * password -> PBKDF2-SHA256 (ITER iterations, salt "ks" from tools/lock.json) -> 256-bit master key
  * master key + a fresh random 16-byte salt per file and write -> HKDF-SHA256 -> AES-256-GCM key
  * fresh random 12-byte IV per file and write; the slot name ("REPORTS.best") is the GCM associated data
The browser (lock.js) runs the same steps with WebCrypto. "Remember on this device" keeps the master key, not the password.
tools/lock.json holds only the public PBKDF2 salt and an encrypted check value, so a wrong password fails the build.

The password comes from env FH_REPORT_PASSWORD (in the Action: the repository secret of the same name).
Fail closed: without it, or if it does not match tools/lock.json, nothing is written.

  python tools/seal.py verify          exit 1 if any report data file is plaintext (no password needed)
  python tools/seal.py check           check FH_REPORT_PASSWORD against tools/lock.json and decrypt every report data file
  python tools/seal.py init            new tools/lock.json for FH_REPORT_PASSWORD, then (re)encrypt every data file
                                        (already-encrypted files need the old password in FH_REPORT_PASSWORD_OLD)
"""
import base64
import json
import os
import re
import secrets
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lock.json")
ITER = 600000
INFO = b"fh-seal-v1"
ENV = "FH_REPORT_PASSWORD"
# data file -> slot (window.<NS>.<key>). Only the weekly reports (rosters, lineups, waivers) are locked;
# the podcast luck / power rankings files (best-podcast-data.js, best-power-data.js) stay public on purpose.
FILES = {
    "best-league-report.js": "REPORTS.best",
    "zbt-report.js": "REPORTS.zbt",
    "oopsilons-report.js": "REPORTS.oops",
    "spacex-report.js": "REPORTS.spacex",
}
HEAD = "/* Encrypted data file (tools/seal.py). Unlocked in the browser by lock.js. */\nwindow.LOCKED=window.LOCKED||{};\n"
_RX = re.compile(r'window\.LOCKED\["([A-Z]+\.\w+)"\]=(\{.*\});?\s*$', re.S)


class SealError(Exception):
    pass


def _b(s):
    return base64.b64decode(s)


def _s(b):
    return base64.b64encode(b).decode()


def _master(pw, ks, it):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=ks, iterations=it).derive(pw.encode("utf-8"))


def _fkey(mk, salt):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=INFO).derive(mk)


class Key:
    """Master key for the current password. Raises SealError (fail closed) if the password is missing or wrong."""

    def __init__(self, pw=None, lock=None):
        pw = os.environ.get(ENV, "") if pw is None else pw
        if not pw:
            raise SealError("%s is not set; refusing to write unencrypted data" % ENV)
        if lock is None:
            if not os.path.exists(LOCK):
                raise SealError("tools/lock.json is missing; run `python tools/seal.py init` locally first")
            lock = json.load(open(LOCK))
        self.ks, self.iter = _b(lock["ks"]), int(lock["iter"])
        self.mk = _master(pw, self.ks, self.iter)
        if "check" in lock:
            try:
                ok = self.open_blob("CHECK", lock["check"]) == "fh-ok"
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                raise SealError("%s does not match tools/lock.json (wrong password?)" % ENV)

    def seal_blob(self, slot, obj):
        salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
        pt = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ct = AESGCM(_fkey(self.mk, salt)).encrypt(iv, pt, slot.encode())
        return dict(v=1, kdf="PBKDF2-SHA256+HKDF", alg="AES-256-GCM", iter=self.iter, ks=_s(self.ks), salt=_s(salt), iv=_s(iv), ct=_s(ct))

    def open_blob(self, slot, blob):
        if _b(blob["ks"]) != self.ks:
            raise SealError("%s was encrypted under a different tools/lock.json" % slot)
        pt = AESGCM(_fkey(self.mk, _b(blob["salt"]))).decrypt(_b(blob["iv"]), _b(blob["ct"]), slot.encode())
        return json.loads(pt.decode("utf-8"))

    def seal_js(self, slot, obj):
        return HEAD + 'window.LOCKED["%s"]=%s;\n' % (slot, json.dumps(self.seal_blob(slot, obj), separators=(",", ":")))

    def write(self, path, slot, obj):
        js = self.seal_js(slot, obj)
        assert self.open_text(js)[1] == json.loads(json.dumps(obj, ensure_ascii=False)), "round trip failed"
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(js)
        os.replace(tmp, path)

    def open_text(self, text):
        m = _RX.search(text)
        if not m:
            raise SealError("not an encrypted data file")
        return m.group(1), self.open_blob(m.group(1), json.loads(m.group(2)))


def is_sealed(text):
    return bool(_RX.search(text)) and not re.search(r"window\.(REPORTS|PODCAST|POWER)(\.\w+|\[[^\]]*\])\s*=", text)


def read_plain(text, slot):
    """Parse a legacy plaintext data file (window.NS.key={...})."""
    ns, key = slot.split(".")
    m = re.search(r'window\.%s(\.%s|\["%s"\])\s*=' % (ns, key, key), text)
    i = text.index("{", m.end())
    return json.loads(text[i: text.rindex("}") + 1])


def read(path, slot, key=None):
    """Data object from an encrypted (or legacy plaintext) file; None if absent or unreadable."""
    try:
        t = open(path, encoding="utf-8").read()
    except OSError:
        return None
    try:
        if is_sealed(t):
            if key is None:
                return None
            s, obj = key.open_text(t)
            return obj if s == slot else None
        return read_plain(t, slot)
    except Exception:  # noqa: BLE001
        return None


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "verify"
    out_dir = os.environ.get("FH_OUT_DIR") or ROOT
    paths = {fn: os.path.join(out_dir, fn) for fn in FILES}
    if cmd == "verify":
        bad = [fn for fn, p in paths.items() if os.path.exists(p) and not is_sealed(open(p, encoding="utf-8").read())]
        print("plaintext data files: %s" % (", ".join(bad) or "none"))
        return 1 if bad else 0
    try:
        if cmd == "check":
            k = Key()
            for fn, p in paths.items():
                if os.path.exists(p):
                    s, obj = k.open_text(open(p, encoding="utf-8").read())
                    assert s == FILES[fn]
            print("password matches tools/lock.json; all data files decrypt")
            return 0
        if cmd == "init":
            old = None
            if os.environ.get(ENV + "_OLD"):
                old = Key(os.environ[ENV + "_OLD"])
            data = {}
            for fn, p in paths.items():
                if not os.path.exists(p):
                    continue
                t = open(p, encoding="utf-8").read()
                if is_sealed(t):
                    if old is None:
                        raise SealError("%s is already encrypted; set %s_OLD to re-encrypt it" % (fn, ENV))
                    data[fn] = old.open_text(t)[1]
                else:
                    data[fn] = read_plain(t, FILES[fn])
            pw = os.environ.get(ENV, "")
            if not pw:
                raise SealError("%s is not set" % ENV)
            ks, it = secrets.token_bytes(16), ITER
            k = Key(pw, dict(ks=_s(ks), iter=it))
            lock = dict(_doc="Public PBKDF2 salt and an encrypted check value for tools/seal.py. Holds no secret.",
                        v=1, iter=it, ks=_s(ks), check=k.seal_blob("CHECK", "fh-ok"))
            for fn, obj in data.items():
                k.write(paths[fn], FILES[fn], obj)
            with open(LOCK, "w") as f:
                json.dump(lock, f, indent=1)
                f.write("\n")
            print("wrote tools/lock.json and encrypted: %s" % ", ".join(data))
            return 0
    except SealError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
