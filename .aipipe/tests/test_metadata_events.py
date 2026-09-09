"""Exercise real event -> facts -> reconciliation boundaries with GitHub-shaped responses."""
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote
from aipipe import metadata
from aipipe.github import GhError


class EventAPI:
    def __init__(self, body='Closes #1', base='main', indexed=True, default='main', state='open'):
        self.issue = {'number':1,'state':state,'labels':[{'name':'aipipe:review'},{'name':'user-label'}], 'milestone':{'number':7}}
        self.pr = {'number':2,'state':'open','body':body,'draft':False,'labels':[{'name':'pr-category'}],
                   'milestone':{'number':7},'head':{'repo':{'full_name':'test/repo'}},'base':{'ref':base}}
        self.indexed = indexed
        self.default = default
        self.run = {'id':10,'name':'aipipe review signal','event':'pull_request_review','conclusion':'success',
                    'repository':{'full_name':'test/repo'},'pull_requests':[{'number':2}]}
        self.closed_issue = {'number':5,'state':'closed','labels':[], 'milestone':None}
        self.writes = []
        self.calls = []

    def command(self, args, payload=None):
        self.calls.append(('command', tuple(args)))
        number = (payload or {}).get('variables', {}).get('number', 1)
        nodes = [{'source':{'number':2,'repository':{'nameWithOwner':'test/repo'}}}] if self.indexed and number == self.issue['number'] else []
        return json.dumps({'data':{'repository':{'issue':{'timelineItems':{
            'nodes':nodes,'pageInfo':{'hasNextPage':False}}}}}})

    def request(self, path, method='GET', payload=None):
        self.calls.append((method, path))
        if method != 'GET':
            self.writes.append((path,method,payload))
            item = self.issue if '/issues/1' in path else self.closed_issue if '/issues/5' in path else self.pr
            if method == 'POST' and path.endswith('/labels'):
                item['labels'] += [{'name':n} for n in payload['labels'] if n not in metadata.labels(item)]
            elif method == 'DELETE':
                name = unquote(path.rsplit('/',1)[1])
                item['labels'] = [x for x in item['labels'] if x['name'] != name]
            elif method == 'PATCH':
                item['milestone'] = {'number':payload['milestone']} if payload['milestone'] else None
            else:
                raise AssertionError((path,method))
            return copy.deepcopy(item)
        if path == 'repos/test/repo': return {'default_branch':self.default}
        if path.endswith('/actions/runs/10'): return copy.deepcopy(self.run)
        if path.endswith('/issues/1'): return copy.deepcopy(self.issue)
        if path.endswith('/issues/5'): return copy.deepcopy(self.closed_issue)
        if path.endswith('/pulls/2'): return copy.deepcopy(self.pr)
        if '/git/ref/' in path: raise GhError('api', status=404)
        if '/labels?' in path: return [{'name':s} for s in metadata.STAGES | {'user-label','pr-category'}]
        if '/reviews?' in path: return []
        if '/issues?' in path:
            if 'state=closed' in path: return [copy.deepcopy(self.closed_issue)]
            return [copy.deepcopy(self.issue)]
        raise AssertionError(path)


class MultiEventAPI(EventAPI):
    def __init__(self):
        super().__init__()
        self.issue3 = {'number':3,'state':'open','labels':[{'name':'aipipe:review'}], 'milestone':{'number':7}}
        self.pr4 = {'number':4,'state':'open','body':'Closes #3\nCloses #5','draft':False,'labels':[],
                    'milestone':None,'head':{'repo':{'full_name':'test/repo'}},'base':{'ref':'main'}}

    def command(self, args, payload=None):
        self.calls.append(('command', tuple(args)))
        number = (payload or {}).get('variables', {}).get('number', 1)
        nodes = []
        if number == 1:
            nodes = [{'source':{'number':2,'repository':{'nameWithOwner':'test/repo'}}}]
        elif number == 3:
            nodes = [{'source':{'number':4,'repository':{'nameWithOwner':'test/repo'}}}]
        return json.dumps({'data':{'repository':{'issue':{'timelineItems':{
            'nodes':nodes,'pageInfo':{'hasNextPage':False}}}}}})

    def request(self, path, method='GET', payload=None):
        if method == 'GET':
            self.calls.append((method, path))
            if path == 'repos/test/repo': return {'default_branch':'main'}
            if path.endswith('/issues/1'): return copy.deepcopy(self.issue)
            if path.endswith('/issues/3'): return copy.deepcopy(self.issue3)
            if path.endswith('/pulls/2'): return copy.deepcopy(self.pr)
            if path.endswith('/pulls/4'): return copy.deepcopy(self.pr4)
            if '/git/ref/' in path: raise GhError('api', status=404)
            if '/labels?' in path: return [{'name':s} for s in metadata.STAGES | {'user-label','pr-category'}]
            if '/reviews?' in path: return []
            if '/issues?' in path: return [copy.deepcopy(self.issue), copy.deepcopy(self.issue3)]
            raise AssertionError(path)
        return super().request(path, method, payload)


class EventBoundaryTests(unittest.TestCase):
    def workflow(self, api, event='pull_request_target', payload=None):
        if payload is None:
            payload = {'number':2,'issue':{'number':1},'ref_type':'branch','ref':'aipipe/issue-1'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'event.json'
            path.write_text(json.dumps(payload))
            out = io.StringIO()
            with patch.object(metadata,'Gh',return_value=api), patch.dict(os.environ, {
                'GITHUB_REPOSITORY':'test/repo','GITHUB_EVENT_PATH':str(path),'GITHUB_EVENT_NAME':event}), redirect_stdout(out):
                code = metadata.workflow()
        lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        return code, lines

    def test_index_lag_fails_without_writes_then_retry_converges(self):
        api = EventAPI(indexed=False)
        api.issue['labels'][0]['name'] = 'aipipe:ready'
        before = copy.deepcopy((api.issue,api.pr))
        code, lines = self.workflow(api)
        self.assertEqual(code,1)
        self.assertEqual(lines[0]['status'],'failed')
        self.assertEqual(api.writes,[])
        self.assertEqual((api.issue,api.pr),before)
        api.indexed = True
        code, _ = self.workflow(api)
        self.assertEqual(code,0)
        self.assertEqual(metadata.labels(api.issue),{'aipipe:review','user-label'})
        self.assertEqual(metadata.labels(api.pr),{'aipipe:review','user-label','pr-category'})
        self.assertIsNone(api.pr['milestone'])
        self.assertEqual(api.issue['milestone'],{'number':7})
        writes = len(api.writes)
        code, _ = self.workflow(api)
        self.assertEqual(code,0)
        self.assertEqual(len(api.writes),writes)

    def test_single_issue_with_active_pr_uses_no_more_than_five_reads(self):
        api = EventAPI()
        metadata.Reconciler(api,'test/repo').facts(1)
        read_count = len([call for call in api.calls if call[0] in ('GET','command')])
        self.assertLessEqual(read_count,5)
        self.assertFalse(any('/git/ref/' in call[1] for call in api.calls if call[0] == 'GET'))

    def test_open_issue_with_only_historical_pr_still_reads_branch_for_reopen(self):
        api = EventAPI()
        api.pr['state'] = 'closed'; api.pr['merged'] = True
        metadata.Reconciler(api,'test/repo').facts(1)
        self.assertTrue(any('/git/ref/' in call[1] for call in api.calls if call[0] == 'GET'))

    def test_closed_issue_skips_branch_read(self):
        api = EventAPI(state='closed')
        metadata.Reconciler(api,'test/repo').facts(1)
        self.assertFalse(any('/git/ref/' in call[1] for call in api.calls if call[0] == 'GET'))

    def test_non_default_pr_event_never_mutates_issue_or_pr(self):
        for body in ('Closes #1','Closes #1\nCloses #3','not a closing directive'):
            with self.subTest(body=body):
                api = EventAPI(body=body,base='develop')
                before = copy.deepcopy((api.issue,api.pr))
                code, lines = self.workflow(api)
                self.assertEqual(code,0)
                self.assertEqual(lines[0]['reason'],'non_default_base')
                self.assertEqual(api.writes,[])
                self.assertEqual((api.issue,api.pr),before)

    def test_actual_default_branch_is_used(self):
        api = EventAPI(base='develop',default='develop')
        code, _ = self.workflow(api)
        self.assertEqual(code,0)
        self.assertIsNone(api.pr['milestone'])
        self.assertIn('aipipe:review',metadata.labels(api.pr))

    def test_ambiguous_links_fail_for_all_issue_based_entrypoints_without_blocking_process(self):
        for event in ('issues','schedule','workflow_dispatch','create','delete'):
            with self.subTest(event=event):
                api = EventAPI(body='Closes #1\nCloses #3')
                before = copy.deepcopy((api.issue,api.pr))
                code, lines = self.workflow(api,event)
                self.assertEqual(code,1)
                self.assertTrue(any(line.get('issue') == 1 and line.get('status') == 'failed' for line in lines))
                self.assertFalse(any('/issues/1' in write[0] or '/issues/2' in write[0] for write in api.writes))
                self.assertEqual((api.issue,api.pr),before)

    def test_one_bad_scanned_task_does_not_block_good_task_but_fails_run(self):
        api = MultiEventAPI()
        code, lines = self.workflow(api,'schedule')
        self.assertEqual(code,1)
        self.assertEqual(lines[0]['issue'],1)
        self.assertEqual(lines[0]['status'],'succeeded')
        self.assertEqual(lines[1]['issue'],3)
        self.assertEqual(lines[1]['status'],'failed')
        self.assertIn('aipipe:review',metadata.labels(api.pr))

    def test_workflow_run_missing_pr_association_is_unknown_and_does_not_scan(self):
        api = EventAPI()
        api.run['pull_requests'] = []
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,1)
        self.assertEqual(lines,[{'event':'workflow_run','status':'unknown','reason':'pr_association_unavailable','count':0,'run_id':10}])
        self.assertTrue(any('/actions/runs/10' in call[1] for call in api.calls if call[0] == 'GET'))
        self.assertFalse(any('/issues?' in call[1] for call in api.calls if call[0] == 'GET'))
        self.assertEqual(api.writes,[])

    def test_workflow_run_missing_event_fields_are_unknown_before_any_write(self):
        for field, reason in [('name','workflow_name_unavailable'),('event','workflow_event_unavailable'),
                              ('conclusion','signal_run_incomplete'),('repository','repository_unavailable')]:
            with self.subTest(field=field):
                api = EventAPI()
                api.run.pop(field)
                code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
                self.assertEqual(code,1)
                self.assertEqual(lines[0]['reason'],reason)
                self.assertEqual(api.writes,[])

    def test_workflow_run_requires_run_id_and_ignores_untrusted_payload_summary(self):
        api = EventAPI()
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'name':'aipipe review signal','event':'pull_request_review',
                                                                        'conclusion':'success','repository':{'full_name':'test/repo'},
                                                                        'pull_requests':[{'number':2}]}})
        self.assertEqual(code,1)
        self.assertEqual(lines[0]['reason'],'run_id_unavailable')
        self.assertEqual(api.writes,[])
        api = EventAPI()
        api.run['name'] = 'other workflow'
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10,'name':'aipipe review signal','event':'pull_request_review',
                                                                        'conclusion':'success','repository':{'full_name':'test/repo'},
                                                                        'pull_requests':[{'number':2}]}})
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'unrelated_workflow')
        self.assertEqual(api.writes,[])

    def test_workflow_run_cross_repo_and_non_default_base_skip(self):
        api = EventAPI(); api.run['repository'] = {'full_name':'other/repo'}
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'cross_repository')
        api = EventAPI(base='develop')
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'non_default_base')

    def test_workflow_run_validates_native_signal_run(self):
        api = EventAPI(); api.run['name'] = 'other workflow'
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'unrelated_workflow')
        api = EventAPI(); api.run['event'] = 'push'
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'unrelated_event')
        api = EventAPI(); api.run['conclusion'] = 'failure'
        code, lines = self.workflow(api,'workflow_run',{'workflow_run':{'id':10}})
        self.assertEqual(code,1)
        self.assertEqual(lines[0]['reason'],'signal_run_not_successful')


    def test_schedule_scans_open_and_recent_closed_window(self):
        api = EventAPI()
        api.closed_issue['labels'] = [{'name':'aipipe:done'}]
        targets, errors = metadata.workflow_issue_scan(metadata.Reconciler(api,'test/repo'), closed_scope='recent')
        self.assertEqual(errors, [])
        self.assertEqual(targets, [1, 5])
        calls = [call[1] for call in api.calls if call[0] == 'GET']
        self.assertTrue(any('state=open' in path for path in calls))
        self.assertTrue(any('state=closed' in path and 'since=' in path for path in calls))

    def test_workflow_dispatch_history_uses_separate_bounded_closed_window(self):
        api = EventAPI()
        api.closed_issue['labels'] = [{'name':'aipipe:done'}]
        code, lines = self.workflow(api,'workflow_dispatch',{'inputs':{'closed_scope':'history'}})
        self.assertEqual(code,0)
        self.assertTrue(any('state=closed' in call[1] and 'since=' not in call[1] for call in api.calls if call[0] == 'GET'))
        self.assertTrue(any(line.get('issue') == 5 and line.get('status') == 'succeeded' for line in lines))

    def test_scan_truncation_is_reported_without_blocking_discovered_targets(self):
        api = EventAPI()
        hundred = [copy.deepcopy(api.issue)] + [{'number':n,'state':'open','labels':[]} for n in range(1000,1099)]
        def request(path, method='GET', payload=None):
            if method == 'GET' and 'issues?state=open' in path:
                return copy.deepcopy(hundred)
            return EventAPI.request(api, path, method, payload)
        api.request = request
        with patch.object(metadata, 'SCAN_OPEN_PAGES', 1):
            code, lines = self.workflow(api,'schedule')
        self.assertEqual(code,1)
        self.assertTrue(any(line.get('scan') == 'open' and line.get('reason') == 'scan_truncated' for line in lines))
        self.assertTrue(any(line.get('issue') == 1 and line.get('status') == 'succeeded' for line in lines))
        self.assertIn('aipipe:review', metadata.labels(api.pr))

    def test_review_signal_workflow_itself_has_no_writes(self):
        api = EventAPI()
        code, lines = self.workflow(api,'pull_request_review')
        self.assertEqual(code,0)
        self.assertEqual(lines[0]['reason'],'signal_only')
        self.assertEqual(api.calls,[])
        self.assertEqual(api.writes,[])

    def test_invalid_closing_references_to_this_issue_stop_facts_before_writes(self):
        for body in ('Closes #1, #3','Closes test/repo#1','Fixes https://github.com/test/repo/issues/1',
                     'Closes: #1','This change closes #1','Closes #01'):
            with self.subTest(body=body):
                api = EventAPI(body=body)
                with self.assertRaisesRegex(ValueError,'invalid or ambiguous'):
                    metadata.Reconciler(api,'test/repo').reconcile(1,apply=True)
                self.assertEqual(api.writes,[])

    def test_ordinary_mentions_and_other_tasks_remain_unrelated(self):
        for body in ('Related to #1','Related to #1\nCloses #3','Closes other/repo#1',
                     'Related to #1\nCloses #3\nFixes #4'):
            with self.subTest(body=body):
                api = EventAPI(body=body)
                _, prs, _, _ = metadata.Reconciler(api,'test/repo').facts(1)
                self.assertEqual(prs,[])
                self.assertEqual(api.writes,[])

    def test_ambiguous_non_default_pr_does_not_poison_issue_facts(self):
        api = EventAPI(body='Closes #1\nCloses #3',base='develop')
        _, prs, _, _ = metadata.Reconciler(api,'test/repo').facts(1)
        self.assertEqual(prs,[])
        self.assertEqual(api.writes,[])

    def test_pr_event_uses_current_body_and_never_writes_on_ambiguity(self):
        api = EventAPI(body='Closes #1\nCloses #3')
        code, lines = self.workflow(api)
        self.assertEqual(code,1)
        self.assertEqual(lines[0]['status'],'failed')
        self.assertEqual(api.writes,[])
