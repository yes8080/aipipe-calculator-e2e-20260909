"""Run against a built/installed wheel when AIPIPE_TEST_BINARY is provided."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BINARY = os.environ.get('AIPIPE_TEST_BINARY')

@unittest.skipUnless(BINARY, 'set AIPIPE_TEST_BINARY to validate the installed wheel')
class InstalledCliTests(unittest.TestCase):
    def test_installed_cli_operates_from_foreign_directory_and_keeps_projects_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            outside=Path(temp)/'caller';outside.mkdir()
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            for name in ('one project','two project'):
                root=Path(temp)/name
                result=subprocess.run([BINARY,'init','repo','--project',str(root),'--repo','local','--apply','--non-interactive'],cwd=outside,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue((root/'.aipipe/AGENTS.md').is_file())
                self.assertTrue((root/'.aipipe/templates/issue.md').is_file())
                self.assertTrue((root/'.aipipe/compatibility.json').is_file())
                self.assertFalse((root/'docs').exists())
                result=subprocess.run([BINARY,'inspect','--project',str(root)],cwd=outside,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['project'],str(root.resolve()))
                child=root/'nested';child.mkdir()
                result=subprocess.run([BINARY,'inspect'],cwd=child,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['project'],str(root.resolve()))
            result=subprocess.run([BINARY,'--version'],cwd=outside,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertRegex(result.stdout,r'aipipe \d+\.\d+\.\d+')

    def test_installed_cli_blocks_newer_project_contract_before_running_product(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.aipipe').mkdir()
            import sys
            data={'schema_version':1,'compatibility':{'minimum_cli_version':'999.0.0'},
                  'commands':{'test':{'cwd':'.','argv':[sys.executable,'-c','from pathlib import Path; Path("executed").write_text("bad")']}}}
            (root/'.aipipe/project.json').write_text(json.dumps(data))
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            result=subprocess.run([BINARY,'run','test'],cwd=root,env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((root/'executed').exists())
            result=subprocess.run([BINARY,'inspect'],cwd=root,env=env,capture_output=True,text=True)
            self.assertFalse(json.loads(result.stdout)['cli']['compatible'])


    def test_installed_cli_creates_traceable_commit_from_another_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'project';root.mkdir();caller=Path(temp)/'caller';caller.mkdir()
            def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
            git('init','-q');git('config','user.name','Human');git('config','user.email','human@example.invalid');git('config','commit.gpgsign','false')
            (root/'.aipipe').mkdir();(root/'.aipipe/project.json').write_text(json.dumps({'schema_version':1,'repository':'owner/repo'}))
            result=subprocess.run([BINARY,'identity','create','--project',str(root),'--tool','test-tool','--model','unknown','--role','developer','--credential-role','developer'],cwd=caller,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            identity=json.loads(result.stdout)['identity_file']
            (root/'product.txt').write_text('real file');git('add','product.txt')
            message=Path(temp)/'message.md';message.write_text('feat: installed attribution')
            result=subprocess.run([BINARY,'commit','--project',str(root),'--identity',identity,'--issue','1','--message-file',str(message)],cwd=caller,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(git('log','-1','--format=%an'),'test-tool / unknown')
            self.assertIn('Aipipe-Issue: owner/repo#1',git('log','-1','--format=%B'))
            self.assertEqual(git('config','user.name'),'Human')

    def test_installed_status_outputs_structured_json_before_credentials(self):
        with tempfile.TemporaryDirectory(prefix='aipipe installed status ') as temp:
            root=Path(temp)/'project with spaces';(root/'.aipipe').mkdir(parents=True)
            (root/'.aipipe/project.json').write_text('[]')
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            result=subprocess.run([BINARY,'status','--project',str(root),'--issue','1','--role','developer','--json'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(result.stderr,'')
            payload=json.loads(result.stdout)
            self.assertEqual(payload['status'],'failed')
            self.assertEqual(payload['blockers'][0]['code'],'configuration')
            ok=subprocess.run([BINARY,'status','--project',str(root),'--issue','1','--role','developer','--help'],env=env,capture_output=True,text=True)
            self.assertEqual(ok.returncode,0,ok.stderr)
            self.assertIn('--offline',ok.stdout)

    def test_installed_metadata_initialization_is_independent_and_has_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'existing';root.mkdir()
            (root/'.aipipe').mkdir()
            (root/'.aipipe/project.json').write_text('{"schema_version":1}')
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            result=subprocess.run([BINARY,'init','metadata','--project',str(root),'--apply','--non-interactive'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((root/'docs').exists())
            self.assertTrue((root/'.github/workflows/aipipe-metadata.yml').is_file())
            # Import generated runtime without the installed package or a project build.
            import sys
            result=subprocess.run([sys.executable,'-I','-c','import sys; sys.path.insert(0,sys.argv[1]); import metadata; assert metadata.linked_issue({"body":"Closes #7"}) == 7',str(root/'.aipipe/automation')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_installed_merge_405_is_failed_with_one_write_and_safe_diagnostics(self):
        import sys
        with tempfile.TemporaryDirectory(prefix='aipipe merge rejection ') as temp:
            base = Path(temp)
            root = base/'project'
            (root/'.aipipe').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'remote', 'add', 'origin',
                            'https://github.com/owner/repo.git'], check=True)
            (root/'.aipipe/project.json').write_text(json.dumps({
                'schema_version':1, 'repository':'owner/repo',
                'apps':{'delivery':{'credential_ref':'test/delivery'}}}))
            registry = base/'credentials.json'
            registry.write_text(json.dumps({'credentials':{
                'test/delivery':{'kind':'env', 'name':'TEST_TOKEN'}}}))
            env = dict(os.environ, TEST_TOKEN='synthetic-secret')
            env.pop('PYTHONPATH', None)
            created = subprocess.run([BINARY, 'identity', 'create', '--project', str(root),
                                      '--tool', 'test', '--model', 'unknown', '--role', 'reviewer',
                                      '--credential-role', 'delivery'], env=env, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            actor = json.loads(created.stdout)['identity_file']
            log = base/'requests.jsonl'
            stub = base/'gh'
            stub.write_text('#!' + sys.executable + '\n' + '''import json, sys
from pathlib import Path
args = sys.argv[1:]
method = args[args.index('--method')+1]
with Path(__file__).with_name('requests.jsonl').open('a') as out:
    out.write(json.dumps({'method':method,'path':args[1]})+'\\n')
if method == 'PUT':
    print('gh: Pull Request is not mergeable. synthetic-secret (HTTP 405)', file=sys.stderr)
    sys.exit(1)
if '/commits?' in args[1]:
    print('[]')
else:
    print(json.dumps({'number':6,'head':{'sha':'a'*40},'commits':0,'body':'Closes #1'}))
''')
            stub.chmod(0o700)
            env['PATH'] = str(base) + os.pathsep + env.get('PATH', '')
            result = subprocess.run([BINARY, 'github', '--project', str(root),
                                     '--credentials', str(registry), '--identity', actor,
                                     '--role', 'delivery', '--result-json', '--',
                                     'pr', 'merge', '6', '--squash', '--match-head-commit', 'a'*40],
                                    cwd=base, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '')
            data = json.loads(result.stdout)
            self.assertEqual(data['primary']['status'], 'failed')
            self.assertEqual(data['primary']['error']['status'], 405)
            self.assertEqual(data['primary']['error']['method'], 'PUT')
            self.assertEqual(data['primary']['error']['reason'], 'http')
            self.assertEqual(data['metadata']['status'], 'not_run')
            self.assertNotIn('synthetic-secret', result.stdout)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(sum(call['method'] == 'PUT' for call in calls), 1)
            self.assertEqual(calls[-1]['method'], 'PUT')

if __name__=='__main__':unittest.main()
