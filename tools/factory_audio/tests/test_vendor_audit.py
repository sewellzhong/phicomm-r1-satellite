import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "vendor_audit", ROOT / "tools/factory_audio/audit-vendor-abi.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class VendorAuditTest(unittest.TestCase):
    def test_unknown_binary_is_rejected_before_symbol_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "vendor.so"
            candidate.write_bytes(b"not a vendor library")
            with self.assertRaisesRegex(RuntimeError, "hash_not_3448_baseline"):
                audit.audit(candidate)

    def test_pinned_hashes_cover_both_observed_r1_variants(self):
        self.assertEqual(
            {"libuni4michal.so", "libuni4michalchance.so"},
            set(audit.KNOWN_LIBRARIES.values()),
        )
        self.assertIn("uni_4mic_pcm_read", audit.REQUIRED_SYMBOLS)
        self.assertIn("get4MicDoaResult", audit.REQUIRED_SYMBOLS)


if __name__ == "__main__":
    unittest.main()
