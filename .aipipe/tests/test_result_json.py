import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aipipe import cli, config, reporting
from aipipe.github import GhError


SHA = 'a' * 40
MERGE_SHA = 'b' * 40


def actor(repo='owner/repo'):
    return {'schema_version':1, 'agent_id':str(uuid.uuid4()), 'repository':repo,
            'tool':'codex', 'model':'gpt-5.5', 'role':'reviewer',
            'credential_role':'delivery'}


class FakeClient:
    def __init__(self, write=None, readback=None):
        self.write = write or {}
        self.readback = readback or {'head':{'sha':SHA}, 'merged':True, 'merge_commit_sha':MERGE_SHA}
        self.calls = []

    def request(self, path, method='GET', payload=None):
        self.calls.append((path, method, payload))
        if method != 'GET':
            if isinstance(self.write, Exception):
                raise self.write
            return self.write
        if path.endswith('/commits?per_page=100&page=1'):
            return []
        if path.endswith('/pulls/6'):
            after_write = any(call[1] != 'GET' for call in self.calls)
            if isinstance(self.readback, Exception) and after_write:
                raise self.readback
            base = {'head':{'sha':SHA}, 'merged':True, 'merge_commit_sha':MERGE_SHA}
            return dict(self.readback if after_write and not isinstance(self.readback, Exception) else base,
                        number=6, body='Closes #1', commits=0)
        raise AssertionError(path)


class MetadataService:
    def __init__(self, client, repo, error=None):
        self.error = error

    def get(self, path):
        return {'body':'Closes #1'}

    def reconcile(self, *args, **kwargs):
        if self.error:
            raise self.error
        return []


class ResultJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aipipe result json ')
        self.root = Path(self.temp.name)
        config.save(self.root/'.aipipe/project.json',
                    {'schema_version':1, 'repository':'owner/repo',
                     'apps':{'delivery':{'credential_ref':'owner/repo/delivery'}}})
        self.identity = self.root/'.aipipe/.runtime/agents/reviewer.json'
        self.identity.parent.mkdir(parents=True, exist_ok=True)
        self.identity.write_text(json.dumps(actor()))
        self.registry = self.root.parent/'registry with spaces.json'
        self.registry.write_text(json.dumps({'credentials':{'owner/repo/delivery':{'kind':'env', 'name':'TOKEN'}}}))

    def tearDown(self):
        self.temp.cleanup()
        self.registry.unlink(missing_ok=True)

    def run_cli(self, fake, extra, metadata_error=None, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch('aipipe.runner.verify_remote', return_value='https://github.com/owner/repo.git'), \
             patch('aipipe.runner.Gh', return_value=fake), \
             patch('aipipe.metadata.Reconciler', side_effect=lambda client, repo: MetadataService(client, repo, metadata_error)), \
             patch('aipipe.metadata.linked_issue', return_value=1), \
             patch.dict(os.environ, {'TOKEN':'secret'}, clear=False), \
             redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['github', '--project', str(self.root), '--credentials', str(self.registry),
                             '--role', 'delivery', '--identity', str(self.identity),
                             '--result-json', '--', *extra])
        self.assertEqual(err.getvalue(), '')
        return code, json.loads(out.getvalue()), fake.calls

    def test_review_success_outputs_one_json_object(self):
        fake = FakeClient(write={'commit_id':SHA, 'id':123})
        code, result, calls = self.run_cli(fake, ['pr', 'review', '6', '--approve',
                                                 '--match-head-commit', SHA, '--body', 'Verified'])
        self.assertEqual(code, 0)
        self.assertEqual(result['operation'], 'review')
        self.assertEqual(result['primary'], {'status':'succeeded', 'head':SHA, 'review_id':123})
        self.assertEqual(result['metadata']['status'], 'succeeded')
        self.assertEqual(sum(method == 'POST' and path.endswith('/reviews') for path, method, _ in calls), 1)

    def test_workflow_metadata_mode_marks_pending_without_inline_sync(self):
        config.save(self.root/'.aipipe/project.json',
                    {'schema_version':1, 'repository':'owner/repo', 'metadata':{'mode':'workflow'},
                     'apps':{'delivery':{'credential_ref':'owner/repo/delivery'}}})
        fake = FakeClient(write={'commit_id':SHA, 'id':123})
        out, err = io.StringIO(), io.StringIO()
        with patch('aipipe.runner.verify_remote', return_value='https://github.com/owner/repo.git'), \
             patch('aipipe.runner.Gh', return_value=fake), \
             patch('aipipe.metadata.Reconciler', side_effect=AssertionError('inline metadata sync')), \
             patch.dict(os.environ, {'TOKEN':'secret'}, clear=False), \
             redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['github', '--project', str(self.root), '--credentials', str(self.registry),
                             '--role', 'delivery', '--identity', str(self.identity),
                             '--result-json', '--', 'pr', 'review', '6', '--approve',
                             '--match-head-commit', SHA, '--body', 'Verified'])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['primary']['status'], 'succeeded')
        self.assertEqual(result['metadata'], {'status':'pending'})
        self.assertEqual(result['recovery']['scope'], 'none')

    def test_merge_metadata_failure_preserves_primary_success_and_recovery_context(self):
        body = self.root/'.aipipe/.runtime/merge body.md'
        body.write_text('Merge summary\n')
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA})
        code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                 '--match-head-commit', SHA, '--body-file', str(body)],
                                          metadata_error=ValueError('private detail'))
        self.assertEqual(code, 0)
        self.assertEqual(result['primary'], {'status':'succeeded', 'head':SHA, 'merge_sha':MERGE_SHA})
        self.assertEqual(result['metadata']['status'], 'failed')
        self.assertEqual(result['metadata']['error'], {'category':'metadata_failed', 'phase':'metadata'})
        self.assertEqual(result['recovery']['scope'], 'metadata')
        argv = result['recovery']['argv']
        self.assertEqual(argv[0], 'aipipe')
        self.assertIn(str(self.root.resolve()), argv)
        self.assertIn(str(self.registry.resolve()), argv)
        self.assertIn(str(self.identity.resolve()), argv)
        self.assertNotIn('private detail', json.dumps(result))
        self.assertEqual(sum(method == 'PUT' and path.endswith('/merge') for path, method, _ in calls), 1)

    def test_unsupported_result_json_stops_before_credentials_and_writes(self):
        with patch('aipipe.runner.authenticated_env', side_effect=AssertionError('credential read')), \
             patch('aipipe.runner.verify_remote', side_effect=AssertionError('remote read')), \
             redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = cli.main(['github', '--project', str(self.root), '--credentials', str(self.registry),
                             '--role', 'delivery', '--identity', str(self.identity),
                             '--result-json', '--', 'pr', 'merge', '6', '--auto', '--squash',
                             '--match-head-commit', SHA])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['primary']['status'], 'failed')
        self.assertEqual(result['primary']['error']['phase'], 'preflight')

    def test_write_rejection_is_failed_but_readback_rejection_is_unknown(self):
        write_rejected = FakeClient(write=GhError('api', status=403))
        code, result, calls = self.run_cli(write_rejected, ['pr', 'merge', '6', '--squash',
                                                           '--match-head-commit', SHA])
        self.assertEqual(code, 1)
        self.assertEqual(result['primary']['status'], 'failed')
        self.assertEqual(result['primary']['error'], {'category':'github_rejected', 'phase':'write', 'status':403})
        self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

        readback_rejected = FakeClient(write={'merged':True, 'sha':MERGE_SHA},
                                       readback=GhError('api', status=403))
        code, result, calls = self.run_cli(readback_rejected, ['pr', 'merge', '6', '--squash',
                                                              '--match-head-commit', SHA])
        self.assertEqual(code, 2)
        self.assertEqual(result['primary']['status'], 'unknown')
        self.assertEqual(result['primary']['error'], {'category':'readback_unconfirmed', 'phase':'readback', 'status':403})
        self.assertEqual(result['recovery']['scope'], 'read_only')
        self.assertIn('number,state,mergedAt,mergeCommit,headRefOid', result['recovery']['argv'])
        self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_missing_or_bad_success_response_is_unknown(self):
        for payload in (None, 'ok', [], {'merged':True}, {'commit_id':'c'*40}):
            with self.subTest(payload=payload):
                fake = FakeClient(write=payload)
                code, result, calls = self.run_cli(fake, ['pr', 'review', '6', '--comment',
                                                         '--match-head-commit', SHA, '--body', 'Observed'])
                self.assertEqual(code, 2)
                self.assertEqual(result['primary']['status'], 'unknown')
                self.assertEqual(result['primary']['error']['category'], 'invalid_success_response')
                self.assertEqual(sum(method == 'POST' for _, method, _ in calls), 1)

    def test_structured_unknown_without_exception_is_collected_for_reporting(self):
        for fake, category in (
            (FakeClient(write={'merged':True}), 'invalid_success_response'),
            (FakeClient(write={'merged':True, 'sha':MERGE_SHA}, readback={'head':{'sha':'c'*40}}), 'readback_mismatch'),
        ):
            with self.subTest(category=category), patch('aipipe.reporting.report', return_value=None) as report:
                code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash', '--match-head-commit', SHA])
                self.assertEqual(code, 2)
                self.assertEqual(result['primary']['status'], 'unknown')
                self.assertIn(category, [event.get('category') for event in report.call_args.args[1]])
                self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)
        fake = FakeClient(write={'commit_id':SHA}, readback={'head':{'sha':'c'*40}})
        with patch('aipipe.reporting.report', return_value=None) as report:
            code, result, _ = self.run_cli(fake, ['pr', 'review', '6', '--approve', '--body', 'Verified', '--match-head-commit', SHA])
            self.assertEqual(code, 2)
            self.assertIn('head_changed', [event.get('category') for event in report.call_args.args[1]])

    def test_documented_merge_rejections_fail_without_retry_or_metadata(self):
        for status in (403, 404, 405, 409, 422):
            with self.subTest(status=status):
                fake = FakeClient(write=GhError('api', status=status))
                code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                         '--match-head-commit', SHA])
                self.assertEqual(code, 1)
                self.assertEqual(result['primary']['status'], 'failed')
                self.assertEqual(result['primary']['error'],
                                 {'category':'github_rejected', 'phase':'write', 'status':status})
                self.assertEqual(result['metadata']['status'], 'not_run')
                self.assertEqual(result['recovery']['scope'], 'none')
                self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)
                self.assertEqual(calls[-1][1], 'PUT')

    def test_ambiguous_writes_and_failed_readback_remain_unknown(self):
        for status in (None, 408, 429, 500, 502, 503):
            for operation, decision in (('merge', '--squash'), ('review', '--approve')):
                with self.subTest(status=status, operation=operation):
                    fake = FakeClient(write=GhError('api', code=1, status=status))
                    argv = ['pr', operation, '6', decision, '--match-head-commit', SHA]
                    if operation == 'review':
                        argv += ['--body', 'Verified']
                    code, result, calls = self.run_cli(fake, argv)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['primary']['status'], 'unknown')
                    self.assertEqual(result['recovery']['scope'], 'read_only')
                    self.assertEqual(sum(method != 'GET' for _, method, _ in calls), 1)
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA},
                          readback=GhError('api', status=405))
        code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                 '--match-head-commit', SHA])
        self.assertEqual(code, 2)
        self.assertEqual(result['primary']['error']['phase'], 'readback')
        self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_merge_response_with_non_string_sha_is_unknown_after_one_write(self):
        for sha in (None, 1, [], {}):
            with self.subTest(sha=repr(sha)):
                fake = FakeClient(write={'merged':True, 'sha':sha})
                code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                         '--match-head-commit', SHA])
                self.assertEqual(code, 2)
                self.assertEqual(result['primary']['status'], 'unknown')
                self.assertEqual(result['primary']['error'], {'category':'invalid_success_response', 'phase':'write'})
                self.assertEqual(result['recovery']['scope'], 'read_only')
                self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_unhandled_result_json_write_exception_is_single_sanitized_unknown_json(self):
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA})
        out, err = io.StringIO(), io.StringIO()
        with patch('aipipe.runner.verify_remote', return_value='https://github.com/owner/repo.git'), \
             patch('aipipe.runner.Gh', return_value=fake), \
             patch('aipipe.runner.submit_attributed_result_json', side_effect=TypeError('late write classification bug')), \
             patch.dict(os.environ, {'TOKEN':'secret'}, clear=False), \
             redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['github', '--project', str(self.root), '--credentials', str(self.registry),
                             '--role', 'delivery', '--identity', str(self.identity),
                             '--result-json', '--', 'pr', 'merge', '6', '--squash',
                             '--match-head-commit', SHA])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['primary']['status'], 'unknown')
        self.assertEqual(result['primary']['error'], {'category':'write_unconfirmed', 'phase':'write'})
        self.assertEqual(result['recovery']['scope'], 'read_only')
        self.assertNotIn('late write classification bug', out.getvalue())
        self.assertEqual(sum(method != 'GET' for _, method, _ in fake.calls), 0)

    def test_readback_attribute_error_is_unknown_json_after_one_write(self):
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA},
                          readback=AttributeError('private shape detail'))
        code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                 '--match-head-commit', SHA])
        self.assertEqual(code, 2)
        self.assertEqual(result['primary']['status'], 'unknown')
        self.assertEqual(result['primary']['error'], {'category':'readback_unconfirmed', 'phase':'readback'})
        self.assertEqual(result['recovery']['scope'], 'read_only')
        self.assertNotIn('private shape detail', json.dumps(result))
        self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_head_change_after_review_is_unknown(self):
        fake = FakeClient(write={'commit_id':SHA}, readback={'head':{'sha':'c'*40}})
        code, result, calls = self.run_cli(fake, ['pr', 'review', '6', '--comment',
                                                 '--match-head-commit', SHA, '--body', 'Observed'])
        self.assertEqual(code, 2)
        self.assertEqual(result['primary']['status'], 'unknown')
        self.assertEqual(result['primary']['error'], {'category':'head_changed', 'phase':'readback'})
        self.assertEqual(result['recovery']['scope'], 'read_only')
        self.assertEqual(sum(method == 'POST' for _, method, _ in calls), 1)

    def test_scalar_head_in_merge_readback_is_unknown_json(self):
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA}, readback={'head':'not an object',
                                                                           'merged':True,
                                                                           'merge_commit_sha':MERGE_SHA})
        code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                 '--match-head-commit', SHA])
        self.assertEqual(code, 2)
        self.assertEqual(result['primary']['status'], 'unknown')
        self.assertEqual(result['primary']['error'], {'category':'readback_mismatch', 'phase':'readback'})
        self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_merge_readback_requires_boolean_true_merged_flag(self):
        for merged in ('false', 'true', 1, 0, [], {}):
            with self.subTest(merged=repr(merged)):
                fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA},
                                  readback={'head':{'sha':SHA}, 'merged':merged,
                                            'merge_commit_sha':MERGE_SHA})
                code, result, calls = self.run_cli(fake, ['pr', 'merge', '6', '--squash',
                                                         '--match-head-commit', SHA])
                self.assertEqual(code, 2)
                self.assertEqual(result['primary']['status'], 'unknown')
                self.assertEqual(result['primary']['error'], {'category':'readback_mismatch', 'phase':'readback'})
                self.assertEqual(sum(method == 'PUT' for _, method, _ in calls), 1)

    def test_recovery_paths_are_absolute_when_called_with_relative_inputs(self):
        caller = self.root/'caller'
        caller.mkdir()
        relative_registry = os.path.relpath(self.registry, caller)
        relative_identity = os.path.relpath(self.identity, caller)
        fake = FakeClient(write={'merged':True, 'sha':MERGE_SHA},
                          readback=GhError('api', status=500))
        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        try:
            os.chdir(caller)
            with patch('aipipe.runner.verify_remote', return_value='https://github.com/owner/repo.git'), \
                 patch('aipipe.runner.Gh', return_value=fake), \
                 patch.dict(os.environ, {'TOKEN':'secret'}, clear=False), \
                 redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['github', '--project', str(self.root), '--credentials', relative_registry,
                                 '--role', 'delivery', '--identity', relative_identity,
                                 '--result-json', '--', 'pr', 'merge', '6', '--squash',
                                 '--match-head-commit', SHA])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        argv = result['recovery']['argv']
        self.assertIn(str(self.registry.resolve()), argv)
        self.assertIn(str(self.identity.resolve()), argv)
        self.assertNotIn(relative_registry, argv)
        self.assertNotIn(relative_identity, argv)

    def test_malformed_registry_attribute_error_is_failed_json_before_write(self):
        registry = self.root.parent/'malformed registry.json'
        registry.write_text('[]')
        out, err = io.StringIO(), io.StringIO()
        try:
            with patch('aipipe.runner.verify_remote', return_value='https://github.com/owner/repo.git'), \
                 patch('aipipe.runner.Gh', side_effect=AssertionError('no gh client after malformed credentials')), \
                 redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['github', '--project', str(self.root), '--credentials', str(registry),
                                 '--role', 'delivery', '--identity', str(self.identity),
                                 '--result-json', '--', 'pr', 'merge', '6', '--squash',
                                 '--match-head-commit', SHA])
        finally:
            registry.unlink(missing_ok=True)
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['operation'], 'merge')
        self.assertEqual(result['pr'], 6)
        self.assertEqual(result['primary']['status'], 'failed')
        self.assertEqual(result['primary']['error'], {'category':'validation', 'phase':'preflight'})
        self.assertEqual(result['metadata']['status'], 'not_run')
        self.assertNotIn('get', out.getvalue())

    def test_bad_startup_configuration_still_outputs_failed_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'.aipipe').mkdir()
            (root/'.aipipe/project.json').write_text(json.dumps({'schema_version':1}))
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['github', '--project', str(root), '--credentials', str(self.registry),
                                 '--role', 'delivery', '--identity', str(self.identity),
                                 '--result-json', '--', 'pr', 'merge', '6', '--squash',
                                 '--match-head-commit', SHA])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['operation'], 'merge')
        self.assertEqual(result['pr'], 6)
        self.assertEqual(result['primary']['status'], 'failed')
        self.assertEqual(result['primary']['error']['phase'], 'preflight')
        self.assertEqual(result['metadata']['status'], 'not_run')

    def test_missing_configuration_still_outputs_failed_json(self):
        with tempfile.TemporaryDirectory() as temp:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['github', '--project', temp, '--credentials', str(self.registry),
                                 '--role', 'delivery', '--identity', str(self.identity),
                                 '--result-json', '--', 'pr', 'review', '6', '--comment',
                                 '--match-head-commit', SHA, '--body', 'Observed'])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), '')
        result = json.loads(out.getvalue())
        self.assertEqual(result['operation'], 'review')
        self.assertEqual(result['pr'], 6)
        self.assertEqual(result['primary']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
