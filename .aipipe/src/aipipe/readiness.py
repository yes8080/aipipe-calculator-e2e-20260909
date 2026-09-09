"""Read-only handoff checks and guarded batch release; GitHub is the ledger."""
import json
import os
from pathlib import Path
import shutil
from urllib.parse import quote
from . import context, config, publish, compatibility, identity
from string import Template
from .credentials import authenticated_env
from .github import Gh, verify_remote, owner


def outcome(data, purpose, checks, runtime=None):
    return {'cli':runtime, 'purpose': purpose, 'ready': all(item['ok'] for item in checks),
            'ready_for': {'plan':'local_planning', 'publish':'github_publishing',
                          'develop':'developer_handoff', 'review':'reviewer_handoff',
                          'handoff':'owner_handoff'}[purpose],
            'checks': checks,
            'business_acceptance': {'evaluated': False, 'ci_execution': 'not_checked',
                                    'independent_review': 'not_checked', 'test_effectiveness': 'not_checked'},
            'configured_commands': sorted(data.get('commands', {})),
            'warnings': [] if data.get('commands') else ['No native commands registered; establish them with the first slice or register existing project commands.'],
            'note':'This checks handoff prerequisites, not business tests or PR approval. Recheck on the receiving host and after token expiry.'}


def inspect(data, root, registry, purpose='handoff', env=None, offline=False):
    env = os.environ if env is None else env
    runtime=compatibility.describe(root,data)
    checks = [{'name':'cli_compatibility','ok':runtime['compatible'],'detail':runtime}]
    if not runtime['compatible']:return outcome(data,purpose,checks,runtime)
    if offline:
        if purpose not in ('plan','develop','review'):
            raise ValueError('offline mode cannot authorize publishing, release or remote handoff')
        for name in data.get('commands', {}):
            try:
                config.product_command(data, root, name)
                checks.append({'name':name, 'ok':True, 'detail':'local command configuration valid; command not executed'})
            except ValueError as exc:
                checks.append({'name':name, 'ok':False, 'detail':str(exc)})
        result = outcome(data, purpose, checks, runtime)
        result.update(ready_for={'plan':'local_planning','develop':'local_development','review':'local_review'}[purpose],
                      offline=True, remote_access_evaluated=False)
        return result
    clients = {}
    def check(name, operation):
        try:
            detail = operation()
            checks.append({'name': name, 'ok': True, 'detail': detail})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            checks.append({'name': name, 'ok': False, 'detail': str(exc)})
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    if purpose == 'plan':
        return outcome(data, purpose, checks, runtime)
    repo = data.get('repository')
    check('repository', lambda: verify_remote(data, root))
    roles = {'publish':('delivery',), 'develop':('developer',), 'review':('delivery',), 'handoff':('developer','delivery')}[purpose]
    for role in roles:
        def identity(role=role):
            entry = data.get('apps', {}).get(role, {})
            require(all(entry.get(k) for k in ('app_id','installation_id','slug','credential_ref')),
                    role+': App binding incomplete; run init apps, not only config set')
            gh = Gh(env=authenticated_env(data, root, role, registry, env))
            result = gh.request('installation/repositories?per_page=100')
            visible = result.get('repositories', [])
            require(result.get('total_count') == 1 and len(visible) == 1 and visible[0]['full_name'].lower() == repo.lower(),
                    role+': token must be installation-scoped to this repository only')
            viewer = json.loads(gh.command(['api','graphql','--input','-'], {'query':'query { viewer { login } }'}))
            login = viewer.get('data', {}).get('viewer', {}).get('login')
            require(login == entry['slug']+'[bot]', role+': credential belongs to a different identity')
            clients[role] = gh
            return login+'; repository access verified'
        check(role, identity)
    if purpose in ('develop','review','handoff'):
        def gates():
            require(all(role in clients for role in roles), 'verify the requested role credentials first')
            require(all(data.get('apps', {}).get(role, {}).get('app_id') for role in ('developer','delivery')), 'configure both App identities')
            gh = clients[roles[0]]
            remote = gh.request('repos/'+repo)
            require(remote['default_branch'] == data.get('default_branch'), 'default branch differs from configuration')
            require(remote.get('allow_squash_merge') and remote.get('delete_branch_on_merge'), 'run init checks to configure squash and branch cleanup')
            ci = data.get('ci', {})
            from .policy import required_checks
            required_checks(data)
            workflow = Path(ci.get('workflow_path') or '')
            require(workflow.parent.as_posix() == '.github/workflows' and workflow.suffix in ('.yml','.yaml'), 'configure the business workflow path')
            remote_file = gh.request('repos/'+repo+'/contents/'+workflow.as_posix()+'?ref='+quote(data['default_branch'], safe=''))
            require(isinstance(remote_file, dict) and remote_file.get('type') == 'file', 'workflow path does not resolve to a file')
            from .policy import audit
            return audit(data, owner() if purpose == 'handoff' else gh, owner_view=purpose == 'handoff')
        check('handoff_gates', gates)
    return outcome(data, purpose, checks, runtime)


def run(args):
    root, path = context.resolve(args.project, args.config, create=args.offline)
    data = config.read_config(path)[0] if path.is_file() else {'schema_version':1}
    result = inspect(data, root, args.credentials, args.purpose, offline=args.offline)
    result['cli_on_path'] = bool(shutil.which('aipipe'))
    if not result['cli_on_path']:
        result['cli_hint'] = 'Use python3 .aipipe/scripts/aipipe.py in a full checkout, or add the installed CLI to this host PATH.'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ready'] else 1


def release(args):
    root, path = context.resolve(args.project, args.config)
    data, _ = config.read_config(path)
    actor=identity.load(getattr(args,'identity',None),data['repository'],'delivery')
    if args.apply:identity.required(data,actor)
    result = inspect(data, root, args.credentials, 'handoff')
    if not result['ready']:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise ValueError('handoff is incomplete; milestone was not released')
    environment = authenticated_env(data, root, 'delivery', args.credentials, os.environ)
    gh = Gh(env=environment)
    plan = json.loads(args.plan.read_text())
    template_path = root/'.aipipe/templates/issue.md'
    if not template_path.is_file():
        template_path = context.asset('templates/issue.md')
    try:
        publish.verify_complete(plan, data['repository'], args.design_ref, Template(template_path.read_text()),
                                publish.GitHub(data['repository'], env=environment), args.milestone)
    except publish.PublishError as exc:
        raise ValueError(str(exc)) from None
    endpoint = 'repos/'+data['repository']+'/milestones/'+str(args.milestone)
    milestone = gh.request(endpoint)
    description = milestone.get('description') or ''
    if milestone.get('state') != 'open' or '<!-- aipipe:batch:' not in description:
        raise ValueError('select an open aipipe batch milestone')
    if description.count('aipipe:released=false') + description.count('aipipe:released=true') != 1:
        raise ValueError('milestone must contain exactly one release flag')
    if 'aipipe:released=true' in description:
        print('Already released; current handoff checks passed.')
        return 0
    if not args.apply:
        print('Handoff checks passed. Add --apply to release milestone '+str(args.milestone))
        return 0
    wanted = description.replace('aipipe:released=false','aipipe:released=true')
    if actor:wanted=identity.annotate(wanted,actor,'release')
    gh.request(endpoint,'PATCH',{'description':wanted})
    actual = gh.request(endpoint)
    if actual.get('description') != wanted:
        raise ValueError('release write could not be confirmed; inspect GitHub before retrying')
    print('Milestone released after handoff checks. No development tool was started.')
    return 0
