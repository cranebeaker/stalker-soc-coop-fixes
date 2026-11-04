# english_subtitles

English subtitles for the story voice lines of Shadow of COOP. The mod's own recordings (`sounds\characters_voice\scenario\coop_*`) exist in Russian only.

## How it works
- The game has a built-in subtitle: `npc_sound:play` (sound_theme.script) calls `news_manager.send_sound(npc, faction, point, snd, snd_st, delay)` where `snd_st` is the
  sound file path with `\` replaced by `_`. When the string table has an entry with that id, a PDA news tip with the NPC icon and the text appears (5 s).
  So the NPC lines only need strings: `gamedata/configs/text/eng/z_soc_subtitles.xml` (id = `characters_voice_scenario_<level>_<file>`).
- Lines played as the player's own sound (`type = actor` themes: Mole's PDA voice, helicopter radio) go through `actor_sound:play`, which calls
  `news_manager.send_sound(nil, nil, ...)` (no NPC, no faction): the game shows nothing. `scripts/coop_subtitles.script` wraps `news_manager.send_sound` and shows those
  lines too. It is installed by the bootstrap line in `cutscenes_core/gamedata/scripts/xr_conditions.dscript` (that file is the only load point).
- Tips on clients: the mod relays PDA news from the host to the other players (coop_pda_archive_sync `relay_news`).

## Where the text comes from
Russian transcript with faster-whisper (large-v3-turbo, CPU) of every `scenario/**` .ogg of coop.addon, translated to English by an LLM (Haiku), names per the English
game (Marked One, Sidorovich, Wolf, Duty, Freedom ...). Generated with `tools/gen_subtitles.py`. Machine translated: wording can be off.

## Not covered
Mutant/effect sounds (no speech), the generic stalker chatter (`human_0x/.../states`), the dialog window voices (their text is shown in the dialog already).

## Bottom subtitle (2026-11-03)
The PDA news tip was cut off for long lines and hidden while the UI is off, so every line is now also drawn as a proper subtitle at the bottom centre of the
screen: static `cs_soc_subtitle` (in `soc_save_message\...\ui_custom_msgs.xml`, anchor bot-center, 900 wide) filled by `coop_subtitles.script`
(`show_bottom`, called from the `news_manager.send_sound` wrapper for NPC lines and player-sound lines alike). Text is wrapped at 56 characters, two lines per chunk,
and long lines run as a sequence of chunks timed by length (0.5 s + 0.07 s per character, at least 2.5 s each). A new line replaces the old one. Not shown on the
dedicated server. Written from static analysis, not yet seen in game: check position, size, outline, and that clients receive the line.

## Dialog phrases (2026-11-03)
When an NPC talks to a player, the phrase text did not appear as a subtitle: the speaker only saw the dialog window, the other players a PDA news row. `coop_subtitles.script`
now also wraps two functions of the mod's PDA sync (`coop_pda_archive_sync`): `emit_phrase` (runs on the player who talks) shows the phrase as a bottom subtitle, and
`apply_news` (runs on the other players, news_type 1 = dialog phrase, caption = speaker name) shows "Speaker: text". Both retry once a second until the sync script is loaded.
Written offline, not yet seen in game (a bottom subtitle is a HUD static, so it may stay hidden while the dialog window itself is open).
