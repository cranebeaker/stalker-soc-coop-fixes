# Builds zzz_soc_coop_fixes.db from every patches/<fix>/gamedata folder.
# Usage: python build.py [out.db] [--sarcophagus-fps] [--player-limit 8]
# --player-limit 8 adds the checked-in eight-player data/profile (no game/archive required).
# --sarcophagus-fps adds optional/sarcophagus_fps (better FPS in the big Monolith fights, for weaker PCs).
# --skip=a,b leaves those patch folders out (unfinished work). --stage=DIR also keeps the merged gamedata folder in DIR.
# --compress (default ON) stores the files LZO1X-compressed, --no-compress writes a raw db (tools/pack.py). The db must fit below 4 GiB
# inside coop.addon (see tools/budget.py): the build FAILS (exit 1, db deleted) when it does not. --no-budget-check skips that guard.
import argparse, os, shutil, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
player_parser = argparse.ArgumentParser(add_help=False)
player_parser.add_argument('--player-limit', type=int, choices=[8])
player_options, build_args = player_parser.parse_known_args()
player_profile = player_options.player_limit == 8
args = [a for a in build_args if not a.startswith('--')]
extra = ['sarcophagus_fps'] if '--sarcophagus-fps' in build_args else []
extra += ['mm_style_' + a[11:] for a in build_args if a.startswith('--mm-style=')]   # soc_main_menu: --mm-style=soc | ue4_a | ue4_b (replaces the default main menu style, see patches/soc_main_menu/NOTES.md)
skip = set(sum([a[7:].split(',') for a in build_args if a.startswith('--skip=')], []))
compress = '--no-compress' not in build_args
keep = [a[8:] for a in build_args if a.startswith('--stage=')]
out = os.path.abspath(args[0] if args else os.path.join(here, 'build', 'zzz_soc_coop_fixes.db'))
if player_profile:
    sys.path.insert(0, os.path.join(here, 'tools'))
    import coop_player_limit_build as player_build
    try:
        player_build.validate_output_profile(out)
    except (player_build.ProfileError, OSError) as error:
        sys.exit('BUILD FAILED: ' + str(error))
os.makedirs(os.path.dirname(out), exist_ok=True)
stage = tempfile.mkdtemp(prefix='soc_fixes_')
try:
    for fix in sorted(os.listdir(os.path.join(here, 'patches'))):
        src = os.path.join(here, 'patches', fix, 'gamedata')
        if fix in skip:
            print('skipped', fix)
            continue
        if os.path.isdir(src):
            shutil.copytree(src, stage, dirs_exist_ok=True)
    for fix in extra:
        if not os.path.isdir(os.path.join(here, 'optional', fix, 'gamedata')):
            print(fix, 'has no optional folder: that style is already the default of its patch')
            continue
        shutil.copytree(os.path.join(here, 'optional', fix, 'gamedata'), stage, dirs_exist_ok=True)
    if player_profile:
        try:
            player_build.apply_profile(stage, os.path.join(here, 'optional', 'player_limit_8'))
        except (player_build.ProfileError, OSError) as error:
            sys.exit('BUILD FAILED: ' + str(error))
    if keep:
        shutil.copytree(stage, os.path.join(keep[0], 'gamedata'), dirs_exist_ok=True)
    subprocess.check_call([sys.executable, os.path.join(here, 'tools', 'pack.py'), stage, out] + (['--compress'] if compress else ['--no-compress']))
    if compress:
        r = subprocess.run([sys.executable, os.path.join(here, 'tools', 'verify_db.py'), out, stage], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            os.remove(out)
            sys.exit('BUILD FAILED: the compressed db does not read back identical to the stage folder (db deleted)')
    print('built', out)
    if '--no-budget-check' not in build_args:
        sys.path.insert(0, os.path.join(here, 'tools'))
        import budget
        ok, msg = budget.check(out)
        print(('BUDGET OK: ' if ok else 'BUDGET FAIL: ') + msg)
        if not ok:
            os.remove(out)
            sys.exit('BUILD FAILED: zzz_soc_coop_fixes.db does not fit into coop.addon below 4 GiB (db deleted). '
                     'Skip patches (--skip=...), shrink assets, or see stalker.md section 3.')
    if player_profile:
        try:
            profile = player_build.write_output_profile(out)
        except (player_build.ProfileError, OSError) as error:
            sys.exit('BUILD FAILED: profile not written: ' + str(error))
        print('profile', profile)
finally:
    shutil.rmtree(stage, ignore_errors=True)
