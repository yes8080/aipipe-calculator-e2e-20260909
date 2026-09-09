#!/usr/bin/env python3
"""Owner-only helper: mint one repository-scoped App token into an external 0600 file."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .github import Gh, paginate
ROOT = Path.cwd().resolve()
PERMISSIONS = {
    "developer": {"contents": "write", "pull_requests": "write", "issues": "read", "actions": "read", "checks": "read"},
    "delivery": {"contents": "write", "pull_requests": "write", "issues": "write", "actions": "read", "checks": "read"},
}


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def jwt(app_id, key, now=None):
    now = int(time.time()) if now is None else now
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, separators=(",", ":")).encode())
    data = f"{head}.{body}".encode()
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key)], input=data, capture_output=True)
    if signature.returncode:
        raise ValueError("Unable to sign JWT; check the external RSA private key and openssl installation")
    return data.decode() + "." + b64(signature.stdout)


def external(path, root=ROOT):
    path = path.expanduser().resolve()
    root = root.resolve()
    if path == root or root in path.parents:
        raise ValueError("Private keys and token output must be outside the project checkout")
    return path


def write_token(target, value):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".aipipe-token-", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value + "\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



def request_token(args, transport=None):
    client = transport if transport is not None else Gh(jwt=jwt(args.app_id, args.private_key))
    result = client.request(f'app/installations/{args.installation_id}/access_tokens', 'POST',
                            {'repositories': [args.repository], 'permissions': PERMISSIONS[args.role]})
    if not isinstance(result, dict) or not isinstance(result.get('token'), str) or not result.get('expires_at'):
        raise ValueError('GitHub did not return token and expiration; no response body is displayed')
    return result


def private_json(path, data):
    write_token(path, json.dumps(data, ensure_ascii=False, indent=2))


def register_token(config, root, role, result, registry_path, output=None):
    registry_path = external(Path(registry_path), root)
    entry = config['apps'][role]
    ref = entry.get('credential_ref')
    if not ref:
        raise ValueError('credential_ref is required before token registration')
    repo = config['repository']
    target = external(Path(output) if output else registry_path.parent / 'tokens' / repo / (role+'.token'), root)
    if target == registry_path:
        raise ValueError('token output cannot overwrite the credential registry')
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {'credentials': {}}
    if not isinstance(registry, dict) or not isinstance(registry.get('credentials'), dict):
        raise ValueError('invalid credential registry')
    write_token(target, result['token'])
    registry['credentials'][ref] = {'kind': 'token_file', 'path': str(target), 'expires_at': result['expires_at']}
    private_json(registry_path, registry)
    return target


def key_path(entry, registry_path, provided=None):
    if provided:
        return Path(provided).expanduser().resolve()
    store = Path(registry_path).expanduser().resolve().parent/'owner'
    metadata = store/'apps'/f"{entry['app_id']}.json"
    if metadata.is_file():
        record = json.loads(metadata.read_text())
        if record.get('private_key'):
            return Path(record['private_key']).expanduser().resolve()
    return store/'keys'/f"{entry['app_id']}.pem"


def save_key_reference(entry, role, account, key, store):
    path = Path(store)/'apps'/f"{entry['app_id']}.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(id=entry['app_id'], slug=entry.get('slug'), installation_id=entry.get('installation_id'),
                role=role, account=account, private_key=str(Path(key).resolve()))
    private_json(path, data)


def trust_path(config, root, role, registry_path):
    from .config import repository
    return external(Path(registry_path).expanduser().resolve().parent/'owner'/'trust'/repository(config)/(role+'.json'),root)


def expected_permissions(role):
    return dict(PERMISSIONS[role], metadata='read')


def supports_role(permissions, role):
    rank={'read':1,'write':2}
    return all(rank.get(permissions.get(k),0)>=rank[v] for k,v in expected_permissions(role).items())


def verify_app_policy(app, config, root, role, registry_path):
    entry=config['apps'][role]
    if app.get('id')!=entry['app_id']:
        raise ValueError('App identity does not match project binding')
    account=app.get('owner',{}).get('login','')
    permissions=app.get('permissions',{})
    if account.lower()==config['repository'].split('/')[0].lower() and permissions==expected_permissions(role):
        return
    path=trust_path(config,root,role,registry_path)
    if not path.is_file():
        raise ValueError('shared App requires Owner trust outside the project; use auth trust-app to inspect exact owner and permissions')
    if os.name=='posix' and path.stat().st_mode & 0o077:
        raise ValueError('Owner App trust file must be private (0600)')
    record=json.loads(path.read_text())
    wanted={'repository':config['repository'],'role':role,'app_id':entry['app_id'],
            'app_owner':account,'permissions':permissions}
    if record!=wanted or not supports_role(permissions,role):
        raise ValueError('App identity or permissions changed since Owner trust; inspect and reauthorize exact policy')


def trust(args):
    from . import config, context
    root,path=context.resolve(args.project,args.config)
    data=config.read_config(path)[0]
    from .compatibility import enforce
    enforce(root,data)
    entry=data.get('apps',{}).get(args.role,{})
    if not entry.get('app_id'):raise ValueError('bind an explicit App ID before trusting a shared App')
    key=external(key_path(entry,args.credentials,args.private_key),root)
    if os.name=='posix' and key.stat().st_mode & 0o077:raise ValueError('App key must be private (0600)')
    app=Gh(jwt=jwt(entry['app_id'],key)).request('app')
    permissions=json.loads(args.permissions_file.read_text())
    if (app.get('id')!=entry['app_id'] or app.get('owner',{}).get('login','').lower()!=args.app_owner.lower()
            or permissions!=app.get('permissions') or not supports_role(permissions,args.role)):
        raise ValueError('explicit App owner/permissions do not match the real App or cannot supply the role')
    record={'repository':data['repository'],'role':args.role,'app_id':entry['app_id'],
            'app_owner':app['owner']['login'],'permissions':permissions}
    print(json.dumps(record,ensure_ascii=False,indent=2))
    if args.apply:
        private_json(trust_path(data,root,args.role,args.credentials),record)
        print('Owner trust saved outside project. No App permissions changed and no role token was issued.')
    else:print('Preview only; use --apply to save exactly this shared App trust.')
    return 0


def bind_and_issue(config, root, role, private_key, registry_path, output=None):
    from .config import repository
    repo = repository(config)
    entry = config['apps'][role]
    key = external(Path(private_key), root)
    if not key.is_file():
        raise ValueError('external App private key does not exist')
    if os.name == 'posix' and key.stat().st_mode & 0o077:
        raise ValueError('App private key must be private (0600)')
    if output is not None and Path(output).expanduser().resolve() == key:
        raise ValueError("token output cannot overwrite App private key")
    client = Gh(jwt=jwt(entry['app_id'], key))
    app = client.request('app')
    verify_app_policy(app, config, root, role, registry_path)
    installation = client.request('repos/'+repo+'/installation')
    if installation.get('app_id') != entry['app_id']:
        raise ValueError('installation is associated with a different App')
    known = entry.get('installation_id')
    if known is not None and known != installation['id']:
        raise ValueError('installation changed; inspect and explicitly update the binding')
    entry.update(slug=app['slug'], installation_id=installation['id'])
    entry.setdefault('credential_ref', 'aipipe/'+repo+'/'+role)
    result = client.request(f"app/installations/{installation['id']}/access_tokens", 'POST',
                            {'repositories': [repo.split('/')[1]], 'permissions': PERMISSIONS[role]})
    if not isinstance(result, dict) or not result.get('token') or not result.get('expires_at'):
        raise ValueError('invalid token response; secret payload is not displayed')
    if result.get('permissions') != expected_permissions(role):
        raise ValueError('issued token permissions differ from the minimum role; token was not saved')
    env = dict(os.environ)
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
        env.pop(name, None)
    env['GH_TOKEN'] = result['token']
    visible = paginate(Gh(env=env),'installation/repositories',key='repositories')
    if [x['full_name'].lower() for x in visible] != [repo.lower()]:
        raise ValueError('issued token is not restricted to the selected repository')
    target = register_token(config, root, role, result, registry_path, output)
    print(f'{role}: App {entry["app_id"]}, installation {entry["installation_id"]}; token saved to {target}; expires {result["expires_at"]}')
    return result['expires_at']


def add_options(p):
    p.add_argument('--role', choices=PERMISSIONS, required=True)
    p.add_argument('--app-id', type=int)
    p.add_argument('--installation-id', type=int)
    p.add_argument('--private-key', type=Path)
    p.add_argument('--repository', help='repository short name; optional when project is configured')
    p.add_argument('--output', type=Path)


def issue(args):
    from .context import resolve
    from .config import read_config, save
    root, path = resolve(getattr(args, 'project', None), getattr(args, 'config', None), create=True)
    if path.exists():
        config, root = read_config(path)
        from .compatibility import enforce
        enforce(root,config)
        if config.get('repository') and config.get('apps', {}).get(args.role, {}).get('app_id'):
            entry = config['apps'][args.role]
            for name in ('app_id', 'installation_id'):
                if getattr(args, name, None) is not None and getattr(args, name) != entry.get(name):
                    raise ValueError('explicit identity differs from project configuration')
            if args.repository and args.repository != config['repository'].split('/')[1]:
                raise ValueError('repository differs from project configuration')
            registry = getattr(args, 'credentials', Path.home()/'.config/aipipe/credentials.json')
            key = key_path(entry, registry, args.private_key)
            bind_and_issue(config, root, args.role, key, registry, args.output)
            save(path, config)
            return 0
    if not all((args.app_id, args.installation_id, args.private_key, args.repository, args.output)):
        raise ValueError('configure the App first, or supply all explicit Owner token arguments')
    if args.app_id <= 0 or args.installation_id <= 0 or not re.fullmatch(r'[A-Za-z0-9_.-]+', args.repository):
        raise ValueError('positive IDs and one repository short name are required')
    args.private_key = external(args.private_key, root)
    args.output = external(args.output, root)
    if args.private_key == args.output:
        raise ValueError('token output cannot overwrite private key')
    result = request_token(args)
    write_token(args.output, result['token'])
    print(f'Token saved to {args.output}; expires {result["expires_at"]}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Owner-only App token issuance through gh')
    parser.add_argument('--project', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--credentials', type=Path, default=Path.home()/'.config/aipipe/credentials.json')
    add_options(parser)
    return issue(parser.parse_args(argv))
