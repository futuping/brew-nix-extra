import json
import tempfile
import unittest
from pathlib import Path

from scripts import update_google_chrome as updater


class SourceValidationTests(unittest.TestCase):
    def valid_source(self):
        return {
            "version": "151.0.7922.72",
            "url": updater.CHROME_URL,
            "hash": "sha256-yDcYj9H4chDcr+weFyVypet13SHNzYqFLHr7ZLfrJUo=",
            "etag": "67a5369-e441ac88",
            "lastModified": "Wed, 29 Jul 2026 20:51:52 GMT",
            "size": 275758234,
        }

    def test_loads_complete_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.json"
            path.write_text(json.dumps(self.valid_source()), encoding="utf-8")
            source = updater.load_source(path)
        self.assertEqual(source.version, "151.0.7922.72")

    def test_rejects_no_check_hash(self):
        data = self.valid_source()
        data["hash"] = "no_check"
        with self.assertRaises(updater.UpdateError):
            updater.validate_source_data(data)

    def test_rejects_unexpected_url(self):
        data = self.valid_source()
        data["url"] = "https://example.invalid/googlechrome.dmg"
        with self.assertRaises(updater.UpdateError):
            updater.validate_source_data(data)

    def test_normalizes_http_etag(self):
        self.assertEqual(updater.normalize_etag('W/"abc-123"'), "abc-123")


class OfficialMetadataTests(unittest.TestCase):
    def test_accepts_expected_homebrew_cask(self):
        data = {
            "token": "google-chrome",
            "version": "151.0.7922.72",
            "url": updater.CHROME_URL,
            "sha256": "no_check",
            "auto_updates": True,
            "artifacts": [{"app": ["Google Chrome.app"]}],
        }
        self.assertEqual(
            updater.validate_homebrew_cask(data),
            "151.0.7922.72",
        )

    def test_rejects_changed_homebrew_artifact(self):
        data = {
            "token": "google-chrome",
            "version": "151.0.7922.72",
            "url": updater.CHROME_URL,
            "sha256": "no_check",
            "auto_updates": True,
            "artifacts": [{"pkg": ["GoogleChrome.pkg"]}],
        }
        with self.assertRaises(updater.UpdateError):
            updater.validate_homebrew_cask(data)

    def test_accepts_one_fully_rolled_out_version(self):
        data = {"releases": [{"version": "151.0.7922.72"}]}
        self.assertEqual(
            updater.validate_version_history(data),
            "151.0.7922.72",
        )


class CandidateSelectionTests(unittest.TestCase):
    def source(self):
        return updater.Source(
            version="150.0.7871.129",
            url=updater.CHROME_URL,
            hash="sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            etag="old-etag",
            lastModified="Mon, 20 Jul 2026 00:00:00 GMT",
            size=270000000,
        )

    def remote(self):
        return updater.RemoteObject(
            etag="new-etag",
            last_modified="Wed, 29 Jul 2026 20:51:52 GMT",
            size=275758234,
        )

    def test_selects_verified_new_version(self):
        candidate = updater.select_candidate(
            self.source(),
            "151.0.7922.72",
            "151.0.7922.72",
            "151.0.7922.72",
            "sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
            self.remote(),
        )
        self.assertEqual(candidate.version, "151.0.7922.72")
        self.assertEqual(candidate.etag, "new-etag")

    def test_accepts_signed_same_version_repack(self):
        current = self.source()
        candidate = updater.select_candidate(
            current,
            current.version,
            current.version,
            current.version,
            "sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=",
            self.remote(),
        )
        self.assertEqual(candidate.version, current.version)
        self.assertNotEqual(candidate.hash, current.hash)

    def test_refuses_downgrade(self):
        with self.assertRaises(updater.UpdateError):
            updater.select_candidate(
                self.source(),
                "149.0.7000.1",
                "149.0.7000.1",
                "149.0.7000.1",
                "sha256-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
                self.remote(),
            )

    def test_rejects_unannounced_bundle_version(self):
        with self.assertRaises(updater.UpdateError):
            updater.select_candidate(
                self.source(),
                "151.0.7922.72",
                "151.0.7922.72",
                "152.0.8000.1",
                "sha256-EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE=",
                self.remote(),
            )


if __name__ == "__main__":
    unittest.main()
