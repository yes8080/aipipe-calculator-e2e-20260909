import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aipipe import cli, readiness, initialize


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data={'schema_version':1,'repository':'acme/sample','default_branch':'main',
                   'apps':{r:{'app_id':i,'installation_id':i+100,'slug':'acme-'+r,'credential_ref':r} for r,i in [('developer',10),('delivery',20)]},
                   'ci':{'required_check':'ci','integration_id':15368,'workflow_path':'.github/workflows/aipipe-product.yml'}}
        (self.root/'plan.json').write_text('{}')
        patch.object(readiness.publish,'verify_complete',return_value={}).start()
        self.calls=[];self.wrong_identity=False;self.broad=False;self.rules=initialize.quality_rules(self.data,'ci',15368)
        self.description='<!-- aipipe:batch:MVP -->\naipipe:released=false\nProduct scope'
        test=self
        class Client:
            def __init__(self,env):self.role=env['role']
            def command(self,args,payload):return json.dumps({'data':{'viewer':{'login':'wrong[bot]' if test.wrong_identity else 'acme-'+self.role+'[bot]'}}})
            def request(self,path,method='GET',payload=None):
                test.calls.append((self.role,path,method,payload))
                if path.startswith('installation/repositories'):
                    return {'total_count':2 if test.broad else 1,'repositories':[{'full_name':'acme/sample'}]}
                if path.endswith('/milestones/1'):
                    if method=='PATCH':test.description=payload['description']
                    return {'state':'open','description':test.description}
                if '/contents/' in path:return {'type':'file'}
                if path.endswith('/protection'):return None
                if '/rules/branches/' in path:
                    indices=[2] if 'aipipe%2F' in path else [0,1]
                    return [dict(r,ruleset_id=i) for i in indices for r in test.rules[i]['rules']]
                if '/rulesets?' in path:return [{'id':i,'enforcement':'active'} for i in range(len(test.rules))]
                if '/rulesets/' in path:
                    result=dict(test.rules[int(path.rsplit('/',1)[1])])
                    if self.role!='owner':result.pop('bypass_actors',None)
                    return result
                return {'default_branch':'main','allow_squash_merge':True,'delete_branch_on_merge':True}
        self.addCleanup(patch.stopall)
        patch.object(readiness,'Gh',Client).start()
        patch.object(readiness,'owner',side_effect=lambda:Client({'role':'owner'})).start()
        patch.object(readiness,'authenticated_env',side_effect=lambda data,root,role,registry,env:{'role':role}).start()
        patch.object(readiness,'verify_remote',return_value='https://github.com/acme/sample.git').start()

    def inspect(self,purpose='handoff'):
        return readiness.inspect(self.data,self.root,self.root.parent/'credentials.json',purpose)

    def test_binding_only_cannot_pass_handoff_or_release(self):
        self.data['apps']={}
        self.assertFalse(self.inspect()['ready'])
        self.assertEqual(self.calls,[])
        self.assert_release_fails_without_patch()

    def assert_release_fails_without_patch(self):
        args=cli.parser().parse_args(['release','--plan',str(self.root/'plan.json'),'--design-ref','a'*40,'--milestone','1','--apply'])
        with patch.object(readiness.context,'resolve',return_value=(self.root,self.root/'.aipipe/project.json')),patch.object(readiness.config,'read_config',return_value=(self.data,self.root)),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
            readiness.release(args)
        self.assertFalse(any(method=='PATCH' for _,_,method,_ in self.calls))

    def test_wrong_bot_and_multi_repository_token_are_rejected(self):
        self.wrong_identity=True;self.assertFalse(self.inspect()['ready'])
        self.wrong_identity=False;self.broad=True;self.assertFalse(self.inspect()['ready'])

    def test_missing_or_bypassed_quality_rules_block_release(self):
        self.rules[0]['bypass_actors']=[{'actor_id':20,'actor_type':'Integration','bypass_mode':'always'}]
        self.assert_release_fails_without_patch()

    def test_local_plan_and_publish_do_not_require_unrelated_capabilities(self):
        original=self.data;self.data={};self.assertTrue(self.inspect('plan')['ready']);self.assertEqual(self.calls,[])
        self.data=original;self.data.pop('ci');self.data['apps'].pop('developer')
        self.assertTrue(self.inspect('publish')['ready'])

    def test_developer_and_reviewer_do_not_load_opposite_role_token(self):
        for purpose,role in [('develop','developer'),('review','delivery')]:
            self.calls.clear();self.assertTrue(self.inspect(purpose)['ready'])
            self.assertEqual({x[0] for x in self.calls},{role})

    def test_full_handoff_requires_owner_visibility_without_elevating_app(self):
        with patch.object(readiness,'owner',side_effect=ValueError('Owner login unavailable')):
            self.assertFalse(self.inspect()['ready'])
            self.assertTrue(self.inspect('develop')['ready'])

    def test_empty_business_project_can_be_ready_for_development_not_claim_tests_passed(self):
        result=self.inspect();self.assertTrue(result['ready'])
        self.assertIn('not business tests',result['note'])
        self.assertEqual(result['ready_for'],'owner_handoff')
        self.assertFalse(result['business_acceptance']['evaluated'])
        self.assertEqual(result['business_acceptance']['ci_execution'],'not_checked')
        self.assertTrue(result['warnings'])
        self.assertFalse((self.root/'package.json').exists())

    def test_offline_work_has_no_credentials_no_network_and_validates_native_cwd(self):
        for purpose in ('plan','develop','review'):
            with patch.object(readiness,'authenticated_env',side_effect=AssertionError('credentials read')), patch.object(readiness,'owner',side_effect=AssertionError('network')):
                result=readiness.inspect({},self.root,None,purpose,offline=True)
                self.assertTrue(result['ready']);self.assertFalse(result['remote_access_evaluated'])
        self.assertEqual(self.calls,[])
        data={'commands':{'test':{'argv':['python3','-V'],'cwd':'missing'}}}
        self.assertFalse(readiness.inspect(data,self.root,None,'develop',offline=True)['ready'])
        with self.assertRaises(ValueError):readiness.inspect({},self.root,None,'publish',offline=True)

    def test_offline_cli_does_not_initialize_a_traditional_project(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['doctor','--project',str(self.root),'--for','develop','--offline']),0)
        self.assertEqual(json.loads(out.getvalue())['ready_for'],'local_development')
        self.assertFalse((self.root/'.aipipe').exists());self.assertEqual(self.calls,[])

    def test_release_contract_failure_is_controlled_and_never_writes(self):
        args=['release','--project',str(self.root),'--plan',str(self.root/'plan.json'),'--design-ref','a'*40,'--milestone','1','--apply']
        out=io.StringIO()
        with patch.object(readiness.context,'resolve',return_value=(self.root,self.root/'.aipipe/project.json')),patch.object(readiness.config,'read_config',return_value=(self.data,self.root)),patch.object(readiness.publish,'verify_complete',side_effect=readiness.publish.PublishError('batch differs')),contextlib.redirect_stderr(out):
            self.assertEqual(cli.main(args),2)
        self.assertIn('batch differs',out.getvalue());self.assertNotIn('Traceback',out.getvalue())
        self.assertFalse(any(method!='GET' for _,_,method,_ in self.calls))

    def test_release_preserves_scope_is_idempotent_and_requires_apply(self):
        args=cli.parser().parse_args(['release','--plan',str(self.root/'plan.json'),'--design-ref','a'*40,'--milestone','1'])
        with patch.object(readiness.context,'resolve',return_value=(self.root,self.root/'.aipipe/project.json')),patch.object(readiness.config,'read_config',return_value=(self.data,self.root)),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(readiness.release(args),0)
            self.assertIn('released=false',self.description)
            args.apply=True
            self.assertEqual(readiness.release(args),0);self.assertEqual(readiness.release(args),0)
        self.assertEqual(self.description,'<!-- aipipe:batch:MVP -->\naipipe:released=true\nProduct scope')
        self.assertEqual(sum(method=='PATCH' for _,_,method,_ in self.calls),1)

if __name__=='__main__':unittest.main()
