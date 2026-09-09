"""Opt-in, best-effort defect reports. Never upload raw command output."""
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from . import __version__, config, context
from .credentials import authenticated_env
from .github import Gh, GhError, diagnostic_endpoint

DESTINATION = 'yes8080/aipipe-template'
_events = ContextVar('aipipe_error_events', default=None)


def begin():
    return _events.set([])


def capture_result(category, phase):
    events = _events.get()
    if events is None or category not in ('invalid_success_response', 'readback_mismatch', 'head_changed'):
        return
    item = {'type':'ResultError', 'category':category,
            'phase':phase if phase in ('write', 'readback') else 'execution'}
    if item not in events and len(events) < 5:
        events.append(item)


def capture(exc, phase='execution'):
    events = _events.get()
    if events is None:
        return
    item = {'type':type(exc).__name__ if type(exc) in (ValueError, OSError, KeyError,
             TypeError, AttributeError, RuntimeError, GhError) else 'Exception'}
    item['phase'] = phase if phase in ('preflight', 'write', 'readback', 'metadata',
                                     'execution', 'internal') else 'execution'
    if isinstance(exc, GhError):
        item['type'] = 'GitHubError'
        if type(exc.status) is int and 100 <= exc.status <= 599:
            item['http_status'] = exc.status
        if exc.reason in ('http', 'network', 'timeout', 'unavailable', 'process', 'invalid_response'):
            item['reason'] = exc.reason
        if exc.method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            item['method'] = exc.method
        if exc.endpoint:
            item['endpoint'] = diagnostic_endpoint(exc.endpoint)
    # Only package module identifiers and line numbers, never source or filenames.
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        module = tb.tb_frame.f_globals.get('__name__', '')
        if module in {'aipipe.'+name for name in ('cli', 'runner', 'readiness', 'github',
                      'metadata', 'status', 'config', 'credentials', 'identity', 'publish',
                      'initialize', 'owner_auth', 'policy', 'compatibility', 'context')}:
            frames.append({'module':module, 'line':tb.tb_lineno})
        tb = tb.tb_next
    if frames:
        item['frames'] = frames[-6:]
    if item not in events and len(events) < 5:
        events.append(item)


def report(args, events):
    # Explicit offline/read-only inspection and dry-run contracts take precedence.
    if not events or getattr(args, 'offline', False) or args.action in (
            'inspect', 'config', 'auth', 'identity', 'run', 'status'):
        return None
    if args.action in ('publish', 'release', 'init', 'metadata') and not getattr(args, 'apply', False):
        return None
    try:
        root, path = context.resolve(getattr(args, 'project', None), getattr(args, 'config', None))
        data, _ = config.read_config(path)
    except (ValueError, OSError, KeyError, TypeError):
        return None  # Missing/invalid configuration cannot authorize any upload.
    settings = data.get('error_reporting', {})
    if not settings.get('enabled', False):
        return None
    # Separate explicit reference: never borrow the current project's token or Owner login.
    reporter_config = {'repository':DESTINATION, 'apps':{
        'delivery':{'credential_ref':settings['credential_ref']}},
        'execution':data.get('execution', {})}
    env = authenticated_env(reporter_config, root, 'delivery', args.credentials, os.environ)
    client = Gh(env=env, cwd=root, timeout=5)
    action = args.action if args.action in ('github', 'api', 'push', 'doctor', 'metadata',
                                          'publish', 'release', 'init', 'commit') else 'cli'
    payload = {'schema_version':1, 'aipipe_version':__version__, 'action':action, 'errors':events}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    marker = '<!-- aipipe:error-report:'+fingerprint+' -->'
    # Reuse gh's native issue listing/pagination; no local report database.
    issues = json.loads(client.command(['issue', 'list', '--repo', DESTINATION,
                                       '--state', 'all', '--limit', '500', '--json', 'number,body']))
    if not isinstance(issues, list):
        raise ValueError('report lookup not confirmed')
    for issue in issues:
        if isinstance(issue, dict) and marker in (issue.get('body') or '') and type(issue.get('number')) is int:
            return 'existing issue #'+str(issue['number'])
    if len(issues) >= 500:
        raise ValueError('report lookup limit reached; inspect before creating')
    body = (marker+'\n## 自动缺陷报告\n\n由项目显式启用 error_reporting 后提交。'
            '以下仅含固定字段、脱敏路由和 aipipe 内部栈位置，不含项目名、原始命令参数、'
            '错误消息、响应正文、环境变量或凭据。该报告是诊断线索，不代表已确认产品缺陷。'
            '\n\n```json\n'+encoded+'\n```\n')
    # gh accepts a body file, keeping multiline data out of shell interpolation.
    fd, temporary = tempfile.mkstemp(prefix='aipipe-error-', suffix='.md')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(body)
        url = client.command(['issue', 'create', '--repo', DESTINATION,
                              '--title', '[aipipe report] '+action+' '+events[0]['type']+' '+fingerprint[:12],
                              '--body-file', temporary]).strip()
    finally:
        Path(temporary).unlink(missing_ok=True)
    prefix = 'https://github.com/'+DESTINATION+'/issues/'
    if not url.startswith(prefix) or not url[len(prefix):].isdigit():
        raise ValueError('report write not confirmed')
    return 'created issue #'+url[len(prefix):]


def finish(args, token):
    events = _events.get()
    _events.reset(token)  # Report failures must not recursively report themselves.
    if args is None or not events:
        return
    try:
        result = report(args, events)
        if result:
            print('aipipe error report: '+result+' in '+DESTINATION, file=sys.stderr)
    except Exception:
        # Preserve exit code/stdout and never print reporter credentials or payload errors.
        print('aipipe error report unavailable; original result unchanged; no report write retried.',
              file=sys.stderr)
