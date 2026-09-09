import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aipipe import cli, config, identity, publish, runner


def actor(role='developer',credential_role='developer',model='unknown'):
    return {'schema_version':1,'agent_id':str(uuid.uuid4()),'tool':'codex','model':model,
            'role':role,'credential_role':credential_role,'repository':'owner/repo'}


class MetadataTests(unittest.TestCase):
    def test_independent_actors_and_append_history_round_trip(self):
        first=actor();second=actor('reviewer','delivery')
        body='Closes #1\n\nReal test report.\n'
        published=identity.annotate(body,first,'pr:create')
        edited=identity.annotate('Updated report\n',second,'review', 'a'*40, published)
        core,records=identity.split(edited)
        self.assertEqual(core,'Updated report');self.assertEqual(len(records),2)
        self.assertNotEqual(records[0]['agent_id'],records[1]['agent_id'])
        again=identity.annotate(edited,second,'review','a'*40)
        self.assertEqual(len(identity.split(again)[1]),2)
        self.assertEqual(identity.canonical({'body':published})['body'],body)

    def test_rejects_unknown_secret_fields_controls_and_wrong_repo_or_role(self):
        for changed in ({'token':'SECRET'}, {'tool':'codex\nforged'}, {'model':'<bad>'}, {'agent_id':'not-a-uuid'}, {'role':'reviewer'}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):identity.validate(dict(actor(),**changed))
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'actor.json';p.write_text(json.dumps(actor()))
            with self.assertRaisesRegex(ValueError,'different repository'):identity.load(p,'elsewhere/repo')
            with self.assertRaisesRegex(ValueError,'operation role'):identity.load(p,'owner/repo','delivery')

    def test_malformed_metadata_is_not_silently_removed(self):
        for body in ('business\n'+identity.START, identity.END, identity.START+'\n{}\n'+identity.END):
            with self.assertRaises(ValueError):identity.split(body)

    def test_generic_review_is_sha_bound_and_developer_cannot_approve(self):
        class Client:
            def request(self,*args):return {'head':{'sha':'a'*40}}
        with self.assertRaisesRegex(ValueError,'commit_id'):identity.api_payload('pulls/6/reviews','POST',{'body':'tested','event':'APPROVE'},actor('reviewer','delivery'),Client(),'owner/repo')
        with self.assertRaisesRegex(ValueError,'reviewer'):identity.api_payload('pulls/6/reviews','POST',{'body':'tested','event':'APPROVE','commit_id':'a'*40},actor(),Client(),'owner/repo')
        result=identity.api_payload('pulls/6/reviews','POST',{'body':'tested','event':'APPROVE','commit_id':'a'*40},actor('reviewer','delivery'),Client(),'owner/repo')
        self.assertEqual(identity.split(result['body'])[1][0]['sha'],'a'*40)

    def test_gh_review_payload_is_bound_to_verified_sha(self):
        class Client:
            def request(self,*args):return {'head':{'sha':'a'*40}}
        args=['pr','review','6','--request-changes','--match-head-commit','a'*40,'--body','Reproduction and criteria']
        request,paths=identity.github_arguments(args,actor('reviewer','delivery'),Client(),'owner/repo')
        self.assertEqual(request[2]['event'],'REQUEST_CHANGES');self.assertEqual(request[2]['commit_id'],'a'*40)
        self.assertEqual(paths,[])
        with self.assertRaisesRegex(ValueError,'head'):identity.github_arguments(args[:-4]+['--body','report'],actor('reviewer','delivery'),Client(),'owner/repo')

    def test_merge_preserves_all_commit_authors_and_requires_sha(self):
        class Client:
            def request(self,path):
                if '/commits' in path:return [{'sha':'b'*40,'commit':{'author':{'name':'Other tool / other model','email':'other@example.invalid'},'message':'feat\nAipipe-Tool: other'}}]
                return {'head':{'sha':'a'*40},'body':'Closes #1'}
        request,paths=identity.github_arguments(['pr','merge','6','--squash','--match-head-commit','a'*40],actor('reviewer','delivery'),Client(),'owner/repo')
        body=request[2]['commit_message']
        self.assertIn('Other tool / other model',body);self.assertIn('Aipipe-Tool: other',body)
        self.assertEqual(identity.split(body)[1][-1]['sha'],'a'*40)
        self.assertEqual(request[2]['sha'],'a'*40);self.assertEqual(paths,[])
        with self.assertRaisesRegex(ValueError,'immediate'):identity.github_arguments(['pr','merge','6','--squash','--auto','--match-head-commit','a'*40],actor('reviewer','delivery'),Client(),'owner/repo')

    def test_publication_keeps_provenance_but_compares_original_contract(self):
        client=publish.GitHub('owner/repo',actor=actor('planner','delivery'))
        with patch.object(client.transport,'request') as request:
            request.side_effect=lambda path,method,payload:dict(payload,number=1)
            actual=client.request('issues','POST',{'body':'Contract\n','title':'Slice'})
            sent=request.call_args.args[2]
            self.assertIn(identity.START,sent['body']);self.assertEqual(actual['body'],'Contract\n')


    def test_publish_retry_and_release_completeness_preserve_actor_history(self):
        from test_publish_batch import FakeGitHub, example_plan, TEMPLATE, REPO, SHA
        fake=FakeGitHub();planner=actor('planner','delivery');planner['repository']=REPO
        client=publish.GitHub(REPO,actor=planner)
        def transport(path,method='GET',payload=None):
            return fake.request(path.removeprefix('repos/'+REPO+'/'),method,payload)
        with patch.object(client.transport,'request',side_effect=transport):
            plan=example_plan();publish.publish(plan,REPO,SHA,TEMPLATE,client,output=lambda _:None)
            self.assertTrue(all(identity.START in i['body'] for i in fake.data['issues']))
            saved=json.dumps(fake.data,sort_keys=True);fake.calls.clear()
            publish.publish(plan,REPO,SHA,TEMPLATE,client,output=lambda _:None)
            publish.verify_complete(plan,REPO,SHA,TEMPLATE,client,1)
            self.assertEqual(fake.writes,[]);self.assertEqual(json.dumps(fake.data,sort_keys=True),saved)
            fake.data['issues'][0]['body']='Changed scope\n'+fake.data['issues'][0]['body']
            with self.assertRaises(publish.PublishError):publish.verify_complete(plan,REPO,SHA,TEMPLATE,client,1)

    def test_merge_keeps_preexisting_pr_identity_blocks(self):
        first=actor();pr_body=identity.annotate('Closes #1',first,'pr:create')
        class Client:
            def request(self,path):
                if '/commits' in path:return []
                return {'head':{'sha':'a'*40},'body':pr_body,'commits':0}
        request,paths=identity.github_arguments(['pr','merge','6','--squash','--match-head-commit','a'*40],actor('reviewer','delivery'),Client(),'owner/repo')
        self.assertEqual(len(identity.split(request[2]['commit_message'])[1]),2)

    def test_required_identity_stops_before_credentials_or_git(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config.save(root/'.aipipe/project.json',{'schema_version':1,'repository':'owner/repo','attribution':{'required':True}})
            for args in (['push','--role','developer','aipipe/issue-1'],['github','--role','delivery','--','pr','merge','6','--squash'],['api','--role','delivery','issues/1','--method','PATCH']):
                with patch('subprocess.run',side_effect=AssertionError('process')),patch('aipipe.runner.authenticated_env',side_effect=AssertionError('credentials')),patch('sys.stderr',new_callable=io.StringIO) as err:
                    self.assertEqual(cli.main(['--project',str(root),*args]),2)
                    self.assertIn('execution identity required',err.getvalue())


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.git('init','-q');self.git('config','user.name','Human')
        self.git('config','user.email','human@example.invalid');self.git('config','commit.gpgsign','false')
        config.save(self.root/'.aipipe/project.json',{'schema_version':1,'repository':'owner/repo'})
        self.actor=actor();self.file=self.root/'.aipipe/.runtime/actor.json';self.file.parent.mkdir();self.file.write_text(json.dumps(self.actor))
        self.message=self.root/'.aipipe/.runtime/message.md';self.message.write_text('feat: tested change\n')
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):
        return subprocess.check_output(['git',*args],cwd=self.root,text=True,stderr=subprocess.STDOUT).strip()
    def stage(self,name='product.txt'):
        (self.root/name).write_text('product\n');self.git('add',name)
    def commit(self,*extra):
        with patch('sys.stdout',new_callable=io.StringIO):
            return cli.main(['commit','--project',str(self.root),'--identity',str(self.file),'--issue','1','--message-file',str(self.message),*extra])

    def test_actual_commit_overrides_inherited_author_without_changing_git_config(self):
        self.stage()
        with patch.dict(os.environ,{'GIT_AUTHOR_NAME':'Wrong human','GIT_COMMITTER_EMAIL':'wrong@example.invalid','GH_TOKEN':'SECRET'}):
            self.assertEqual(self.commit(),0)
        self.assertEqual(self.git('log','-1','--format=%an'), 'codex / unknown')
        self.assertEqual(self.git('log','-1','--format=%ae'),identity.email(self.actor))
        self.assertIn(self.actor['agent_id'],self.git('log','-1','--format=%B'))
        self.assertEqual(self.git('config','user.name'),'Human')
        self.assertNotIn('.aipipe',self.git('show','--format=','--name-only','HEAD'))
        identity.verify_commits(self.root,{'attribution':{'required':True}},self.actor)

    def test_delegated_author_and_operator_and_coauthor_are_distinct(self):
        other=actor(model='writer-model');p=self.root/'writer.json';p.write_text(json.dumps(other))
        coauthor=actor(model='helper-model');q=self.root/'helper.json';q.write_text(json.dumps(coauthor))
        self.stage();self.assertEqual(self.commit('--author-identity',str(p),'--coauthor-identity',str(q)),0)
        self.assertEqual(self.git('log','-1','--format=%an'),'codex / writer-model')
        self.assertEqual(self.git('log','-1','--format=%cn'),'codex / unknown [developer]')
        message=self.git('log','-1','--format=%B');self.assertIn('Aipipe-Operator-Agent: '+self.actor['agent_id'],message)
        self.assertIn('Co-authored-by: codex / helper-model',message)

    def test_identity_creation_is_local_and_does_not_need_credentials(self):
        with patch('sys.stdout',new_callable=io.StringIO) as out,patch('aipipe.credentials.credential',side_effect=AssertionError('credential read')):
            result=cli.main(['identity','create','--project',str(self.root),'--tool','opencode','--model','unknown','--role','developer','--credential-role','developer'])
        self.assertEqual(result,0)
        result=json.loads(out.getvalue());p=Path(result['identity_file']);self.assertTrue(p.is_file())
        self.assertEqual(identity.load(p)['model'],'unknown')

    def test_raw_commit_rejected_after_rollout_baseline_but_history_preserved(self):
        self.stage();self.git('commit','-qm','historical');baseline=self.git('rev-parse','HEAD')
        data={'attribution':{'required':True,'legacy_before':baseline}}
        identity.verify_commits(self.root,data,self.actor)
        self.stage('new.txt');self.git('commit','-qm','unattributed new work')
        with self.assertRaisesRegex(ValueError,'author metadata'):identity.verify_commits(self.root,data,self.actor)

    def test_no_token_in_commit_hook_environment_and_no_automatic_stage(self):
        hook=self.root/'.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\ntest -z "$GH_TOKEN" && test -z "$GITHUB_TOKEN" && test -z "$AIPIPE_SECRET"\n');hook.chmod(0o700)
        self.stage();(self.root/'untracked.txt').write_text('not staged')
        with patch.dict(os.environ,{'GH_TOKEN':'SECRET','GITHUB_TOKEN':'SECRET','AIPIPE_SECRET':'SECRET'}):self.assertEqual(self.commit(),0)
        self.assertNotIn('untracked.txt',self.git('show','--format=','--name-only','HEAD'))

    def test_in_progress_cherry_pick_is_not_reauthored(self):
        self.stage();(self.root/'.git/CHERRY_PICK_HEAD').write_text('a'*40)
        with patch('sys.stderr',new_callable=io.StringIO) as err:self.assertEqual(self.commit(),2)
        self.assertIn('original authors',err.getvalue())

    def test_squash_then_next_slice_checks_only_new_work_and_rejects_raw_commit(self):
        self.stage();self.git('commit','-qm','published initial project');self.git('branch','-M','main')
        self.git('switch','-qc','slice-one');self.stage('legacy.txt');self.git('commit','-qm','old work before rollout')
        baseline=self.git('rev-parse','HEAD');self.stage('first.txt');self.assertEqual(self.commit(),0)
        self.git('switch','main');self.git('merge','--squash','slice-one');self.git('commit','-qm','Published squash with multiple original author records')
        published=self.git('rev-parse','HEAD')
        with tempfile.TemporaryDirectory() as folder:
            remote=Path(folder)/'remote.git';subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
            self.git('remote','add','origin',str(remote));self.git('push','-q','origin','main')
            self.git('switch','-qc','slice-two');self.stage('second.txt');self.assertEqual(self.commit(),0)
            # Even an incorrect local tracking ref must not exempt the new work.
            self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'))
            actual=runner.fetch_published_base(self.root,'main',dict(os.environ))
            self.assertEqual(actual,published)
            data={'attribution':{'required':True,'legacy_before':baseline}}
            identity.verify_commits(self.root,data,self.actor,published_base=actual)
            # Fresh single-branch clones may no longer have the old rollout object.
            identity.verify_commits(self.root,{'attribution':{'required':True,'legacy_before':'0'*40}},self.actor,published_base=actual)
            self.stage('bad.txt');self.git('commit','-qm','raw new code')
            with self.assertRaisesRegex(ValueError,'author metadata'):identity.verify_commits(self.root,data,self.actor,published_base=actual)
            with self.assertRaisesRegex(ValueError,'cannot fetch'):
                runner.fetch_published_base(self.root,'main',{},lambda args,**kw:subprocess.CompletedProcess(args,1 if 'fetch' in args else 0,stdout=published+'\trefs/heads/main\n'))


class DeliveryBoundaryTests(unittest.TestCase):
    def test_merge_uses_put_with_sha_and_readback_not_gh_preflight(self):
        class Client:
            def __init__(self):self.calls=[]
            def request(self,path,*args):
                self.calls.append((path,args))
                if args:return {'merged':True,'sha':'b'*40}
                return {'merged':True,'merge_commit_sha':'b'*40,'head':{'sha':'a'*40}}
        client=Client();payload={'sha':'a'*40,'merge_method':'squash','commit_message':'Authors and actual operator'}
        result=runner.submit_attributed(client,'owner/repo','merge','6',payload)
        self.assertTrue(result['merged']);self.assertEqual(client.calls[0],('repos/owner/repo/pulls/6/merge',('PUT',payload)))
        self.assertEqual(len(client.calls),2)

    def test_merge_rejection_and_uncertain_readback_do_not_retry_or_claim_success(self):
        for replies in ([{'merged':False}], [{'merged':True,'sha':'b'*40},{'merged':False,'head':{'sha':'a'*40}}]):
            class Client:
                def request(self,*args):return replies.pop(0)
            with self.assertRaises(ValueError):runner.submit_attributed(Client(),'owner/repo','merge','6',{'sha':'a'*40})
            self.assertEqual(replies,[])
        class Denied:
            def request(self,*args):raise RuntimeError('405 required checks have not passed')
        with self.assertRaisesRegex(RuntimeError,'405'):runner.submit_attributed(Denied(),'owner/repo','merge','6',{'sha':'a'*40})

    def test_merge_rejects_role_and_unhandled_flags_and_keeps_custom_body_history(self):
        first=actor()
        class Client:
            def request(self,path):
                if '/commits' in path:return []
                return {'head':{'sha':'a'*40},'commits':0,'body':identity.annotate('Old description',first,'pr:create')}
        args=['pr','merge','6','--squash','--match-head-commit','a'*40,'--body','Actual merge summary']
        with self.assertRaisesRegex(ValueError,'reviewer'):identity.github_arguments(args,actor(),Client(),'owner/repo')
        reviewer=actor('reviewer','delivery')
        with self.assertRaisesRegex(ValueError,'unsupported'):identity.github_arguments(args+['--delete-branch'],reviewer,Client(),'owner/repo')
        request,_=identity.github_arguments(args,reviewer,Client(),'owner/repo')
        body=request[2]['commit_message'];self.assertIn('Actual merge summary',body)
        self.assertEqual(len(identity.split(body)[1]),2)

    def test_remote_fetch_fails_closed_and_does_not_trust_local_tracking_ref(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,stdout='a'*40+'\trefs/heads/main\n')
        self.assertEqual(runner.fetch_published_base(Path('.'),'main',{},run),'a'*40)
        self.assertIn('ls-remote',calls[0]);self.assertIn('fetch',calls[1]);self.assertEqual(calls[1][-1],'a'*40)
        for output in ('bad\trefs/heads/main\n','a'*40+'\trefs/heads/other\n'):
            with self.assertRaises(ValueError):runner.fetch_published_base(Path('.'),'main',{},lambda *a,**k:subprocess.CompletedProcess(a,0,stdout=output))
        with self.assertRaisesRegex(ValueError,'cannot read'):runner.fetch_published_base(Path('.'),'main',{},lambda *a,**k:subprocess.CompletedProcess(a,1,stdout=''))
        self.assertIsNone(runner.fetch_published_base(Path('.'),'main',{},lambda *a,**k:subprocess.CompletedProcess(a,0,stdout='')))
