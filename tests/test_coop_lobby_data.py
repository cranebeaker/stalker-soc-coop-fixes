"""Контракт guarded-сборщика level.game, без запуска игры и Wine."""

import hashlib
import importlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRIPT = TOOLS / "build_coop_lobby_data.py"
sys.path.insert(0, str(TOOLS))


def chunk(identifier, payload):
    return struct.pack("<II", identifier, len(payload)) + payload


def unpack_chunks(data):
    result = []
    offset = 0
    while offset < len(data):
        identifier, size = struct.unpack_from("<II", data, offset)
        result.append((identifier, data[offset + 8 : offset + 8 + size]))
        offset += 8 + size
    if offset != len(data):
        raise AssertionError("Некорректная длина тестового chunk")
    return result


def point(index, *, team=0, kind=0, mask=1, tail=0):
    return struct.pack("<6fBBHB", index + 0.25, -0.0, -index - 0.5,
                       0.0, index / 10, -0.0, team, kind, mask, tail)


RESERVED = point(0, mask=5, tail=231)
# Canonical ID 0..n-1, non-lobby записи между actor records намеренны.
RECORDS = [(0, RESERVED), (1, point(1, mask=3, tail=201)),
           (2, point(40, team=4, tail=170)), (3, point(2, tail=202)),
           (4, point(41, kind=1, tail=171)), (5, point(3, mask=9, tail=203)),
           (6, point(42, mask=8, tail=172)), (7, point(4, tail=204))]
SOURCE = chunk(0x1000, b"opaque\x00\xffother chunk") + chunk(
    0x2000, b"".join(chunk(*record) for record in RECORDS)
) + chunk(0x3579, b"unknown outer\x00\xfe")
TRANSFORMS = [{"position": [i + 10.5, -17.25, 23.5 - i],
               "rotation": [-0.0, i / 10, 0.0]} for i in range(8)]


def is_lobby(payload):
    return payload[24] == 0 and payload[25] == 0 and struct.unpack_from(
        "<H", payload, 26
    )[0] & 1


class LobbyPatchTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Отсутствует guarded-сборщик данных лобби")
        self.builder = importlib.import_module("build_coop_lobby_data")

    def test_patch_preserves_unknown_data_and_builds_nine_filtered_records(self):
        result = self.builder.patch_level(SOURCE, TRANSFORMS)
        before = unpack_chunks(SOURCE)
        after = unpack_chunks(result)
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2], before[2])
        self.assertEqual(len(result), len(SOURCE) + 4 * 37)
        self.assertEqual(len(after[1][1]), len(before[1][1]) + 4 * 37)
        records = unpack_chunks(after[1][1])
        self.assertEqual([i for i, _ in records],
                         list(range(len(RECORDS) + 4)))
        self.assertEqual(len(set(i for i, _ in records)), len(records))
        self.assertEqual(records[0], RECORDS[0])
        for index in (2, 4, 6):
            self.assertEqual(records[index], RECORDS[index])
        lobby = [payload for _, payload in records if is_lobby(payload)]
        self.assertEqual(len(lobby), 9)
        self.assertEqual(lobby[0], RESERVED)
        original_actors = [payload for _, payload in RECORDS if is_lobby(payload)][1:]
        for index, (payload, transform) in enumerate(zip(lobby[1:], TRANSFORMS)):
            self.assertEqual(payload[:24], struct.pack(
                "<6f", *transform["position"], *transform["rotation"]
            ))
            self.assertEqual(payload[24:], original_actors[index % 4][24:])
        self.assertEqual(SOURCE, chunk(0x1000, before[0][1]) +
                         chunk(0x2000, before[1][1]) + chunk(0x3579, before[2][1]))

    def test_rejects_repeated_patch(self):
        patched = self.builder.patch_level(SOURCE, TRANSFORMS)
        with self.assertRaisesRegex(self.builder.PatchError, "5"):
            self.builder.patch_level(patched, TRANSFORMS)

    def test_rejects_gapped_child_ids_before_selecting_reserved_point(self):
        gapped = chunk(0x2000, b"".join(
            chunk(identifier, point(index))
            for index, identifier in enumerate((0, 2, 3, 4, 5))
        ))
        previous_arbitrary_ids = chunk(0x2000, b"".join(
            chunk(identifier, record)
            for identifier, (_, record) in zip((3, 17, 2, 25, 9, 4, 81, 6), RECORDS)
        ))
        for data in (gapped, previous_arbitrary_ids):
            with self.subTest(data=data[:16].hex()):
                with self.assertRaisesRegex(self.builder.PatchError, "ID"):
                    self.builder.patch_level(data, TRANSFORMS)

    def test_rejects_permuted_child_ids_before_selecting_reserved_point(self):
        data = chunk(0x2000, b"".join(
            chunk(identifier, point(index))
            for index, identifier in enumerate((1, 0, 2, 3, 4))
        ))
        with self.assertRaisesRegex(self.builder.PatchError, "ID"):
            self.builder.patch_level(data, TRANSFORMS)

    def test_requires_exactly_five_source_lobby_points(self):
        for records in (RECORDS[:-1], RECORDS + [(8, point(5))]):
            with self.subTest(count=len(records)):
                with self.assertRaisesRegex(self.builder.PatchError, "5"):
                    self.builder.patch_level(chunk(0x2000, b"".join(
                        chunk(*record) for record in records)), TRANSFORMS)

    def test_rejects_duplicate_outer_or_child_ids(self):
        for data in (SOURCE + chunk(0x1000, b"duplicate"),
                     chunk(0x2000, b"".join(chunk(*record) for record in RECORDS) +
                           chunk(3, point(9, team=1)))):
            with self.subTest(data=data[-20:]):
                with self.assertRaisesRegex(self.builder.PatchError, "ID"):
                    self.builder.patch_level(data, TRANSFORMS)

    def test_rejects_missing_or_ambiguous_target_chunk(self):
        for data in (chunk(0x1000, b"other"), SOURCE + chunk(0x2000, b"")):
            with self.assertRaises(self.builder.PatchError):
                self.builder.patch_level(data, TRANSFORMS)

    def test_rejects_truncated_headers_payloads_and_wrong_record_sizes(self):
        target = b"".join(chunk(*record) for record in RECORDS)
        malformed = [b"", SOURCE[:-1], SOURCE + b"\x01", chunk(0x2000, target[:-1]),
                     chunk(0x2000, target + b"\x00"),
                     chunk(0x2000, target + chunk(8, b"\x00" * 28)),
                     chunk(0x2000, target + chunk(8, b"\x00" * 30))]
        for data in malformed:
            with self.subTest(length=len(data)):
                with self.assertRaises(self.builder.PatchError):
                    self.builder.patch_level(data, TRANSFORMS)

    def test_rejects_noncanonical_high_child_id(self):
        target = b"".join(chunk(*record) for record in RECORDS)
        with self.assertRaises(self.builder.PatchError):
            self.builder.patch_level(chunk(0x2000, target +
                chunk(0xFFFFFFFD, point(9, team=1))), TRANSFORMS)

    def test_rejects_invalid_actor_count_shape_and_nonfinite_or_unrepresentable_float(self):
        invalid = [TRANSFORMS[:7], TRANSFORMS + TRANSFORMS[:1], None,
                   [{"position": [1, 2], "rotation": [0, 0, 0]}] * 8,
                   [{"position": [1, 2, 3], "rotation": [0, 0, 0], "x": 1}] * 8]
        for number in (math.nan, math.inf, -math.inf, 1e100, True, "1"):
            invalid.append([{"position": [number, 0, 0], "rotation": [0, 0, 0]}] * 8)
        for transforms in invalid:
            with self.subTest(transforms=repr(transforms)[:80]):
                with self.assertRaises(self.builder.PatchError):
                    self.builder.patch_level(SOURCE, transforms)

    def test_rejects_nonfinite_source_point(self):
        records = list(RECORDS)
        records[0] = (0, struct.pack("<f", math.nan) + RESERVED[4:])
        with self.assertRaises(self.builder.PatchError):
            self.builder.patch_level(chunk(0x2000, b"".join(
                chunk(*record) for record in records)), TRANSFORMS)


class LobbyStageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Отсутствует guarded-сборщик данных лобби")
        self.builder = importlib.import_module("build_coop_lobby_data")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "originals"
        self.source.mkdir()
        self.maps = [f"coop_test_{index:02}" for index in range(18)]
        self.layout = {"format": 1, "maps": {name: {
            "sha256": hashlib.sha256(SOURCE).hexdigest(), "actors": TRANSFORMS
        } for name in self.maps}}
        for name in self.maps:
            directory = self.source / "levels" / name
            directory.mkdir(parents=True)
            (directory / "level.game").write_bytes(SOURCE)
        self.profile = self.root / "layout.json"
        self.save_layout()
        self.output = self.root / "new-stage"

    def save_layout(self):
        self.profile.write_text(json.dumps(self.layout), encoding="utf-8")

    def build(self):
        return self.builder.build_stage(self.source, self.profile, self.output)

    def test_stage_contains_only_patched_levels_and_leaves_sources_unchanged(self):
        (self.source / "ignored.exe").write_bytes(b"do not copy")
        (self.source / "levels" / self.maps[0] / "level.spawn").write_bytes(b"other")
        hashes = self.build()
        self.assertEqual(set(hashes), set(self.maps))
        paths = sorted(p.relative_to(self.output).as_posix()
                       for p in self.output.rglob("*") if p.is_file())
        self.assertEqual(paths, [f"levels/{name}/level.game" for name in self.maps])
        for name in self.maps:
            actual = (self.output / "levels" / name / "level.game").read_bytes()
            self.assertEqual(actual, self.builder.patch_level(SOURCE, TRANSFORMS))
            self.assertEqual(hashes[name], hashlib.sha256(actual).hexdigest())
            self.assertEqual((self.source / "levels" / name / "level.game").read_bytes(), SOURCE)

    def test_bad_last_hash_creates_no_stage_or_temporary_files(self):
        self.layout["maps"][self.maps[-1]]["sha256"] = "0" * 64
        self.save_layout()
        before = set(self.root.iterdir())
        with self.assertRaisesRegex(self.builder.PatchError, "SHA256"):
            self.build()
        self.assertEqual(set(self.root.iterdir()), before)

    def test_bad_last_transform_is_validated_before_any_writes(self):
        self.layout["maps"][self.maps[-1]]["actors"] = TRANSFORMS[:7]
        self.save_layout()
        with mock.patch("tempfile.mkdtemp", side_effect=AssertionError("premature write")):
            with self.assertRaises(self.builder.PatchError):
                self.build()
        self.assertFalse(self.output.exists())

    def test_bad_last_source_structure_creates_no_stage(self):
        broken = SOURCE[:-1]
        (self.source / "levels" / self.maps[-1] / "level.game").write_bytes(broken)
        self.layout["maps"][self.maps[-1]]["sha256"] = hashlib.sha256(broken).hexdigest()
        self.save_layout()
        with self.assertRaises(self.builder.PatchError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_profile_version_map_set_and_map_count(self):
        initial = json.loads(self.profile.read_text())
        invalid = [{**initial, "format": 2}, {**initial, "format": True},
                   {**initial, "unknown": 1}, {"format": 1, "maps": {}},
                   {"format": 1, "maps": dict(list(initial["maps"].items())[:17])}]
        renamed = json.loads(self.profile.read_text())
        renamed["maps"]["different"] = renamed["maps"].pop(self.maps[-1])
        invalid.append(renamed)
        unsafe = json.loads(self.profile.read_text())
        unsafe["maps"]["../escape"] = unsafe["maps"].pop(self.maps[-1])
        invalid.append(unsafe)
        for value in invalid:
            with self.subTest(value=repr(value)[:80]):
                self.profile.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(self.builder.PatchError):
                    self.build()
                self.assertFalse(self.output.exists())

    def test_rejects_duplicate_json_keys_and_nonstandard_numbers(self):
        for text in ('{"format":1,"format":1,"maps":{}}',
                     '{"format":1,"maps":{"x":NaN}}'):
            self.profile.write_text(text, encoding="utf-8")
            with self.assertRaises(self.builder.PatchError):
                self.build()
            self.assertFalse(self.output.exists())

    def test_rejects_existing_output_and_inplace_or_nested_output(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("unchanged")
        for output in (self.output, self.source, self.source / "stage"):
            with self.subTest(output=output):
                with self.assertRaises(self.builder.PatchError):
                    self.builder.build_stage(self.source, self.profile, output)
        self.assertEqual(marker.read_text(), "unchanged")

    def test_rejects_symlink_source_profile_level_output_and_ancestor(self):
        link = self.root / "source-link"
        link.symlink_to(self.source, target_is_directory=True)
        layout_link = self.root / "layout-link.json"
        layout_link.symlink_to(self.profile)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(self.root, target_is_directory=True)
        self.output.symlink_to(self.root / "missing", target_is_directory=True)
        for source, profile, output in (
            (link, self.profile, self.root / "a"),
            (self.source, layout_link, self.root / "a"),
            (self.source, self.profile, self.output),
            (self.source, self.profile, parent_link / "a"),
        ):
            with self.assertRaises(self.builder.PatchError):
                self.builder.build_stage(source, profile, output)
        self.output.unlink()
        level = self.source / "levels" / self.maps[0] / "level.game"
        level.unlink()
        level.symlink_to(self.source / "levels" / self.maps[1] / "level.game")
        with self.assertRaises(self.builder.PatchError):
            self.build()

    def test_write_failure_does_not_publish_partial_stage(self):
        before = set(self.root.iterdir())
        with mock.patch.object(self.builder.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(set(self.root.iterdir()), before)

    def test_publish_race_does_not_replace_an_existing_empty_directory(self):
        publish = self.builder._publish_stage

        def race(temporary, output):
            output.mkdir()
            race.identity = output.stat().st_ino
            return publish(temporary, output)

        with mock.patch.object(self.builder, "_publish_stage", side_effect=race):
            with self.assertRaises(self.builder.PatchError):
                self.build()
        self.assertEqual(self.output.stat().st_ino, race.identity)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cli_requires_profile_and_reports_failure_without_output(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--source-dir", str(self.source),
                                 "--output-dir", str(self.output)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertIn(b"--layout-file", result.stderr)

    def test_cli_builds_new_stage_with_explicit_profile(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--source-dir", str(self.source),
                                 "--layout-file", str(self.profile), "--output-dir", str(self.output)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(len(list(self.output.glob("levels/*/level.game"))), 18)


if __name__ == "__main__":
    unittest.main()
