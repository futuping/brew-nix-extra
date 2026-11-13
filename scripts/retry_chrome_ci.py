#!/usr/bin/env python3
"""Retry only reviewed GitHub runner failures, with three total attempts."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://api.github.com"
WORKFLOW_PATH = ".github/workflows/update-google-chrome.yml"
INSTALL_STEP = (
    "Run cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24"
)
APPLICATION_STEPS = (
    "Run updater tests",
    "Update the verified source pin",
    "Check updated source",
    "Commit an update or keep schedules active",
)
CAPACITY_FAILURE = (
    "The job was not acquired by Runner of type hosted even after multiple attempts"
)
CAPACITY_NOTICE = (
    "Due to capacity constraints, jobs targeting macOS arm64 runners may "
    "experience longer queue times."
)
PROFILE_ERROR = "cat: /etc/zshrc: Attribute not found"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 30
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class RetryError(RuntimeError):
    """A request or response could not be verified safely."""


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_external: bool = False):
        self.allow_external = allow_external

    def redirect_request(self, request, response, code, message, headers, new_url):
        original = urllib.parse.urlsplit(request.full_url)
        if any(ord(character) < 32 or ord(character) == 127 for character in new_url):
            raise RetryError("Refusing an invalid GitHub HTTP redirect")
        try:
            target = urllib.parse.urlsplit(new_url)
            target_port = target.port
        except ValueError:
            raise RetryError("Refusing an invalid GitHub HTTP redirect") from None
        if (
            request.get_method() != "GET"
            or target.scheme != "https"
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target_port not in (None, 443)
            or (not self.allow_external and target.netloc != original.netloc)
        ):
            raise RetryError("Refusing an unexpected GitHub HTTP redirect")
        redirected = super().redirect_request(
            request, response, code, message, headers, new_url
        )
        if redirected is not None and target.netloc != original.netloc:
            # GitHub job logs redirect to signed storage URLs. Never forward the
            # repository token to that host, including on subsequent redirects.
            redirected.remove_header("Authorization")
        return redirected


class GitHubClient:
    def __init__(self, token: str):
        if not token or "\n" in token or "\r" in token:
            raise RetryError("GITHUB_TOKEN is required")
        self.token = token

    def request(self, path: str, *, log: bool = False, post: bool = False) -> bytes:
        if not path.startswith("/repos/") or ".." in path or "#" in path:
            raise RetryError("Refusing an unexpected GitHub API path")
        request = urllib.request.Request(
            API_URL + path,
            data=b"{}" if post else None,
            method="POST" if post else "GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "brew-nix-extra-ci-retry",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        opener = urllib.request.build_opener(SafeRedirect(allow_external=log))
        limit = MAX_LOG_BYTES if log else MAX_JSON_BYTES
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                if response.status != (201 if post else 200):
                    raise RetryError("Unexpected GitHub response status")
                body = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            # HTTPError/URLError strings may contain signed log URLs. Do not
            # print those URLs, the response body, or authorization headers.
            error.close()
            raise RetryError(f"GitHub request failed (HTTP {error.code})") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
            raise RetryError(
                f"GitHub request failed ({type(error).__name__})"
            ) from None
        if len(body) > limit:
            raise RetryError("GitHub response exceeded the size limit")
        return body

    def get_json(self, path: str):
        try:
            return json.loads(self.request(path))
        except (ValueError, UnicodeError):
            raise RetryError("GitHub returned invalid JSON") from None

    def get_log(self, path: str) -> str:
        try:
            return self.request(path, log=True).decode("utf-8")
        except UnicodeError:
            raise RetryError("GitHub returned an invalid UTF-8 job log") from None

    def rerun_failed_jobs(self, path: str) -> None:
        # A POST is never retried: a lost response does not prove rejection.
        self.request(path, post=True)


def run_rejection(run: dict, repository: str, run_id: int, attempt: int) -> str:
    if not isinstance(run, dict):
        raise RetryError("GitHub returned an invalid workflow run")
    if (
        run.get("id") != run_id
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") != repository
        or not isinstance(run.get("head_repository"), dict)
        or run["head_repository"].get("full_name") != repository
        or run.get("path") != WORKFLOW_PATH
        or run.get("head_branch") != "main"
        or run.get("event") not in ("schedule", "workflow_dispatch")
    ):
        return "run source is outside the approved Chrome workflow"
    if run.get("run_attempt") != attempt:
        return "run attempt has changed"
    if attempt >= 3:
        return "three-attempt budget exhausted"
    if run.get("status") != "completed" or run.get("conclusion") not in (
        "failure",
        "cancelled",
    ):
        return "run is not a completed failure"
    return ""


def installer_failure_in_log(log: str) -> bool:
    log = ANSI_PATTERN.sub("", log)
    start = "##[group]" + INSTALL_STEP
    end = "##[end-action id=__cachix_install-nix-action.__run;outcome=failure;"
    if log.count(start) != 1:
        return False
    section = log.split(start, 1)[1]
    if end not in section:
        return False
    section = section.split(end, 1)[0]
    return any(line.endswith(" " + PROFILE_ERROR) for line in section.splitlines())


def classify_job(
    client: GitHubClient, repository: str, run_id: int, attempt: int, job: dict
) -> str:
    if not isinstance(job, dict):
        raise RetryError("GitHub returned an invalid workflow job")
    if (
        job.get("name") != "update"
        or job.get("run_id") != run_id
        or job.get("run_attempt") != attempt
        or job.get("status") != "completed"
        or job.get("conclusion") not in ("failure", "cancelled")
        or type(job.get("id")) is not int
    ):
        return ""
    steps = job.get("steps")
    base = f"/repos/{repository}"
    if steps == [] and job.get("runner_id") == 0:
        check_url = job.get("check_run_url", "")
        match = re.fullmatch(
            re.escape(API_URL + base + "/check-runs/") + r"([0-9]+)", check_url
        )
        if not match:
            raise RetryError("Job has no verified check-run URL")
        annotations = client.get_json(
            f"{base}/check-runs/{match[1]}/annotations?per_page=100"
        )
        if (
            not isinstance(annotations, list)
            or len(annotations) >= 100
            or any(not isinstance(a, dict) for a in annotations)
        ):
            raise RetryError("Incomplete or invalid check annotations")
        failures = [
            a.get("message") for a in annotations
            if a.get("annotation_level") == "failure"
        ]
        notices = [
            a.get("message") for a in annotations
            if a.get("annotation_level") == "notice"
        ]
        if (
            failures
            and all(message == CAPACITY_FAILURE for message in failures)
            and CAPACITY_NOTICE in notices
        ):
            return "macOS runner capacity"
        return ""
    if not isinstance(steps, list) or job.get("conclusion") != "failure":
        return ""
    if any(not isinstance(step, dict) for step in steps):
        raise RetryError("GitHub returned invalid job steps")
    failed = [step for step in steps if step.get("conclusion") == "failure"]
    if len(failed) != 1 or failed[0].get("name") != INSTALL_STEP:
        return ""
    installer_index = steps.index(failed[0])
    following = steps[installer_index + 1:]
    if any(step.get("conclusion") != "success" for step in steps[:installer_index]):
        return ""
    # Every business step must be present exactly once and skipped. Only the
    # runner's own cleanup steps may have executed after the installer failed.
    for name in APPLICATION_STEPS:
        matches = [step for step in following if step.get("name") == name]
        if len(matches) != 1 or matches[0].get("conclusion") != "skipped":
            return ""
    for step in following:
        if step.get("name") not in APPLICATION_STEPS and not (
            str(step.get("name", "")).startswith("Post ")
            or step.get("name") == "Complete job"
        ):
            return ""
        if step.get("conclusion") not in ("success", "skipped"):
            return ""
    log = client.get_log(f"{base}/actions/jobs/{job['id']}/logs")
    if installer_failure_in_log(log):
        return "Nix installer /etc/zshrc attribute failure"
    return ""


def retry_run(
    client: GitHubClient, repository: str, run_id: int, attempt: int, *, apply: bool = False
) -> dict:
    if not REPOSITORY_PATTERN.fullmatch(repository) or ".." in repository:
        raise RetryError("Invalid repository name")
    if run_id < 1 or attempt < 1:
        raise RetryError("Run ID and attempt must be positive integers")
    path = f"/repos/{repository}/actions/runs/{run_id}"
    run = client.get_json(path)
    rejection = run_rejection(run, repository, run_id, attempt)
    decision = {"run_id": run_id, "attempt": attempt, "retry": False, "applied": False}
    if rejection:
        return {**decision, "reason": rejection}
    jobs = client.get_json(f"{path}/attempts/{attempt}/jobs?per_page=100")
    if not isinstance(jobs, dict) or not isinstance(jobs.get("jobs"), list):
        raise RetryError("GitHub returned an invalid jobs response")
    if jobs.get("total_count") != 1 or len(jobs.get("jobs", [])) != 1:
        return {**decision, "reason": "expected exactly one update job"}
    reason = classify_job(client, repository, run_id, attempt, jobs["jobs"][0])
    if not reason:
        return {**decision, "reason": "failure is outside the infrastructure allowlist"}
    if apply:
        current = client.get_json(path)
        rejection = run_rejection(current, repository, run_id, attempt)
        if rejection or any(
            current.get(key) != run.get(key)
            for key in ("head_sha", "status", "conclusion", "run_attempt")
        ):
            return {**decision, "reason": "run changed before retry; no request sent"}
        client.rerun_failed_jobs(f"{path}/rerun-failed-jobs")
    return {**decision, "retry": True, "applied": apply, "reason": reason}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = retry_run(
            GitHubClient(os.environ.get("GITHUB_TOKEN", "")),
            args.repository,
            args.run_id,
            args.attempt,
            apply=args.apply,
        )
    except RetryError as error:
        print(f"CI retry failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
