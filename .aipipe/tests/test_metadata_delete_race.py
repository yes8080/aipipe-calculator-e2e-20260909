"""Reproduce interleaved metadata writers using real reconciliation and API semantics."""
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit, parse_qs
from aipipe import metadata, runner
from test_metadata_events import EventAPI


class DeleteAPI(EventAPI):
    def __init__(self, module=metadata):
        super().__init__()
        self.module = module
        self.issue['state'] = 'closed'
        self.pr.update(state='closed', merged=True)
        self.pr['labels'].append({'name':'aipipe:review'})
        self.calls = []
        self.interleave = None
        self.target = 1
        self.delete_error = None
        self.read_error = None

    def request(self, path, method='GET', payload=None):
        self.calls.append((path,method))
        if method == 'GET' and '/issues/' in path and '/labels?' in path:
            if self.read_error:
                raise self.module.GhError('api', status=self.read_error)
            n = int(path.split('/issues/')[1].split('/')[0])
            item = self.issue if n == 1 else self.pr
            page = int(parse_qs(urlsplit(path).query)['page'][0])
            return copy.deepcopy(item['labels'][(page-1)*100:page*100])
        if method == 'DELETE' and '/labels/' in path:
            n = int(path.split('/issues/')[1].split('/')[0])
            if n == self.target and self.interleave:
                callback, self.interleave = self.interleave, None
                callback()
            if self.delete_error:
                raise self.module.GhError('api', status=self.delete_error)
            item = self.issue if n == 1 else self.pr
            label = unquote(path.rsplit('/',1)[1])
            if label not in self.module.labels(item):
                raise self.module.GhError('api', status=404)
        # Standalone bundle imports its own GhError class.
        if method == 'GET' and '/git/ref/' in path:
            raise self.module.GhError('api', status=404)
        return super().request(path,method,payload)


def racing_api(module=metadata, target=1):
    api = DeleteAPI(module); api.target = target
    api.interleave = lambda: module.Reconciler(api,'test/repo').reconcile(1,apply=True,expected_pr=2)
    return api


class DeleteRaceTests(unittest.TestCase):
    def assert_done(self, api, module=metadata):
        self.assertEqual(module.labels(api.issue),{'aipipe:done','user-label'})
        self.assertEqual(module.labels(api.pr),{'aipipe:done','user-label','pr-category'})
        self.assertEqual(api.issue['milestone'],{'number':7})
        self.assertIsNone(api.pr['milestone'])

    def test_two_writers_converge_for_issue_and_pr(self):
        for target in (1,2):
            with self.subTest(target=target):
                api = racing_api(target=target)
                service = metadata.Reconciler(api,'test/repo')
                service.reconcile(1,apply=True,expected_pr=2)
                self.assert_done(api)
                deletes = [p for p,m in api.calls if m=='DELETE' and f'/issues/{target}/' in p]
                self.assertEqual(len(deletes),2)  # One attempt per writer, no write retry.
                count = len(api.writes)
                self.assertEqual(service.reconcile(1,apply=True,expected_pr=2),[])
                self.assertEqual(len(api.writes),count)

    def test_404_with_label_still_present_fails_even_on_later_page(self):
        api=DeleteAPI();api.delete_error=404
        api.issue['labels']=[{'name':f'user-{n}'} for n in range(100)]+[{'name':'aipipe:review'}]
        with self.assertRaises(metadata.GhError) as caught:
            metadata.Reconciler(api,'test/repo').reconcile(1,apply=True)
        self.assertEqual(caught.exception.status,404)
        self.assertIn('DELETE repos/test/repo/issues/1/labels/aipipe%3Areview',str(caught.exception))
        self.assertTrue(any('/issues/1/labels?' in p and 'page=2' in p for p,m in api.calls))
        self.assertEqual(sum(m=='DELETE' for p,m in api.calls),1)

    def test_unreadable_object_is_not_success(self):
        for status in (403,404,500):
            with self.subTest(status=status):
                api=DeleteAPI();api.delete_error=404;api.read_error=status
                with self.assertRaises(metadata.GhError) as caught:
                    metadata.Reconciler(api,'test/repo').reconcile(1,apply=True)
                self.assertIn('GET repos/test/repo/issues/1/labels',str(caught.exception))
                self.assertEqual(caught.exception.status,status)
                self.assertEqual(sum(m=='DELETE' for p,m in api.calls),1)

    def test_other_delete_errors_are_not_suppressed_or_retried(self):
        for status in (403,422,500):
            with self.subTest(status=status):
                api=DeleteAPI();api.delete_error=status
                with self.assertRaises(metadata.GhError) as caught:
                    metadata.Reconciler(api,'test/repo').reconcile(1,apply=True)
                self.assertEqual(caught.exception.status,status)
                self.assertIn('DELETE repos/test/repo/issues/1/labels/',str(caught.exception))
                self.assertFalse(any('/issues/1/labels?' in p for p,m in api.calls))
                self.assertEqual(sum(m=='DELETE' for p,m in api.calls),1)

    def test_lifecycle_change_still_fails_final_fact_check(self):
        api=DeleteAPI()
        def reopen():
            api.issue['labels']=[x for x in api.issue['labels'] if x['name']!='aipipe:review']
            api.issue['state']='open'
        api.interleave=reopen
        with self.assertRaisesRegex(ValueError,'changed during synchronization'):
            metadata.Reconciler(api,'test/repo').reconcile(1,apply=True)
        self.assertEqual(sum(m=='DELETE' and '/issues/1/' in p for p,m in api.calls),1)

    def test_read_only_does_not_delete_or_verify_a_mutation(self):
        api=DeleteAPI();service=metadata.Reconciler(api,'test/repo')
        self.assertTrue(service.reconcile(1))
        self.assertEqual(api.writes,[])
        self.assertFalse(any('/issues/1/labels?' in p for p,m in api.calls))

    def test_source_and_generated_delete_event_entrypoints(self):
        path=Path(metadata.__file__).resolve().parents[2]/'automation/metadata.py'
        spec=importlib.util.spec_from_file_location('delete_race_standalone',path)
        standalone=importlib.util.module_from_spec(spec)
        with patch('sys.path',[str(path.parent),*__import__('sys').path]):spec.loader.exec_module(standalone)
        for module in (metadata,standalone):
            with self.subTest(module=module.__name__),tempfile.TemporaryDirectory() as d:
                event=Path(d)/'event.json';event.write_text(json.dumps({'ref_type':'branch','ref':'aipipe/issue-1'}))
                api=racing_api(module)
                with patch.object(module,'Gh',return_value=api),patch.dict(os.environ,{'GITHUB_REPOSITORY':'test/repo','GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'delete'}),redirect_stdout(io.StringIO()):
                    module.workflow()
                self.assert_done(api,module)

    def run_merge(self, api):
        args=Namespace(project=None,config=None,action='github',role='delivery',identity=Path('/tmp/id'),credentials=None,args=['pr','merge','2','--squash'])
        with ExitStack() as stack:
            for name,value in [('context.resolve',(Path('/tmp'),Path('/tmp/config'))),('read_config',({'repository':'test/repo'},Path('/tmp'))),('compatibility.enforce',None),('identity.load',{'credential_role':'delivery'}),('verify_remote','https://github.com/test/repo.git'),('authenticated_env',{}),('identity.github_arguments',(('merge','2',{}),[])),('Gh',api)]:
                stack.enter_context(patch('aipipe.runner.'+name,return_value=value))
            submit=stack.enter_context(patch('aipipe.runner.submit_attributed',return_value={'merged':True}))
            stack.enter_context(redirect_stdout(io.StringIO()))
            try:return runner.execute(args)
            finally:submit.assert_called_once()

    def test_post_merge_cli_uses_real_reconciler_and_does_not_repeat_merge(self):
        api=racing_api()
        self.assertEqual(self.run_merge(api),0)
        self.assert_done(api)

    def test_post_merge_permission_error_keeps_partial_success_message(self):
        api=DeleteAPI();api.delete_error=403
        with self.assertRaisesRegex(ValueError,'merge succeeded.*do not repeat.*DELETE repos/test/repo/issues/1/labels/'):
            self.run_merge(api)
