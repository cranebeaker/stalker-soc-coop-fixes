"""Offline test of the machine code of the patch (no game needed): runs the REAL bytes of the shared routine `calc` (the 64-bit view window of CStreamReader)
from a patched xrCore.dll in the Unicorn x86 emulator and compares it with a plain 64-bit reference, for thousands of random readers, including
windows that straddle the 4 GiB, 8 GiB ... lines, readers that are not registered (must return ecx = 0), and the original 32-bit result for small files.

usage: python emu_calc_test.py <patched xrCore.dll>        (pip install unicorn pefile)
"""
import random
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_EIP

IB = 0x10000000
GRAN = 0x10000
pe = pefile.PE(sys.argv[1])
secs = {s.Name.rstrip(b"\0").decode(): s for s in pe.sections}
xpat, xpad = secs[".xpat"], secs[".xpad"]
code = pe.__data__[xpat.PointerToRawData:xpat.PointerToRawData + xpat.SizeOfRawData]
CALC = IB + xpat.VirtualAddress          # the first cave is calc
TABLE = IB + xpad.VirtualAddress + 0x10
RET_STUB = 0x30000000
THIS = 0x40000000
STACK = 0x50000000

mu = Uc(UC_ARCH_X86, UC_MODE_32)
mu.mem_map(IB + xpat.VirtualAddress, 0x1000)
mu.mem_write(IB + xpat.VirtualAddress, code[:0x1000])
mu.mem_map(IB + xpad.VirtualAddress, 0x1000)
mu.mem_map(RET_STUB, 0x1000)
mu.mem_write(RET_STUB, b"\xf4")                  # hlt = "returned"
mu.mem_map(THIS, 0x1000)
mu.mem_map(STACK, 0x10000)


def ref(start_lo, start_hi, size_lo, size_hi, window, cur, vs_lo):
    start64 = (start_hi << 32) | start_lo
    pos = start64 + cur
    end = (pos + window + GRAN - 1) & ~(GRAN - 1)
    size64 = (size_hi << 32) | size_lo
    end = min(end, size64)
    view_start = pos - (pos % GRAN)
    return ((end - view_start) & 0xFFFFFFFF, (pos >> 32) & 0xFFFFFFFF)


def run(registered, start_lo, start_hi, size_lo, size_hi, window, cur, view_start_lo, slot=5):
    # table: 32 entries of (obj, start_hi, size_hi), zero except the registered one
    mu.mem_write(TABLE, b"\0" * (32 * 12))
    if registered:
        mu.mem_write(TABLE + slot * 12, struct.pack("<III", THIS, start_hi, size_hi))
    # a CStreamReader: +0xc start offset, +0x14 archive size low, +0x18 window, +0x1c current offset
    obj = bytearray(0x30)
    struct.pack_into("<IIII", obj, 0xc, start_lo, 0, size_lo, window)
    struct.pack_into("<I", obj, 0x14, size_lo)
    struct.pack_into("<I", obj, 0x18, window)
    struct.pack_into("<I", obj, 0x1c, cur)
    struct.pack_into("<I", obj, 0xc, start_lo)
    mu.mem_write(THIS, bytes(obj))
    esp = STACK + 0x8000
    mu.mem_write(esp, struct.pack("<III", RET_STUB, THIS, view_start_lo))   # return address, arg1 = this, arg2 = view start low
    mu.reg_write(UC_X86_REG_ESP, esp)
    for r, v in ((UC_X86_REG_EBX, 0x11111111), (UC_X86_REG_ESI, 0x22222222), (UC_X86_REG_EDI, 0x33333333)):
        mu.reg_write(r, v)
    mu.emu_start(CALC, RET_STUB + 1, count=2000)
    eax, ecx, edx = (mu.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX))
    saved = tuple(mu.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI))
    return eax, ecx, edx, saved, mu.reg_read(UC_X86_REG_ESP)


rnd = random.Random(1)
fails = 0
n = 0
straddle = 0
for i in range(20000):
    kind = rnd.choice(["small", "above", "straddle", "edge", "plain"])
    cur = rnd.choice([0, rnd.randrange(0, 1 << 24), rnd.randrange(0, 1 << 28)])
    window = rnd.choice([GRAN, GRAN * 4, GRAN * 16, 1 << 20, 4 << 20])
    if kind == "small":      # a file in an add-on below 4 GiB: registered with size_hi = 0 would not even exist; test the arithmetic anyway
        start64 = rnd.randrange(0, 1 << 31); size64 = rnd.randrange(start64 + cur + 1, (1 << 32) - 1)
    elif kind == "above":
        start64 = rnd.randrange(1 << 32, 6 << 30); size64 = rnd.randrange(start64 + 1, 8 << 30)
    elif kind == "straddle":  # start a little below a multiple of 4 GiB, the current window crosses it
        k = rnd.randrange(1, 3)
        start64 = (k << 32) - rnd.randrange(0, 1 << 26); size64 = rnd.randrange(start64 + (1 << 27), start64 + (1 << 30))
    elif kind == "edge":      # window that ends exactly on a 4 GiB line or at the end of the archive
        k = rnd.randrange(1, 3)
        start64 = (k << 32) - rnd.choice([window, 2 * window, 4 * window, 4]) - cur
        size64 = rnd.choice([k << 32, (k << 32) + GRAN, (k << 32) + 1, start64 + cur + window])
        start64 = max(start64, 0)
    else:
        start64 = rnd.randrange(0, 10 << 30); size64 = start64 + rnd.randrange(1, 1 << 30)
    if start64 + cur >= size64:
        continue
    start_lo, start_hi = start64 & 0xFFFFFFFF, start64 >> 32
    size_lo, size_hi = size64 & 0xFFFFFFFF, size64 >> 32
    pos = start64 + cur
    vs_lo = (pos - pos % GRAN) & 0xFFFFFFFF
    want_bytes, want_hi = ref(start_lo, start_hi, size_lo, size_hi, window, cur, vs_lo)
    eax, ecx, edx, saved, esp = run(True, start_lo, start_hi, size_lo, size_hi, window, cur, vs_lo)
    n += 1
    if ((pos + window + GRAN - 1) & ~(GRAN - 1)) > (1 << 32) > pos - pos % GRAN and ((pos - pos % GRAN) >> 32) != (((pos + window + GRAN - 1) & ~(GRAN - 1)) >> 32):
        straddle += 1
    bad = (ecx != 1 or eax != want_bytes or edx != want_hi or saved != (0x11111111, 0x22222222, 0x33333333) or esp != STACK + 0x8000 + 12 + 4 - 4 + 0)
    # stdcall ret 8: esp = esp0 + 4 (return address) + 8 (two args)
    if esp != STACK + 0x8000 + 12:
        bad = True
    if bad:
        fails += 1
        if fails <= 5:
            print("FAIL", dict(start=hex(start64), size=hex(size64), window=hex(window), cur=cur), "got", hex(eax), ecx, hex(edx), "want", hex(want_bytes), 1, hex(want_hi), [hex(x) for x in saved], hex(esp))
    # a reader that is not registered must be reported as such and left alone
    eax2, ecx2, edx2, saved2, esp2 = run(False, start_lo, start_hi, size_lo, size_hi, window, cur, vs_lo)
    if ecx2 != 0 or saved2 != (0x11111111, 0x22222222, 0x33333333) or esp2 != STACK + 0x8000 + 12:
        fails += 1
        print("FAIL unregistered", hex(ecx2))
print("%d random readers checked (%d with a window crossing a 4 GiB multiple), %d failures" % (n, straddle, fails))
print("ALL PASS" if fails == 0 else "FAILED")
sys.exit(1 if fails else 0)
