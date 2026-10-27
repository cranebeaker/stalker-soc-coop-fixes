"""Offline test (no game) of the registration code of the patch: runs the REAL bytes of the hook in file_from_archive(CStreamReader) (S5, registers a reader in
the table before construct) and of CStreamReader::destroy (S6, removes it) from a patched xrCore.dll in the Unicorn x86 emulator, with GetFileSize and
UnmapViewOfFile stubbed.  Checks: only readers of files in an add-on above 4 GiB are registered, the table fills and frees correctly, the original call
(construct) still happens with the same arguments, and the registers the caller relies on are preserved.

usage: python emu_register_test.py <patched xrCore.dll> <listing.txt of build_patch.py>     (pip install unicorn pefile)
"""
import re
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

IB = 0x10000000
pe = pefile.PE(sys.argv[1])
secs = {s.Name.rstrip(b"\0").decode(): s for s in pe.sections}
xpat, xpad = secs[".xpat2"], secs[".xpad2"]
code = pe.__data__[xpat.PointerToRawData:xpat.PointerToRawData + xpat.SizeOfRawData]
listing = open(sys.argv[2], encoding="utf-8").read()
S5 = int(re.search(r"^; S5 .*-> cave ([0-9a-f]+)", listing, re.M).group(1), 16)
N = 128
S7 = int(re.search(r"^; S7 .*-> cave ([0-9a-f]+)", listing, re.M).group(1), 16)
S6 = int(re.search(r"^; S6 .*-> cave ([0-9a-f]+)", listing, re.M).group(1), 16)
TABLE = IB + xpad.VirtualAddress + 0x10
IAT_GFS, IAT_UNMAP = IB + 0x350d4, IB + 0x350d0
STUB_GFS, STUB_UNMAP, STUB_CONSTRUCT, STUB_AFTER = 0x31000000, 0x31000010, 0x31000020, IB + 0xbecf
VTABLE, FILE, ARCH, OBJ, STACK, HEAP = 0x40000000, 0x40001000, 0x40002000, 0x40003000, 0x50000000, 0x40004000

mu = Uc(UC_ARCH_X86, UC_MODE_32)
mu.mem_map(IB + xpat.VirtualAddress, 0x1000); mu.mem_write(IB + xpat.VirtualAddress, code[:0x1000])
mu.mem_map(IB + xpad.VirtualAddress, 0x1000)
mu.mem_map(IB + 0x35000, 0x1000)
mu.mem_map(IB + 0x22000, 0x1000); mu.mem_write(IB + 0x22190, bytes([0xc3])); mu.mem_write(IB + 0x2241e, bytes([0x90]))   # map() stub and the instruction after the call in open_chunk
mu.mem_map(IB + 0xb000, 0x1000)            # so that the jump back to 0x1000becf lands somewhere
mu.mem_map(0x31000000, 0x1000)
mu.mem_map(0x40000000, 0x10000)
mu.mem_map(STACK, 0x10000)
mu.mem_write(IAT_GFS, struct.pack("<I", STUB_GFS)); mu.mem_write(IAT_UNMAP, struct.pack("<I", STUB_UNMAP))
mu.mem_write(VTABLE, struct.pack("<III", 0, STUB_CONSTRUCT, 0))
for a in (STUB_GFS, STUB_UNMAP, STUB_CONSTRUCT, STUB_AFTER):
    mu.mem_write(a, b"\x90")

state = {"size_lo": 0, "size_hi": 0, "construct_calls": [], "unmap": 0}


def hook(uc, addr, size, ud):
    esp = uc.reg_read(UC_X86_REG_ESP)
    if addr == STUB_GFS:         # DWORD GetFileSize(HANDLE h, LPDWORD high)  stdcall
        ret, h, hi_ptr = struct.unpack("<III", bytes(uc.mem_read(esp, 12)))
        assert h == 0x1234, "hFile argument wrong: %x" % h
        if hi_ptr:
            uc.mem_write(hi_ptr, struct.pack("<I", state["size_hi"]))
        uc.reg_write(UC_X86_REG_EAX, state["size_lo"])
        uc.reg_write(UC_X86_REG_ESP, esp + 12); uc.reg_write(UC_X86_REG_EIP, ret)
    elif addr == STUB_UNMAP:     # BOOL UnmapViewOfFile(LPCVOID)  stdcall
        ret, _ = struct.unpack("<II", bytes(uc.mem_read(esp, 8)))
        state["unmap"] += 1
        uc.reg_write(UC_X86_REG_EAX, 1); uc.reg_write(UC_X86_REG_ESP, esp + 8); uc.reg_write(UC_X86_REG_EIP, ret)
    elif addr == STUB_CONSTRUCT:  # construct(hMap*, start*, size*, archive_size*, window*) thiscall, ECX = this
        args = struct.unpack("<IIIIII", bytes(uc.mem_read(esp, 24)))
        state["construct_calls"].append((uc.reg_read(UC_X86_REG_ECX), args[1:]))
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + 20); uc.reg_write(UC_X86_REG_EIP, args[0])
    elif addr == STUB_AFTER:
        uc.emu_stop()


mu.hook_add(UC_HOOK_CODE, hook, begin=0x31000000, end=0x31001000)
mu.hook_add(UC_HOOK_CODE, hook, begin=STUB_AFTER, end=STUB_AFTER + 1)
ret_after_destroy = 0x31000F00
mu.mem_write(ret_after_destroy, b"\xf4")


def table():
    raw = bytes(mu.mem_read(TABLE, N * 12))
    return [struct.unpack_from("<III", raw, i * 12) for i in range(N)]


def hook_site(obj, ptr64_lo, ptr64_hi, size_lo, size_hi):
    """what the CStreamReader file_from_archive code has when it reaches the patched 6 bytes (see the function: esi = new reader, edi = file, ebx = archive, edx = vtable)"""
    state["size_lo"], state["size_hi"] = size_lo, size_hi
    state["construct_calls"].clear()
    mu.mem_write(FILE + 0x20, struct.pack("<II", ptr64_lo, ptr64_hi))
    mu.mem_write(ARCH + 4, struct.pack("<I", 0x1234))
    mu.mem_write(OBJ, struct.pack("<I", VTABLE))
    esp = STACK + 0x8000
    # the five pushed arguments as the function builds them: window*, archive_size*, file_size*, start*, then (in the cave) eax = hMap*
    args = struct.pack("<IIII", 0xAAA4, 0xAAA3, 0xAAA2, 0xAAA1)
    mu.mem_write(esp, args)
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ESI, obj); mu.reg_write(UC_X86_REG_EDI, FILE); mu.reg_write(UC_X86_REG_EBX, ARCH)
    mu.reg_write(UC_X86_REG_EDX, VTABLE); mu.reg_write(UC_X86_REG_EAX, 0xBEEF0008); mu.reg_write(UC_X86_REG_ECX, 0)
    mu.reg_write(UC_X86_REG_EBP, 0x12121212)
    mu.emu_start(S5, STUB_AFTER + 1, count=5000)
    return state["construct_calls"][:]


fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ((" : " + str(info)) if info != "" else ""))
    fails += 0 if cond else 1


mu.mem_write(TABLE, b"\0" * (N * 12))
# 1. a file of a plain (not add-on) archive: ptr64 = 0, not registered, construct still called
c = hook_site(OBJ, 0, 0, 0x1000, 0)
check("plain archive file: nothing registered, construct called once with this=ecx and the same argument pointers",
      all(e[0] == 0 for e in table()) and len(c) == 1 and c[0][0] == OBJ and c[0][1] == (0xBEEF0008, 0xAAA4, 0xAAA3, 0xAAA2, 0xAAA1), c)
# 2. add-on below 4 GiB (archive size high = 0, start high = 0): not registered
c = hook_site(OBJ, 0x1000, 0, 0x90000000, 0)
check("add-on below 4 GiB: not registered", all(e[0] == 0 for e in table()) and len(c) == 1)
# 3. add-on above 4 GiB, file below the line: registered with size_hi (start_hi = 0)
c = hook_site(OBJ, 0x7000000, 0, 0x30000000, 1)
t = [e for e in table() if e[0]]
check("add-on above 4 GiB, file below the 4 GiB line: registered (start_hi 0, size_hi 1)", t == [(OBJ, 0, 1)] and len(c) == 1, t)
# 4. file above the line
OBJ2 = OBJ + 0x100
mu.mem_write(OBJ2, struct.pack("<I", VTABLE))
c = hook_site(OBJ2, 0x1234, 1, 0x30000000, 1)
t = sorted([e for e in table() if e[0]], key=lambda e: e[0])
check("file above 4 GiB: registered with start_hi 1", t == [(OBJ, 0, 1), (OBJ2, 1, 1)], t)
# 5. registered registers are preserved for the original call (edx = vtable, ecx = this)
check("construct called with ecx = new reader", c[0][0] == OBJ2)
# 6. destroy removes only its own entry and still calls UnmapViewOfFile
mu.mem_write(OBJ + 0x24, struct.pack("<I", 0xDEAD0000))
esp = STACK + 0x9000
mu.mem_write(esp, struct.pack("<I", ret_after_destroy))
mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_ECX, OBJ); mu.reg_write(UC_X86_REG_EBX, 0x77777777)
state["unmap"] = 0
mu.emu_start(S6, ret_after_destroy + 1, count=5000)
t = sorted([e for e in table() if e[0]], key=lambda e: e[0])
check("destroy(OBJ): its entry is gone, the other stays, UnmapViewOfFile called, ebx preserved, returns",
      t == [(OBJ2, 1, 1)] and state["unmap"] == 1 and mu.reg_read(UC_X86_REG_EBX) == 0x77777777 and mu.reg_read(UC_X86_REG_ESP) == esp + 4, (t, state["unmap"]))
# 7. destroy of a reader that is not in the table: only unmaps
mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_ECX, OBJ + 0x500)
mu.mem_write(OBJ + 0x500 + 0x24, struct.pack("<I", 0))
state["unmap"] = 0
mu.emu_start(S6, ret_after_destroy + 1, count=5000)
check("destroy of an unregistered reader changes nothing and unmaps", [e for e in table() if e[0]] == [(OBJ2, 1, 1)] and state["unmap"] == 1)
# 8. the table holds N readers; the one after is simply not registered (and the original call still happens)
mu.mem_write(TABLE, b"\0" * (N * 12))
for i in range(N):
    o = OBJ + 0x1000 + i * 0x40
    mu.mem_write(o, struct.pack("<I", VTABLE))
    hook_site(o, 0x10, 1, 0x30000000, 1)
check("N readers registered", len([e for e in table() if e[0]]) == N)
o = OBJ + 0x3000
mu.mem_write(o, struct.pack("<I", VTABLE))
c = hook_site(o, 0x10, 1, 0x30000000, 1)
check("reader N+1: table full, not registered, construct still called", len([e for e in table() if e[0]]) == N and len(c) == 1 and c[0][0] == o)
# 9. open_chunk child hook (S7): the child of a registered parent is registered with the parent's high dwords plus the carry of start + offset
def chunk_site(parent, child, frame=STACK + 0xC000):
    mu.mem_write(frame - 4, struct.pack("<I", parent))
    esp = frame - 0x40
    mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_EBP, frame)
    mu.reg_write(UC_X86_REG_EBX, child); mu.reg_write(UC_X86_REG_ECX, child)
    for r, v in ((UC_X86_REG_EAX, 0x11111111), (UC_X86_REG_EDX, 0x22222222), (UC_X86_REG_ESI, 0x33333333), (UC_X86_REG_EDI, 0x44444444)):
        mu.reg_write(r, v)
    mu.emu_start(S7, IB + 0x2241e + 1, count=5000)
    return [mu.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EBP)]


mu.mem_write(TABLE, b"\0" * (N * 12))
P, C, C2, C3 = OBJ + 0x100, OBJ + 0x200, OBJ + 0x300, OBJ + 0x400
mu.mem_write(P + 0xc, struct.pack("<I", 0xFF000000))
hook_site(P, 0xFF000000, 0, 0x30000000, 1)                       # the parent: registered by S5 (start_hi 0, size_hi 1)
mu.mem_write(C + 0xc, struct.pack("<I", 0xFF000100))              # child inside the same 4 GiB block
regs = chunk_site(P, C)
t = sorted([e for e in table() if e[0]], key=lambda e: e[0])
check("child below the wrap: registered with the parent's high dwords (0, 1), registers preserved", (C, 0, 1) in t and regs == [0x11111111, 0x22222222, 0x33333333, 0x44444444, C, C, STACK + 0xC000], (t, [hex(r) for r in regs]))
mu.mem_write(C2 + 0xc, struct.pack("<I", 0x00000100))             # child start wrapped past 2^32
chunk_site(P, C2)
t = {e[0]: e[1:] for e in table() if e[0]}
check("child whose start wrapped past 2^32: start_hi = parent's + 1", t.get(C2) == (1, 1), t.get(C2))
chunk_site(OBJ + 0x700, C3)                                       # parent not registered (plain archive file)
check("child of an unregistered parent: not registered", C3 not in {e[0] for e in table()})
print("ALL PASS" if fails == 0 else "FAILED (%d)" % fails)
sys.exit(1 if fails else 0)
