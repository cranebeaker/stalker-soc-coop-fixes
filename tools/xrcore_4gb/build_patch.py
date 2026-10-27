"""Patch xrMPE's xrCore.dll so add-ons (.addon tar files) can be larger than 4 GiB.

The engine's add-on loader (CLocatorAPI::ProcessAddon / ProcessArchive / LoadArchive / file_from_addon) already has 64-bit
pieces (SetFilePointerEx in the chunk reader, a u64 absolute offset in struct file, MapViewOfFile with the high offset),
but a few spots keep a 32-bit offset or pass 0 as the high half:

  1. ProcessAddon counts the position in the tar in a 32-bit variable and saves it for each member.
     Now: a hidden counter H (how many times the position wrapped past 2^32); the value saved for each member is
     position / 512 (a tar member starts on a 512 byte boundary), which fits 32 bits up to 2 TiB.  It is stored in
     archive.offset as before (the archive struct and the vector of archives stay unchanged).
  2. ProcessArchive and LoadArchive open the chunk reader with the 64-bit offset (offset << 9 split into low, high);
     they used to push 0 as high.
  3. LoadArchive computes each file's absolute position as entry.ptr + archive.offset in 64 bits and hands the high half
     to Register (it was hard-coded 0).
  4. file_from_addon clamps the mapped view to the real 64-bit file size (GetFileSize with the high dword) instead of the
     low 32 bits stored in the archive record.
  5. CStreamReader (rs_open: used for video textures and some level files) maps its window with 32-bit offsets and clamps
     with the 32-bit archive size.  Its four mapping routines (construct, map, remap, advance) get a 64-bit window
     calculation for readers registered in a small table; file_from_archive(CStreamReader) registers a reader when the
     file lies in an add-on larger than 4 GiB, CStreamReader::destroy removes it.  Readers of everything else run the
     original code unchanged (add-ons below 4 GiB behave exactly as before).

Everything new is position independent (the DLL uses ASLR) and lives in two new sections: ".xpat" (code, read+execute)
and ".xpad" (two dwords, read+write).
Not changed: single files (not .db) stored directly in the tar above 4 GiB; a single tar member must stay below 2 GiB
(fseek with a 32-bit long).

usage: python build_patch.py <original xrCore.dll> <patched xrCore.dll>
"""
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

IB = 0x10000000
SEC_RVA = 0x199000          # new code section .xpat (read + execute), right after .reloc (0x195000 + 0x362c, page aligned)
SEC_VSIZE = 0x1000
SEC_RAW = 0xC00
DATA_RVA = 0x19A000         # new data section .xpad (read + write): two dwords
DATA_VSIZE = 0x1000
DATA_RAW = 0x200
H_RVA = DATA_RVA            # dword: how many times the tar position wrapped past 2^32
TMPHI_RVA = DATA_RVA + 4    # dword: high half of a file's absolute position, from the cave to the Register call
TABLE_N = 128               # entries of the reader table
TABLE_RVA = DATA_RVA + 0x10  # TABLE_N entries of 12 bytes: (CStreamReader*, start offset high dword, archive size high dword)
IAT_GETFILESIZE_RVA = 0x350d4   # IAT slot of KERNEL32!GetFileSize (the code calls it as CALL dword ptr [0x100350d4])
IAT_UNMAP_RVA = 0x350d0         # IAT slot of KERNEL32!UnmapViewOfFile (CALL dword ptr [0x100350d0])

ks = Ks(KS_ARCH_X86, KS_MODE_32)
cs = Cs(CS_ARCH_X86, CS_MODE_32)


def A(rva):
    return IB + rva


def asm(text, addr):
    enc, _ = ks.asm(text, addr)
    return bytes(enc)


def build(base, text):
    """assemble a cave placed at absolute address `base`.  A line `@L` marks the label L that follows a `call L`
    (position independent addressing: `pop reg` gives L at run time); {H}, {TMPHI}, {IAT} become 32-bit displacements
    from L to the data dwords / the GetFileSize IAT slot."""
    text = text.replace("{N}", str(TABLE_N))
    text = text.replace("{CALC}", str(A(SEC_RVA)))      # the shared routine is the first cave
    if "@L" not in text:
        return asm(text, base)
    pre, post = text.split("@L", 1)
    n = len(asm(pre + "\nL:\n", base))
    L = base + n
    for key, rva in (("{H}", H_RVA), ("{TMPHI}", TMPHI_RVA), ("{IAT}", IAT_GETFILESIZE_RVA), ("{TABLE}", TABLE_RVA), ("{IATUNMAP}", IAT_UNMAP_RVA)):
        post = post.replace(key, "0x%x" % ((rva - (L - IB)) & 0xFFFFFFFF))
    return asm(pre + "\nL:\n" + post, base)


# enc of a position = (H << 23) | (P >> 9)       (P = 32-bit tar position in esi/[esp+0x1c], H = wrap counter)
CAVES = [
    # ---------------------------------------------------------------- shared routine (first cave: its address is {CALC})
    # calc(this, view_start_lo)  [stdcall, 2 args]: for a CStreamReader registered in the table (a reader of a file of an add-on that is larger
    # than 4 GiB, see the register hook below) it returns ecx = 1, edx = high dword of the view start and eax = number of bytes to map, all in
    # 64-bit arithmetic; ecx = 0 for any other reader (the original code then runs unchanged).  Preserves ebx, esi, edi.
    ("calc  64-bit view window of a CStreamReader", None, None, """
        push ebx
        push esi
        push edi
        mov esi, dword ptr [esp+0x10]
        call L
        @L
        pop ebx
        lea ebx, [ebx + {TABLE}]
        mov ecx, {N}
        find:
        cmp dword ptr [ebx], esi
        je found
        add ebx, 12
        dec ecx
        jnz find
        xor ecx, ecx
        jmp done
        found:
        mov eax, dword ptr [esi+0xc]
        add eax, dword ptr [esi+0x1c]
        mov edx, dword ptr [ebx+4]
        adc edx, 0
        mov edi, edx
        add eax, dword ptr [esi+0x18]
        adc edx, 0
        add eax, 0xffff
        adc edx, 0
        and eax, 0xffff0000
        cmp edx, dword ptr [ebx+8]
        ja clampit
        jb noclamp
        cmp eax, dword ptr [esi+0x14]
        jbe noclamp
        clampit:
        mov eax, dword ptr [esi+0x14]
        noclamp:
        sub eax, dword ptr [esp+0x14]
        mov edx, edi
        mov ecx, 1
        done:
        pop edi
        pop esi
        pop ebx
        ret 8"""),
    # ---------------------------------------------------------------- ProcessAddon: 64-bit position
    ("A  H = 0 at the first header read", 0x8ce0, "8bf0 8944242c", f"""
        mov esi, eax
        mov dword ptr [esp+0x2c], eax
        push eax
        call L
        @L
        pop eax
        mov dword ptr [eax + {{H}}], 0
        pop eax
        jmp {A(0x8ce6)}"""),
    ("B  carry when the position grows (main loop)", 0x939d, "03f1 8974241c", f"""
        add esi, ecx
        push edx
        call L
        @L
        pop edx
        adc dword ptr [edx + {{H}}], 0
        pop edx
        mov dword ptr [esp+0x1c], esi
        jmp {A(0x93a3)}"""),
    ("C  carry (zero block scan)", 0x8d1c, "03f0 33c9 85c0", f"""
        add esi, eax
        push edx
        call L
        @L
        pop edx
        adc dword ptr [edx + {{H}}], 0
        pop edx
        xor ecx, ecx
        test eax, eax
        jmp {A(0x8d22)}"""),
    ("D  borrow (zero block scan)", 0x8d55, "81ee00020000", f"""
        sub esi, 0x200
        push edx
        call L
        @L
        pop edx
        sbb dword ptr [edx + {{H}}], 0
        pop edx
        jmp {A(0x8d5b)}"""),
    ("E  snapshot of a member offset -> [esp+0x10]", 0x8df4, "89742410 85f6", f"""
        push edx
        call L
        @L
        pop edx
        mov edx, dword ptr [edx + {{H}}]
        shl edx, 23
        push eax
        mov eax, esi
        shr eax, 9
        or edx, eax
        pop eax
        mov dword ptr [esp+0x14], edx
        pop edx
        test esi, esi
        jmp {A(0x8dfa)}"""),
    ("F  snapshot (special entry) -> [esp+0x2c]", 0x9005, "8b74241c 8974242c", f"""
        mov esi, dword ptr [esp+0x1c]
        push edx
        call L
        @L
        pop edx
        mov edx, dword ptr [edx + {{H}}]
        shl edx, 23
        push eax
        mov eax, esi
        shr eax, 9
        or edx, eax
        pop eax
        mov dword ptr [esp+0x30], edx
        pop edx
        jmp {A(0x900d)}"""),
    ("G  snapshot (special entry) -> [esp+0x20] (CMOVNZ)", 0x9167, "0f454c241c", f"""
        jnz do
        jmp {A(0x916c)}
        do:
        mov ecx, dword ptr [esp+0x1c]
        push edx
        call L
        @L
        pop edx
        mov edx, dword ptr [edx + {{H}}]
        shl edx, 23
        shr ecx, 9
        or ecx, edx
        pop edx
        jmp {A(0x916c)}"""),
    # ---------------------------------------------------------------- consumers of archive.offset (stored as offset / 512)
    ("H  ProcessArchive: open the archive header chunk at the 64-bit offset", 0x844a, "6a00 ff7318", f"""
        mov eax, dword ptr [ebx+0x18]
        shr eax, 23
        push eax
        mov eax, dword ptr [ebx+0x18]
        shl eax, 9
        push eax
        jmp {A(0x844f)}"""),
    ("I  LoadArchive: open the file list chunk at the 64-bit offset", 0x7fdd, "6a00 ff7618", f"""
        mov eax, dword ptr [esi+0x18]
        shr eax, 23
        push eax
        mov eax, dword ptr [esi+0x18]
        shl eax, 9
        push eax
        jmp {A(0x7fe2)}"""),
    ("J  LoadArchive: absolute file position = entry.ptr + (offset << 9), 64-bit", 0x8098,
     "037e18 3b4e18 1bc0 23c7 8944240c", f"""
        push edx
        mov eax, dword ptr [esi+0x18]
        mov edx, eax
        shl eax, 9
        shr edx, 23
        add edi, eax
        adc edx, 0
        call L
        @L
        pop eax
        mov dword ptr [eax + {{TMPHI}}], edx
        pop edx
        xor ecx, ecx
        cmp ecx, dword ptr [esi+0x18]
        sbb eax, eax
        and eax, edi
        mov dword ptr [esp+0xc], eax
        jmp {A(0x80a6)}"""),
    ("K  LoadArchive: push the high half of the position to Register", 0x8116, "6a00 ff742410", f"""
        call L
        @L
        pop eax
        push dword ptr [eax + {{TMPHI}}]
        push dword ptr [esp+0x10]
        jmp {A(0x811c)}"""),
    ("L  file_from_addon: clamp the view to the real 64-bit file size", 0xd379,
     "8b742418 8b4e0c 85d2 7210 7704 3bc1 760a 8bc1 c744241c00000000", f"""
        mov esi, dword ptr [esp+0x18]
        push eax
        push edx
        push 0
        push esp
        push dword ptr [esi+4]
        call L
        @L
        pop ecx
        call dword ptr [ecx + {{IAT}}]
        pop ecx
        pop edx
        push eax
        mov eax, dword ptr [esp+4]
        cmp edx, ecx
        ja clamp
        jb ok
        cmp eax, dword ptr [esp]
        jbe ok
        clamp:
        mov eax, dword ptr [esp]
        add esp, 8
        mov dword ptr [esp+0x1c], 0
        jmp {A(0xd394)}
        ok:
        add esp, 8
        jmp {A(0xd394)}"""),
    # ---------------------------------------------------------------- CStreamReader (rs_open: video, some level files)
    ("S1 CStreamReader::construct: 64-bit view", 0x2215c, "3bc80f46c18b4d082bc150516a00", f"""
        push ecx
        push dword ptr [ebp+8]
        push esi
        call {{CALC}}
        test ecx, ecx
        pop ecx
        jz orig
        mov ecx, dword ptr [ebp+8]
        push eax
        push ecx
        push edx
        jmp {A(0x2216a)}
        orig:
        mov eax, dword ptr [esi+0x14]
        cmp ecx, eax
        cmovbe eax, ecx
        mov ecx, dword ptr [ebp+8]
        sub eax, ecx
        push eax
        push ecx
        push 0
        jmp {A(0x2216a)}"""),
    ("S2 CStreamReader::map: 64-bit view", 0x221d5, "8b46143bc80f46c12bc750576a00", f"""
        push ecx
        push edi
        push esi
        call {{CALC}}
        test ecx, ecx
        pop ecx
        jz orig
        push eax
        push edi
        push edx
        jmp {A(0x221e3)}
        orig:
        mov eax, dword ptr [esi+0x14]
        cmp ecx, eax
        cmovbe eax, ecx
        sub eax, edi
        push eax
        push edi
        push 0
        jmp {A(0x221e3)}"""),
    ("S3 CStreamReader::remap: 64-bit view", 0x46b0, "8b46143bc80f46c12bc750576a00", f"""
        push ecx
        push edi
        push esi
        call {{CALC}}
        test ecx, ecx
        pop ecx
        jz orig
        push eax
        push edi
        push edx
        jmp {A(0x46be)}
        orig:
        mov eax, dword ptr [esi+0x14]
        cmp ecx, eax
        cmovbe eax, ecx
        sub eax, edi
        push eax
        push edi
        push 0
        jmp {A(0x46be)}"""),
    ("S4 CStreamReader::advance: 64-bit view", 0x22277, "8b47143bc80f46c12bc350536a00", f"""
        push ecx
        push ebx
        push edi
        call {{CALC}}
        test ecx, ecx
        pop ecx
        jz orig
        push eax
        push ebx
        push edx
        jmp {A(0x22285)}
        orig:
        mov eax, dword ptr [edi+0x14]
        cmp ecx, eax
        cmovbe eax, ecx
        sub eax, ebx
        push eax
        push ebx
        push 0
        jmp {A(0x22285)}"""),
    # register the reader (object, start offset high dword, archive size high dword) in the table before construct maps it
    ("S5 file_from_archive(CStreamReader): register readers of files above 4 GiB", 0xbec9, "8bce50ff5204", f"""
        mov ecx, esi
        push eax
        pushad
        call L
        @L
        pop ebp
        mov eax, dword ptr [edi+0x20]
        or eax, dword ptr [edi+0x24]
        jz skip
        push 0
        push esp
        push dword ptr [ebx+4]
        call dword ptr [ebp + {{IAT}}]
        pop edx
        mov eax, dword ptr [edi+0x24]
        or eax, edx
        jz skip
        lea ebx, [ebp + {{TABLE}}]
        mov ecx, {{N}}
        claim:
        xor eax, eax
        lock cmpxchg dword ptr [ebx], esi
        jz got
        add ebx, 12
        dec ecx
        jnz claim
        jmp skip
        got:
        mov eax, dword ptr [edi+0x24]
        mov dword ptr [ebx+4], eax
        mov dword ptr [ebx+8], edx
        skip:
        popad
        call dword ptr [edx+4]
        jmp {A(0xbecf)}"""),
    # CStreamReader::open_chunk builds the child reader inline (not through construct) and maps it with `call map` at 0x10022419.
    # The child is a window into the same file: register it with its parent's high dwords (plus the carry of start + offset)
    ("S7 CStreamReader::open_chunk: register the child reader of a registered parent", 0x2241e - 5, "e872fdffff", f"""
        pushad
        mov edi, dword ptr [ebp-4]
        call L
        @L
        pop esi
        lea esi, [esi + {{TABLE}}]
        mov edx, esi
        mov ecx, {{N}}
        findp:
        cmp dword ptr [edx], edi
        je gotp
        add edx, 12
        dec ecx
        jnz findp
        jmp skip
        gotp:
        mov edi, dword ptr [edx+4]
        mov eax, dword ptr [ebp-4]
        mov ecx, dword ptr [ebx+0xc]
        cmp ecx, dword ptr [eax+0xc]
        adc edi, 0
        mov ecx, {{N}}
        claim:
        xor eax, eax
        lock cmpxchg dword ptr [esi], ebx
        jz got
        add esi, 12
        dec ecx
        jnz claim
        jmp skip
        got:
        mov dword ptr [esi+4], edi
        mov eax, dword ptr [edx+8]
        mov dword ptr [esi+8], eax
        skip:
        popad
        call {A(0x22190)}
        jmp {A(0x2241e)}"""),
    # forget the reader when it is closed (CStreamReader::destroy = the whole 10 byte function)
    ("S6 CStreamReader::destroy: remove the reader from the table", 0x4650, "ff7124ff15d0500310c3", """
        push ebx
        call L
        @L
        pop ebx
        lea eax, [ebx + {TABLE}]
        mov edx, {N}
        unreg:
        cmp dword ptr [eax], ecx
        jne nxt
        mov dword ptr [eax], 0
        jmp done
        nxt:
        add eax, 12
        dec edx
        jnz unreg
        done:
        push dword ptr [ecx+0x24]
        call dword ptr [ebx + {IATUNMAP}]
        pop ebx
        ret"""),
]


def main(src, dst):
    data = bytearray(open(src, "rb").read())
    pe_off = struct.unpack_from("<I", data, 0x3c)[0]
    assert data[pe_off:pe_off + 4] == b"PE\0\0"
    coff = pe_off + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    assert struct.unpack_from("<H", data, opt)[0] == 0x10b
    assert struct.unpack_from("<I", data, opt + 28)[0] == IB
    sec_table = opt + opt_size
    hdr_end = sec_table + 40 * nsec
    secs = [struct.unpack_from("<8sIIIIIIHHI", data, sec_table + 40 * i) for i in range(nsec)]
    first_raw = min(s[4] for s in secs)
    assert hdr_end + 80 <= first_raw, "no room for two more section headers"
    assert max(s[4] + s[3] for s in secs) == len(data), "data after the last section"
    assert struct.unpack_from("<I", data, opt + 56)[0] == SEC_RVA, "SizeOfImage is not what the layout assumes"
    assert struct.unpack_from("<I", data, opt + 96 + 8 * 4)[0] == 0, "file is signed"
    assert not any(s[0].startswith(b".xpat") for s in secs), "already patched"

    def rva2off(rva):
        for s in secs:
            if s[2] <= rva < s[2] + s[3]:
                return rva - s[2] + s[4]
        raise ValueError(hex(rva))

    out = bytearray()
    placed = []
    for name, site, orig_hex, text in CAVES:
        rva = SEC_RVA + len(out)
        code = build(A(rva), text)
        out += code
        out += b"\x90" * ((-len(out)) % 4)
        placed.append((name, site, bytes.fromhex(orig_hex.replace(" ", "")) if orig_hex else b"", rva, code))
    assert len(out) <= SEC_RAW, hex(len(out))
    out += b"\0" * (SEC_RAW - len(out))

    for name, site, orig, rva, code in placed:
        if site is None:
            continue
        off = rva2off(site)
        have = bytes(data[off:off + len(orig)])
        assert have == orig, (name, have.hex(), orig.hex())
        assert len(orig) >= 5, name
        patch = b"\xe9" + struct.pack("<i", rva - (site + 5)) + b"\x90" * (len(orig) - 5)
        data[off:off + len(patch)] = patch

    raw0 = len(data)
    hdr = bytearray(80)
    struct.pack_into("<8sIIIIIIHHI", hdr, 0, b".xpat2", SEC_VSIZE, SEC_RVA, SEC_RAW, raw0, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<8sIIIIIIHHI", hdr, 40, b".xpad2", DATA_VSIZE, DATA_RVA, DATA_RAW, raw0 + SEC_RAW, 0, 0, 0, 0, 0xC0000040)
    data[hdr_end:hdr_end + 80] = hdr
    struct.pack_into("<H", data, coff + 2, nsec + 2)
    struct.pack_into("<I", data, opt + 56, DATA_RVA + DATA_VSIZE)
    struct.pack_into("<I", data, opt + 4, struct.unpack_from("<I", data, opt + 4)[0] + SEC_RAW)        # SizeOfCode
    struct.pack_into("<I", data, opt + 8, struct.unpack_from("<I", data, opt + 8)[0] + DATA_RAW)       # SizeOfInitializedData
    struct.pack_into("<I", data, opt + 64, 0)
    data += out + bytes(DATA_RAW)
    open(dst, "wb").write(data)

    print("section .xpat rva %x, %d bytes of code in %d caves, file %d -> %d bytes" % (SEC_RVA, len(out.rstrip(b"\0")), len(placed), len(data) - SEC_RAW, len(data)))
    for name, site, orig, rva, code in placed:
        print("\n; %s   site %s (%d bytes) -> cave %x (%d bytes)" % (name, "-" if site is None else "%x" % (IB + site), len(orig), IB + rva, len(code)))
        for i in cs.disasm(code, IB + rva):
            print("  %x  %-6s %s" % (i.address, i.mnemonic, i.op_str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
