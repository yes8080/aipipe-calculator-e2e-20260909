import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aipipe import owner_auth as auth, cli, config

class SharedAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'repo';self.root.mkdir()
        self.registry=self.base/'credentials.json';self.key=self.base/'key.pem';self.key.write_text('fixture');self.key.chmod(0o600)
        self.data={'schema_version':1,'repository':'target/project','apps':{'developer':{'app_id':10,'credential_ref':'project-dev'}}}
        self.permissions=dict(auth.expected_permissions('developer'),workflows='write',administration='read')
        self.app={'id':10,'slug':'shared-dev','owner':{'login':'shared-org'},'permissions':self.permissions}
        self.calls=[];test=self
        class API:
            def request(self,path,method='GET',payload=None):
                test.calls.append((path,method,payload))
                path=path.split('?')[0]
                if path=='app':return test.app
                if path.endswith('/installation'):return {'id':20,'app_id':10}
                if path.endswith('/access_tokens'):return {'token':'fixture-token','expires_at':'2099-01-01T00:00:00Z','permissions':copy.deepcopy(test.returned_permissions)}
                if path=='installation/repositories':return {'repositories':[{'full_name':'target/project'}]}
                raise AssertionError(path)
        self.returned_permissions=auth.expected_permissions('developer')
        self.patches=[patch.object(auth,'Gh',return_value=API()),patch.object(auth,'jwt',return_value='fixture-jwt')]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def save_trust(self):
        auth.private_json(auth.trust_path(self.data,self.root,'developer',self.registry),
            {'repository':'target/project','role':'developer','app_id':10,'app_owner':'shared-org','permissions':self.permissions})

    def test_project_config_cannot_self_authorize_shared_app(self):
        self.data['apps']['developer']['trusted']=True
        with self.assertRaises(ValueError):auth.bind_and_issue(self.data,self.root,'developer',self.key,self.registry)
        self.assertFalse(any(m=='POST' for _,m,_ in self.calls));self.assertFalse(self.registry.exists())

    def test_trusted_app_only_issues_minimum_role_on_selected_repo(self):
        self.save_trust()
        with patch('builtins.print'):auth.bind_and_issue(self.data,self.root,'developer',self.key,self.registry)
        payload=next(body for _,m,body in self.calls if m=='POST')
        self.assertEqual(payload,{'repositories':['project'],'permissions':auth.PERMISSIONS['developer']})
        self.assertNotIn('workflows',payload['permissions'])
        self.assertEqual(self.registry.stat().st_mode&0o777,0o600)

    def test_permission_drift_and_broader_returned_token_are_rejected(self):
        self.save_trust();self.app['permissions']=dict(self.permissions,issues='write')
        with self.assertRaises(ValueError):auth.bind_and_issue(self.data,self.root,'developer',self.key,self.registry)
        self.assertFalse(any(m=='POST' for _,m,_ in self.calls))
        self.app['permissions']=self.permissions;self.returned_permissions['workflows']='write'
        with self.assertRaises(ValueError):auth.bind_and_issue(self.data,self.root,'developer',self.key,self.registry)
        self.assertFalse(self.registry.exists())

    def test_trust_is_preview_by_default_and_exact_repo_and_role_scoped(self):
        config.save(self.root/'.aipipe/project.json',self.data)
        file=self.base/'permissions.json';file.write_text(json.dumps(self.permissions))
        argv=['auth','trust-app','--project',str(self.root),'--credentials',str(self.registry),
              '--role','developer','--app-owner','shared-org','--private-key',str(self.key),'--permissions-file',str(file)]
        with patch('builtins.print'):self.assertEqual(cli.main(argv),0)
        self.assertFalse(auth.trust_path(self.data,self.root,'developer',self.registry).exists())
        with patch('builtins.print'):self.assertEqual(cli.main(argv+['--apply']),0)
        other=copy.deepcopy(self.data);other['repository']='target/other'
        with self.assertRaises(ValueError):auth.verify_app_policy(self.app,other,self.root,'developer',self.registry)
        self.assertFalse(any(m=='POST' for _,m,_ in self.calls))
