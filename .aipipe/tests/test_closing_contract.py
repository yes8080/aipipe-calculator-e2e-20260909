"""Cross-product acceptance checks for closing references through real entrypoints."""
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from aipipe import metadata
from test_metadata_events import EventAPI

KEYWORDS = ('close','closes','closed','fix','fixes','fixed','resolve','resolves','resolved')
REFERENCES = ('#3','test/repo#3','other/repo#3','https://github.com/test/repo/issues/3',
              'https://github.com/other/repo/issues/3','https://github.com/test/repo/pull/3')


class ClosingContractTests(unittest.TestCase):
    def run_workflow(self, module, body, event='pull_request_target', target=1):
        api = EventAPI(body=body)
        api.issue['number'] = target
        original = api.request
        def request(path, method='GET', payload=None):
            if method == 'GET' and path.endswith('/issues/'+str(target)):
                return copy.deepcopy(api.issue)
            if '/git/ref/' in path:
                raise module.GhError('api',status=404)
            return original(path,method,payload)
        api.request = request
        before = copy.deepcopy((api.issue,api.pr))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'event.json'
            path.write_text(json.dumps({'number':2,'issue':{'number':target}}))
            out = io.StringIO()
            with patch.object(module,'Gh',return_value=api), patch.dict(os.environ,{
                'GITHUB_REPOSITORY':'test/repo','GITHUB_EVENT_PATH':str(path),'GITHUB_EVENT_NAME':event}), redirect_stdout(out):
                code = module.workflow()
        self.assertEqual(code,1)
        self.assertIn('failed', out.getvalue())
        self.assertEqual(api.writes,[])
        self.assertEqual((api.issue,api.pr),before)

    def test_every_keyword_reference_and_order_rejects_mixed_closures(self):
        for keyword in KEYWORDS:
            for reference in REFERENCES:
                for separator in (' ',': ',':\n'):
                    extra='This also '+keyword.upper()+separator+reference
                    for body in ('Closes #1\n\n'+extra,extra+'\n\nCloses #1'):
                        with self.subTest(body=body):
                            self.run_workflow(metadata,body)

    def test_issue_and_sweep_paths_reject_valid_line_plus_extra_closure(self):
        for event in ('issues','schedule','workflow_dispatch'):
            for target in (1,3):
                for extra in ('This also fixes #3','This also fixes test/repo#3',
                              'This also fixes https://github.com/test/repo/issues/3'):
                    with self.subTest(event=event,target=target,extra=extra):
                        self.run_workflow(metadata,'Closes #1\n\n'+extra,event,target)
            self.run_workflow(metadata,'Closes #1\n\nThis also fixes other/repo#3',event)

    def test_lists_and_repeated_same_issue_cannot_hide_extra_closures(self):
        for body in ('Closes #1\n\nAlso fixes #1','Closes #1, #3','Closes #1 and #3',
                     'Closes #1\n\nResolves #3, resolves other/repo#4',
                     'Closes #1\n\nFixed: #3, #4','Closes #1\n\nThis fixes #3 & #4'):
            with self.subTest(body=body): self.run_workflow(metadata,body)

    def test_ordinary_mentions_and_normal_fix_prose_remain_valid(self):
        for suffix in ('Related to #3','See other/repo#3','This fixes rendering; see regression tests.',
                       'Related: https://github.com/other/repo/issues/3','This resolves the rendering bug.\nRelated #3'):
            body='Closes #1\n\n'+suffix
            self.assertEqual(metadata.linked_issue({'body':body}),1)
            self.assertFalse(metadata.closing_mentions_issue({'body':body},'test/repo',3))
        for body in ('\tCloses #1\r\n\r\nRelated #3','  CLOSES #1  \n','fixed #1'):
            self.assertEqual(metadata.linked_issue({'body':body}),1)

    def test_generated_standalone_runtime_rejects_the_same_combinations(self):
        path=Path(metadata.__file__).resolve().parents[2]/'automation/metadata.py'
        spec=importlib.util.spec_from_file_location('aipipe_test_standalone',path)
        standalone=importlib.util.module_from_spec(spec)
        with patch('sys.path',[str(path.parent),*__import__('sys').path]):
            spec.loader.exec_module(standalone)
        for keyword in KEYWORDS:
            for reference in REFERENCES:
                with self.subTest(keyword=keyword,reference=reference):
                    self.run_workflow(standalone,'Closes #1\n\nThis also '+keyword+': '+reference)

    def test_cli_and_fact_lookup_share_full_body_acceptance(self):
        from argparse import Namespace
        from aipipe import cli
        args=Namespace(action='metadata',project=None,config=None,apply=True,role='owner',identity=Path('/tmp/id'),
                       pr=2,issue=None,credentials=None)
        for extra in ('This also fixes #3','This also fixes other/repo#3'):
            api=EventAPI(body='Closes #1\n\n'+extra)
            with patch('aipipe.context.resolve',return_value=(Path('/tmp'),Path('/tmp/config'))), patch('aipipe.config.read_config',return_value=({},Path('/tmp'))), patch('aipipe.compatibility.enforce'), patch('aipipe.identity.project_repo',return_value='test/repo'), patch('aipipe.identity.load',return_value={'credential_role':'owner'}), patch('aipipe.github.verify_remote'), patch('aipipe.github.owner',return_value=api):
                with self.assertRaisesRegex(ValueError,'additional closing'):
                    cli.dispatch(args)
            self.assertFalse(api.writes)
