import copy
import http.client
import io
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from scripts import retry_chrome_ci as retry


REPOSITORY = "futuping/brew-nix-extra"
BASE = "/repos/futuping/brew-nix-extra"
RUN_ID = 43452045575
RUN_PATH = f"{BASE}/actions/runs/{RUN_ID}"


def run_fixture():
    return {
        "id": RUN_ID,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "path": ".github/workflows/update-google-chrome.yml",
        "head_branch": "main",
        "head_sha": "422e1d6dafb9ab169d3f9a230dfab7d6b923bfcc",
        "event": "schedule",
        "status": "completed",
        "conclusion": "failure",
        "run_attempt": 1,
    }


def job_fixture(capacity=False):
    steps = [
        {"name": "Set up job", "conclusion": "success"},
        {"name": "Run actions/checkout@v7", "conclusion": "success"},
        {
            "name": "Run cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24",
            "conclusion": "failure",
        },
        {"name": "Run updater tests", "conclusion": "skipped"},
        {"name": "Update the verified source pin", "conclusion": "skipped"},
        {"name": "Check updated source", "conclusion": "skipped"},
        {"name": "Commit an update or keep schedules active", "conclusion": "skipped"},
        {"name": "Post Run actions/checkout@v7", "conclusion": "success"},
        {"name": "Complete job", "conclusion": "success"},
    ]
    return {
        "id": 131976421050,
        "run_id": RUN_ID,
        "run_attempt": 1,
        "name": "update",
        "status": "completed",
        "conclusion": "cancelled" if capacity else "failure",
        "runner_id": 0 if capacity else 123,
        "check_run_url": "https://api.github.com/repos/futuping/brew-nix-extra/check-runs/12345",
        "steps": [] if capacity else steps,
    }


# Relevant lines from the Nov 13 installer failure, including the ANSI reset
# before cat's error. Earlier or later steps must not supply the match.
PROFILE_LOG = """2026-11-13T15:28:04.5808920Z ##[group]Run cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24
2026-11-13T15:28:04.5988360Z ##[start-action display=Run ${GITHUB_ACTION_PATH}/install-nix.sh;id=__cachix_install-nix-action.__run]
2026-11-13T15:28:04.6745240Z ##[group]Installing Nix
2026-11-13T15:28:24.6466620Z \x1b[0mcat: /etc/zshrc: Attribute not found
2026-11-13T15:28:24.9793510Z ##[error]Process completed with exit code 1.
2026-11-13T15:28:24.9810260Z ##[end-action id=__cachix_install-nix-action.__run;outcome=failure;conclusion=failure;duration_ms=20381]
2026-11-13T15:28:24.9965490Z Post job cleanup.
"""

CAPACITY_ANNOTATIONS = [
    {
        "annotation_level": "failure",
        "message": "The job was not acquired by Runner of type hosted even after multiple attempts",
    },
    {
        "annotation_level": "notice",
        "message": "Due to capacity constraints, jobs targeting macOS arm64 runners may experience longer queue times.",
    },
]


class RetryDecisionTests(unittest.TestCase):
    def make_client(self, *, capacity=False, run=None, job=None, refreshed=None):
        client = Mock()
        initial = run_fixture() if run is None else run
        selected_job = job_fixture(capacity) if job is None else job
        run_reads = 0

        def get_json(path):
            nonlocal run_reads
            if path == RUN_PATH:
                run_reads += 1
                if run_reads > 1 and refreshed is not None:
                    return copy.deepcopy(refreshed)
                return copy.deepcopy(initial)
            if path == RUN_PATH + "/attempts/1/jobs?per_page=100":
                return {"total_count": 1, "jobs": [copy.deepcopy(selected_job)]}
            if path == BASE + "/check-runs/12345/annotations?per_page=100":
                return copy.deepcopy(CAPACITY_ANNOTATIONS)
            self.fail(f"Unexpected API read: {path}")

        client.get_json.side_effect = get_json
        client.get_log.return_value = PROFILE_LOG
        return client

    def decide(self, client, *, attempt=1, apply=False):
        return retry.retry_run(client, REPOSITORY, RUN_ID, attempt, apply=apply)

    def test_profile_failure_is_read_only_by_default(self):
        client = self.make_client()
        result = self.decide(client)
        self.assertTrue(result["retry"])
        self.assertFalse(result["applied"])
        client.rerun_failed_jobs.assert_not_called()
        client.get_log.assert_called_once_with(
            BASE + "/actions/jobs/131976421050/logs"
        )

    def test_capacity_failure_requests_only_failed_job_rerun(self):
        client = self.make_client(capacity=True)
        result = self.decide(client, apply=True)
        self.assertTrue(result["applied"])
        client.rerun_failed_jobs.assert_called_once_with(RUN_PATH + "/rerun-failed-jobs")
        client.get_log.assert_not_called()

    def test_rejects_untrusted_workflow_sources(self):
        for field, value in (
            ("repository", {"full_name": "outsider/repository"}),
            ("head_repository", {"full_name": "outsider/repository"}),
            ("head_branch", "unreviewed"),
            ("path", ".github/workflows/other.yml"),
            ("event", "pull_request"),
            ("event", "push"),
            ("event", "workflow_run"),
            ("id", 1),
        ):
            with self.subTest(field=field, value=value):
                run = run_fixture()
                run[field] = value
                client = self.make_client(run=run)
                self.assertFalse(self.decide(client, apply=True)["retry"])
                client.get_log.assert_not_called()
                client.rerun_failed_jobs.assert_not_called()

    def test_accepts_manual_dispatch_and_cancelled_capacity_run(self):
        run = run_fixture()
        run.update(event="workflow_dispatch", conclusion="cancelled")
        self.assertTrue(self.decide(self.make_client(capacity=True, run=run))["retry"])

    def test_stops_after_three_total_attempts(self):
        run = run_fixture()
        run["run_attempt"] = 3
        client = self.make_client(run=run)
        self.assertFalse(self.decide(client, attempt=3, apply=True)["retry"])
        client.get_json.assert_called_once_with(RUN_PATH)
        client.rerun_failed_jobs.assert_not_called()

    def test_ignores_stale_event_and_active_or_successful_run(self):
        for changes in (
            {"run_attempt": 2},
            {"status": "in_progress", "conclusion": None},
            {"status": "queued", "conclusion": None},
            {"conclusion": "success"},
            {"conclusion": "timed_out"},
        ):
            with self.subTest(changes=changes):
                run = run_fixture()
                run.update(changes)
                self.assertFalse(self.decide(self.make_client(run=run))["retry"])

    def test_does_not_retry_business_failure_even_if_log_contains_profile_error(self):
        for index in range(3, 7):
            with self.subTest(step=index):
                job = job_fixture()
                job["steps"][2]["conclusion"] = "success"
                for step in job["steps"][3:index]:
                    step["conclusion"] = "success"
                job["steps"][index]["conclusion"] = "failure"
                client = self.make_client(job=job)
                self.assertFalse(self.decide(client, apply=True)["retry"])
                client.get_log.assert_not_called()
                client.rerun_failed_jobs.assert_not_called()

    def test_rejects_ran_missing_or_unknown_application_step(self):
        for mutation in ("ran", "missing", "unknown", "second_failure"):
            with self.subTest(mutation=mutation):
                job = job_fixture()
                if mutation == "ran":
                    job["steps"][3]["conclusion"] = "success"
                elif mutation == "missing":
                    job["steps"].pop(3)
                elif mutation == "unknown":
                    job["steps"].insert(3, {"name": "Unexpected work", "conclusion": "success"})
                else:
                    job["steps"][-2]["conclusion"] = "failure"
                self.assertFalse(self.decide(self.make_client(job=job))["retry"])

    def test_rejects_error_text_outside_installer_step_and_other_install_errors(self):
        clean_log = PROFILE_LOG.replace(retry.PROFILE_ERROR, "unrelated installer failure")
        for log in (
            clean_log,
            "2026-11-13T15:28:00Z " + retry.PROFILE_ERROR + "\n" + clean_log,
            clean_log + "2026-11-13T15:28:26Z " + retry.PROFILE_ERROR + "\n",
            retry.PROFILE_ERROR,
            PROFILE_LOG.replace("outcome=failure", "outcome=success"),
        ):
            with self.subTest(log=log):
                client = self.make_client()
                client.get_log.return_value = log
                self.assertFalse(self.decide(client)["retry"])

    def test_capacity_requires_both_annotations_and_unallocated_runner(self):
        for annotations in ([], CAPACITY_ANNOTATIONS[:1], CAPACITY_ANNOTATIONS[1:]):
            client = self.make_client(capacity=True)
            original = client.get_json.side_effect
            client.get_json.side_effect = lambda path: (
                annotations if "/annotations?" in path else original(path)
            )
            self.assertFalse(self.decide(client)["retry"])
        job = job_fixture(capacity=True)
        job["runner_id"] = 123
        self.assertFalse(self.decide(self.make_client(job=job))["retry"])

    def test_capacity_rejects_cross_repository_annotation_url(self):
        job = job_fixture(capacity=True)
        job["check_run_url"] = "https://api.github.com/repos/outsider/repo/check-runs/1"
        with self.assertRaises(retry.RetryError):
            self.decide(self.make_client(job=job))

    def test_capacity_rejects_additional_unknown_failure(self):
        client = self.make_client(capacity=True)
        original = client.get_json.side_effect
        client.get_json.side_effect = lambda path: (
            CAPACITY_ANNOTATIONS + [
                {"annotation_level": "failure", "message": "Repository policy rejected this job"}
            ]
            if "/annotations?" in path else original(path)
        )
        self.assertFalse(self.decide(client, apply=True)["retry"])
        client.rerun_failed_jobs.assert_not_called()

    def test_rejects_multiple_jobs(self):
        client = self.make_client()
        original = client.get_json.side_effect
        client.get_json.side_effect = lambda path: (
            {"total_count": 2, "jobs": [job_fixture(), job_fixture()]}
            if "/jobs?" in path else original(path)
        )
        self.assertFalse(self.decide(client)["retry"])

    def test_rejects_job_from_another_attempt(self):
        job = job_fixture()
        job["run_attempt"] = 2
        client = self.make_client(job=job)
        self.assertFalse(self.decide(client, apply=True)["retry"])
        client.get_log.assert_not_called()
        client.rerun_failed_jobs.assert_not_called()

    def test_rechecks_run_immediately_before_post(self):
        for changes in (
            {"run_attempt": 2},
            {"status": "in_progress"},
            {"head_sha": "a" * 40},
            {"conclusion": "success"},
            {"head_branch": "other"},
        ):
            with self.subTest(changes=changes):
                refreshed = run_fixture()
                refreshed.update(changes)
                client = self.make_client(refreshed=refreshed)
                self.assertFalse(self.decide(client, apply=True)["applied"])
                client.rerun_failed_jobs.assert_not_called()

    def test_invalid_arguments_never_make_requests(self):
        for repository, run_id, attempt in (
            ("owner/repo/../../bad", RUN_ID, 1),
            ("owner/repo?query=x", RUN_ID, 1),
            (REPOSITORY, 0, 1),
            (REPOSITORY, RUN_ID, 0),
        ):
            client = Mock()
            with self.assertRaises(retry.RetryError):
                retry.retry_run(client, repository, run_id, attempt)
            client.get_json.assert_not_called()


class TransportTests(unittest.TestCase):
    def redirect(self, url, *, external=True, method="GET"):
        request = urllib.request.Request(
            "https://api.github.com/repos/owner/repo/actions/jobs/1/logs",
            headers={"Authorization": "Bearer secret"},
            method=method,
        )
        return retry.SafeRedirect(external).redirect_request(
            request, None, 302, "Found", {}, url
        )

    def test_signed_log_redirect_strips_repository_authorization(self):
        request = self.redirect("https://logs.example.test/file?signature=signed-secret")
        self.assertIsNone(request.get_header("Authorization"))
        again = retry.SafeRedirect(True).redirect_request(
            request, None, 302, "Found", {}, "https://other.example.test/file"
        )
        self.assertIsNone(again.get_header("Authorization"))

    def test_same_api_origin_retains_authorization(self):
        request = self.redirect("https://api.github.com/next", external=False)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_rejects_non_https_and_unexpected_api_redirects(self):
        for url, external, method in (
            ("http://logs.example.test/file", True, "GET"),
            ("file:///tmp/logs", True, "GET"),
            ("https://user:password@logs.example.test/file", True, "GET"),
            ("https://logs.example.test:444/file", True, "GET"),
            ("https://logs.example.test/file", False, "GET"),
            ("https://api.github.com/next", False, "POST"),
        ):
            with self.subTest(url=url, method=method):
                with self.assertRaises(retry.RetryError):
                    self.redirect(url, external=external, method=method)

    def test_malformed_redirect_errors_do_not_contain_signed_url(self):
        for url in (
            "https://logs.example.test:invalid/file?signature=secret",
            "https://[invalid/file?signature=secret",
            "https://logs.example.test/file?signature=secret\nheader",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(
                    retry.RetryError, r"^Refusing an invalid GitHub HTTP redirect$"
                ):
                    self.redirect(url)

    @patch("scripts.retry_chrome_ci.urllib.request.build_opener")
    def test_transport_exception_details_are_not_exposed(self, build):
        for error in (
            http.client.InvalidURL("signed-log-url?signature=secret"),
            urllib.error.URLError("signed-log-url?signature=secret"),
            ValueError("signed-log-url?signature=secret"),
        ):
            with self.subTest(error=type(error).__name__):
                build.return_value.open.side_effect = error
                with self.assertRaises(retry.RetryError) as caught:
                    retry.GitHubClient("token").get_log(BASE + "/actions/jobs/1/logs")
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("signed-log-url", str(caught.exception))

    @patch("scripts.retry_chrome_ci.urllib.request.build_opener")
    def test_http_errors_never_print_signed_url_and_post_is_not_retried(self, build):
        error = urllib.error.HTTPError(
            "https://logs.example.test/file?signature=secret", 503, "secret", {}, io.BytesIO()
        )
        build.return_value.open.side_effect = error
        with self.assertRaisesRegex(retry.RetryError, r"^GitHub request failed \(HTTP 503\)$"):
            retry.GitHubClient("token").rerun_failed_jobs(RUN_PATH + "/rerun-failed-jobs")
        build.return_value.open.assert_called_once()
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 30)

    @patch("scripts.retry_chrome_ci.urllib.request.build_opener")
    def test_response_size_is_bounded(self, build):
        response = build.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"x" * 17
        with patch.object(retry, "MAX_LOG_BYTES", 16):
            with self.assertRaisesRegex(retry.RetryError, "size limit"):
                retry.GitHubClient("token").get_log(BASE + "/actions/jobs/1/logs")
        response.read.assert_called_once_with(17)

    def test_malformed_json_is_an_error(self):
        client = retry.GitHubClient("token")
        with patch.object(client, "request", return_value=b"not JSON"):
            with self.assertRaisesRegex(retry.RetryError, "invalid JSON"):
                client.get_json(RUN_PATH)


if __name__ == "__main__":
    unittest.main()
