import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aipipe import cli, config
from aipipe.github import GhError

SHA = 'a' * 40
NEW_SHA = 'b' * 40
MAIN_SHA = 'c' * 40
MERGE_SHA = 'd' * 40


def issue(number=1, state='open', labels=('aipipe:ready',), milestone=True):
    return {'number':number, 'state':state, 'title':'Task',
            'labels':[{'name':x} for x in labels],
            'milestone':{'number':1} if milestone else None}


def pr(number=2, issue_number=1, state='open', draft=False, merged=False, head=SHA, body=None):
    return {'number':number, 'state':state, 'title':'PR', 'draft':draft, 'merged':merged,
            'merged_at':'2026-01-01T00:00:00Z' if merged else None,
            'merge_commit_sha':MERGE_SHA if merged else None,
            'body':body if body is not None else f'Closes #{issue_number}\n',
            'labels':[], 'milestone':None, 'head':{'sha':head}, 'base':{'ref':'main'}}


def check(name='ci', app_id=15368, status_value='completed', conclusion='success', sha=SHA):
    return {'id':99, 'name':name, 'status':status_value, 'conclusion':conclusion, 'sha':sha,
            'app':{'id':app_id}, 'check_suite':{'app':{'id':app_id}},
            'started_at':'2026-01-01T00:00:00Z', 'completed_at':'2026-01-01T00:01:00Z'}


def commit_status(context='ci', state='success'):
    return {'context':context, 'state':state, 'created_at':'2026-01-01T00:01:00Z'}


def rule(context='ci', app_id=15368, strict=False):
    return {'type':'required_status_checks', 'parameters':{
        'strict_required_status_checks_policy':strict,
        'required_status_checks':[{'context':context, 'integration_id':app_id}]}}


class FakeGh:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        fixture.setdefault('clients', []).append(self)

    def request(self, path, method='GET', payload=None):
        self.calls.append((path, method, payload))
        if method != 'GET':
            raise AssertionError('status must be read-only')
        if path == 'installation/repositories?per_page=100':
            if self.fixture.get('role_error'):
                raise GhError('api', status=self.fixture['role_error'])
            return {'total_count':1, 'repositories':[{'full_name':'owner/repo'}]}
        if self.fixture.get('remote_error') and path.startswith('repos/owner/repo/issues/'):
            raise GhError('api', status=503)
        if path == 'repos/owner/repo':
            return {'default_branch':'main'}
        if path == 'repos/owner/repo/branches/main':
            return {'commit':{'sha':MAIN_SHA}, 'protected':True}
        if path.startswith('repos/owner/repo/rules/branches/main'):
            if self.fixture.get('rules_error'):
                raise GhError('api', status=503)
            return self.fixture.get('rules', [rule()])
        if path.startswith('repos/owner/repo/issues/'):
            number = int(path.rsplit('/', 1)[1])
            return self.fixture.get('issues', {}).get(number, issue(number))
        if path.startswith('repos/owner/repo/pulls/') and '/reviews?' not in path:
            number = int(path.split('/')[4])
            values = self.fixture.get('pulls', {}).get(number, pr(number))
            if isinstance(values, list):
                index = min(self.fixture.setdefault('pull_reads', {}).get(number, 0), len(values)-1)
                self.fixture['pull_reads'][number] = index + 1
                return values[index]
            return values
        if path.startswith('repos/owner/repo/git/ref/heads/aipipe/issue-'):
            number = int(path.rsplit('-', 1)[1])
            if number in self.fixture.get('branches', set()):
                return {'ref':'refs/heads/aipipe/issue-'+str(number)}
            raise GhError('api', status=404)
        if path.startswith('repos/owner/repo/pulls/') and '/reviews?' in path:
            number = int(path.split('/')[4])
            return self.fixture.get('reviews', {}).get(number, [])
        if path.startswith('repos/owner/repo/commits/'):
            raise AssertionError('status should read commit statusCheckRollup through GraphQL')
        raise AssertionError(path)

    def command(self, args, payload=None):
        self.calls.append(('command:'+' '.join(args), 'GET', payload))
        query = (payload or {}).get('query', '')
        if 'viewer' in query:
            return json.dumps({'data':{'viewer':{'login':'dev-app[bot]'}}})
        if 'reviewDecision' in query or 'mergeStateStatus' in query:
            if self.fixture.get('native_error'):
                raise GhError('graphql', status=502)
            number = payload['variables']['number']
            native = self.fixture.get('native', {}).get(number, {'reviewDecision':'APPROVED', 'mergeStateStatus':'CLEAN'})
            return json.dumps({'data':{'repository':{'pullRequest':native}}})
        if 'statusCheckRollup' in query:
            sha = payload['variables']['expression']
            if self.fixture.get('rollup_error'):
                raise GhError('graphql', status=502)
            object_sha = self.fixture.get('rollup_oid', sha)
            nodes = []
            for run in self.fixture.get('checks', {}).get(sha, []):
                app = run.get('app') or {}
                nodes.append({'__typename':'CheckRun', 'databaseId':run.get('id'), 'name':run.get('name'),
                              'status':str(run.get('status') or '').upper(),
                              'conclusion':str(run.get('conclusion') or '').upper() if run.get('conclusion') is not None else None,
                              'startedAt':run.get('started_at'), 'completedAt':run.get('completed_at'),
                              'detailsUrl':run.get('details_url'),
                              'checkSuite':{'app':{'databaseId':app.get('id'), 'slug':app.get('slug')},
                                            'commit':{'oid':run.get('sha', object_sha)}}})
            for status_item in self.fixture.get('statuses', {}).get(sha, []):
                nodes.append({'__typename':'StatusContext', 'context':status_item.get('context'),
                              'state':str(status_item.get('state') or '').upper(),
                              'targetUrl':status_item.get('target_url')})
            return json.dumps({'data':{'repository':{'object':{'oid':object_sha, 'statusCheckRollup':{
                'state':'SUCCESS', 'contexts':{'totalCount':len(nodes),
                'pageInfo':{'hasNextPage':False, 'endCursor':None}, 'nodes':nodes}}}}}})
        if 'timelineItems' in query:
            number = payload['variables']['number']
            nodes = [{'source':{'number':n, 'repository':{'nameWithOwner':'owner/repo'}}}
                     for n in self.fixture.get('links', {}).get(number, [])]
            return json.dumps({'data':{'repository':{'issue':{'timelineItems':{
                'pageInfo':{'hasNextPage':False, 'endCursor':None}, 'nodes':nodes}}}}})
        raise AssertionError(args)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aipipe status ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config.save(self.root/'.aipipe/project.json', {'schema_version':1, 'repository':'owner/repo', 'default_branch':'main',
            'apps':{'developer':{'app_id':10, 'installation_id':20, 'slug':'dev-app', 'credential_ref':'dev'},
                    'delivery':{'app_id':11, 'installation_id':21, 'slug':'delivery-app', 'credential_ref':'delivery'}},
            'ci':{'required_check':'ci', 'integration_id':15368},
            'compatibility':{'minimum_cli_version':'0.5.0'}})
        (self.root/'.aipipe/compatibility.json').write_text(json.dumps({'minimum_cli_version':'0.5.0', 'resource_version':'0.5.0'}))
        self.registry = self.root.parent/'registry with spaces.json'
        self.registry.write_text(json.dumps({'credentials':{'dev':{'kind':'env','name':'TOKEN'}, 'delivery':{'kind':'env','name':'TOKEN'}}}))
        self.fixture = {'issues':{1:issue()}, 'pulls':{}, 'links':{}, 'reviews':{}, 'checks':{}, 'statuses':{}, 'branches':set()}

    def tearDown(self):
        self.registry.unlink(missing_ok=True)

    def run_status(self, args=None):
        args = args or ['--issue','1','--role','developer','--json']
        out, err = io.StringIO(), io.StringIO()
        with patch('aipipe.status.Gh', side_effect=lambda *a, **k: FakeGh(self.fixture)), \
             patch('aipipe.status.verify_remote', return_value='https://github.com/owner/repo.git'), \
             patch.dict(os.environ, {'TOKEN':'secret'}, clear=False), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(['status','--project',str(self.root),'--credentials',str(self.registry), *args])
        self.assertEqual(err.getvalue(), '')
        return code, json.loads(out.getvalue()), self.fixture.get('clients', [])

    def linked_ready(self, reviews=None, checks=None, statuses=None, pull=None, native=None):
        pull = pull or pr()
        first = pull[0] if isinstance(pull, list) else pull
        self.fixture['pulls'] = {first['number']:pull}
        self.fixture['links'] = {1:[first['number']]}
        self.fixture['reviews'] = {first['number']:reviews if reviews is not None else [{'id':1,'state':'APPROVED','user':{'login':'reviewer'},'commit_id':first['head']['sha']}]}
        self.fixture['checks'] = {first['head']['sha']:checks if checks is not None else [check(sha=first['head']['sha'])]}
        self.fixture['statuses'] = {first['head']['sha']:statuses if statuses is not None else []}
        self.fixture['native'] = {first['number']:native or {'reviewDecision':'APPROVED', 'mergeStateStatus':'CLEAN'}}

    def assert_no_writes(self, clients):
        self.assertFalse(any(method != 'GET' for client in clients for _, method, _ in client.calls))

    def test_issue_without_pr_is_pending_and_read_only(self):
        code, result, clients = self.run_status()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['pr']['status'], 'missing')
        self.assertEqual(result['blockers'][0]['code'], 'pr_missing')
        self.assertTrue(any('aipipe/issue-1' in action and 'Closes #1' in action for action in result['next_actions']))
        self.assert_no_writes(clients)

    def test_open_pr_with_approval_and_required_check_is_ready(self):
        self.linked_ready()
        code, result, clients = self.run_status()
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['reviews']['status'], 'succeeded')
        self.assertEqual(result['checks']['status'], 'succeeded')
        self.assertEqual(result['stage']['value'], 'review')
        self.assert_no_writes(clients)
        self.assertFalse(any('/commits/' in path for client in clients for path, _, _ in client.calls if isinstance(path, str)))

    def test_native_review_decision_is_required_for_green_status(self):
        self.linked_ready(native={'reviewDecision':None, 'mergeStateStatus':'CLEAN'})
        code, result, _ = self.run_status()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('reviews', {b['code'] for b in result['blockers']})
        self.assertEqual(result['reviews']['status'], 'unknown')

    def test_native_review_decision_read_failure_is_not_green(self):
        self.linked_ready()
        self.fixture['native_error'] = True
        code, result, _ = self.run_status()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('reviews', {b['code'] for b in result['blockers']})
        self.assertIn('merge_state', {b['code'] for b in result['blockers']})

    def test_draft_changes_requested_and_head_change_are_blockers(self):
        self.linked_ready(pull=pr(draft=True), native={'reviewDecision':'APPROVED', 'mergeStateStatus':'DRAFT'})
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'pending')
        self.assertIn('draft', {b['code'] for b in result['blockers']})

        self.linked_ready(reviews=[{'id':2,'state':'CHANGES_REQUESTED','user':{'login':'reviewer'},'commit_id':SHA}], native={'reviewDecision':'CHANGES_REQUESTED', 'mergeStateStatus':'BLOCKED'})
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('reviews', {b['code'] for b in result['blockers']})

        self.linked_ready(pull=[pr(head=SHA), pr(head=NEW_SHA)])
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('head_changed', {b['code'] for b in result['blockers']})

    def test_required_check_states_sources_and_graphql_status_contexts(self):
        cases = [
            ([], [], 'failed'),
            ([check(status_value='queued', conclusion=None)], [], 'pending'),
            ([check(conclusion='failure')], [], 'failed'),
            ([check(app_id=999)], [], 'failed'),
            ([check(conclusion='skipped')], [], 'succeeded'),
            ([check(conclusion='neutral')], [], 'succeeded'),
            ([check()], [commit_status(state='failure')], 'failed'),
            ([], [commit_status(state='success')], 'succeeded'),
        ]
        for runs, statuses, expected in cases:
            with self.subTest(expected=expected, runs=runs, statuses=statuses):
                self.fixture['clients'] = []
                self.linked_ready(checks=runs, statuses=statuses)
                code, result, _ = self.run_status()
                self.assertEqual(result['checks']['status'], expected)
                if expected != 'succeeded':
                    self.assertIn('checks', {b['code'] for b in result['blockers']})

    def test_rollup_commit_mismatch_is_unknown(self):
        self.linked_ready(checks=[check(sha=NEW_SHA)])
        code, result, _ = self.run_status()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('checks', {b['code'] for b in result['blockers']})

    def test_newer_queued_check_run_overrides_older_success(self):
        older = check(status_value='completed', conclusion='success', sha=SHA)
        older['id'] = 100
        newer = check(status_value='queued', conclusion=None, sha=SHA)
        newer['id'] = 200
        newer['started_at'] = None
        newer['completed_at'] = None
        self.linked_ready(checks=[older, newer])
        code, result, _ = self.run_status()
        self.assertEqual(code, 1)
        self.assertEqual(result['checks']['status'], 'pending')
        self.assertEqual(result['checks']['required'][0]['check_run_id'], 200)

    def test_visible_wildcard_source_does_not_conflict_with_configured_pin(self):
        self.fixture['rules'] = [rule('ci', app_id=-1)]
        self.linked_ready()
        code, result, _ = self.run_status()
        self.assertEqual(code, 0)
        self.assertEqual(result['checks']['status'], 'succeeded')
        self.assertFalse(any(item.get('reason') == 'conflicting_required_check_source' for item in result['checks']['required']))

    def test_visible_required_checks_and_rule_read_errors_are_not_green(self):
        self.fixture['rules'] = [rule('ci'), rule('extra', app_id=222, strict=False)]
        self.linked_ready(checks=[check('ci')])
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'failed')
        contexts = {item['context'] for item in result['checks']['required']}
        self.assertEqual(contexts, {'ci', 'extra'})

        self.fixture.pop('rules', None)
        self.fixture['rules_error'] = True
        self.linked_ready()
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('checks', {b['code'] for b in result['blockers']})

    def test_pr_target_uses_complete_issue_association_and_detects_ambiguity(self):
        self.linked_ready(pull=pr(number=7))
        code, result, _ = self.run_status(['--pr','7','--role','developer','--json'])
        self.assertEqual(code, 0)
        self.assertEqual(result['issue']['number'], 1)
        self.fixture['pulls'] = {7:pr(number=7, body='Closes #1\nFixes #2\n')}
        code, result, _ = self.run_status(['--pr','7','--role','developer','--json'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['blockers'][0]['code'], 'ambiguous_association')

    def test_merged_pr_checks_merge_commit_not_current_main(self):
        merged = pr(state='closed', merged=True, head=SHA)
        self.linked_ready(pull=merged, reviews=[], checks=[])
        self.fixture['checks'] = {MERGE_SHA:[check(sha=MERGE_SHA, conclusion='failure')], MAIN_SHA:[check(sha=MAIN_SHA)]}
        self.fixture['statuses'] = {MERGE_SHA:[], MAIN_SHA:[]}
        code, result, _ = self.run_status()
        self.assertEqual(result['checks']['head'], MERGE_SHA)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('merged_main_checks', {b['code'] for b in result['blockers']})

    def test_missing_final_head_readback_is_unknown(self):
        self.linked_ready(pull=[pr(head=SHA), {**pr(head=None), 'head':{}}])
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('head_changed', {b['code'] for b in result['blockers']})

    def test_closed_unmerged_pr_has_next_action(self):
        self.linked_ready(pull=pr(state='closed', merged=False))
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cancelled', {b['code'] for b in result['blockers']})
        self.assertTrue(any('closed-unmerged' in action for action in result['next_actions']))

    def test_offline_reads_no_credentials_or_network(self):
        out = io.StringIO()
        with patch('aipipe.status.authenticated_env', side_effect=AssertionError('credential read')), \
             patch('aipipe.status.Gh', side_effect=AssertionError('network')), \
             contextlib.redirect_stdout(out):
            code = cli.main(['status','--project',str(self.root),'--issue','1','--role','developer','--offline','--json'])
        result = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['remote_access_evaluated'])
        self.assertEqual(result['role']['status'], 'unknown')

    def test_role_and_remote_failures_are_structured(self):
        self.fixture['role_error'] = 403
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['blockers'][0]['code'], 'role')
        self.assertEqual(result['role']['error']['category'], 'permission_denied')

        self.fixture.pop('role_error')
        self.fixture['remote_error'] = True
        code, result, _ = self.run_status()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['blockers'][0]['code'], 'facts')

    def test_version_and_malformed_config_are_structured_before_credentials(self):
        data = json.loads((self.root/'.aipipe/project.json').read_text())
        data['compatibility']['minimum_cli_version'] = '9.9.9'
        (self.root/'.aipipe/project.json').write_text(json.dumps(data))
        out = io.StringIO()
        with patch('aipipe.status.authenticated_env', side_effect=AssertionError('credential read')), \
             contextlib.redirect_stdout(out):
            code = cli.main(['status','--project',str(self.root),'--issue','1','--role','developer','--json'])
        result = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['blockers'][0]['code'], 'compatibility')

        (self.root/'.aipipe/project.json').write_text('[]')
        out = io.StringIO()
        with patch('aipipe.status.authenticated_env', side_effect=AssertionError('credential read')), \
             contextlib.redirect_stdout(out):
            code = cli.main(['status','--project',str(self.root),'--issue','1','--role','developer','--json'])
        result = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['blockers'][0]['code'], 'configuration')


if __name__ == '__main__':
    unittest.main()
