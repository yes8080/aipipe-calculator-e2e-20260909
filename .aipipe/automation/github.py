"""GitHub command construction and authenticated transport."""
import json
import os
import re
import subprocess
from urllib.parse import unquote, urlsplit, parse_qsl, urlencode

def remote_repository(url):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?", url.strip())
    return match.group(1).lower() if match else None


def verify_remote(config, root, capture=subprocess.run):
    from .config import repository
    result = capture(["git", "remote", "get-url", "origin"], cwd=root, text=True, capture_output=True)
    if result.returncode or remote_repository(result.stdout) != repository(config).lower():
        raise ValueError("origin does not match project.repository; verify the checkout before writing GitHub")
    return result.stdout.strip()


def gh_command(repo, args):
    if args and args[0] == "--":
        args = args[1:]
    if len(args) < 2 or args[0] not in {"issue", "pr", "run", "workflow"}:
        raise ValueError("github accepts gh issue/pr/run/workflow subcommands; use api for repository REST endpoints")
    if any(x in {"-R", "--repo", "--hostname"} or x.startswith(("--repo=", "--hostname=", "-R")) for x in args):
        raise ValueError("repository overrides are not accepted; use project configuration")
    if any("github.com/" in x and re.match(r"^(https?://|git@)", x) for x in args[2:3]):
        raise ValueError("use local Issue/PR numbers, not cross-repository URLs")
    return ["gh", *args, "--repo", repo]


def api_command(repo, path, method, body):
    decoded = unquote(path.split("?", 1)[0])
    if (not path or path.startswith(("/", "http:", "https:")) or "#" in path
            or decoded.startswith("/") or "\\" in decoded or "%" in decoded
            or any(part in (".", "..") for part in decoded.split("/"))):
        raise ValueError("api path must be a repository-relative REST endpoint")
    result = ["gh", "api", f"repos/{repo}/{path}", "--method", method, "-H", "Cache-Control: no-cache"]
    if body:
        result.extend(["--input", str(body)])
    return result



def paginate(client, path, key=None, max_pages=1000):
    """Read every page or fail; never interpret a truncated result as absence."""
    url=urlsplit(path)
    query=[(k,v) for k,v in parse_qsl(url.query,keep_blank_values=True) if k not in ('page','per_page')]
    items=[];seen=set()
    for page in range(1,max_pages+1):
        result=client.request(url.path+'?'+urlencode(query+[('per_page',100),('page',page)]))
        values=result.get(key) if key and isinstance(result,dict) else result if not key else None
        if not isinstance(values,list):raise ValueError('paginated GitHub response must contain a list: '+path)
        fingerprint=json.dumps(values,sort_keys=True,separators=(',',':'))
        if values and fingerprint in seen:raise ValueError('GitHub repeated a page; result is not complete: '+path)
        seen.add(fingerprint);items.extend(values)
        if len(values)<100:
            if key and isinstance(result.get('total_count'),int) and len(items)<result['total_count']:
                raise ValueError('GitHub pagination ended before total_count; inspect before proceeding: '+path)
            return items
    raise ValueError('GitHub pagination safety limit reached; result is not complete: '+path)


def diagnostic_endpoint(path):
    """Match API route positions; every parameter is opaque, even 'actions'."""
    path = path.split('?', 1)[0].split('#', 1)[0].strip('/')
    repo = 'repos/{value}/{value}'
    routes = [repo, 'app', 'graphql', 'user', 'installation/repositories',
              'app/installations', 'app/installations/{value}',
              'app/installations/{value}/access_tokens',
              'orgs/{value}/rulesets', 'orgs/{value}/rulesets/{value}',
              repo+'/installation', repo+'/rules/branches/{path}',
              repo+'/contents', repo+'/contents/{path}',
              repo+'/branches', repo+'/branches/{path}']
    for resource in ('issues', 'pulls', 'milestones', 'labels', 'rulesets'):
        routes += [repo+'/'+resource, repo+'/'+resource+'/{value}']
    for resource in ('issues', 'pulls'):
        for child in ('reviews', 'merge', 'comments', 'commits', 'labels'):
            routes += [repo+'/'+resource+'/{value}/'+child,
                       repo+'/'+resource+'/{value}/'+child+'/{path}']
    for child in ('check-runs', 'status', 'statuses'):
        routes += [repo+'/commits/{value}/'+child]
    for child in ('ref', 'refs', 'matching-refs'):
        routes += [repo+'/git/'+child+'/{path}']
    for resource in ('runs', 'jobs', 'workflows'):
        routes += [repo+'/actions/'+resource, repo+'/actions/'+resource+'/{value}']
        for child in ('jobs', 'logs', 'runs', 'dispatches'):
            routes += [repo+'/actions/'+resource+'/{value}/'+child]
    for route in routes:
        pattern = re.escape(route).replace(re.escape('{value}'), '[^/]+').replace(re.escape('{path}'), '.+')
        if re.fullmatch(pattern, path):
            return '/' + route.replace('{path}', '{value}')
    return '/{value}'


class GhError(ValueError):
    def __init__(self, operation, code=None, status=None, reason=None, method=None, endpoint=None):
        self.status = status
        self.code = code
        self.reason = reason
        self.method = method
        self.endpoint = endpoint
        detail = f'HTTP {status}' if status else f'exit {code}'
        context = f' {method} {endpoint}' if method and endpoint else ''
        kind = f'; reason={reason}' if reason else ''
        super().__init__(f'gh {operation}{context} failed ({detail}{kind}); inspect request, connectivity, identity and remote state; no write was retried')


class Gh:
    def __init__(self, env=None, jwt=None, cwd=None, timeout=60):
        self.env = dict(os.environ if env is None else env)
        for key in ('GH_DEBUG', 'DEBUG'):
            self.env.pop(key, None)
        self.env.update(GH_HOST='github.com', GH_PROMPT_DISABLED='1')
        self.jwt = jwt
        if jwt:
            for key in ('GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
                self.env.pop(key, None)
            self.env['GH_TOKEN'] = jwt
        self.cwd = cwd
        self.timeout = timeout

    def command(self, args, payload=None):
        try:
            result = subprocess.run(['gh', *args], cwd=self.cwd, env=self.env,
                                    input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise GhError(args[0], code='timed out', reason='timeout') from None
        except OSError:
            raise GhError(args[0], code='unavailable', reason='unavailable') from None
        if result.returncode:
            match = re.search(r'HTTP (\d{3})', result.stderr or '')
            status = int(match.group(1)) if match else None
            network = re.search(r'error connecting to|could not resolve host|no such host|connection refused|connection reset|TLS handshake timeout|i/o timeout',
                                result.stderr or '', re.IGNORECASE)
            reason = 'http' if status else 'network' if network else 'process'
            raise GhError(args[0], result.returncode, status, reason=reason)
        return result.stdout

    def request(self, path, method='GET', payload=None):
        args = ['api', path, '--method', method, '-H', 'Cache-Control: no-cache',
                '-H', 'Accept: application/vnd.github+json']
        if self.jwt:
            # Real GitHub probe: gh's default token scheme fails for App JWTs.
            args += ['-H', 'Authorization: Bearer '+self.jwt]
        if payload is not None:
            args += ['--input', '-']
        try:
            text = self.command(args, payload)
        except GhError as exc:
            raise GhError('api', code=exc.code, status=exc.status, reason=exc.reason,
                          method=method, endpoint=diagnostic_endpoint(path)) from None
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise GhError('api: invalid JSON response', code='unknown', reason='invalid_response',
                          method=method, endpoint=diagnostic_endpoint(path)) from None


def owner():
    env = dict(os.environ)
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_DEBUG', 'DEBUG'):
        env.pop(key, None)
    return Gh(env=env)
