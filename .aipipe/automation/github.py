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


class GhError(ValueError):
    def __init__(self, operation, code=None, status=None):
        self.status = status
        self.code = code
        detail = f'HTTP {status}' if status else f'exit {code}'
        super().__init__(f'gh {operation} failed ({detail}); inspect identity, permissions and remote state; no write was retried')


class Gh:
    def __init__(self, env=None, jwt=None, cwd=None):
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

    def command(self, args, payload=None):
        try:
            result = subprocess.run(['gh', *args], cwd=self.cwd, env=self.env,
                                    input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise GhError(args[0], code='unavailable or timed out') from None
        if result.returncode:
            match = re.search(r'HTTP (\d{3})', result.stderr or '')
            raise GhError(args[0], result.returncode, int(match.group(1)) if match else None)
        return result.stdout

    def request(self, path, method='GET', payload=None):
        args = ['api', path, '--method', method, '-H', 'Cache-Control: no-cache',
                '-H', 'Accept: application/vnd.github+json']
        if self.jwt:
            # Real GitHub probe: gh's default token scheme fails for App JWTs.
            args += ['-H', 'Authorization: Bearer '+self.jwt]
        if payload is not None:
            args += ['--input', '-']
        text = self.command(args, payload)
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise GhError('api: invalid JSON response', code='unknown') from None


def owner():
    env = dict(os.environ)
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_DEBUG', 'DEBUG'):
        env.pop(key, None)
    return Gh(env=env)
