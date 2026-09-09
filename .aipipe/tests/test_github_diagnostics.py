import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aipipe.github import Gh, GhError, diagnostic_endpoint
from aipipe.runner import clean_error


class GitHubDiagnosticsTests(unittest.TestCase):
    def test_user_values_matching_route_words_are_still_redacted(self):
        for path, expected in (
            ('repos/private/project/contents/actions/workflows/user', '/repos/{value}/{value}/contents/{value}'),
            ('repos/private/project/labels/user', '/repos/{value}/{value}/labels/{value}'),
            ('repos/private/project/branches/actions/workflows', '/repos/{value}/{value}/branches/{value}'),
            ('repos/private/project/rules/branches/user', '/repos/{value}/{value}/rules/branches/{value}'),
            ('repos/private/project/git/refs/heads/actions/workflows', '/repos/{value}/{value}/git/refs/{value}'),
            ('repos/private/project/unknown/user?secret=actions', '/{value}'),
        ):
            with self.subTest(path=path):
                self.assertEqual(diagnostic_endpoint(path), expected)
    def failure(self, stderr='', status=1, error=None, method='GET'):
        result = subprocess.CompletedProcess([], status, 'private-response', stderr)
        with patch('aipipe.github.subprocess.run', side_effect=error, return_value=result) as run:
            with self.assertRaises(GhError) as caught:
                Gh(env={'GH_TOKEN':'private-token'}).request(
                    'repos/private-owner/private-repo/rules/branches/private-branch?token=private-query',
                    method, {'secret':'private-payload'} if method == 'PUT' else None)
        self.assertEqual(run.call_count, 1)
        exc = caught.exception
        visible = str(exc) + str(clean_error(exc, 'write'))
        for secret in ('private-response', 'private-token', 'private-owner', 'private-repo',
                       'private-branch', 'private-query', 'private-payload', 'private-stderr'):
            self.assertNotIn(secret, visible)
        self.assertIn('/repos/{value}/{value}/rules/branches/{value}', str(exc))
        self.assertEqual(exc.method, method)
        return exc

    def test_network_and_http_failures_have_safe_request_context(self):
        exc = self.failure('error connecting to api.github.com private-stderr')
        self.assertEqual(exc.reason, 'network')
        self.assertEqual(clean_error(exc, 'preflight')['reason'], 'network')
        exc = self.failure('gh: blocked private-stderr (HTTP 405)', method='PUT')
        self.assertEqual(exc.status, 405)
        self.assertEqual(exc.reason, 'http')

    def test_timeout_unavailable_and_unrecognized_errors_are_distinct(self):
        exc = self.failure(error=subprocess.TimeoutExpired(['secret-command'], 60,
                                                           output='private-response', stderr='private-stderr'),
                           method='PUT')
        self.assertEqual(exc.reason, 'timeout')
        exc = self.failure(error=FileNotFoundError('private-stderr'))
        self.assertEqual(exc.reason, 'unavailable')
        exc = self.failure('private-stderr')
        self.assertEqual(exc.reason, 'process')

    def test_invalid_json_keeps_safe_context_and_does_not_retry(self):
        exc = self.failure(status=0)
        self.assertEqual(exc.reason, 'invalid_response')


if __name__ == '__main__':
    unittest.main()
