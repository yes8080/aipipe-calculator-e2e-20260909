import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aipipe import runner
from aipipe import config as generator


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "traditional-java-project"
        (self.root / ".aipipe").mkdir(parents=True)
        self.path = self.root / ".aipipe/project.json"
        self.registry = self.base / "credentials.json"
        self.config = {"schema_version": 1, "repository": "acme/orders", "default_branch": "develop",
                       "apps": {"developer": {"credential_ref": "orders/developer"},
                                "delivery": {"credential_ref": "orders/delivery"}}, "commands": {}}
        self.path.write_text(json.dumps(self.config))
        self.registry.write_text(json.dumps({"credentials": {
            "orders/developer": {"kind": "env", "name": "AIPIPE_DEV"},
            "orders/delivery": {"kind": "env", "name": "AIPIPE_REVIEW"}}}))
        self.env = {"PATH": os.environ.get("PATH", ""), "AIPIPE_DEV": "fake-developer-token",
                    "AIPIPE_REVIEW": "fake-delivery-token", "GH_TOKEN": "personal-token"}
        self.calls = []

    def args(self, *args):
        return runner.parser().parse_args(["--config", str(self.path), "--credentials", str(self.registry), *args])

    def fake(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[:3] == ["git", "remote", "get-url"]:
            return subprocess.CompletedProcess(command, 0, "https://github.com/acme/orders.git\n", "")
        return subprocess.CompletedProcess(command, 0)

    def test_traditional_project_initialization_runs_existing_command_without_docs_or_apps(self):
        commandfile = self.base / "commands.json"
        commandfile.write_text(json.dumps({"native.verify": {"cwd": ".", "argv": [sys.executable, "-c", "from pathlib import Path; Path('verified').write_text('ok')"]}}))
        config = {"schema_version": 1, "default_branch": "develop", "commands": {}}
        args = generator.parser().parse_args(["--commands-file", str(commandfile)])
        self.path.write_text(json.dumps(generator.update(config, args)))
        self.assertEqual(runner.execute(self.args("run", "native.verify")), 0)
        self.assertEqual((self.root / "verified").read_text(), "ok")
        self.assertFalse((self.root / "docs").exists())

    def test_product_process_does_not_receive_github_or_declared_credentials(self):
        self.config["commands"] = {"test": {"cwd": ".", "argv": ["native-test"]}}
        self.config["execution"] = {"strip_env": ["CUSTOM_WRITE_SECRET"]}
        self.path.write_text(json.dumps(self.config))
        env = dict(self.env, GITHUB_TOKEN="legacy-token", CUSTOM_WRITE_SECRET="custom", DEBUG="business-debug")
        runner.execute(self.args("run", "test"), run=self.fake, env=env)
        child = self.calls[0][1]["env"]
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "AIPIPE_DEV", "AIPIPE_REVIEW", "CUSTOM_WRITE_SECRET"):
            self.assertNotIn(key, child)
        self.assertEqual(child["DEBUG"], "business-debug")

    def test_each_github_action_uses_only_its_requested_role(self):
        for role, expected in (("developer", "fake-developer-token"), ("delivery", "fake-delivery-token")):
            runner.execute(self.args("github", "--role", role, "--", "pr", "view", "31"), run=self.fake, env=self.env)
            command, params = self.calls[-1]
            self.assertEqual(command, ["gh", "pr", "view", "31", "--repo", "acme/orders"])
            self.assertEqual(params["env"]["GH_TOKEN"], expected)
            self.assertNotIn("AIPIPE_DEV", params["env"])
            self.assertNotIn("AIPIPE_REVIEW", params["env"])

    def test_missing_role_does_not_fall_back_to_personal_login(self):
        self.registry.write_text('{"credentials": {}}')
        with self.assertRaises(ValueError):
            runner.execute(self.args("github", "--role", "developer", "--", "issue", "view", "1"), run=self.fake, env=self.env)
        self.assertEqual(len(self.calls), 1)  # only read the remote

    def test_wrong_checkout_stops_before_loading_credentials_or_gh(self):
        self.registry.unlink()
        def different(command, **kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, 0, "https://github.com/acme/other.git\n", "")
        with self.assertRaisesRegex(ValueError, "origin"):
            runner.execute(self.args("github", "--role", "delivery", "--", "pr", "merge", "1"), run=different, env=self.env)
        self.assertEqual(len(self.calls), 1)

    def test_preview_needs_no_registry_or_git_remote(self):
        self.registry.unlink()
        plan = self.base / "existing-plan.json"
        plan.write_text((Path(__file__).resolve().parents[1] / "plans/batch.example.json").read_text())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = runner.execute(self.args("publish", "--plan", str(plan), "--design-ref", "1" * 40), run=self.fake, env=self.env)
        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("DRY RUN", output.getvalue())
        self.assertIn("Repository: acme/orders", output.getvalue())

    def test_failed_write_is_propagated_once(self):
        def fail(command, **kwargs):
            result = self.fake(command, **kwargs)
            return result if command[0] == "git" else subprocess.CompletedProcess(command, 7)
        result = runner.execute(self.args("api", "--role", "delivery", "milestones", "--method", "POST", "--input", "body.json"), run=fail, env=self.env)
        self.assertEqual(result, 7)
        self.assertEqual(sum(x[0][0] == "gh" for x in self.calls), 1)

    def test_expired_token_stops_before_github_action(self):
        registry = json.loads(self.registry.read_text())
        registry["credentials"]["orders/developer"]["expires_at"] = "2000-01-01T00:00:00Z"
        self.registry.write_text(json.dumps(registry))
        with self.assertRaisesRegex(ValueError, "expired"):
            runner.execute(self.args("github", "--role", "developer", "--", "pr", "view", "1"), run=self.fake, env=self.env)
        self.assertEqual(len(self.calls), 1)

    def test_outside_token_file_is_read_without_output(self):
        tokenfile = self.base / "developer.token"
        tokenfile.write_text("fake-file-token\n")
        tokenfile.chmod(0o600)
        self.registry.write_text(json.dumps({"credentials": {"orders/developer": {"kind": "token_file", "path": str(tokenfile)}}}))
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            runner.execute(self.args("github", "--role", "developer", "--", "issue", "view", "1"), run=self.fake, env={})
        self.assertEqual(capture.getvalue(), "")
        self.assertEqual(self.calls[-1][1]["env"]["GH_TOKEN"], "fake-file-token")

    def test_secret_file_inside_checkout_and_escape_command_are_rejected(self):
        with self.assertRaises(ValueError):
            runner.outside(self.path, self.root)
        with self.assertRaises(ValueError):
            runner.product_command({"commands": {"bad": {"cwd": "..", "argv": ["echo"]}}}, self.root, "bad")
        with self.assertRaises(ValueError):
            runner.gh_command("acme/orders", ["pr", "view", "1", "--repo", "other/repo"])

    def test_push_uses_temporary_app_helper_without_force(self):
        runner.execute(self.args("push", "--role", "developer", "feature/existing"), run=self.fake, env=self.env)
        command = self.calls[-1][0]
        self.assertIn("credential.helper=", command)
        self.assertEqual(command[-1], "HEAD:refs/heads/feature/existing")
        self.assertNotIn("--force", command)

    def test_remote_binding_accepts_git_urls_and_existing_branch(self):
        self.assertEqual(runner.remote_repository("git@github.com:acme/orders.git"), "acme/orders")
        self.assertEqual(runner.remote_repository("https://github.com/acme/orders.git"), "acme/orders")
        self.assertIsNone(runner.remote_repository("https://elsewhere.test/acme/orders"))

    def test_api_cannot_escape_repository_with_encoded_parent_paths(self):
        for path in ("../other/issues", "%2e%2e/other/issues", "%252e%252e/other/issues", "/repos/other/repo"):
            with self.assertRaises(ValueError):
                runner.api_command("acme/orders", path, "POST", None)
        self.assertIn("repos/acme/orders/issues?labels=aipipe%3Aready", runner.api_command("acme/orders", "issues?labels=aipipe%3Aready", "GET", None))


if __name__ == "__main__":
    unittest.main()
