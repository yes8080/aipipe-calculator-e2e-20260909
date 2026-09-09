"""Offline behavioral tests: no GitHub credentials or network calls are used."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
from string import Template
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
from aipipe import publish as publisher
SHA = "a" * 40
REPO = "example/product"
TEMPLATE = Template((ROOT / "templates/issue.md").read_text(encoding="utf-8"))


def example_plan():
    return json.loads((ROOT / "plans/batch.example.json").read_text(encoding="utf-8"))


class FakeGitHub(publisher.GitHub):
    """In-memory API with paginated reads and independently visible write results."""
    def __init__(self):
        super().__init__(REPO)
        self.data = {"labels": [], "milestones": [], "issues": []}
        self.calls = []
        self.hidden_issue_list_reads = 0
        self.uncertain_issue = False
        self.bad_milestone = False

    @property
    def writes(self):
        return [call for call in self.calls if call[1] != "GET"]

    def request(self, path, method="GET", payload=None):
        self.calls.append((path, method, copy.deepcopy(payload)))
        url = urlsplit(path)
        parts = url.path.split("/")
        resource = parts[0]
        if resource == "contents":
            return {"type": "file", "path": "/".join(parts[1:])}
        if method == "GET":
            if len(parts) > 1:
                key = "name" if resource == "labels" else "number"
                identifier = unquote(parts[1]) if key == "name" else int(parts[1])
                return copy.deepcopy(next(item for item in self.data[resource] if item[key] == identifier))
            query = parse_qs(url.query)
            page, size = int(query["page"][0]), int(query["per_page"][0])
            entries = self.data[resource]
            if resource == "issues" and self.hidden_issue_list_reads:
                self.hidden_issue_list_reads -= 1
                entries = []
            return copy.deepcopy(entries[(page - 1) * size:page * size])
        if method != "POST":
            raise AssertionError("publisher must never PATCH existing content")
        obj = copy.deepcopy(payload)
        if resource != "labels":
            obj["number"] = len(self.data[resource]) + 1
            obj["state"] = "open"
        if resource == "issues":
            obj["milestone"] = {"number": -1 if self.bad_milestone else payload["milestone"]}
            obj["labels"] = [{"name": name} for name in payload["labels"]]
        self.data[resource].append(obj)
        if resource == "issues" and self.uncertain_issue:
            raise publisher.UncertainWrite("connection lost after server accepted Issue")
        return copy.deepcopy(obj)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.plan = example_plan()
        self.api = FakeGitHub()

    def publish(self, plan=None):
        return publisher.publish(plan or self.plan, REPO, SHA, TEMPLATE, self.api,
                                 pause=lambda _: None, output=lambda _: None)

    def seed(self):
        self.publish()
        self.api.calls.clear()

    def test_offline_default_renders_unresolved_dependencies_without_calling_gh(self):
        with tempfile.TemporaryDirectory() as folder:
            plan_path = Path(folder) / "batch.json"
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            with patch.object(publisher.subprocess, "run", side_effect=AssertionError("must remain offline")):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = publisher.main(["--repo", REPO, "--plan", str(plan_path), "--design-ref", SHA])
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", output.getvalue())
        self.assertIn("B01-S001（发布后填入 Issue 编号）", output.getvalue())
        self.assertIn(f"/blob/{SHA}/docs/development.md", output.getvalue())
        self.assertIn("./mvnw -B verify", output.getvalue())

    def test_apply_creates_ordered_dependencies_and_never_releases_batch(self):
        numbers = self.publish()
        self.assertEqual(numbers, {"B01-S001": 1, "B01-S002": 2})
        self.assertIn("前置 Issue：#1", self.api.data["issues"][1]["body"])
        self.assertIn("aipipe:released=false", self.api.data["milestones"][0]["description"])
        self.assertFalse(any(call[1] == "PATCH" for call in self.api.calls))

    def test_exact_reimport_reuses_even_closed_issue_without_writes(self):
        self.seed()
        self.api.data["issues"][0]["state"] = "closed"
        self.api.data["issues"][1]["labels"] = [{"name": "aipipe:active"}]
        self.assertEqual(self.publish()["B01-S001"], 1)
        self.assertEqual(self.api.writes, [])

    def test_changed_later_issue_stops_before_any_write(self):
        self.seed()
        # A plan revision changes an existing Issue; no new label/milestone/Issue may be written.
        revised = copy.deepcopy(self.plan)
        revised["slices"][1]["acceptance"].append("新增要求")
        with self.assertRaisesRegex(publisher.PublishError, "differs"):
            self.publish(revised)
        self.assertEqual(self.api.writes, [])

    def test_apply_without_delivery_token_does_not_use_global_gh_login(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "batch.json"
            path.write_text(json.dumps(self.plan), encoding="utf-8")
            with patch.dict(publisher.os.environ, {}, clear=True), \
                    patch.object(publisher.subprocess, "run", side_effect=AssertionError("no gh fallback")), \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                code = publisher.main(["--repo", REPO, "--plan", str(path), "--design-ref", SHA, "--apply"])
        self.assertEqual(code, 2)
        self.assertIn("Delivery GH_TOKEN", error.getvalue())

    def test_changed_design_version_is_a_content_conflict(self):
        self.seed()
        with self.assertRaisesRegex(publisher.PublishError, "differs"):
            publisher.publish(self.plan, REPO, "b" * 40, TEMPLATE, self.api, pause=lambda _: None)
        self.assertEqual(self.api.writes, [])

    def test_existing_product_design_directory_is_preserved(self):
        self.plan["design_path"] = "design/architecture.md"
        self.publish()
        self.assertIn(f"/blob/{SHA}/design/architecture.md", self.api.data["issues"][0]["body"])
        self.assertTrue(any(call[0] == f"contents/design/architecture.md?ref={SHA}" for call in self.api.calls))

    def test_unsafe_design_paths_are_rejected_before_remote_reads(self):
        unsafe_paths = ["../architecture.md", "design/../../architecture.md", "/design/architecture.md",
                        ".git/config", "design/.GIT/config", "C:\\design\\architecture.md", "C:/design.md",
                        "design\\..\\architecture.md", ".", "design/architecture\x00.md"]
        for path in unsafe_paths:
            with self.subTest(path=path):
                plan = copy.deepcopy(self.plan)
                plan["design_path"] = path
                with self.assertRaisesRegex(publisher.PublishError, "safe repository-relative"):
                    self.publish(plan)
        self.assertEqual(self.api.calls, [])

    def test_partial_unreleased_batch_resumes_without_duplicate(self):
        self.seed()
        self.api.data["issues"].pop()
        self.publish()
        self.assertEqual(len(self.api.data["issues"]), 2)
        self.assertEqual([call[0] for call in self.api.writes], ["issues"])

    def test_released_batch_is_not_extended_or_reset(self):
        self.seed()
        self.api.data["issues"].pop()
        milestone = self.api.data["milestones"][0]
        milestone["description"] = milestone["description"].replace("released=false", "released=true")
        with self.assertRaisesRegex(publisher.PublishError, "released, started or closed"):
            self.publish()
        self.assertIn("released=true", milestone["description"])
        self.assertEqual(self.api.writes, [])

    def test_started_partial_batch_is_not_extended(self):
        self.seed()
        self.api.data["issues"].pop()
        self.api.data["issues"][0]["labels"].append({"name": "aipipe:active"})
        with self.assertRaisesRegex(publisher.PublishError, "started"):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_duplicate_marker_in_remote_issue_is_rejected(self):
        self.seed()
        duplicate = copy.deepcopy(self.api.data["issues"][0])
        duplicate["number"] = 99
        self.api.data["issues"].append(duplicate)
        with self.assertRaisesRegex(publisher.PublishError, "duplicate slice marker"):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_title_collision_with_unmarked_milestone_is_not_adopted(self):
        self.api.data["milestones"] = [{"number": 7, "state": "open",
            "title": self.plan["milestone"]["title"], "description": "Human-owned milestone"}]
        with self.assertRaisesRegex(publisher.PublishError, "milestone differs"):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_reads_all_issue_pages_and_does_not_treat_pr_markers_as_issues(self):
        self.seed()
        actual = self.api.data["issues"]
        pr = copy.deepcopy(actual[0])
        pr.update({"number": 888, "pull_request": {"url": "https://example.invalid/pr/888"}})
        filler = [{"number": number + 1000, "body": "unrelated", "state": "open"} for number in range(100)]
        self.api.data["issues"] = filler + [pr] + actual
        self.publish()
        self.assertTrue(any("page=2" in call[0] for call in self.api.calls))
        self.assertEqual(self.api.writes, [])

    def test_creation_waits_for_list_visibility_using_reads_only(self):
        self.api.hidden_issue_list_reads = 3
        self.publish()
        self.assertEqual(len([call for call in self.api.writes if call[0] == "issues"]), 2)
        self.assertEqual(len(self.api.data["issues"]), 2)

    def test_ambiguous_create_stops_without_retry_or_next_slice(self):
        self.api.uncertain_issue = True
        with self.assertRaises(publisher.UncertainWrite):
            self.publish()
        self.assertEqual(len([call for call in self.api.writes if call[0] == "issues"]), 1)
        self.assertEqual(len(self.api.data["issues"]), 1)

    def test_write_confirmation_checks_milestone_before_next_slice(self):
        self.api.bad_milestone = True
        with self.assertRaisesRegex(publisher.UncertainWrite, "milestone differs"):
            self.publish()
        self.assertEqual(len(self.api.data["issues"]), 1)

    def test_validation_rejects_forward_dependencies_and_empty_test_commands(self):
        bad_dependency = copy.deepcopy(self.plan)
        bad_dependency["slices"][0]["depends_on"] = ["B01-S002"]
        no_commands = copy.deepcopy(self.plan)
        no_commands["slices"][0]["verification"] = []
        for plan in (bad_dependency, no_commands):
            with self.subTest(plan=plan):
                with self.assertRaises(publisher.PublishError):
                    self.publish(plan)
        self.assertEqual(self.api.calls, [])

    def test_transport_uses_no_cache_stdin_json_and_never_shell_execution(self):
        result = subprocess.CompletedProcess([], 0, stdout='{"number":1}', stderr="")
        with patch.object(publisher.subprocess, "run", return_value=result) as run:
            publisher.GitHub(REPO).request("issues", "POST", {"body": "literal $(not-a-command)"})
        args, options = run.call_args
        self.assertIn("Cache-Control: no-cache", args[0])
        self.assertIn("--input", args[0])
        self.assertEqual(json.loads(options["input"])["body"], "literal $(not-a-command)")
        self.assertNotIn("shell", options)

    def test_invalid_write_response_is_uncertain_not_retried(self):
        result = subprocess.CompletedProcess([], 0, stdout="not json", stderr="")
        with patch.object(publisher.subprocess, "run", return_value=result) as run:
            with self.assertRaises(publisher.UncertainWrite):
                publisher.GitHub(REPO).request("issues", "POST", {"title": "Example"})
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
