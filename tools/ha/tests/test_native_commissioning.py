"""Commissioning accepts only a private, single-use local request."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from custom_components.r1_input_guard.commissioning import consume, write_report

class CommissioningTests(unittest.TestCase):
    def test_missing_marker_is_noop(self):
        with TemporaryDirectory() as directory:
            self.assertIsNone(consume(Path(directory, 'missing')))
    def test_private_pairing_consumed_once(self):
        with TemporaryDirectory() as directory:
            path=Path(directory,'request')
            value={'action':'pair','host':'192.0.2.1','name':'r1-test',
                   'protocol_mac':'02:11:22:33:44:55','noise_psk':base64.b64encode(b'x'*32).decode()}
            path.write_text(json.dumps(value));path.chmod(0o600)
            self.assertEqual(consume(path),value)
            self.assertIsNone(consume(path))
    def test_shared_file_and_symlink_are_rejected(self):
        with TemporaryDirectory() as directory:
            path=Path(directory,'request');path.write_text('{"action":"inspect"}');path.chmod(0o644)
            with self.assertRaises(ValueError): consume(path)
            path.chmod(0o600)
            link=Path(directory,'link');link.symlink_to(path)
            with self.assertRaises(OSError): consume(link)
            self.assertTrue(path.exists())
    def test_bad_key_is_consumed_without_reuse(self):
        with TemporaryDirectory() as directory:
            path=Path(directory,'request');path.write_text(json.dumps({'action':'pair','host':'192.0.2.1',
                'name':'r1-test','protocol_mac':'02:11:22:33:44:55','noise_psk':'bad'}));path.chmod(0o600)
            with self.assertRaises(ValueError): consume(path)
            self.assertFalse(path.exists())
    def test_report_private_and_rejects_symlink(self):
        with TemporaryDirectory() as directory:
            path=Path(directory,'report');write_report(path,{'ok':True})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            link=Path(directory,'link');link.symlink_to(path)
            with self.assertRaises(OSError): write_report(link,{'ok':False})
            self.assertTrue(json.loads(path.read_text())['ok'])
