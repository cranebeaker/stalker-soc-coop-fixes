"""Make the in-game probe for the >4 GiB add-on test.
For every file of the given cutscene dbs (the source files) it records the u32 values at a few offsets, writes
<out>\\scripts\\xrbigtest.script, and in the game the script opens each file through the engine's file system and compares.
usage: gen_bigtest.py <out dir> <db> [<db> ...]"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "stalker_xrmpe"))   # xdb.py
import xdb

out = sys.argv[1]
rows = []
for db in sys.argv[2:]:
    with open(db, "rb") as f:
        for name, rs, cs, ptr in xdb.index(f, 0, os.path.getsize(db)):
            if not rs:
                continue
            assert rs == cs, "stored raw expected: " + name
            f.seek(ptr)
            data = f.read(cs)
            offs = sorted(set([0, min(4100, (len(data) - 4) // 4 * 4), len(data) // 2 // 4 * 4, (len(data) - 4) // 4 * 4]))
            vals = [(o, struct.unpack_from("<I", data, o)[0]) for o in offs if o + 4 <= len(data)]
            low = name.lower()
            if low.startswith("textures\\"):
                alias, rel = "$game_textures$", name[len("textures\\"):]
            elif low.startswith("sounds\\"):
                alias, rel = "$game_sounds$", name[len("sounds\\"):]
            else:
                raise SystemExit("unexpected path " + name)
            rows.append((os.path.basename(db), alias, rel, len(data), vals))

lines = []
for dbn, alias, rel, size, vals in rows:
    lines.append('\t{ "%s", "%s", "%s", %d, { %s } },' % (dbn, alias, rel.replace("\\", "\\\\"), size, ", ".join("{%d, %d}" % v for v in vals)))

script = """-- probe for the >4 GiB add-on test (generated; not shipped)
local EXPECT = {
%s
}

local function say(s) printf_msg("%%s", "[BIGTEST] " .. s) end

function ping()
	return "BIGOK " .. #EXPECT
end

function count()
	return #EXPECT
end

function exist_all()
	local fs = getFS()
	local n, miss = 0, {}
	for i, e in ipairs(EXPECT) do
		if fs:exist(e[2], e[3]) then n = n + 1 else miss[#miss + 1] = e[3] end
	end
	return n .. " exist, " .. #miss .. " missing" .. (#miss > 0 and (": " .. table.concat(miss, ", ")) or "")
end

-- control: a normal file from low in the add-on, read and closed the same way
function lowtest(close)
	local fs = getFS()
	local r = fs:r_open("$game_config$", "system.ltx")
	r:r_seek(0)
	local v = r:r_u32()
	say("low read " .. v)
	if close then fs:r_close(r); say("low closed") end
	return "low ok " .. v
end

-- check one file (by index): open it through the engine and compare the words with the source file
function probe(i, noclose)
	local e = EXPECT[i]
	if e == nil then return "no such index" end
	say("open " .. i .. " " .. e[1] .. " " .. e[3] .. " (" .. e[4] .. " bytes)")
	local fs = getFS()
	local res = {}
	local good, err = pcall(function()
		local r = fs:r_open(e[2], e[3])
		say("opened " .. i)
		for _, p in ipairs(e[5]) do
			r:r_seek(p[1])
			local v = r:r_u32()
			res[#res + 1] = (v == p[2]) and "ok" or string.format("BAD@%%d got %%d want %%d", p[1], v, p[2])
		end
		say("read " .. i)
		if not noclose then
			fs:r_close(r)
			say("closed " .. i)
		end
	end)
	if not good then return "ERR " .. e[3] .. " " .. tostring(err) end
	return e[1] .. " " .. e[3] .. ": " .. table.concat(res, " ")
end
""" % "\n".join(lines)
os.makedirs(os.path.join(out, "scripts"), exist_ok=True)
open(os.path.join(out, "scripts", "xrbigtest.script"), "w", newline="\n").write(script)
print(len(rows), "files ->", os.path.join(out, "scripts", "xrbigtest.script"))
