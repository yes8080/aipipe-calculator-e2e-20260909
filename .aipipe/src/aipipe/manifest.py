"""One-shot manifest registration, using the flow verified against GitHub."""
import html
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from .github import owner
from .owner_auth import PERMISSIONS, external, private_json


def payload(role, account, name, homepage, redirect):
    if role not in PERMISSIONS or not name or len(name) > 34:
        raise ValueError('valid role and App name (1..34 characters) required')
    return {'name': name, 'url': homepage, 'description': 'aipipe '+role+' role', 'public': False,
            'hook_attributes': {'url': homepage, 'active': False}, 'default_events': [],
            'default_permissions': PERMISSIONS[role], 'request_oauth_on_install': False,
            'redirect_url': redirect}


def save_registration(data, role, account, root, store):
    if (not isinstance(data, dict) or type(data.get('id')) is not int or
        data.get('owner', {}).get('login', '').lower() != account.lower() or
        not isinstance(data.get('pem'), str) or not data['pem'].startswith('-----BEGIN ')):
        raise ValueError('unexpected App response; inspect existing registration before retrying')
    if data.get('permissions') != dict(PERMISSIONS[role], metadata='read') or data.get('events'):
        raise ValueError('registered App permissions differ; inspect the existing App')
    key = external(Path(store)/'keys'/f"{data['id']}.pem", root)
    metadata = external(Path(store)/'apps'/f"{data['id']}.json", root)
    key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if key.exists() or metadata.exists():
        raise ValueError('App already saved; reuse it instead of overwriting its key')
    fd, tmp = tempfile.mkstemp(prefix='.app-', dir=key.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(data['pem'])
        os.link(tmp, key)
    finally:
        os.unlink(tmp)
    record = {k: data.get(k) for k in ('id', 'slug', 'name', 'permissions', 'events')}
    record.update(role=role, account=account, private_key=str(key))
    private_json(metadata, record)
    return record


def register(role, account, account_type, name, homepage, root, store, no_browser=False, timeout=600):
    payload(role, account, name, homepage, 'http://127.0.0.1/callback')
    if timeout <= 0 or timeout > 3300:
        raise ValueError('manifest timeout must be between 1 and 3300 seconds')
    state = secrets.token_urlsafe(32)
    start = '/start/'+secrets.token_urlsafe(24)
    result = {}
    consumed = False
    destination = ('https://github.com/settings/apps/new' if account_type == 'User' else
                   'https://github.com/organizations/'+account+'/settings/apps/new')
    client = owner()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def page(self, message, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(message.encode())

        def do_GET(self):
            nonlocal consumed
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                return self.page('Invalid host', 400)
            parsed = urlparse(self.path)
            if parsed.path == start:
                data = payload(role, account, name, homepage, f'http://127.0.0.1:{self.server.server_port}/callback')
                return self.page('<h1>aipipe '+role+'</h1><form method="post" action="'+destination+'?state='+state+'">'
                                 '<input type="hidden" name="manifest" value="'+html.escape(json.dumps(data), quote=True)+'">'
                                 '<button type="submit">Continue to GitHub</button></form>')
            query = parse_qs(parsed.query)
            if parsed.path != '/callback' or consumed or query.get('state') != [state] or len(query.get('code', [])) != 1:
                return self.page('Invalid or consumed callback', 400)
            consumed = True
            try:
                data = client.request('app-manifests/'+query['code'][0]+'/conversions', 'POST')
                result['record'] = save_registration(data, role, account, root, store)
                self.page('<h1>App saved</h1><p>Return to the terminal to continue installation.</p>')
            except (ValueError, OSError):
                result['error'] = 'Registration may exist but local completion failed; inspect the existing App before retrying.'
                self.page(result['error'], 502)

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        server.timeout = 1
        url = f'http://127.0.0.1:{server.server_port}'+start
        print('Open on this machine to register the App: '+url, flush=True)
        if not no_browser:
            webbrowser.open(url)
        deadline = time.monotonic()+timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if 'record' not in result:
        raise ValueError(result.get('error', 'Registration timed out; inspect GitHub before another registration'))
    return result['record']
