"""Replace the shader models\\antigas_glass (not in the xrMPE shader library: the client crashes when it draws the model) by models\\weapons in the
converted SoC suit models stalker_ecolog.ogf (SSP-99 orange) and stalker_chemical.ogf (SSP-99 green).

The shader name sits in the OGF_TEXTURE chunk (texture name, 0, shader name, 0). The new name is padded with zero bytes to the old length, so the chunk size,
every parent chunk size and the file size stay exactly as they were. Safe to run again (nothing to do when the shader is already replaced).

  python -I patches\\marked_one\\tools\\fix_antigas_shader.py [--dry-run]
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MESHES = os.path.join(os.path.dirname(HERE), "gamedata", "meshes", "actors", "marked_one")
FILES = ["stalker_ecolog.ogf", "stalker_chemical.ogf"]
OLD = b"models\\antigas_glass"
NEW = b"models\\weapons"          # same shader the SEVA scientist suit uses for its glass


def chunks(b, off, end):
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", b, off)
        yield cid & 0x7FFFFFFF, off + 8, size
        off += 8 + size


def fix(b):
    """returns number of replaced shader names; b is a bytearray edited in place"""
    n = 0

    def walk(off, end):
        nonlocal n
        for cid, o, size in chunks(b, off, end):
            if cid == 2 and size > 2:
                payload = bytes(b[o:o + size])
                parts = payload.split(b"\x00")
                if len(parts) > 1 and parts[1] == OLD:
                    new = parts[0] + b"\x00" + NEW + b"\x00"
                    new += b"\x00" * (size - len(new))
                    assert len(new) == size
                    b[o:o + size] = new
                    n += 1
            elif cid == 9:
                for _c, co, csz in chunks(b, o, o + size):
                    walk(co, co + csz)

    walk(0, len(b))
    return n


def main():
    dry = "--dry-run" in sys.argv
    for name in FILES:
        p = os.path.join(MESHES, name)
        b = bytearray(open(p, "rb").read())
        size = len(b)
        n = fix(b)
        assert len(b) == size
        print("%-24s replaced %d shader name(s)%s" % (name, n, " (dry run)" if dry else ""))
        if n and not dry:
            open(p, "wb").write(bytes(b))


if __name__ == "__main__":
    main()
