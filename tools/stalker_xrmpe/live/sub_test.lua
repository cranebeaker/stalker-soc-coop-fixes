-- Test of patches/english_subtitles in the live harness (run with lua.ps1 -File sub_test.lua).
coop_subtitles.install()
local out = {}
local function add(s) out[#out + 1] = s end

-- 1) the real call chain of an actor-type voice line: what does actor_sound:play hand to news_manager.send_sound?
local seen = {}
local prev = news_manager.send_sound
news_manager.send_sound = function(npc, faction, point, str, str2, d)
	seen[#seen + 1] = string.format("npc=%s faction=%s snd=%s", tostring(npc), tostring(faction), tostring(str))
	return prev(npc, faction, point, str, str2, d)
end
local pid = live.players()[1].id
xr_sound.set_sound_play(pid, "krot_help_pda_1", nil, nil, true)
news_manager.send_sound = prev
add("chain: " .. (seen[1] or "send_sound was NOT called"))

-- 2) what the wrapper shows: capture give_game_news
local real = db.actor
local got = nil
db.actor = { give_game_news = function(self, caption, text, tex, delay, show, kind) got = { caption, text, tex, delay, show, kind } end }
news_manager.send_sound(nil, nil, nil, "characters_voice\\scenario\\coop_l03_agroprom\\krot_help_pda_2")
db.actor = real
if got then add(string.format("popup: caption=[%s] text=[%s] show=%s", tostring(got[1]), tostring(got[2]), tostring(got[5]))) else add("popup: NOT shown") end

-- 3) a line without a string must stay silent; an NPC line (faction given) must go to the original function only
got = nil
db.actor = { give_game_news = function(self, ...) got = { ... } end }
news_manager.send_sound(nil, nil, nil, "characters_voice\\scenario\\coop_l03_agroprom\\psy_storm")
db.actor = real
add("no-string line shows a popup: " .. tostring(got ~= nil))
return table.concat(out, " || ")
