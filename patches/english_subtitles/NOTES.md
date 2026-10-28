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
