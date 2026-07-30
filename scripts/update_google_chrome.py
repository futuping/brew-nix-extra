#!/usr/bin/env python3
"""Update the fixed Google Chrome source after verifying the official DMG."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PATH = ROOT / "sources" / "google-chrome.json"

CHROME_URL = (
    "https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg"
)
HOMEBREW_CASK_API = "https://formulae.brew.sh/api/cask/google-chrome.json"
VERSION_HISTORY_API = (
    "https://versionhistory.googleapis.com/v1/chrome/platforms/"
    "mac_arm64/channels/stable/versions/all/releases"
)

EXPECTED_APP = "Google Chrome.app"
EXPECTED_BUNDLE_ID = "com.google.Chrome"
EXPECTED_TEAM_ID = "EQHXZ8M8AV"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){3}$")
SRI_PATTERN = re.compile(r"^sha256-[A-Za-z0-9+/]{43}=$")
ETAG_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


class UpdateError(RuntimeError):
    """Raised when upstream state cannot be accepted safely."""


@dataclass(frozen=True)
class Source:
    version: str
    url: str
    hash: str
    etag: str
    lastModified: str
    size: int


@dataclass(frozen=True)
class RemoteObject:
    etag: str
    last_modified: str
    size: int


def version_key(version: str) -> tuple[int, int, int, int]:
    if not VERSION_PATTERN.fullmatch(version):
        raise UpdateError(f"invalid four-component Chrome version: {version!r}")
    return tuple(int(component) for component in version.split("."))  # type: ignore[return-value]


def validate_url(url: str) -> None:
    if url != CHROME_URL:
        raise UpdateError(f"unexpected Chrome download URL: {url}")


def normalize_etag(value: str | None) -> str:
    if not value:
        return ""
    etag = value.strip()
    if etag.startswith("W/"):
        etag = etag[2:].strip()
    if len(etag) >= 2 and etag[0] == etag[-1] == '"':
        etag = etag[1:-1]
    if etag and not ETAG_PATTERN.fullmatch(etag):
        raise UpdateError(f"unexpected ETag: {value!r}")
    return etag


def validate_source_data(data: Any) -> Source:
    if not isinstance(data, dict):
        raise UpdateError("source state must be a JSON object")

    expected_types = {
        "version": str,
        "url": str,
        "hash": str,
        "etag": str,
        "lastModified": str,
        "size": int,
    }
    for key, expected_type in expected_types.items():
        if not isinstance(data.get(key), expected_type):
            raise UpdateError(f"source field {key!r} has the wrong type")

    source = Source(
        version=data["version"],
        url=data["url"],
        hash=data["hash"],
        etag=data["etag"],
        lastModified=data["lastModified"],
        size=data["size"],
    )
    version_key(source.version)
    validate_url(source.url)
    if not SRI_PATTERN.fullmatch(source.hash):
        raise UpdateError("source hash must be a complete SHA-256 SRI value")
    if normalize_etag(source.etag) != source.etag:
        raise UpdateError("source ETag must be stored without quotes or weakness prefix")
    if not source.lastModified:
        raise UpdateError("source Last-Modified value must not be empty")
    if source.size <= 0 or source.size > MAX_DOWNLOAD_BYTES:
        raise UpdateError(f"source size is outside the accepted range: {source.size}")
    return source


def load_source(path: Path) -> Source:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UpdateError(f"unable to read source state {path}: {error}") from error
    return validate_source_data(data)


def request_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "futuping/brew-nix-extra Chrome updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise UpdateError(f"unexpected HTTP status for {url}: {response.status}")
            return json.load(response)
    except (OSError, json.JSONDecodeError) as error:
        raise UpdateError(f"unable to read JSON from {url}: {error}") from error


def validate_homebrew_cask(data: Any) -> str:
    if not isinstance(data, dict):
        raise UpdateError("Homebrew cask API response is not an object")
    if data.get("token") != "google-chrome":
        raise UpdateError("Homebrew cask token is not google-chrome")

    version = data.get("version")
    if not isinstance(version, str):
        raise UpdateError("Homebrew cask version is missing")
    version_key(version)

    validate_url(data.get("url"))
    if data.get("sha256") != "no_check":
        raise UpdateError("Homebrew cask no longer uses the expected no_check hash")
    if data.get("auto_updates") is not True:
        raise UpdateError("Homebrew cask is no longer marked auto_updates")

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not any(
        isinstance(artifact, dict)
        and isinstance(artifact.get("app"), list)
        and artifact["app"]
        and artifact["app"][0] == EXPECTED_APP
        for artifact in artifacts
    ):
        raise UpdateError("Homebrew cask no longer installs Google Chrome.app")
    return version


def fetch_homebrew_version() -> str:
    return validate_homebrew_cask(request_json(HOMEBREW_CASK_API))


def validate_version_history(data: Any) -> str:
    if not isinstance(data, dict):
        raise UpdateError("Google Version History response is not an object")
    releases = data.get("releases")
    if not isinstance(releases, list) or len(releases) != 1:
        raise UpdateError("Google Version History did not return exactly one release")
    release = releases[0]
    if not isinstance(release, dict):
        raise UpdateError("Google Version History release is not an object")
    version = release.get("version")
    if not isinstance(version, str):
        raise UpdateError("Google Version History release has no version")
    version_key(version)
    return version


def fetch_google_version() -> str:
    query = urllib.parse.urlencode(
        {
            "filter": "fraction=1,endtime=none",
            "order_by": "version desc",
            "page_size": "1",
        }
    )
    return validate_version_history(request_json(f"{VERSION_HISTORY_API}?{query}"))


def validate_response_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "dl.google.com":
        raise UpdateError(f"download redirected to an unexpected host: {url}")


def fetch_remote_object() -> RemoteObject:
    request = urllib.request.Request(
        CHROME_URL,
        method="HEAD",
        headers={"User-Agent": "futuping/brew-nix-extra Chrome updater"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise UpdateError(
                    f"unexpected Chrome HEAD status: {response.status}"
                )
            validate_response_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type != "application/x-apple-diskimage":
                raise UpdateError(f"unexpected Chrome content type: {content_type}")

            raw_size = response.headers.get("Content-Length")
            if raw_size is None or not raw_size.isdigit():
                raise UpdateError("Chrome response has no valid Content-Length")
            size = int(raw_size)
            if size <= 0 or size > MAX_DOWNLOAD_BYTES:
                raise UpdateError(f"Chrome download size is unsafe: {size}")

            etag = normalize_etag(response.headers.get("ETag"))
            last_modified = response.headers.get("Last-Modified", "").strip()
            if not etag or not last_modified:
                raise UpdateError("Chrome response lacks ETag or Last-Modified")
            return RemoteObject(etag, last_modified, size)
    except OSError as error:
        raise UpdateError(f"unable to inspect Chrome download: {error}") from error


def download_dmg(path: Path, expected: RemoteObject) -> None:
    request = urllib.request.Request(
        CHROME_URL,
        headers={"User-Agent": "futuping/brew-nix-extra Chrome updater"},
    )
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise UpdateError(
                    f"unexpected Chrome download status: {response.status}"
                )
            validate_response_url(response.geturl())
            with path.open("wb") as destination:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("Chrome download exceeded the size limit")
                    destination.write(chunk)
    except OSError as error:
        raise UpdateError(f"unable to download Chrome DMG: {error}") from error

    if written != expected.size:
        raise UpdateError(
            f"Chrome download size changed: expected {expected.size}, got {written}"
        )


def sha256_sri(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return "sha256-" + base64.b64encode(digest.digest()).decode("ascii")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        details = ""
        if isinstance(error, subprocess.CalledProcessError):
            details = (error.stderr or error.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise UpdateError(f"command failed: {' '.join(command)}{suffix}") from error


def inspect_dmg(path: Path) -> str:
    if sys.platform != "darwin":
        raise UpdateError("Chrome DMG verification requires macOS")

    with tempfile.TemporaryDirectory(prefix="chrome-dmg.") as temporary:
        mountpoint = Path(temporary) / "mount"
        mountpoint.mkdir()
        attached = False
        try:
            run(
                [
                    "/usr/bin/hdiutil",
                    "attach",
                    "-readonly",
                    "-nobrowse",
                    "-noautoopen",
                    "-mountpoint",
                    str(mountpoint),
                    str(path),
                ]
            )
            attached = True

            app = mountpoint / EXPECTED_APP
            plist_path = app / "Contents" / "Info.plist"
            if not app.is_dir() or not plist_path.is_file():
                raise UpdateError(f"Chrome DMG does not contain {EXPECTED_APP}")

            run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
            signature = run(
                ["/usr/bin/codesign", "-dv", "--verbose=4", str(app)]
            )
            signature_details = signature.stderr + signature.stdout
            if f"Identifier={EXPECTED_BUNDLE_ID}" not in signature_details:
                raise UpdateError("Chrome signature has an unexpected identifier")
            if f"TeamIdentifier={EXPECTED_TEAM_ID}" not in signature_details:
                raise UpdateError("Chrome signature has an unexpected Team ID")
            if (
                f"Developer ID Application: Google LLC ({EXPECTED_TEAM_ID})"
                not in signature_details
            ):
                raise UpdateError("Chrome is not signed by the expected Google authority")

            with plist_path.open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            if plist.get("CFBundleIdentifier") != EXPECTED_BUNDLE_ID:
                raise UpdateError("Chrome Info.plist has an unexpected bundle ID")

            version = plist.get("CFBundleShortVersionString")
            if not isinstance(version, str):
                raise UpdateError("Chrome Info.plist has no short version")
            version_key(version)

            executable_name = plist.get("CFBundleExecutable")
            if not isinstance(executable_name, str) or not executable_name:
                raise UpdateError("Chrome Info.plist has no executable name")
            executable = app / "Contents" / "MacOS" / executable_name
            architectures = run(["/usr/bin/lipo", "-archs", str(executable)]).stdout.split()
            if "arm64" not in architectures:
                raise UpdateError("Chrome executable does not contain arm64")
            return version
        finally:
            if attached:
                run(["/usr/bin/hdiutil", "detach", "-force", str(mountpoint)])


def select_candidate(
    current: Source,
    homebrew_version: str,
    google_version: str,
    bundle_version: str,
    digest: str,
    remote: RemoteObject,
) -> Source:
    current_key = version_key(current.version)
    homebrew_key = version_key(homebrew_version)
    google_key = version_key(google_version)
    bundle_key = version_key(bundle_version)

    if bundle_key < current_key:
        raise UpdateError(
            f"refusing Chrome downgrade from {current.version} to {bundle_version}"
        )
    if bundle_key > max(homebrew_key, google_key):
        raise UpdateError(
            "Chrome DMG is newer than both Homebrew and Google Version History"
        )
    if bundle_version not in {
        current.version,
        homebrew_version,
        google_version,
    }:
        raise UpdateError(
            "Chrome DMG version does not match the current, Homebrew, or "
            "fully rolled-out Google version"
        )
    if not SRI_PATTERN.fullmatch(digest):
        raise UpdateError("computed Chrome hash is not a SHA-256 SRI value")

    return Source(
        version=bundle_version,
        url=CHROME_URL,
        hash=digest,
        etag=remote.etag,
        lastModified=remote.last_modified,
        size=remote.size,
    )


def write_source(path: Path, source: Source) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(asdict(source), temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def update_source(path: Path, check: bool, force: bool = False) -> bool:
    current = load_source(path)
    homebrew_version = fetch_homebrew_version()
    google_version = fetch_google_version()
    remote = fetch_remote_object()

    print(
        "Chrome versions: "
        f"pinned={current.version}, Homebrew={homebrew_version}, "
        f"Google fully rolled out={google_version}"
    )

    if (
        not force
        and current.etag == remote.etag
        and current.lastModified == remote.last_modified
        and current.size == remote.size
    ):
        if current.version == google_version:
            print(f"Google Chrome {current.version} is already current")
        else:
            print(
                f"Google announced {google_version}, but the Stable DMG has "
                "not changed; deferring"
            )
        return False

    with tempfile.TemporaryDirectory(prefix="chrome-update.") as temporary:
        dmg_path = Path(temporary) / "googlechrome.dmg"
        download_dmg(dmg_path, remote)
        digest = sha256_sri(dmg_path)
        bundle_version = inspect_dmg(dmg_path)

    candidate = select_candidate(
        current,
        homebrew_version,
        google_version,
        bundle_version,
        digest,
        remote,
    )
    if candidate == current:
        print(f"Google Chrome {current.version} source is already current")
        return False

    print(
        f"Verified Google Chrome {candidate.version}: "
        f"{candidate.hash} ({candidate.size} bytes)"
    )
    if check:
        print("source pin requires an update")
        return True

    write_source(path, candidate)
    print(f"Updated {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_PATH,
        help="source state JSON to inspect or update",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report an available source update without writing it",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="download and verify the DMG even when HTTP validators are unchanged",
    )
    arguments = parser.parse_args()

    try:
        changed = update_source(
            arguments.source.resolve(),
            arguments.check,
            arguments.force,
        )
    except UpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 1 if arguments.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
