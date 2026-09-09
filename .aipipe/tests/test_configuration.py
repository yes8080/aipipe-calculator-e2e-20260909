import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aipipe import config
from aipipe import owner_auth as token


class ConfigurationTests(unittest.TestCase):
    def update(self, original, *args):
        return config.update(original, config.parser().parse_args(args))

    def test_partial_configuration_preserves_existing_ci_and_custom_settings(self):
        original = {"repository": "owner/project", "default_branch": "develop", "ci": {"required_check": "build"}, "custom": {"module": "orders"}}
        result = self.update(original, "--role", "developer", "--app-id", "10", "--installation-id", "20")
        self.assertEqual(result["default_branch"], "develop")
        self.assertEqual(result["ci"], original["ci"])
        self.assertEqual(result["custom"], original["custom"])
        self.assertNotIn("apps", original)

    def test_rebinding_requires_intent_and_clears_old_installation(self):
        original = {"repository": "old/project", "apps": {"developer": {"app_id": 10, "installation_id": 20}}, "ci": {"required_check": "old"}}
        with self.assertRaises(ValueError):
            self.update(original, "--repo", "new/project")
        result = self.update(original, "--repo", "new/project", "--rebind", "--default-branch", "develop")
        self.assertEqual(result["apps"]["developer"], {})
        self.assertIsNone(result["ci"]["required_check"])
        self.assertEqual(result["default_branch"], "develop")

    def test_single_check_flag_cannot_silently_override_multi_check_contract(self):
        data={'ci':{'required_checks':[{'context':'unit','integration_id':1}]}}
        with self.assertRaisesRegex(ValueError,'checks-file'):self.update(data,'--check-name','other')
        self.assertEqual(data['ci']['required_checks'][0]['context'],'unit')

    def test_cannot_alias_both_roles_to_same_app(self):
        with self.assertRaises(ValueError):
            self.update({"apps": {"developer": {"app_id": 10}}}, "--role", "delivery", "--app-id", "10")

    def test_changed_app_does_not_reuse_old_installation(self):
        result = self.update({"apps": {"developer": {"app_id": 10, "installation_id": 20, "slug": "old"}}}, "--role", "developer", "--app-id", "11")
        self.assertIsNone(result["apps"]["developer"]["installation_id"])
        self.assertIsNone(result["apps"]["developer"]["slug"])

    def test_invalid_values_leave_configuration_file_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "project.json"
            path.write_text('{"repository": "owner/repo"}\n')
            with self.assertRaises(ValueError):
                config.main(["--config", str(path), "--workflow-path", "../../secret.yml"])
            self.assertEqual(path.read_text(), '{"repository": "owner/repo"}\n')


    def test_string_command_reports_field_without_echoing_value_or_reading_credentials(self):
        from aipipe import cli
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'.aipipe/project.json'; path.parent.mkdir()
            path.write_text(json.dumps({'schema_version':1,'commands':{'test':'SECRET_DO_NOT_ECHO'}}))
            for args in (['inspect'],['doctor','--for','develop'],['github','--role','developer','--','issue','view','1'],['push','--role','developer','aipipe/issue-1']):
                with self.subTest(args=args), patch('aipipe.runner.credential',side_effect=AssertionError('credential read')), patch('aipipe.readiness.authenticated_env',side_effect=AssertionError('credential read')), patch('subprocess.run',side_effect=AssertionError('subprocess')), patch('sys.stderr',new_callable=io.StringIO) as err:
                    self.assertEqual(cli.main(['--project',str(root),*args]),2)
                    self.assertIn(str(path),err.getvalue())
                    self.assertIn('commands["test"]',err.getvalue())
                    self.assertIn('cwd and argv',err.getvalue())
                    self.assertIn('not an App credential error',err.getvalue())
                    self.assertNotIn('SECRET_DO_NOT_ECHO',err.getvalue())

    def test_invalid_command_fields_report_path_and_setter_preserves_original(self):
        cases=[('test:e2e',{'argv':['npm','run','test:e2e']},'command name'),('test',{'argv':'npm test'},'.argv'),('test',{'argv':['npm'],'cwd':False},'.cwd'),('test',{'argv':['npm'],'cwd':'../outside'},'.cwd')]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'.aipipe/project.json'; path.parent.mkdir()
            original={'schema_version':1,'commands':{'build':{'argv':['npm','run','build']}}}
            config.save(path,original); saved=path.read_bytes()
            source=root/'commands.json'
            for name,command,message in cases:
                with self.subTest(name=name,command=command):
                    source.write_text(json.dumps({name:command}))
                    with self.assertRaisesRegex(ValueError,message):
                        config.main(['--project',str(root),'--commands-file',str(source)])
                    self.assertEqual(path.read_bytes(),saved)
                    with self.assertRaisesRegex(ValueError,message):
                        config.validate({'schema_version':1,'commands':{name:command}})

    def test_metadata_mode_is_explicit_and_preserves_default_inline(self):
        result = self.update({'schema_version':1}, '--metadata-mode', 'workflow')
        self.assertEqual(result['metadata']['mode'], 'workflow')
        self.assertEqual(config.validate({'schema_version':1})['schema_version'], 1)
        with self.assertRaisesRegex(ValueError, 'metadata.mode'):
            config.validate({'schema_version':1, 'metadata':{'mode':'other'}})
        with self.assertRaisesRegex(ValueError, 'metadata must be an object'):
            config.validate({'schema_version':1, 'metadata':'workflow'})

    def test_native_script_colon_is_allowed_in_argv_and_shell_syntax_stays_literal(self):
        from aipipe import cli, runner
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'.aipipe/project.json'
            config.save(path,{'schema_version':1,'commands':{'e2e':{'cwd':'.','argv':['npm','run','test:e2e','$(touch sentinel)']}}})
            with patch('aipipe.runner.subprocess.run') as run:
                run.return_value.returncode=0
                self.assertEqual(runner.execute(cli.parser().parse_args(['--project',str(root),'run','e2e']),run=run),0)
                self.assertEqual(run.call_args.args[0],['npm','run','test:e2e','$(touch sentinel)'])
                self.assertFalse(run.call_args.kwargs.get('shell',False))
            self.assertFalse((root/'sentinel').exists())


class TokenTests(unittest.TestCase):
    def test_checkout_paths_and_resolved_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            root.mkdir()
            link = Path(folder) / "external-link"
            link.symlink_to(root)
            for path in (root / "secret.pem", link / "token"):
                with self.assertRaises(ValueError):
                    token.external(path, root)

    def test_output_is_private_and_contains_only_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "owner" / "token"
            token.write_token(path, "FAKE_TEST_TOKEN")
            self.assertEqual(path.read_text(), "FAKE_TEST_TOKEN\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_jwt_is_verifiable_and_expires_under_ten_minutes(self):
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / "test.pem"
            public = Path(folder) / "public.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)], check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, capture_output=True)
            head, body, signature = token.jwt(10, private, now=1000).split(".")
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            self.assertEqual(claims, {"iat": 940, "exp": 1540, "iss": "10"})
            sigfile = Path(folder) / "signature"
            sigfile.write_bytes(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
            verified = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public), "-signature", str(sigfile)], input=f"{head}.{body}".encode(), capture_output=True)
            self.assertEqual(verified.returncode, 0)

    def test_request_is_repository_and_role_scoped(self):
        seen = []
        class Transport:
            def request(self, path, method, body):
                seen.append((path, method, body))
                return {"token": "FAKE_TEST_TOKEN", "expires_at": "2099-01-01T00:00:00Z"}
        args = argparse.Namespace(repository="sample", role="developer", installation_id=3, app_id=4, private_key=Path("unused"))
        result = token.request_token(args, Transport())
        self.assertEqual(seen[0][:2], ("app/installations/3/access_tokens", "POST"))
        data = seen[0][2]
        self.assertEqual(data["repositories"], ["sample"])
        self.assertEqual(data["permissions"]["issues"], "read")
        self.assertNotIn("workflows", data["permissions"])
        self.assertEqual(result["token"], "FAKE_TEST_TOKEN")


if __name__ == "__main__":
    unittest.main()
