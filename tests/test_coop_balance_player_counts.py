"""Execute the shipped balance Lua in LuaJIT; only the engine API is mocked.

Run: python3 -m unittest discover -s tests -p test_coop_balance_player_counts.py -v
from work/source. This does not start X-Ray or verify its network/ALife bindings.
"""

import configparser
import ctypes
import ctypes.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BALANCE = ROOT / "patches/soc_economy/gamedata/scripts/coop_balance.script"
SCALING = ROOT / "patches/player_scaling/gamedata/scripts/player_scaling.script"
HOST_CFG = ROOT / "patches/host_settings/gamedata/scripts/coop_host_cfg.script"


def lua_string(value):
    """Quote arbitrary source/config text without translating its Lua syntax."""
    equals = ""
    while "]" + equals + "]" in value:
        equals += "="
    return "[" + equals + "[" + value + "]" + equals + "]"


def ini_literal(path):
    ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    ini.read(path, encoding="utf-8")
    return "{" + ",".join(
        "[ " + lua_string(section) + " ]={" + ",".join(
            "[ " + lua_string(key) + " ]=" + lua_string(value)
            for key, value in ini[section].items()
        ) + "}" for section in ini.sections()
    ) + "}"


ENGINE_API = r'''
NOW, SERVER, DEDICATED, API_COUNT = 0, true, false, 0
LEVEL_NAME, DISTANCE = "coop_l01_escape", 1000
db, objects, calls, logs, host_values = {mp_actors={}}, {}, {}, {}, {}
function time_global() return NOW end
function OnServer() return SERVER end
function OnClient() return not SERVER end
function IsDedicatedServer() return DEDICATED end
function get_players_count() return API_COUNT end
function printf_msg(fmt, ...) table.insert(logs, string.format(fmt, ...)) end
function getFS() return {update_path=function(self, root, name) return root.."/"..name end} end
-- Virtualize only file I/O: the real coop_host_cfg parses this host fixture.
io = {open=function(path, mode)
    if path~="$app_data_root$/coop_settings.ltx" or mode~="r" then return nil end
    local lines={"[client]", "voice_language=auto"}
    for section, values in pairs(host_values) do
        table.insert(lines,"["..section.."]")
        for key, value in pairs(values) do table.insert(lines,key.."="..tostring(value)) end
    end
    return {read=function() return table.concat(lines,"\n") end, close=function() end}
end}
function make_ini(data)
    return {
        section_exist=function(self, section) return data[section] ~= nil end,
        line_exist=function(self, section, key) return data[section] and data[section][key] ~= nil or false end,
        r_float=function(self, section, key) return assert(tonumber(data[section][key])) end,
        r_bool=function(self, section, key) return data[section][key] == "true" end,
        r_string=function(self, section, key) return data[section][key] end,
    }
end
function ini_file(path) return INIS[path] end
function vector_at(x)
    return {x=x or 0, distance_to=function(self, other) return math.abs(self.x-other.x) end,
        sub=function(self, other) return vector_at(self.x-other.x) end,
        set=function(self) return self end}
end
function vector() return vector_at(0) end
level = {
    name=function() return LEVEL_NAME end,
    object_by_id=function(id) return objects[id] end,
    add_call=function(fn, done) table.insert(calls, {fn=fn, done=done}) end,
}
function advance(milliseconds)
    NOW = NOW + milliseconds
    local old = calls
    calls = {}
    for _, call in ipairs(old) do
        if call.fn() then call.done() else table.insert(calls, call) end
    end
end
function players(alive, dead, stale_slots)
    db.mp_actors = {}
    for id=1, alive+(dead or 0) do
        local living = id <= alive
        local actor = {alive=function() return living end, id=function() return id end,
            position=function() return vector_at(0) end}
        db.mp_actors[id] = actor
        objects[id] = actor
    end
    API_COUNT = stale_slots or alive+(dead or 0)+(DEDICATED and 1 or 0)
end
function no_script_errors()
    for _, line in ipairs(logs) do
        assert(not line:find("error:") and not line:find("error reading"), line)
    end
end
function make_trader()
    local npc = {batches=0, sections={}}
    function npc:name() return "fixture_trader" end
    function npc:buy_supplies(config, section)
        self.batches = self.batches+1
        table.insert(self.sections, section)
        assert(config == trader_config and section == "supplies_test_ammo")
    end
    trader_config = make_ini({supplies_test_ammo={ammo="1,1"}})
    local tt = {config=trader_config, current_buy_supplies="supplies_test"}
    CB.on_supplied(npc, tt, tt.current_buy_supplies)
    return npc, tt
end
named_sections = {}
function system_ini()
    return {line_exist=function(self, section, key) return key == "story_id" and named_sections[section] or false end}
end
utils = {parse_names=function(text)
    local result = {}
    for item in text:gmatch("[^,%s]+") do table.insert(result, item) end
    return result
end}
story_flags = {story_flags={}}
function story_flags.set_flag(name, value) story_flags.story_flags[name] = value end
local world = {
    object=function(self, id) return objects[id] end,
    release=function(self, obj) objects[obj.id] = nil end,
}
function alife() return world end
function make_smart(id, job_count, population)
    local smart = {id=id, population=population or 0, jobs={}, position=vector_at(DISTANCE), npc_info={}}
    function smart:name() return "fixture_smart_"..self.id end
    for i=1, job_count do smart.jobs[i] = {job_id=i} end
    objects[id] = smart
    return smart
end
board = {smarts={}, squads={}, created=0, next_id=20000}
function board:setup_squad_and_group() end
function board:enter_smart(squad, id) squad.smart_id=id end
function board:remove_squad(squad)
    self.squads[squad.id] = nil
    objects[squad.id] = nil
    for _, entry in pairs(self.smarts) do entry.squads[squad.id] = nil end
end
function make_squad(id, base, faction, section, smart)
    local squad = {id=id, members={}, added=0, settings_id=section or "fixture_squad",
        player_id=faction or "bandit", online=false, board=board, smart_id=smart and smart.id}
    function squad:npc_count() return #self.members end
    function squad:squad_members()
        local i=0
        return function() i=i+1; return self.members[i] end
    end
    function squad:add_squad_member(section, position, lv, gv, index)
        local member_id = self.id*100 + #self.members+1
        local obj = {id=member_id, group_id=self.id, position=position,
            m_level_vertex_id=lv, m_game_vertex_id=gv}
        objects[member_id] = obj
        table.insert(self.members, {id=member_id, object=obj})
        self.added = self.added+1
        return member_id
    end
    function squad:assign_squad_member_to_smart(id, destination)
        destination.population=destination.population+1
    end
    function squad:set_squad_relation() end
    function squad:update() end
    squad.sound_manager = {unregister_npc=function() end}
    function squad:unregister_member(id)
        for i, member in ipairs(self.members) do
            if member.id==id then table.remove(self.members, i); break end
        end
    end
    for i=1, base do squad:add_squad_member("generic", vector_at(0), 0, 0, i) end
    squad.added = 0
    objects[id], board.squads[id] = squad, squad
    return squad
end
function board:create_squad(smart, section)
    self.created, self.next_id = self.created+1, self.next_id+1
    local squad = make_squad(self.next_id, 3, "bandit", section, smart)
    self.smarts[smart.id].squads[squad.id] = squad
    smart.population = smart.population+3
    PS.on_squad_created(squad, smart)
    return squad
end
sim_board = {
    squad_ltx=make_ini({fixture_squad={npc="generic"}, fixture_squad_ps={npc="generic"},
        named_squad={npc="story_character"}}),
    get_sim_board=function() return board end,
}
sim_squad_scripted_cl_manager = {get_squad_manager=function()
    return {remove_member=function() end}
end}
function make_target(id, monster)
    local state = {health=1}
    local obj = {monster=monster, invincible=false, received_hits=0}
    function obj:id() return id end
    function obj:alive() return state.health>0 end
    function obj:invulnerable() return self.invincible end
    function obj:position() return vector_at(1) end
    function obj:hit(h)
        self.received_hits=self.received_hits+1
        self.last_hit=h
        state.health=0
    end
    setmetatable(obj, {
        __index=function(self, key) if key=="health" then return state.health end end,
        __newindex=function(self, key, value)
            if key=="health" then state.health=state.health+value else rawset(self, key, value) end
        end,
    })
    objects[id] = obj
    return obj
end
function IsMonster(obj) return obj.monster end
function IsStalker(obj) return not obj.monster end
hit = setmetatable({fire_wound=1}, {__call=function()
    return {bone=function(self, name) self.bone_name=name end}
end})
'''


class LuaJIT:
    def __init__(self):
        library = ctypes.util.find_library("luajit-5.1")
        if not library:
            raise unittest.SkipTest("libluajit-5.1 is required; no substitute formula is used")
        self.lib = ctypes.CDLL(library)
        signatures = {
            "luaL_newstate": (ctypes.c_void_p, []),
            "luaL_openlibs": (None, [ctypes.c_void_p]),
            "luaL_loadstring": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_char_p]),
            "lua_pcall": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
            "lua_tolstring": (ctypes.c_char_p, [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]),
            "lua_settop": (None, [ctypes.c_void_p, ctypes.c_int]),
            "lua_close": (None, [ctypes.c_void_p]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, arguments
        self.state = self.lib.luaL_newstate()
        if not self.state:
            raise RuntimeError("luaL_newstate failed")
        self.lib.luaL_openlibs(self.state)

    def close(self):
        if self.state:
            self.lib.lua_close(self.state)
            self.state = None

    def run(self, source):
        self.lib.lua_settop(self.state, 0)
        error = self.lib.luaL_loadstring(self.state, source.encode("utf-8"))
        if not error:
            error = self.lib.lua_pcall(self.state, 0, 1, 0)
        value = self.lib.lua_tolstring(self.state, -1, None)
        text = value.decode("utf-8", errors="replace") if value else None
        if error:
            raise AssertionError("LuaJIT: " + str(text))
        return text


class ActualBalanceLuaTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaJIT()
        self.addCleanup(self.lua.close)
        self.lua.run(ENGINE_API)
        self.lua.run("INIS = {" +
            '["misc\\\\coop_balance.ltx"]=make_ini(' + ini_literal(
                ROOT / "patches/soc_economy/gamedata/configs/misc/coop_balance.ltx") + ")," +
            '["player_scaling.ltx"]=make_ini(' + ini_literal(
                ROOT / "patches/player_scaling/gamedata/configs/player_scaling.ltx") + ")}")
        for name, path in (("coop_host_cfg", HOST_CFG), ("CB", BALANCE), ("PS", SCALING)):
            self.lua.run(name + "=setmetatable({}, {__index=_G}); "
                "local source=assert(loadstring(" + lua_string(path.read_text(encoding="utf-8")) +
                "," + lua_string(str(path)) + ")); setfenv(source," + name + "); source()")
        self.lua.run("coop_balance=CB; player_scaling=PS")

    def check(self, source):
        return self.lua.run(source + "\nno_script_errors()")

    def test_both_scripts_count_live_players_1_4_5_8(self):
        for count in (1, 4, 5, 8):
            with self.subTest(players=count):
                self.check(f"players({count}); assert(CB.player_count()=={count}); assert(PS.player_count()=={count})")
        self.check("assert(PS.test_count==nil)")

    def test_dedicated_slot_dead_and_broken_actors_and_stale_entries(self):
        for count in (1, 4, 5, 8):
            with self.subTest(dedicated_players=count):
                self.check(f"DEDICATED=true; players({count}, 2); "
                    f"assert(API_COUNT=={count+3}); assert(CB.player_count()=={count}); assert(PS.player_count()=={count})")
        self.check('''
            DEDICATED=true; players(8, 0, 5)
            assert(CB.player_count()==4 and PS.player_count()==4)
            DEDICATED=false; API_COUNT=5
            assert(CB.player_count()==5 and PS.player_count()==5)
            db.mp_actors[99]={alive=function() error("unavailable actor") end}
            assert(CB.player_count()==5 and PS.player_count()==5)
            players(0, 8); assert(CB.player_count()==0 and PS.player_count()==0)
        ''')

    def test_count_api_failure_falls_back_to_living_actors(self):
        self.check('''
            players(5, 3); get_players_count=function() error("API unavailable") end
            assert(CB.player_count()==5 and PS.player_count()==5)
            db.mp_actors=nil; assert(CB.player_count()==0 and PS.player_count()==0)
        ''')

    def test_ammo_actual_calls_for_caps_four_and_eight(self):
        expected = {4: {1: 0, 4: 3, 5: 3, 8: 3}, 8: {1: 0, 4: 3, 5: 4, 8: 7}}
        self.check("assert(CB.cfg().max_players==4)")
        for cap, rows in expected.items():
            for count, batches in rows.items():
                with self.subTest(cap=cap, players=count):
                    self.check(f'''
                        host_values.ammo={{max_players={cap}}}; coop_host_cfg.reload()
                        players({count}); npc, tt=make_trader(); CB.trader_ammo(npc, tt)
                        assert(npc.batches=={batches}, npc.batches)
                        assert(tt.cb_given=={min(count, cap)})
                    ''')

    def test_ammo_join_leave_throttle_supply_refresh_and_server_guard(self):
        self.check('''
            host_values.ammo={max_players=8}; coop_host_cfg.reload()
            players(1); npc, tt=make_trader(); CB.trader_ammo(npc,tt)
            players(5); advance(2999); CB.trader_ammo(npc,tt); assert(npc.batches==0)
            advance(1); CB.trader_ammo(npc,tt); assert(npc.batches==4 and tt.cb_given==5)
            players(8); advance(3000); CB.trader_ammo(npc,tt); assert(npc.batches==7)
            players(1); advance(3000); CB.trader_ammo(npc,tt)
            assert(npc.batches==7 and tt.cb_given==8)
            players(8); advance(3000); CB.trader_ammo(npc,tt); assert(npc.batches==7)
            CB.on_supplied(npc,tt,"supplies_test"); CB.trader_ammo(npc,tt)
            assert(npc.batches==14 and tt.cb_given==8)
            CB.on_supplied(npc,tt,"wrong_supplies"); CB.trader_ammo(npc,tt)
            assert(npc.batches==14 and tt.cb_given==1)
            SERVER=false; npc, tt=make_trader(); CB.trader_ammo(npc,tt)
            assert(npc.batches==0 and tt.cb_given==1 and tt.cb_next==NOW+3000)
        ''')

    def test_ammo_host_factor_integer_fractional_and_disabled(self):
        for factor, random_value, batches, served in ((2, .75, 8, 5), (.5, .25, 4, 5), (.5, .75, 0, 5), (0, .25, 0, 1)):
            with self.subTest(factor=factor, random=random_value):
                self.check(f'''
                    host_values.ammo={{max_players=8, ammo_per_extra_player={factor}}}; coop_host_cfg.reload()
                    math.random=function() return {random_value} end
                    players(5); npc, tt=make_trader(); CB.trader_ammo(npc,tt)
                    assert(npc.batches=={batches} and tt.cb_given=={served})
                ''')

    def test_ammo_dead_and_dedicated_slots_do_not_deliver_batches(self):
        self.check('''
            host_values.ammo={max_players=8}; coop_host_cfg.reload()
            DEDICATED=true; players(5,3); npc,tt=make_trader(); CB.trader_ammo(npc,tt)
            assert(API_COUNT==9 and npc.batches==4 and tt.cb_given==5)
        ''')

    def test_scaling_factors_saturate_at_four_players(self):
        for count, factor in ((1, 1), (4, 2.5), (5, 2.5), (8, 2.5)):
            with self.subTest(players=count):
                self.check(f"players({count}); assert(PS.factor(false,PS.player_count())=={factor}); "
                    f"assert(PS.factor(true,PS.player_count())=={factor})")

    def test_scaling_real_squad_additions_and_member_cap(self):
        for count, added in ((1, 0), (4, 6), (5, 6), (8, 6)):
            with self.subTest(players=count):
                self.check(f'''
                    players({count}); smart=make_smart(1000+{count},100,0)
                    squad=make_squad(100+{count},4,"bandit","fixture_squad",smart)
                    PS.on_squad_created(squad,smart)
                    assert(squad.added=={added}, squad.added)
                ''')
        self.check('''
            players(8); smart=make_smart(1100,100,0)
            squad=make_squad(200,10,"monster","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==6)
        ''')

    def test_scaling_slot_fraction_population_margin_and_pending_base(self):
        self.check('''
            players(8); smart=make_smart(1000,10,2)
            assert(PS.slot_capacity(smart,false)==6)
            assert(PS.free_slots(smart,false,2)==1)
            squad=make_squad(100,2,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==1)
            smart=make_smart(1001,10,6)
            squad=make_squad(101,2,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==0)
            smart.jobs={
                common={jobs={{job_id=1},{job_id=2},{job_id=3},{job_id=4}}},
                human={_precondition_is_monster=false,jobs={{job_id=5},{job_id=6},{job_id=7},{job_id=8}}},
                mutant={_precondition_is_monster=true,jobs={{job_id=9},{job_id=10}}},
            }
            assert(PS.slot_capacity(smart,false)==4 and PS.slot_capacity(smart,true)==3)
        ''')

    def test_scaling_preserves_named_friendly_clones_and_skipped_levels(self):
        self.check('''
            players(8); named_sections.story_character=true
            smart=make_smart(1000,100,0)
            local cases={{"stalker","fixture_squad"},{"bandit","named_squad"},{"bandit","fixture_squad_ps"}}
            for i, pair in ipairs(cases) do
                local squad=make_squad(100+i,4,pair[1],pair[2],smart)
                PS.on_squad_created(squad,smart); assert(squad.added==0)
            end
            LEVEL_NAME="coop_l11_sarcofag"
            squad=make_squad(110,4,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==0)
            LEVEL_NAME="coop_l01_escape"; SERVER=false
            squad=make_squad(111,4,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==0)
            SERVER=true; host_values.enemy_scaling={enabled=false}; coop_host_cfg.reload()
            squad=make_squad(112,4,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==0)
        ''')

    def test_host_overrides_factors_and_member_limit_but_not_safety_keys(self):
        self.check('''
            PS.cfg(); CB.cfg()
            host_values.enemy_scaling={human_extra_per_player=.25, mutant_extra_per_player=.1,
                max_factor=3, max_extra_members=2, slot_fraction=1, slot_margin=0,
                max_extra_squads_per_smart=99}
            host_values.damage={player_damage_mult=2,log=false}
            assert(PS.factor(false,8)==2.5 and CB.cfg().player_damage_mult==1.5)
            coop_host_cfg.reload()
            assert(PS.factor(false,8)==2.75 and math.abs(PS.factor(true,8)-1.7)<1e-10)
            assert(PS.cfg().slot_fraction==.6 and PS.cfg().slot_margin==1)
            assert(PS.cfg().max_extra_squads_per_smart==1)
            assert(CB.cfg().player_damage_mult==2 and CB.cfg().log==false)
            players(8); smart=make_smart(1000,100,0)
            squad=make_squad(100,4,"bandit","fixture_squad",smart)
            PS.on_squad_created(squad,smart); assert(squad.added==2)
        ''')

    def test_reinforcement_uses_actual_delay_distance_slots_and_one_squad_cap(self):
        self.check('''
            players(8); smart=make_smart(1000,100,3)
            squad=make_squad(100,3,"bandit","fixture_squad",smart)
            board.smarts[smart.id]={smrt=smart,squads={[squad.id]=squad}}
            PS.install(); advance(1000); advance(29000); assert(board.created==0)
            advance(10000); assert(board.created==1)
            advance(10000); assert(board.created==1)
        ''')

    def test_reinforcement_one_player_nearby_player_or_full_smart_blocks_creation(self):
        self.check('''
            players(1); smart=make_smart(1000,10,6)
            squad=make_squad(100,3,"bandit","fixture_squad",smart)
            board.smarts[smart.id]={smrt=smart,squads={[squad.id]=squad}}
            PS.install(); advance(1000); advance(40000); assert(board.created==0)
            players(8); advance(1000); advance(40000); assert(board.created==0)
            smart.population=2; smart.position=vector_at(119)
            advance(10000); assert(board.created==0)
            smart.position=vector_at(120)
            advance(10000); assert(board.created==1)
        ''')

    def test_damage_real_callbacks_apply_same_multiplier_for_one_and_eight(self):
        for count in (1, 8):
            for monster in (False, True):
                with self.subTest(players=count, monster=monster):
                    self.check(f'''
                        players({count}); target=make_target(1000,{str(monster).lower()})
                        local who=db.mp_actors[1]
                        if target.monster then target.health=-.2 end
                        CB.on_npc_hit(target,.2,who,1)
                        if not target.monster then target.health=-.2 end
                        advance(119); assert(math.abs(target.health-.8)<1e-10)
                        advance(1); assert(math.abs(target.health-.7)<1e-10)
                    ''')

    def test_damage_lethal_extra_uses_hit_and_player_credit(self):
        self.check('''
            players(1); target=make_target(1000,false)
            CB.on_npc_hit(target,.8,db.mp_actors[1],1); target.health=-.8
            advance(120)
            assert(target.received_hits==1 and target.last_hit.power==10)
            assert(target.last_hit.draftsman==db.mp_actors[1])
            assert(target.last_hit.bone_name=="bip01_spine")
        ''')


if __name__ == "__main__":
    unittest.main()
