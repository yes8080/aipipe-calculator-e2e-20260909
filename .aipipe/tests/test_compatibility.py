import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aipipe import cli, compatibility, initialize, config, readiness, runner

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'.aipipe/project.json'
        config.save(self.file,{'schema_version':1,'compatibility':{'minimum_cli_version':'0.3.0'}})

    def test_old_cli_blocks_execution_before_credentials_or_network_but_inspect_works(self):
        with patch.object(compatibility,'__version__','0.2.9'),patch.object(runner,'authenticated_env',side_effect=AssertionError('credentials')):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['github','--project',str(self.root),'--role','developer','--','issue','list']),2)
            out=io.StringIO()
            with contextlib.redirect_stdout(out):self.assertEqual(cli.main(['inspect','--project',str(self.root)]),0)
            self.assertFalse(json.loads(out.getvalue())['cli']['compatible'])
            with patch.object(readiness,'authenticated_env',side_effect=AssertionError('credentials')):
                self.assertFalse(readiness.inspect(config.read_config(self.file)[0],self.root,None)['ready'])

    def test_resource_contract_and_project_minimum_use_stricter_version(self):
        (self.root/'.aipipe/compatibility.json').write_text('{"resource_version":"0.3.0","minimum_cli_version":"999.0.0"}')
        result=compatibility.describe(self.root,config.read_config(self.file)[0])
        self.assertEqual(result['minimum_cli_version'],'999.0.0');self.assertFalse(result['compatible'])
        self.assertIn('implementation',result);self.assertIn('entrypoint',result)

    def test_bundled_source_and_resource_drift_are_reported_without_executing_source(self):
        source=self.root/'.aipipe/src/aipipe';source.mkdir(parents=True)
        (source/'__init__.py').write_text('__version__ = "0.2.2"\nraise Exception("must not execute")')
        result=compatibility.describe(self.root,{})
        self.assertEqual(result['bundled_version'],'0.2.2');self.assertTrue(result['warnings'])

    def test_scaffold_does_not_relabel_old_custom_skills_as_new_resources(self):
        (self.root/'.aipipe/AGENTS.md').write_text('custom old entry')
        initialize.scaffold(self.root)
        self.assertEqual((self.root/'.aipipe/AGENTS.md').read_text(),'custom old entry')
        self.assertFalse((self.root/'.aipipe/compatibility.json').exists())

    def test_fresh_resources_include_contract_and_invalid_versions_are_rejected(self):
        initialize.scaffold(self.root)
        self.assertEqual(json.loads((self.root/'.aipipe/compatibility.json').read_text())['minimum_cli_version'],'0.5.3')
        with self.assertRaises(ValueError):config.validate({'schema_version':1,'compatibility':{'minimum_cli_version':'next'}})
