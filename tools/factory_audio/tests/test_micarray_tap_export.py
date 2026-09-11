from pathlib import Path
import importlib.util
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "micarray_export", ROOT / "tools/factory_audio/export-micarray-tap-capture.py"
)
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)


class MicArrayTapExportTest(unittest.TestCase):
    def test_parses_exact_unique_diagnostic_paths(self):
        root = export.DIAGNOSTIC_ROOT
        marker = "complete " + " ".join(
            f"{key}={root}/1700000000000-{index}.wav"
            for index, key in enumerate(export.OUTPUT_KEYS)
        )
        paths = export.parse_output_paths(marker)
        self.assertEqual(set(export.OUTPUT_KEYS), set(paths))
        self.assertEqual(len(paths), len(set(paths.values())))

    def test_rejects_unavailable_or_outside_path(self):
        marker = " ".join(f"{key}=unavailable" for key in export.OUTPUT_KEYS)
        with self.assertRaisesRegex(export.ExportError, "output_path_missing"):
            export.parse_output_paths(marker)

    def test_output_must_be_new_and_outside_repository(self):
        with self.assertRaisesRegex(export.ExportError, "outside_repository"):
            export.validate_output(ROOT / "private-audio")
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory)
            with self.assertRaisesRegex(export.ExportError, "already_exists"):
                export.validate_output(existing)

    def test_parses_v86_package_identity(self):
        dump = "  codePath=/data/app/dev.sewellzhong.r1probe-1\n  versionCode=86 targetSdk=22\n"
        self.assertEqual(
            (86, "/data/app/dev.sewellzhong.r1probe-1/base.apk"),
            export.parse_package_identity(dump),
        )


if __name__ == "__main__":
    unittest.main()
