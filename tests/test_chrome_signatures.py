import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import update_google_chrome as updater


DETRITUS = "resource fork, Finder information, or similar detritus not allowed"
SUCCESS = subprocess.CompletedProcess([], 0, "", "")


class SignatureRecoveryTests(unittest.TestCase):
    def test_valid_original_needs_no_copy(self):
        app = Path("/fixture/Google Chrome.app")
        with patch.object(updater, "run", return_value=SUCCESS) as run:
            verified = updater.verify_app_signature(app, Path("/staging"))
            self.assertEqual(verified, app)
        run.assert_called_once_with(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)]
        )

    def test_other_signature_failures_are_not_retried(self):
        with patch.object(
            updater, "run", side_effect=updater.UpdateError("invalid signature")
        ) as run:
            with self.assertRaisesRegex(updater.UpdateError, "invalid signature"):
                updater.verify_app_signature(Path("/fixture"), Path("/staging"))
        self.assertEqual(run.call_count, 1)

    def test_metadata_recovery_rechecks_strict_signature_without_resigning(self):
        with patch.object(
            updater,
            "run",
            side_effect=[
                updater.UpdateError(DETRITUS), SUCCESS, SUCCESS, SUCCESS, SUCCESS,
            ],
        ) as run:
            verified = updater.verify_app_signature(Path("/fixture"), Path("/staging"))
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(verified, Path("/staging/Google Chrome.app"))
        self.assertEqual(commands[-1], [
            "/usr/bin/codesign", "--verify", "--deep", "--strict", str(verified)
        ])
        self.assertEqual(commands[2:4], [
            ["/usr/bin/xattr", "-drs", "com.apple.FinderInfo", str(verified)],
            ["/usr/bin/xattr", "-drs", "com.apple.ResourceFork", str(verified)],
        ])
        self.assertFalse(any("--sign" in command for command in commands))

    def test_invalid_signature_after_cleanup_is_rejected(self):
        with patch.object(updater, "run", side_effect=[
            updater.UpdateError(DETRITUS), SUCCESS, SUCCESS, SUCCESS,
            updater.UpdateError("sealed resource is missing or invalid"),
        ]):
            with self.assertRaisesRegex(updater.UpdateError, "sealed resource"):
                updater.verify_app_signature(Path("/fixture"), Path("/staging"))

    def test_cleanup_failure_is_not_ignored(self):
        with patch.object(updater, "run", side_effect=[
            updater.UpdateError(DETRITUS), SUCCESS,
            updater.UpdateError("permission denied"),
        ]):
            with self.assertRaisesRegex(updater.UpdateError, "permission denied"):
                updater.verify_app_signature(Path("/fixture"), Path("/staging"))


@unittest.skipUnless(sys.platform == "darwin", "requires macOS signature tools")
class NativeSignatureRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chrome-signature-test.")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "original" / updater.EXPECTED_APP
        contents = self.app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        self.binary = contents / "MacOS" / "fixture"
        shutil.copyfile("/usr/bin/true", self.binary)
        self.binary.chmod(0o755)
        self.resource = contents / "Resources" / "sealed.txt"
        self.resource.write_text("original signed resource")
        with (contents / "Info.plist").open("wb") as destination:
            plistlib.dump({
                "CFBundleIdentifier": "org.example.signature-fixture",
                "CFBundleExecutable": "fixture",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
            }, destination)
        # Ad-hoc signing is confined to this synthetic offline test fixture.
        updater.run(["/usr/bin/codesign", "--force", "--sign", "-", str(self.app)])
        updater.run([
            "/usr/bin/codesign", "--verify", "--deep", "--strict", str(self.app)
        ])

    def add_forbidden_metadata(self):
        updater.run([
            "/usr/bin/xattr", "-wx", "com.apple.FinderInfo",
            "00" * 8 + "04" + "00" * 23, str(self.binary),
        ])
        updater.run([
            "/usr/bin/xattr", "-w", "com.apple.ResourceFork", "fixture resource fork",
            str(self.binary),
        ])

    def cdhash(self, app):
        details = updater.run(["/usr/bin/codesign", "-dv", "--verbose=4", str(app)])
        return re.search(r"^CDHash=(.+)$", details.stderr, re.MULTILINE).group(1)

    def test_cleans_only_temporary_metadata_and_keeps_original_signature(self):
        original_hash = self.cdhash(self.app)
        original_bytes = self.binary.read_bytes()
        self.add_forbidden_metadata()
        updater.run([
            "/usr/bin/xattr", "-w", "org.example.keep", "preserved", str(self.binary)
        ])
        with self.assertRaisesRegex(updater.UpdateError, DETRITUS):
            updater.run([
                "/usr/bin/codesign", "--verify", "--deep", "--strict", str(self.app)
            ])
        verified = updater.verify_app_signature(self.app, self.root / "verification")
        copied_binary = verified / "Contents" / "MacOS" / "fixture"
        self.assertEqual(self.cdhash(verified), original_hash)
        self.assertEqual(copied_binary.read_bytes(), original_bytes)
        retained = updater.run([
            "/usr/bin/xattr", "-p", "org.example.keep", str(copied_binary)
        ])
        self.assertEqual(retained.stdout.strip(), "preserved")
        original_attrs = updater.run(["/usr/bin/xattr", str(self.binary)]).stdout
        self.assertIn("com.apple.FinderInfo", original_attrs)
        self.assertIn("com.apple.ResourceFork", original_attrs)

    def test_tampered_resources_still_fail_after_metadata_cleanup(self):
        self.add_forbidden_metadata()
        self.resource.write_text("tampered after signing")
        with self.assertRaises(updater.UpdateError):
            updater.verify_app_signature(self.app, self.root / "verification")


if __name__ == "__main__":
    unittest.main()
