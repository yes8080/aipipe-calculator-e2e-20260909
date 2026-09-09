import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aipipe.metadata import STAGES, Reconciler, linked_issue, plan, pr_stage
from aipipe.github import GhError


def issue(state='open', names=('aipipe:ready','bug')):
    return {'number':1, 'state':state, 'labels':[{'name':x} for x in names], 'milestone':{'number':3}}


def pr(state='open', draft=False, merged=False):
    return {'number':2,'state':state,'draft':draft,'merged':merged,'body':'Closes #1\n\nTested',
            'labels':[{'name':'custom'}], 'milestone':None,'head':{'sha':'a'*40}}


class MetadataTests(unittest.TestCase):
    def test_canonical_link(self):
        self.assertEqual(linked_issue(pr()),1)
        for body in ('No link', 'Closes #1, #3', 'Closes owner/repo#1', 'Closes #1\nFixes #2', 'Closes #0'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                linked_issue({'body':body})

    def test_lifecycle(self):
        self.assertEqual(plan(issue(),[],{},False)[1]['stage'],'ready')
        self.assertEqual(plan(issue(),[],{},True)[1]['stage'],'active')
        self.assertEqual(plan(issue(),[pr(draft=True)],{},True)[1]['stage'],'active')
        self.assertEqual(plan(issue(),[pr()],{},True)[1]['stage'],'review')
        merged=pr(state='closed',merged=True)
        self.assertEqual(plan(issue('closed'),[merged],{},False)[1]['stage'],'done')
        self.assertEqual(plan(issue('closed'),[],{},False)[1]['stage'],'cancelled')
        self.assertEqual(plan(issue(),[merged],{},False)[1]['stage'],'ready')  # reopened needs work

    def test_closed_issue_with_open_pr_is_not_delivered(self):
        self.assertEqual(plan(issue('closed'),[pr()],{},True)[1]['stage'],'cancelled')
        self.assertEqual(plan(issue('closed'),[pr()],{},True)[2]['stage'],'review')

    def test_developer_cannot_apply_before_reading_credentials(self):
        from argparse import Namespace
        from aipipe import metadata
        args=Namespace(project=None,config=None,apply=True,role='developer')
        with patch('aipipe.context.resolve',return_value=(Path('/tmp'),Path('/tmp/config'))), patch('aipipe.config.read_config',return_value=({},Path('/tmp'))), patch('aipipe.compatibility.enforce'), patch('aipipe.identity.project_repo',return_value='test/repo'), patch('aipipe.credentials.authenticated_env') as auth:
            with self.assertRaisesRegex(ValueError,'Developer may check'): metadata.run(args)
            auth.assert_not_called()

    def test_reviews_and_dismissal(self):
        review={'id':1,'user':{'login':'reviewer'},'state':'CHANGES_REQUESTED','commit_id':'old'}
        self.assertEqual(pr_stage(pr(),[review]),'changes-requested')
        approved={**review,'id':2,'state':'APPROVED'}
        self.assertEqual(pr_stage(pr(),[review,approved]),'review')
        self.assertEqual(pr_stage(pr(),[{**review,'state':'DISMISSED'}]),'review')
        self.assertEqual(pr_stage(pr(),[review,{**review,'id':2,'state':'COMMENTED'}]),'changes-requested')

    def test_block_and_inheritance(self):
        result=plan(issue(names=('aipipe:blocked','bug')),[pr()],{},True)
        self.assertEqual(result[1]['stage'],'blocked')
        self.assertEqual(result[2],{'stage':'blocked','milestone':None,'inherit':{'bug'}})
        self.assertEqual(plan(issue('closed',('aipipe:blocked',)),[pr('closed',merged=True)],{},False)[1]['stage'],'done')

    def test_milestone_counts_only_the_issue(self):
        item=issue(); pull=pr(); pull['milestone']={'number':3}
        result=plan(item,[pull],{},True)
        self.assertNotIn('milestone',result[1])
        self.assertIsNone(result[2]['milestone'])
        self.assertEqual(item['milestone'],{'number':3})

    def test_multiple_active_prs_fail(self):
        with self.assertRaisesRegex(ValueError,'multiple active'):
            plan(issue(),[pr(),{**pr(),'number':4}],{},True)

    def test_sync_preserves_user_labels_and_is_idempotent(self):
        fake=Fake(); service=Reconciler(fake,'test/repo')
        service.facts=lambda n:(copy.deepcopy(fake.items[1]),[copy.deepcopy(fake.items[2])],{},True)
        diff=service.reconcile(1)
        self.assertEqual(len(diff),2)
        self.assertEqual(fake.writes,[])
        service.reconcile(1,True)
        self.assertEqual({x['name'] for x in fake.items[2]['labels']},{'custom','bug','aipipe:review'})
        self.assertIsNone(fake.items[2]['milestone'])
        count=len(fake.writes)
        self.assertEqual(service.reconcile(1,True),[])
        self.assertEqual(len(fake.writes),count)

    def test_cleared_milestone_and_stale_stage(self):
        fake=Fake(); fake.items[1]['milestone']=None; fake.items[2]['milestone']={'number':5}
        fake.items[2]['labels'].append({'name':'aipipe:ready'})
        service=Reconciler(fake,'test/repo')
        service.facts=lambda n:(copy.deepcopy(fake.items[1]),[copy.deepcopy(fake.items[2])],{},True)
        service.reconcile(1,True)
        self.assertIsNone(fake.items[2]['milestone'])
        self.assertNotIn('aipipe:ready',{x['name'] for x in fake.items[2]['labels']})

    def test_partial_failure_not_retried(self):
        fake=Fake(); service=Reconciler(fake,'test/repo')
        service.facts=lambda n:(issue(),[pr()],{},True)
        with self.assertRaisesRegex(ValueError,'changed during'):
            service.reconcile(1,True)
        self.assertEqual(sum(x[1]=='POST' for x in fake.writes),2)

    def test_missing_expected_pr_fails_before_write(self):
        fake=Fake(); service=Reconciler(fake,'test/repo'); service.facts=lambda n:(issue(),[],{},False)
        with self.assertRaisesRegex(ValueError,'cross-reference'):
            service.reconcile(1,True,expected_pr=2)
        self.assertFalse(fake.writes)

    def test_branch_auth_failure_is_not_absence(self):
        fake=Fake(); service=Reconciler(fake,'test/repo')
        with patch.object(service,'get',side_effect=GhError('api',status=403)):
            with self.assertRaises(GhError): service.branch(1)
        with patch.object(service,'get',side_effect=GhError('api',status=404)):
            self.assertFalse(service.branch(1))

    def test_successful_review_is_not_repeated_when_metadata_fails(self):
        from argparse import Namespace
        from aipipe import runner
        args=Namespace(project=None,config=None,action='github',role='delivery',identity=Path('/tmp/id'),credentials=None,args=['pr','review','2','--approve'])
        with patch('aipipe.runner.context.resolve',return_value=(Path('/tmp'),Path('/tmp/config'))), patch('aipipe.runner.read_config',return_value=({'repository':'test/repo'},Path('/tmp'))), patch('aipipe.runner.compatibility.enforce'), patch('aipipe.runner.identity.load',return_value={'credential_role':'delivery'}), patch('aipipe.runner.verify_remote',return_value='https://github.com/test/repo.git'), patch('aipipe.runner.authenticated_env',return_value={}), patch('aipipe.runner.identity.github_arguments',return_value=(('review','2',{}),[])), patch('aipipe.runner.submit_attributed',return_value={'id':3}) as review, patch('aipipe.metadata.Reconciler') as reconciler, patch('builtins.print'):
            reconciler.return_value.get.return_value=pr()
            reconciler.return_value.reconcile.side_effect=ValueError('permission denied')
            with self.assertRaisesRegex(ValueError,'review succeeded.*do not repeat'):
                runner.execute(args)
            review.assert_called_once()
            reconciler.return_value.reconcile.assert_called_once_with(1,apply=True,expected_pr=2)

    def test_workflow_generated_from_package(self):
        from aipipe.initialize import install_metadata
        import aipipe.metadata as module
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); install_metadata(root); install_metadata(root)
            self.assertEqual((root/'.aipipe/automation/metadata.py').read_bytes(),Path(module.__file__).read_bytes())
            workflow=(root/'.github/workflows/aipipe-metadata.yml').read_text()
            self.assertIn('github.event.repository.default_branch',workflow)
            self.assertIn('workflow_run:', workflow)
            self.assertIn('queue: max', workflow)
            self.assertNotIn('pull_request.head',workflow)
            self.assertNotIn('secrets.',workflow)
            signal=(root/'.github/workflows/aipipe-review-signal.yml').read_text()
            self.assertIn('pull_request_review:', signal)
            self.assertIn('permissions: {}', signal)
            self.assertNotIn('checkout', signal)
            self.assertNotIn('artifact', signal.lower())
            self.assertNotIn('cache', signal.lower())
            (root/'.aipipe/automation/metadata.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'differs'): install_metadata(root)


class Fake:
    def __init__(self):
        self.items={1:issue(),2:pr()}; self.writes=[]
    def request(self,path,method='GET',payload=None):
        if method=='GET' and '/labels?' in path:
            return [{'name':x} for x in STAGES|{'bug','custom'}]
        self.writes.append((path,method,payload))
        number=int(path.split('/issues/')[1].split('/')[0]); item=self.items[number]
        if method=='POST':
            existing={x['name'] for x in item['labels']}
            item['labels'] += [{'name':x} for x in payload['labels'] if x not in existing]
        elif method=='DELETE':
            from urllib.parse import unquote
            label=unquote(path.rsplit('/',1)[1]);item['labels']=[x for x in item['labels'] if x['name']!=label]
        elif method=='PATCH':
            item['milestone']={'number':payload['milestone']} if payload['milestone'] else None
