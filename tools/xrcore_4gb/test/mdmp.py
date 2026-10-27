"""Print the exception and the module/offset of a Windows minidump (32-bit process): python mdmp.py <file.mdmp>"""
import struct
import sys

b = open(sys.argv[1], "rb").read()
sig, ver, nstreams, dir_rva = struct.unpack_from("<4sIII", b, 0)
assert sig == b"MDMP"
streams = {}
for i in range(nstreams):
    t, size, rva = struct.unpack_from("<III", b, dir_rva + 12 * i)
    streams.setdefault(t, []).append((size, rva))
mods = []
if 4 in streams:
    size, rva = streams[4][0]
    n = struct.unpack_from("<I", b, rva)[0]
    for i in range(n):
        base, msize, _, _, name_rva = struct.unpack_from("<QIIII", b, rva + 4 + 108 * i)
        nlen = struct.unpack_from("<I", b, name_rva)[0]
        name = b[name_rva + 4:name_rva + 4 + nlen].decode("utf-16le")
        mods.append((base, msize, name.split("\\")[-1]))


def where(addr):
    for base, msize, name in mods:
        if base <= addr < base + msize:
            return "%s+0x%x" % (name, addr - base)
    return "?"


if 6 in streams:
    size, rva = streams[6][0]
    tid, _ = struct.unpack_from("<II", b, rva)
    code, flags, _, addr, nparams = struct.unpack_from("<IIQQI", b, rva + 8)
    params = struct.unpack_from("<15Q", b, rva + 8 + 4 + 4 + 8 + 8 + 4 + 4)
    print("exception 0x%08x flags %d at 0x%x  = %s  (thread %d)" % (code, flags, addr, where(addr), tid))
    print("params:", [hex(p) for p in params[:nparams]])
    # context (x86): EIP/ESP/registers
    ctx_size, ctx_rva = struct.unpack_from("<II", b, rva + 8 + 4 + 4 + 8 + 8 + 4 + 4 + 15 * 8)
    f = struct.unpack_from("<I", b, ctx_rva)[0]
    names = ["Edi", "Esi", "Ebx", "Edx", "Ecx", "Eax", "Ebp", "Eip", "SegCs", "EFlags", "Esp"]
    off = 0x9c
    vals = struct.unpack_from("<11I", b, ctx_rva + off)
    print("regs:", " ".join("%s=%08x" % (n, v) for n, v in zip(names, vals)))
    # walk a few return addresses on the stack
    esp = vals[10]
    if 9 in streams:     # Memory64List
        pass
    if 5 in streams:     # MemoryListStream
        size5, rva5 = streams[5][0]
        n = struct.unpack_from("<I", b, rva5)[0]
        for i in range(n):
            start, dsize, drva = struct.unpack_from("<QII", b, rva5 + 4 + 16 * i)
            if start <= esp < start + dsize:
                words = struct.unpack_from("<64I", b, drva + (esp - start))
                print("stack words that point into modules:")
                shown = 0
                for w in words:
                    ww = where(w)
                    if ww != "?" and shown < 14:
                        print("   %08x %s" % (w, ww))
                        shown += 1
else:
    print("no exception stream; modules:", [m[2] for m in mods][:5])
