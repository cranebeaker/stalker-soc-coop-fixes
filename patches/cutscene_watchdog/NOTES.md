# cutscene_watchdog

Players reported (Agroprom, first arrival, two real players): the Mole flyover camera starts, both players stand still with the UI off, no console, no ESC, and
after a couple of minutes they can move again. The same camera logic (`sr_cutscene@fly`) runs the Bar arena and Rostok cameras.

The scene ends only when the camera effector reports its end (`sr_cutscene.effector_callback`, then the signal `cameff_end`); the UI and input come back
in that callback. If the callback is not delivered the player stays frozen. With one or two clients entering together the harness showed the callback
arriving 22 s after the start (the .anm is 22.03 s), so the lost callback only happens in real play (timing, joining, lag).

## Fix
`scripts\sr_cutscene.script` is the xrMPE script plus one watchdog (everything else is byte for byte the same): `zone_enter` stores the start time, and
`update` ends the scene when the UI is still off 45 s after the start (`CUTSCENE_WATCHDOG_MS`, the longest flight is about 22 s): it stops the camera
effector, jumps past the last effect and runs the normal end path (`cutscene_callback`), which switches the UI and input back on, faces the look point and
sets `cameff_end`. The log line `[sr_cutscene] watchdog: ... releasing the player` shows when it fired. The worst case for a player is 45 s, not minutes.

Covers all three camera scenes (Agroprom, Bar arena, Rostok). Not proven in game: a player that gets stuck needs the lost callback, which the test PC did not
produce. Written offline, bracket check OK.
