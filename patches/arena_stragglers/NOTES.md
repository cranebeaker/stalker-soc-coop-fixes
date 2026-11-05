# arena_stragglers

Bar arena (Arnie): after the players killed the bloodsuckers of the first fight nothing happened, nobody was taken out of the arena.

## Cause
The fight ends when the whole mutant squad is dead (the squad's `on_death` sets `..._SQUAD_DEAD`, the stop restrictor then teleports the players out).
With two players the player scaling adds members to hostile squads: the arena bloodsucker squad had 12 members instead of 8 (measured with a simulated
two-player count; one more strong bloodsucker and three weak ones, all inside the arena). Weak bloodsuckers are invisible most of the time, so killing
everything that can be seen left one or two alive and the squad never died. With one player the squad has 8 and the fight ended as it should.

## Fix (the scaling stays, the arena stays as hard as before)
`scripts\coop_scn_arena.script` (loaded on every level by the Scene Director, server tick once a second, Bar only, only while the arena flag
`BAR_ARNY_ARENA_SMART_TERRAIN_START_ARENA_GO` is set): for the dog, pseudodog, boar and bloodsucker arena squads it counts the members that are alive.
When at most 2 are alive, all of them are online, and nobody has died for 60 seconds, the remaining ones are killed with `game_object:kill`. The squad then dies
the normal way: flags, teleport out, reward dialog. The timed fights ("during the time") are not touched. The log line `ARENA <squad>: n left and no kill for
60 s: finishing the squad` shows when it fired.

Tested with the live console on the release build (two players simulated with the scaling test count): the bloodsucker squad had 12 members, 10 were
killed, 2 stayed alive; 60 seconds later the log showed `ARENA ...: 2 left and no kill for 60 s: finishing the squad`, the squad died the normal way (`..._SQUAD_DEAD`
and `..._SQUAD_DEAD_FAIL` set, the stop restrictor consumed the dead flag) and the player was moved to the arena exit point. With the real 8-member squad (one player) killing
all members also ended the fight. Not checked: a full session with two real clients. After a fight ended this way the flags `START_ARENA_GO` and `START_CAT_SCENE_INFO`
stayed set (the cutscene restrictor only clears them when it sees the dead flag before the stop restrictor consumes it); the next fight still starts.
