"""Make patches\\cordon\\gamedata\\configs\\misc\\tm_coop_l01_escape.ltx from the mod's file (idempotent on the mod file).
  python make_tm_coop_l01_escape.py <mod gamedata.db0\\configs\\misc\\tm_coop_l01_escape.ltx> <out file>
Changes (everything else is byte for byte the mod's):
  * the bridge pass task (esc_start_5_bottles_of_vodka_for_kuznetsov_quest_task, "Rest on duty"): title and description say 500 rubles (strings of
    st_cordon_soc_chain.xml). Section, flags and completion are unchanged. The task is still in coop_hidden_tasks.ltx (SoC has no such task).
  * three new tasks with the original SoC titles: esc_soc_trader_job_task (SoC esc_trader_job), esc_soc_railroad_passage_task (SoC find_railroad_passage),
    esc_soc_military_documents_task (SoC agroprom_get_military_documents). They replace the level maker's helicopter task / Fox tasks, whose sections stay
    (a save may hold them) but are in coop_hidden_tasks.ltx, so they are never given again.
"""
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
d = open(src, 'rb').read()
NL = b'\r\n' if b'\r\n' in d else b'\n'

# bridge pass task: new strings
m = re.search(rb'\[esc_start_5_bottles_of_vodka_for_kuznetsov_quest_task\].*?(?=\r?\n\[|\Z)', d, re.S)
assert m, 'vodka section'
sec = m.group(0)
sec2 = re.sub(rb'(?m)^(title\s*=\s*)\S+', rb'\1coop_soc_task_pass_name', sec)
sec2 = re.sub(rb'(?m)^(descr\s*=\s*)\S+', rb'\1coop_soc_task_pass_descr', sec2)
d = d[:m.start()] + sec2 + d[m.end():]

# "We don't leave our own behind" (talk to Petruha): Petruha's logic leaves the talk state for good as soon as the ATP bandits are dead, so a
# group that cleared the ATP before talking to him could never finish the task (soft-lock reported 2026-10-21). Done also when the bandits are
# dead, with the same follow-up as the dialog (the ATP task, which completes at once and hands out "return to Wolf").
PETRUHA_EXTRA = b'condlist_1 \t\t\t\t\t\t\t\t\t\t\t= {+ESC_SMART_TERRAIN_3_BANDIT_1_SQUAD_DEAD} complete %=give_task(esc_start_kill_bandits_on_the_atp_quest_task)%'
m = re.search(rb'\[esc_start_talk_to_petruha_quest_task\].*?(?=\r?\n\r?\n|\r?\n;|\r?\n\[|\Z)', d, re.S)
assert m, 'petruha section'
if b'condlist_1' not in m.group(0):
    d = d[:m.end()] + NL + PETRUHA_EXTRA + d[m.end():]

new = '''
;--------------------------------------------------------------------------------------------------------------------------------------
;-- Original SoC after the flash drive (patch cordon, see NOTES.md). Titles and texts are SoC's (st_cordon_soc_chain.xml).
;--   esc_soc_trader_job_task          SoC esc_trader_job: "Work for the trader" (get the special task from Sidorovich), done when he gave it
;--   esc_soc_railroad_passage_task    SoC find_railroad_passage: way north, done on arrival at the Garbage (the old "Road to the North" end)
;--   esc_soc_military_documents_task  SoC agroprom_get_military_documents: done when the Barkeep has the documents. ONE task like SoC: its description
;--                                    and marker follow the objectives (patch agroprom_soc): Cordon text until the group is on Agroprom, "steal the documents"
;--                                    (no marker), then "take the documents to the Barkeep" (marker: the Barkeep) once the case is in hand (flag AGR_START_BREAK_...)
;-- They are given to EVERY player by the server tick of coop_soc_opening.script.
;--------------------------------------------------------------------------------------------------------------------------------------
[esc_soc_trader_job_task]
icon 												= ui_inGame2_esc_start_talk_to_the_sidorovich_quest_1_task
prior 												= 400
storyline 											= true
title 												= coop_soc_task_trader_job_name
descr 												= coop_soc_task_trader_job_descr
target 												= esc_smart_terrain_1_trader_sidorovich
condlist_0 											= {+ESC_SMART_TERRAIN_1_TRADER_SIDOROVICH_GO_TO_FOX_STOP_DIALOG_INFO} complete

[esc_soc_railroad_passage_task]
icon 												= ui_inGame2_esc_start_talk_to_the_fox_quest_2_task
prior 												= 400
storyline 											= true
title 												= coop_soc_task_railroad_name
descr 												= coop_soc_task_railroad_descr
target 												= esc_gar_level_changer
condlist_0 											= {+GAR_WAITING_FOR_THE_ORDER_TO_KILL_YURIK_INFO} complete

[esc_soc_military_documents_task]
icon 												= ui_inGame2_esc_start_talk_to_the_fox_quest_2_task
prior 												= 390
storyline 											= true
title 												= coop_soc_task_documents_name
descr 												= {+AGR_START_BREAK_INTO_A_MILITARY_BASE_QUEST_TASK_INFO} st_agr_start_the_destination_is_a_bar_quest_task_descr, {+AGR_STALKER_HELP_1_INFO} st_agr_start_break_into_a_military_base_quest_task_descr, coop_soc_task_documents_descr
target 												= {+AGR_START_BREAK_INTO_A_MILITARY_BASE_QUEST_TASK_INFO} bar_smart_terrain_1_stalker_barmen
condlist_0 											= {+BAR_SMART_TERRAIN_1_TRADER_BARMEN_HAS_DOCUMENTS_AGROPROM_STOP_DIALOG_INFO} complete
'''.replace('\n', NL.decode()).encode('cp1251')

if b'[esc_soc_trader_job_task]' not in d:
    marker = re.search(rb'(?m)^;-+\r?\n;-- ' + 'Второстепенные квесты'.encode('utf-8'), d)
    assert marker, 'second-rank quests marker'
    d = d[:marker.start()] + new.lstrip(NL) + NL + d[marker.start():]
open(dst, 'wb').write(d)
print('ok', len(d))
