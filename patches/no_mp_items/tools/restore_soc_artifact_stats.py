"""Set cost and *_restore_speed of the mod's af_*_soc sections to the original Shadow of Chernobyl numbers.

usage: python -I restore_soc_artifact_stats.py <original SoC config/misc/artefacts.ltx> <artefacts_soc.ltx>

Only the values that differ are rewritten (bytes, line endings and encoding stay as they are). Immunities already match.
"""
import re
import sys

KEYS = ["cost", "health_restore_speed", "radiation_restore_speed", "satiety_restore_speed",
        "power_restore_speed", "bleeding_restore_speed"]


def parse(text):
    secs = {}
    for m in re.finditer(r"(?ms)^\[([^\]]+)\](?::([^\r\n;]*))?[^\n]*\n(.*?)(?=^\[|\Z)", text):
        par = [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]
        body = {}
        for line in m.group(3).replace("\r", "").split("\n"):
            line = line.split(";")[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                body[k.strip()] = v.strip()
        secs[m.group(1).strip()] = (par, body)
    return secs


def eff(secs, name, seen=()):
    if name not in secs or name in seen:
        return {}
    par, body = secs[name]
    out = {}
    for p in par:
        out.update(eff(secs, p, seen + (name,)))
    out.update(body)
    return out


def main():
    orig = parse(open(sys.argv[1], encoding="cp1251", errors="replace").read())
    path = sys.argv[2]
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    changed = 0
    for name in [n for n in orig if re.match(r"af_[a-z_0-9]+$", n) and not n.endswith("_absorbation")]:
        sec = name + "_soc"
        m = re.search(r"(?ms)^\[%s\][^\n]*\n(.*?)(?=^\[|\Z)" % re.escape(sec), text)
        if not m:
            continue
        o = eff(orig, name)
        body = m.group(1)
        new = body
        for k in KEYS:
            if k not in o:
                continue
            new = re.sub(r"(?m)^(%s\s*=\s*)([^\s;\r]+)" % k, lambda mm: mm.group(1) + o[k], new, count=1)
        if new != body:
            changed += 1
            text = text[:m.start(1)] + new + text[m.end(1):]
    open(path, "wb").write(text.encode("utf-8"))
    print("sections changed:", changed)


main()
