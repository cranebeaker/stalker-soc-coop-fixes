"""Write the English subtitle strings for the mod's story voice lines.

  python tools\gen_subtitles.py <translations.json> [out.xml]

translations.json: {"scenario/coop_l03_agroprom/stalker_help_1": "English text", ...}  (key = path of the .ogg under sounds\characters_voice
without extension; an empty text means "no speech", the line is skipped).
The string id is what the game looks up: "characters_voice_" + the path with "/" replaced by "_" (see patches/english_subtitles/NOTES.md).
"""
import json
import os
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(os.path.dirname(HERE), "patches", "english_subtitles", "gamedata", "configs", "text", "eng", "z_soc_subtitles.xml")


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT
    tr = json.load(open(src, encoding="utf-8"))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<string_table>"]
    n = 0
    for rel in sorted(tr):
        text = " ".join(str(tr[rel]).split())
        if not text:
            continue
        sid = "characters_voice_" + rel.replace("/", "_").replace("\\", "_")
        lines.append('\t<string id="%s"><text>%s</text></string>' % (escape(sid), escape(text)))
        n += 1
    lines.append("</string_table>")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    print("%d subtitle strings -> %s" % (n, out))


if __name__ == "__main__":
    main()
