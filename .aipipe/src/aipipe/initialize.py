"""Optional, composable initialization steps; GitHub remains the ledger."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser
from . import context, config, manifest, owner_auth
from .github import owner, Gh, GhError, remote_repository, verify_remote


def interactive(args):
    return sys.stdin.isatty() and not args.non_interactive


def ask(args, label, default=None):
    if not interactive(args):
        if default is not None:
            return default
        raise ValueError(label+' is required in non-interactive mode')
    suffix = f' [{default}]' if default is not None else ''
    value = input(label+suffix+': ').strip()
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(label+' is required')


def approve(args, description):
    print(description)
    if args.apply:
        return True
    if interactive(args):
        return ask(args, '执行这些改动? yes/no', 'no').lower() in ('y', 'yes')
    print('DRY RUN: add --apply to execute this scope.')
    return False


def scaffold(root):
    dest = root/'.aipipe'
    fresh = not (dest/'AGENTS.md').exists() and not (dest/'skills').exists()
    dest.mkdir(parents=True, exist_ok=True)
    if fresh:
        target=dest/'compatibility.json'
        if not target.exists():shutil.copyfile(context.asset('compatibility.json'), target)
    for name in ('AGENTS.md', 'SKILL.md', 'README.md', 'skills', 'templates', 'references', 'plans/batch.example.json'):
        source = context.asset(name)
        files = list(source.rglob('*')) if source.is_dir() else [source]
        for path in files:
            if not path.is_file():
                continue
            relative = Path(name)/path.relative_to(source) if source.is_dir() else Path(name)
            target = dest/relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)


def selected_repo(args, data, root):
    value = args.repo or data.get('repository')
    if not value and (root/'.git').exists():
        result = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=root, capture_output=True, text=True)
        if result.returncode == 0:
            value = remote_repository(result.stdout)
    if not value:
        value = ask(args, '仓库名称或 OWNER/REPO（仅本地配置填 local）')
    if value == 'local':
        return None
    if '/' not in value:
        value = owner().request('user')['login']+'/'+value
    config.repository({'repository': value})
    if data.get('repository') and data['repository'].lower() != value.lower():
        raise ValueError('repository binding differs; inspect and use config set --rebind explicitly')
    return value


def init_repo(args, root, path, data):
    repo = selected_repo(args, data, root)
    create = args.create
    if repo and interactive(args) and not args.create and not data.get('repository') and not (root/'.git').exists():
        create = ask(args, '仓库操作 create/bind', 'bind') == 'create'
    visibility = args.visibility or (ask(args, '仓库可见性 private/public', 'private') if create else 'private')
    if visibility not in ('private', 'public'):
        raise ValueError('visibility must be private or public')
    if create and interactive(args) and not args.source and not args.empty:
        source = ask(args, '项目来源 template/empty/source', 'template')
        if source not in ('template', 'empty', 'source'):
            raise ValueError('unknown project source')
        args.source = source == 'source'
        args.empty = source == 'empty'
    if create and not args.source and root.exists() and any(root.iterdir()) and not (root/'.git').exists():
        raise ValueError('new clone target must be empty; choose another --project or initialize existing source Git first')
    description = f'Project: {root}\nRepository: {repo or "local only"}\nOperation: {"create" if create else "bind"}; visibility for creation: {visibility}'
    if not approve(args, description):
        return data
    if repo:
        gh = owner()
        existing = None
        try:
            existing = gh.request('repos/'+repo)
        except GhError as exc:
            if exc.status != 404:
                raise
        if existing is None:
            if not create:
                raise ValueError('repository not found or not visible; creation requires --create')
            command = ['repo', 'create', repo, '--'+visibility]
            if args.source:
                if not (root/'.git').exists():
                    raise ValueError('--source requires an existing local Git repository')
                if subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=root, capture_output=True).returncode == 0:
                    raise ValueError('local source already has origin; inspect it before repository creation')
                command += ['--source', str(root), '--remote', 'origin']
                if args.push:
                    command.append('--push')
            elif not args.empty:
                command += ['--template', args.template]
            gh.command(command)
            existing = gh.request('repos/'+repo)
        if not (root/'.git').exists():
            if not root.exists() or not any(root.iterdir()):
                gh.command(['repo', 'clone', repo, str(root)])
            else:
                raise ValueError('target is non-empty and has no Git checkout; initialize its Git remote explicitly, then resume')
        verify_remote({'repository': repo}, root)
        if data.get('repository') is None:
            for role in ('developer', 'delivery'):
                entry = data.setdefault('apps', {}).setdefault(role, {})
                if not entry.get('credential_ref') or entry['credential_ref'] == 'aipipe/'+role:
                    entry['credential_ref'] = 'aipipe/'+repo+'/'+role
        data.update(repository=repo, default_branch=existing.get('default_branch'))
    scaffold(root)
    data.setdefault('schema_version', 1)
    config.save(path, data)
    print('Repository binding saved; App installation, credentials and handoff gates are separate. Run aipipe doctor --for handoff before release. No development plan was generated.')
    return data


def candidates(store, role, account):
    values = []
    for path in (store/'apps').glob('*.json'):
        value = json.loads(path.read_text())
        if value.get('role') == role and (value.get('account') == account or value.get('slug', '').startswith(account+'-aipipe-')):
            values.append(value)
    return values


def init_apps(args, root, path, data, credentials_only=False):
    repo = config.repository(data)
    verify_remote(data, root)
    account = repo.split('/')[0]
    store = owner_auth.external(Path(args.credentials).expanduser().resolve().parent/'owner', root)
    roles = [args.role] if args.role else ['developer', 'delivery']
    if (args.app_id or args.app_name or args.private_key) and not args.role:
        raise ValueError('--app-id, --app-name and --private-key require --role')
    for role in roles:
        provided_key = args.private_key
        entry = data.setdefault('apps', {}).setdefault(role, {})
        if args.app_id:
            if entry.get('app_id') not in (None, args.app_id):
                raise ValueError('App differs from saved binding; use config set to explicitly change it')
            entry['app_id'] = args.app_id
        record = None
        if not entry.get('app_id'):
            known = candidates(store, role, account)
            if len(known) == 1:
                record = known[0]
            elif len(known) > 1:
                raise ValueError('multiple saved Apps for role; select --role and --app-id')
            if record:
                entry.update(app_id=record['id'], slug=record['slug'])
        if not entry.get('credential_ref') or entry['credential_ref'] == 'aipipe/'+role:
            entry['credential_ref'] = 'aipipe/'+repo+'/'+role
        if not entry.get('app_id') and interactive(args) and not credentials_only:
            mode = ask(args, role+' App create/reuse/skip', 'create')
            if mode == 'skip':
                continue
            if mode == 'reuse':
                entry['app_id'] = int(ask(args, 'App ID'))
                provided_key = Path(ask(args, '仓库外 PEM 私钥路径'))
            elif mode != 'create':
                raise ValueError('App operation must be create, reuse or skip')
        if not approve(args, f'{role}: repository {repo}; existing App {entry.get("app_id")}; permissions {json.dumps(owner_auth.PERMISSIONS[role])}; secrets outside {root}'):
            continue
        if not entry.get('app_id'):
            if credentials_only:
                raise ValueError('configure an existing App before issuing credentials')
            account_data = owner().request('users/'+account)
            name = args.app_name or ask(args, role+' App 名称', account+'-aipipe-'+role)
            record = manifest.register(role, account, account_data['type'], name, 'https://github.com/'+repo,
                                       root, store, args.no_browser, args.timeout)
            entry.update(app_id=record['id'], slug=record['slug'])
            config.save(path, data)  # persist registration before installation can be interrupted
        key = owner_auth.key_path(entry, args.credentials, provided_key)
        try:
            owner_auth.bind_and_issue(data, root, role, key, args.credentials)
        except GhError as exc:
            if exc.status != 404 or credentials_only:
                raise
            # A 404 can also mean wrong identity: validate App before giving installation guidance.
            app = Gh(jwt=owner_auth.jwt(entry['app_id'], owner_auth.external(Path(key), root))).request('app')
            owner_auth.save_key_reference(entry, role, account, key, store)
            url = 'https://github.com/apps/'+app['slug']+'/installations/new'
            print('Install ONLY on '+repo+': '+url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            if not interactive(args):
                config.save(path, data)
                raise ValueError('complete repository installation in browser, then rerun init apps with the saved App')
            ask(args, '安装完成后按 Enter 继续', '')
            owner_auth.bind_and_issue(data, root, role, key, args.credentials)
        owner_auth.save_key_reference(entry, role, account, key, store)
        config.save(path, data)
    return data


def quality_rules(data, check, integration):
    branch = 'refs/heads/'+data['default_branch']
    base = {'target': 'branch', 'enforcement': 'active'}
    quality = dict(base, name='aipipe-main-quality', bypass_actors=[], conditions={'ref_name': {'include': [branch], 'exclude': []}},
                   rules=[{'type': 'pull_request', 'parameters': {'required_approving_review_count': 1, 'dismiss_stale_reviews_on_push': True,
                           'require_code_owner_review': False, 'require_last_push_approval': True, 'required_review_thread_resolution': False}},
                          {'type': 'non_fast_forward'}, {'type': 'deletion'}, {'type': 'required_status_checks', 'parameters': {
                           'strict_required_status_checks_policy': True, 'do_not_enforce_on_create': False,
                           'required_status_checks': [dict(i) for i in (data.get('ci',{}).get('required_checks') or [{'context': check, 'integration_id': integration}])]}}])
    def writer(name, pattern, role, mode, create=False):
        return dict(base, name=name, conditions={'ref_name': {'include': [pattern], 'exclude': []}},
                    bypass_actors=[{'actor_type': 'Integration', 'actor_id': data['apps'][role]['app_id'], 'bypass_mode': mode}],
                    rules=([{'type': 'creation'}] if create else [])+[{'type': 'update', 'parameters': {'update_allows_fetch_and_merge': False}}])
    return [quality, writer('aipipe-main-writer', branch, 'delivery', 'pull_request'),
            writer('aipipe-feature-writer', 'refs/heads/aipipe/issue-*', 'developer', 'always', True)]


def covers(actual, expected):
    def contains(got, want):
        if isinstance(want, dict):
            if not isinstance(got, dict):
                return False
            for key, value in want.items():
                candidate = got.get(key, {} if key == 'parameters' else False if key == 'update_allows_fetch_and_merge' else None)
                if key == 'required_approving_review_count' and type(candidate) is int and candidate >= value:
                    continue
                if not contains(candidate, value):
                    return False
            return True
        if isinstance(want, list):
            return isinstance(got, list) and all(any(contains(item, value) for item in got) for value in want)
        return got == want
    return (all(actual.get(k) == expected[k] for k in ('target', 'enforcement', 'conditions', 'bypass_actors'))
            and contains(actual.get('rules'), expected['rules']))


def init_checks(args, root, path, data):
    repo = config.repository(data)
    verify_remote(data, root)
    if getattr(args, 'audit', False):
        from .policy import audit
        print(json.dumps(audit(data, owner()), ensure_ascii=False, indent=2))
        return data
    if not approve(args, f'{repo}: enable auto-merge, squash and branch cleanup; '+('configure required checks and role rules' if args.rules else 'keep existing rules')):
        return data
    gh = owner()
    if args.rules:
        check = args.check_name or data.get('ci', {}).get('required_check')
        if not args.check_name and data.get('ci',{}).get('required_checks'):
            check=data['ci']['required_checks'][0]['context']
        if not check or not args.check_sha:
            raise ValueError('--rules requires a real --check-name and --check-sha to verify its source')
        import re
        if not re.fullmatch(r'[0-9a-fA-F]{40}', args.check_sha):
            raise ValueError('--check-sha must be a full commit SHA')
        config.validate(data)
        if any(not data.get('apps', {}).get(r, {}).get('app_id') for r in ('developer', 'delivery')):
            raise ValueError('both App identities must be configured before writer rules')
        from .github import paginate
        check_runs = paginate(gh,'repos/'+repo+'/commits/'+args.check_sha+'/check-runs',key='check_runs')
        from .policy import required_checks
        names = [i['context'] for i in required_checks(data)] if data.get('ci',{}).get('required_checks') else [check]
        verified = []
        for name in names:
            sources = {x.get('app',{}).get('id') for x in check_runs if x.get('name')==name}
            if len(sources)!=1 or None in sources:raise ValueError('check source missing or ambiguous: '+name)
            verified.append({'context':name,'integration_id':sources.pop()})
        if data.get('ci',{}).get('required_checks') and verified != required_checks(data):
            raise ValueError('observed check sources differ from configured required_checks')
        matches = [x for x in check_runs if x.get('name') == check]
        ids = {x.get('app', {}).get('id') for x in matches}
        if len(ids) != 1 or None in ids:
            raise ValueError('check not found or its App source is ambiguous')
        integration = ids.pop()
        rules = quality_rules(data, check, integration)
        existing = paginate(gh,'repos/'+repo+'/rulesets')
        details = []
        for item in existing:
            if item.get('enforcement') == 'disabled':continue
            source=item.get('source_type','Repository')
            if source not in ('Repository','Organization'):raise ValueError('unsupported ruleset source '+source)
            prefix='orgs/'+item['source'] if source=='Organization' else 'repos/'+repo
            details.append(gh.request(prefix+'/rulesets/'+str(item['id'])))
        missing = []
        for rule in rules:
            matches = [item for item in details if covers(item, rule)]
            if matches:
                print('Reused equivalent rule: '+matches[0]['name'])
            else:
                missing.append(rule)
        if missing and any(not any(covers(item, rule) for rule in rules) for item in details):
            raise ValueError('existing active rules are not equivalent; inspect/adopt them explicitly before adding rules')
        for rule in missing:
            endpoint = 'repos/'+repo+'/rulesets'
            actual = gh.request(endpoint, 'POST', rule)
            confirmed = gh.request(endpoint+'/'+str(actual['id']))
            if not covers(confirmed, rule):
                raise ValueError('rule write could not be confirmed')
        data.setdefault('ci', {})['required_check'] = check
        data['ci']['integration_id'] = integration
        if args.workflow_path:
            data['ci']['workflow_path'] = args.workflow_path
        config.save(path, data)
    gh.command(['repo', 'edit', repo, '--enable-squash-merge', '--enable-auto-merge', '--delete-branch-on-merge'])
    result = gh.request('repos/'+repo)
    if not all(result.get(k) for k in ('allow_squash_merge', 'allow_auto_merge', 'delete_branch_on_merge')):
        raise ValueError('repository settings were not confirmed')
    print('Repository settings verified. Workflow files and product tests are preserved.')
    return data


def run(args):
    root, path = context.resolve(args.project, args.config, create=True)
    data = config.read_config(path)[0] if path.exists() else {'schema_version': 1}
    from .compatibility import enforce
    enforce(root,data)
    component = args.component
    if component is None:
        component = ask(args, '本次初始化 repo/apps/credentials/checks/metadata/all', 'repo')
    if component not in ('repo', 'apps', 'credentials', 'checks', 'metadata', 'all'):
        raise ValueError('unknown initialization component')
    if component == 'metadata':
        if approve(args, 'Generate trusted metadata workflow and runtime; Owner must review and publish via PR.'):
            install_metadata(root)
        return 0
    if component in ('repo', 'all'):
        data = init_repo(args, root, path, data)
    if component in ('apps', 'credentials'):
        init_apps(args, root, path, data, component == 'credentials')
    elif component == 'checks':
        init_checks(args, root, path, data)
    elif component == 'all' and path.exists():
        if args.with_apps or (interactive(args) and ask(args, '接入 GitHub Apps? yes/no', 'no') == 'yes'):
            data = init_apps(args, root, path, data)
        if args.with_checks or (interactive(args) and ask(args, '配置仓库合并设置? yes/no', 'no') == 'yes'):
            init_checks(args, root, path, data)
    print('Completed only the selected initialization component(s); use aipipe doctor --for handoff to verify cross-tool handoff.')
    return 0


def add_options(p):
    p.add_argument('component', nargs='?', choices=('repo', 'apps', 'credentials', 'checks', 'metadata', 'all'))
    p.add_argument('--repo')
    p.add_argument('--create', action='store_true')
    p.add_argument('--visibility', choices=('private', 'public'))
    p.add_argument('--template', default='yes8080/aipipe-template')
    p.add_argument('--empty', action='store_true')
    p.add_argument('--source', action='store_true')
    p.add_argument('--push', action='store_true')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--non-interactive', action='store_true')
    p.add_argument('--role', choices=('developer', 'delivery'))
    p.add_argument('--app-id', type=int)
    p.add_argument('--app-name')
    p.add_argument('--private-key', type=Path)
    p.add_argument('--no-browser', action='store_true')
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--with-apps', action='store_true')
    p.add_argument('--with-checks', action='store_true')
    p.add_argument('--rules', action='store_true')
    p.add_argument('--audit', action='store_true', help='Owner read-only audit of existing rules and branch protection')
    p.add_argument('--check-name')
    p.add_argument('--check-sha')
    p.add_argument('--workflow-path')


def install_metadata(root):
    """Generate exact bundled automation code; never fetch or execute PR contents."""
    workflow = root/'.github/workflows/aipipe-metadata.yml'
    signal_workflow = root/'.github/workflows/aipipe-review-signal.yml'
    runtime = root/'.aipipe/automation'
    outputs = {workflow: context.asset('templates/aipipe-metadata.yml').read_bytes(),
               signal_workflow: context.asset('templates/aipipe-review-signal.yml').read_bytes()}
    for name in ('metadata.py', 'github.py'):
        outputs[runtime/name] = (Path(__file__).parent/name).read_bytes()
    for target in outputs:
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('metadata output escapes project')
        if target.exists() and target.read_bytes() != outputs[target]:
            raise ValueError('metadata output differs: '+str(target)+'; review/remove that generated file before regeneration')
    for target, content in outputs.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
