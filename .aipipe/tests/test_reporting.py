import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aipipe import cli, config, reporting
from aipipe.github import GhError


class ReporterClient:
    def __init__(self, fail=None):
        self.issues = []
        self.calls = []
        self.fail = fail

    def command(self, args, payload=None):
        method = args[1]
        self.calls.append(args)
        if self.fail == method:
            raise GhError('issue', status=503)
        if method == 'list':
            return json.dumps(self.issues)
        item = {'number':26, 'state':'open',
                'title':args[args.index('--title')+1],
                'body':Path(args[args.index('--body-file')+1]).read_text()}
        self.issues.append(item)
        return 'https://github.com/yes8080/aipipe-template/issues/26\n'


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'.aipipe/project.json'
        self.data = {'schema_version':1, 'repository':'private/project',
                     'apps':{'developer':{'credential_ref':'project/developer'}},
                     'error_reporting':{'enabled':True, 'credential_ref':'central/reporter'}}
        config.save(self.path, self.data)
        self.args = SimpleNamespace(action='doctor', project=self.root, config=None,
                                    credentials=self.root.parent/'external-registry.json', offline=False)

    def event(self):
        token = reporting.begin()
        reporting.capture(GhError('private-stderr', code=1, reason='network', method='GET',
                                  endpoint='/repos/private/project/contents/private-file?token=secret'),
                          'preflight')
        events = reporting._events.get()
        reporting._events.reset(token)
        return events

    def test_off_by_default_and_explicit_off_never_read_credentials_or_network(self):
        for settings in (None, {'enabled':False}):
            data = dict(self.data)
            data.pop('error_reporting')
            if settings is not None:
                data['error_reporting'] = settings
            config.save(self.path, data)
            with patch('aipipe.reporting.authenticated_env', side_effect=AssertionError('credential read')), \
                 patch('aipipe.reporting.Gh', side_effect=AssertionError('network')):
                self.assertIsNone(reporting.report(self.args, self.event()))

    def test_dry_run_offline_and_read_only_status_never_report(self):
        for action, offline, apply in (('doctor', True, False), ('status', False, False),
                                      ('metadata', False, False), ('publish', False, False),
                                      ('run', False, False), ('inspect', False, False)):
            with self.subTest(action=action):
                args = SimpleNamespace(**dict(vars(self.args), action=action, offline=offline, apply=apply))
                with patch('aipipe.reporting.authenticated_env', side_effect=AssertionError('credentials')):
                    self.assertIsNone(reporting.report(args, self.event()))

    def test_report_is_sanitized_and_reuses_existing_open_or_closed_issue(self):
        client = ReporterClient()
        with patch('aipipe.reporting.authenticated_env', return_value={'GH_TOKEN':'report-only'}) as auth, \
             patch('aipipe.reporting.Gh', return_value=client):
            self.assertEqual(reporting.report(self.args, self.event()), 'created issue #26')
            client.issues[0]['state'] = 'closed'
            self.assertEqual(reporting.report(self.args, self.event()), 'existing issue #26')
        target = auth.call_args.args[0]
        self.assertEqual(target['repository'], 'yes8080/aipipe-template')
        self.assertEqual(target['apps']['delivery']['credential_ref'], 'central/reporter')
        self.assertEqual(sum(args[1] == 'create' for args in client.calls), 1)
        payload = json.dumps(client.issues)
        for value in ('private-stderr', 'private/project', 'private-file', 'secret', 'report-only', str(self.root)):
            self.assertNotIn(value, payload)
        self.assertIn('network', payload)
        self.assertIn('{value}', payload)
        self.assertTrue(all(args[:2] in (['issue','list'], ['issue','create']) for args in client.calls))
        self.assertFalse((self.root/'.aipipe/.runtime/error-reports').exists())
        for args in client.calls:
            if args[1] == 'create':
                self.assertFalse(Path(args[args.index('--body-file')+1]).exists())

    def test_missing_credential_or_report_failure_preserves_cli_exit_and_stdout(self):
        for failure in ('credentials', 'list', 'create'):
            with self.subTest(failure=failure):
                client = ReporterClient(fail=failure)
                def dispatch(args):
                    reporting.capture(GhError('api', status=503), 'readback')
                    print('{"primary":{"status":"unknown"}}')
                    return 2
                out, err = io.StringIO(), io.StringIO()
                with patch('aipipe.cli.dispatch', side_effect=dispatch), \
                     patch('aipipe.reporting.authenticated_env', side_effect=ValueError('private-token') if failure == 'credentials' else None, return_value={}), \
                     patch('aipipe.reporting.Gh', return_value=client), \
                     contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(['doctor', '--project', str(self.root)])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out.getvalue()), {'primary':{'status':'unknown'}})
                self.assertNotIn('private-token', err.getvalue())
                self.assertLessEqual(sum(args[1] == 'create' for args in client.calls), 1)
                self.assertIsNone(reporting._events.get())

    def test_native_listing_limit_prevents_blind_creation(self):
        client = ReporterClient()
        client.issues = [{'number':n, 'body':'unrelated'} for n in range(500)]
        with patch('aipipe.reporting.authenticated_env', return_value={}), patch('aipipe.reporting.Gh', return_value=client):
            with self.assertRaisesRegex(ValueError, 'limit'):
                reporting.report(self.args, self.event())
        self.assertEqual([args[1] for args in client.calls], ['list'])
        self.assertIn('--limit', client.calls[0])

    def test_configuration_switch_validates_consent_and_preserves_unrelated_fields(self):
        args = config.parser().parse_args(['--auto-report-errors', 'on', '--report-credential-ref', 'central/reporter'])
        updated = config.update({'schema_version':1, 'commands':{}, 'metadata':{'mode':'workflow'}}, args)
        config.validate(updated)
        self.assertTrue(updated['error_reporting']['enabled'])
        self.assertEqual(updated['compatibility']['minimum_cli_version'], '0.5.3')
        self.assertEqual(updated['metadata']['mode'], 'workflow')
        for settings in ({'enabled':'false'}, {'enabled':True}, {'enabled':True, 'credential_ref':'a token'},
                         {'enabled':False, 'repository':'other/repo'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                config.validate({'schema_version':1, 'error_reporting':settings})

    def test_internal_exception_report_does_not_upload_message_or_user_stack(self):
        client = ReporterClient()
        with patch('aipipe.cli.dispatch', side_effect=RuntimeError('private payload /users/private')), \
             patch('aipipe.reporting.authenticated_env', return_value={}), \
             patch('aipipe.reporting.Gh', return_value=client), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['doctor', '--project', str(self.root)]), 2)
        self.assertNotIn('private payload', json.dumps(client.issues))
        self.assertNotIn('/users/', json.dumps(client.issues))
        self.assertIn('RuntimeError', json.dumps(client.issues))
