import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from aipipe import cli, config, context, initialize, manifest, owner_auth
from aipipe.github import Gh, GhError


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'traditional project'
        self.root.mkdir()

    def project(self, root, repository='acme/one'):
        (root/'.aipipe').mkdir(parents=True, exist_ok=True)
        (root/'.git').mkdir(exist_ok=True)
        path=root/'.aipipe/project.json'
        config.save(path, {'schema_version':1,'repository':repository,'commands':{}})
        return path

    def test_help_and_version_need_no_project_or_credential(self):
        for args in (['--help'], ['init','apps','--help'], ['config','set','--help'], ['auth','issue-token','--help'], ['--version']):
            r=subprocess.run([sys.executable,str(ROOT/'scripts/aipipe.py'),*args],cwd=self.root,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('aipipe',r.stdout)

    def test_current_subdirectory_selects_its_project_not_installation(self):
        path=self.project(self.root)
        child=self.root/'src/module';child.mkdir(parents=True)
        old=Path.cwd()
        try:
            os.chdir(child)
            root,found=context.resolve()
            self.assertEqual(root,self.root.resolve())
            self.assertEqual(found,path.resolve())
        finally:
            os.chdir(old)

    def test_nested_git_root_stops_search_into_outer_project(self):
        self.project(self.root)
        nested=self.root/'nested';nested.mkdir();(nested/'.git').write_text('gitdir: elsewhere')
        old=Path.cwd()
        try:
            os.chdir(nested)
            with self.assertRaises(ValueError):context.resolve()
        finally:os.chdir(old)

    def test_conflicting_project_and_config_are_rejected(self):
        first=self.project(self.root)
        other=self.base/'other';other.mkdir();self.project(other,'acme/two')
        with self.assertRaises(ValueError):context.resolve(other,first)

    def test_project_symlink_cannot_write_configuration_outside_project(self):
        outside=self.base/'outside';outside.mkdir()
        (self.root/'.aipipe').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):context.resolve(self.root,create=True)

    def test_traditional_local_initialization_does_not_create_docs_or_touch_product(self):
        product=self.root/'pom.xml';product.write_text('<project/>')
        with contextlib.redirect_stdout(io.StringIO()):
            code=cli.main(['init','repo','--project',str(self.root),'--repo','local','--apply','--non-interactive'])
        self.assertEqual(code,0)
        self.assertEqual(product.read_text(),'<project/>')
        self.assertTrue((self.root/'.aipipe/skills/aipipe-develop/SKILL.md').is_file())
        self.assertFalse((self.root/'docs').exists())
        self.assertIsNone(json.loads((self.root/'.aipipe/project.json').read_text()).get('repository'))

    def test_interactive_init_uses_answers_without_forcing_apps_or_plan(self):
        answers=iter(['repo','local','yes'])
        with patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',side_effect=lambda _:next(answers)),contextlib.redirect_stdout(io.StringIO()):
            result=cli.main(['init','--project',str(self.root)])
        self.assertEqual(result,0)
        self.assertTrue((self.root/'.aipipe/project.json').exists())
        self.assertFalse((self.root/'docs').exists())

    def test_no_apply_preview_leaves_no_local_configuration(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result=cli.main(['init','repo','--project',str(self.root),'--repo','local','--non-interactive'])
        self.assertEqual(result,0)
        self.assertFalse((self.root/'.aipipe').exists())

    def test_noninteractive_missing_repository_stops_without_hanging(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['init','repo','--project',str(self.root),'--non-interactive','--apply']),2)
        self.assertFalse((self.root/'.aipipe').exists())

    def test_both_global_argument_positions_select_same_project(self):
        self.project(self.root)
        for args in (['--project',str(self.root),'inspect'],['inspect','--project',str(self.root)]):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):self.assertEqual(cli.main(args),0)
            self.assertEqual(json.loads(out.getvalue())['repository'],'acme/one')

    def test_invalid_command_config_rejected_before_save(self):
        path=self.project(self.root);before=path.read_text()
        commands=self.base/'commands.json';commands.write_text('{"test":{"argv":[],"cwd":"."}}')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['config','set','--project',str(self.root),'--commands-file',str(commands)]),2)
        self.assertEqual(path.read_text(),before)


class GitHubAuthenticationTests(unittest.TestCase):
    def test_app_jwt_is_sent_as_bearer_and_secret_not_in_error(self):
        seen=[]
        def fake(args,**kwargs):
            seen.append((args,kwargs))
            return subprocess.CompletedProcess(args,1,'','gh: HTTP 401 secret-jwt')
        with patch('subprocess.run',side_effect=fake):
            with self.assertRaises(GhError) as failure:Gh(jwt='secret-jwt',env={}).request('app')
        self.assertIn('Authorization: Bearer secret-jwt',seen[0][0])
        self.assertNotIn('secret-jwt',str(failure.exception))
        self.assertEqual(failure.exception.status,401)
        self.assertEqual(len(seen),1)

    def test_manifest_has_required_disabled_hook_url(self):
        data=manifest.payload('developer','acme','acme-aipipe-developer','https://github.com/acme/tool','http://127.0.0.1:1/callback')
        self.assertTrue(data['hook_attributes']['url'])
        self.assertFalse(data['hook_attributes']['active'])
        self.assertEqual(data['default_events'],[])
        self.assertFalse(data['request_oauth_on_install'])
        self.assertEqual(data['default_permissions']['issues'],'read')
        self.assertNotIn('workflows',data['default_permissions'])

    def test_registration_does_not_persist_unused_secrets_or_overwrite_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();store=Path(temp)/'owner'
            data={'id':17,'slug':'acme-dev','owner':{'login':'acme'},'pem':'-----BEGIN PRIVATE KEY-----\nfixture\n',
                  'permissions':dict(owner_auth.PERMISSIONS['developer'],metadata='read'),'events':[],
                  'client_secret':'must-not-persist','webhook_secret':'must-not-persist'}
            output=io.StringIO()
            with contextlib.redirect_stdout(output):record=manifest.save_registration(data,'developer','acme',root,store)
            self.assertEqual(output.getvalue(),'')
            self.assertEqual((store/'keys/17.pem').stat().st_mode&0o777,0o600)
            self.assertNotIn('must-not-persist',(store/'apps/17.json').read_text())
            with self.assertRaises(ValueError):manifest.save_registration(data,'developer','acme',root,store)
            self.assertEqual((store/'keys/17.pem').read_text(),data['pem'])

    def test_token_output_cannot_overwrite_owner_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();key=Path(temp)/'key.pem';key.write_text('private fixture');key.chmod(0o600)
            data={'repository':'acme/repo','apps':{'developer':{'app_id':17}}}
            with self.assertRaises(ValueError):owner_auth.bind_and_issue(data,root,'developer',key,Path(temp)/'credentials.json',key)
            self.assertEqual(key.read_text(),'private fixture')

    def test_equivalent_rules_are_reused_even_with_different_names(self):
        data={'default_branch':'main','apps':{'developer':{'app_id':10},'delivery':{'app_id':20}}}
        rules=initialize.quality_rules(data,'ci',15368)
        actual=json.loads(json.dumps(rules[1]));actual['name']='existing-writer'
        actual['rules'][0].pop('parameters')
        self.assertTrue(initialize.covers(actual,rules[1]))
        actual['bypass_actors'][0]['actor_id']=10
        self.assertFalse(initialize.covers(actual,rules[1]))

    def test_partial_rules_setup_resumes_without_duplicate_or_weakening(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'.aipipe/project.json'
            data={'schema_version':1,'repository':'acme/repo','default_branch':'main','apps':{'developer':{'app_id':10},'delivery':{'app_id':20}}}
            wanted=initialize.quality_rules(data,'ci',15368)
            existing=dict(wanted[0],id=1);created=[]
            class Transport:
                def command(self,args):return ''
                def request(self,endpoint,method='GET',payload=None):
                    endpoint=endpoint.split('?')[0]
                    if endpoint.endswith('/check-runs'):return {'check_runs':[{'name':'ci','app':{'id':15368}}]}
                    if endpoint.endswith('/rulesets'):
                        if method=='POST':
                            record=dict(payload,id=len(created)+2);created.append(record);return record
                        return [existing]
                    if '/rulesets/' in endpoint:
                        ident=int(endpoint.rsplit('/',1)[1])
                        return next(x for x in [existing,*created] if x['id']==ident)
                    return {'allow_squash_merge':True,'allow_auto_merge':True,'delete_branch_on_merge':True}
            args=cli.parser().parse_args(['init','checks','--rules','--check-name','ci','--check-sha','a'*40,'--apply','--non-interactive'])
            with patch.object(initialize,'owner',return_value=Transport()),patch.object(initialize,'verify_remote'),contextlib.redirect_stdout(io.StringIO()):
                initialize.init_checks(args,root,path,data)
            self.assertEqual([x['name'] for x in created],[wanted[1]['name'],wanted[2]['name']])
            self.assertEqual(json.loads(path.read_text())['ci']['required_check'],'ci')
            created.clear();existing['bypass_actors']=[{'actor_type':'Integration','actor_id':10,'bypass_mode':'always'}]
            with patch.object(initialize,'owner',return_value=Transport()),patch.object(initialize,'verify_remote'),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
                initialize.init_checks(args,root,path,data)
            self.assertEqual(created,[])

    def test_private_owner_key_reference_is_reusable_after_import(self):
        with tempfile.TemporaryDirectory() as temp:
            registry=Path(temp)/'credentials.json';key=Path(temp)/'custom.pem'
            entry={'app_id':17,'installation_id':29,'slug':'acme-developer'}
            owner_auth.save_key_reference(entry,'developer','acme',key,Path(temp)/'owner')
            self.assertEqual(owner_auth.key_path(entry,registry),key.resolve())

    def test_loopback_callback_rejects_wrong_state_and_saves_valid_registration(self):
        import html as html_module
        import re
        import threading
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse,parse_qs
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();errors=[];threads=[];seen=[]
            class Transport:
                def request(self,path,method):
                    seen.append((path,method))
                    return {'id':19,'slug':'acme-aipipe-developer','owner':{'login':'acme'},
                            'pem':'-----BEGIN PRIVATE KEY-----\nfixture\n',
                            'permissions':dict(owner_auth.PERMISSIONS['developer'],metadata='read'),'events':[]}
            def browser(url):
                def visit():
                    try:
                        form=urllib.request.urlopen(url,timeout=5).read().decode()
                        action=html_module.unescape(re.search(r'action="([^"]+)"',form).group(1))
                        state=parse_qs(urlparse(action).query)['state'][0]
                        base=url.split('/start/')[0]
                        try:
                            urllib.request.urlopen(base+'/callback?state=wrong&code=fixture',timeout=5)
                            raise AssertionError('wrong state accepted')
                        except urllib.error.HTTPError as exc:
                            assert exc.code==400
                        page=urllib.request.urlopen(base+'/callback?state='+state+'&code=fixture',timeout=5).read().decode()
                        assert 'App saved' in page and 'PRIVATE KEY' not in page
                    except Exception as exc:errors.append(exc)
                thread=threading.Thread(target=visit);threads.append(thread);thread.start()
                return True
            with patch.object(manifest,'owner',return_value=Transport()),patch.object(manifest.webbrowser,'open',side_effect=browser),contextlib.redirect_stdout(io.StringIO()):
                result=manifest.register('developer','acme','User','acme-aipipe-developer','https://github.com/acme/tool',root,Path(temp)/'owner',timeout=10)
            for thread in threads:thread.join(5)
            self.assertEqual(errors,[])
            self.assertEqual(result['id'],19)
            self.assertEqual(seen,[('app-manifests/fixture/conversions','POST')])


if __name__=='__main__':unittest.main()
