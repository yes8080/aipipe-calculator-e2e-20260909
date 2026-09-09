"""Read-only task handoff status; GitHub remains the ledger."""
from datetime import datetime, timezone
import json
import os
import subprocess
from urllib.parse import quote
from . import compatibility, config, context, metadata
from .credentials import authenticated_env
from .github import Gh, GhError, paginate, verify_remote
from .policy import required_checks, effective

STRUCTURED_ERRORS = (ValueError, OSError, KeyError, TypeError, AttributeError)
ACCEPTABLE_CHECK_CONCLUSIONS = {'success', 'skipped', 'neutral'}
ACCEPTABLE_STATUS_STATES = {'success'}


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def clean_error(exc, category='unavailable'):
    result = {'category':category}
    if isinstance(exc, GhError):
        if exc.status in (401, 403):
            result['category'] = 'permission_denied'
        elif exc.status == 404:
            result['category'] = 'not_found'
        elif exc.status is not None or exc.code is not None:
            result['category'] = 'remote_unavailable'
        if exc.status is not None:
            result['status'] = exc.status
    return result


def unknown(value=None, error=None):
    result = {'status':'unknown'}
    if value is not None:
        result['value'] = value
    if error is not None:
        result['error'] = error
    return result


def local_checkout(root, run=subprocess.run):
    result = {'path':str(root)}
    for key, args in [('branch',['git','branch','--show-current']), ('head',['git','rev-parse','HEAD'])]:
        try:
            proc = run(args, cwd=root, text=True, capture_output=True, check=False)
            result[key] = proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None
        except OSError:
            result[key] = None
    return result


def base_result(args):
    kind = 'issue' if getattr(args, 'issue', None) else 'pr' if getattr(args, 'pr', None) else 'unknown'
    number = getattr(args, 'issue', None) or getattr(args, 'pr', None)
    return {'schema_version':1, 'observed_at':now(), 'repository':unknown(),
            'target':{'kind':kind, 'number':number}, 'offline':bool(getattr(args, 'offline', False)),
            'checkout':unknown(), 'role':{'requested':getattr(args, 'role', None), 'status':'unknown'},
            'issue':unknown(), 'pr':unknown(), 'stage':unknown(), 'reviews':unknown(),
            'checks':unknown(), 'blockers':[], 'next_actions':[]}


def add_blocker(result, code, severity='failed', detail=None):
    item = {'code':code, 'severity':severity}
    if detail:
        item['detail'] = detail
    result['blockers'].append(item)
    return item


def finalize(result):
    severities = {b['severity'] for b in result['blockers']}
    if 'failed' in severities:
        result['status'] = 'failed'
    elif 'unknown' in severities:
        result['status'] = 'unknown'
    elif 'pending' in severities:
        result['status'] = 'pending'
    else:
        result['status'] = 'ready'
    if not result['next_actions']:
        result['next_actions'] = next_actions(result)
    return result


def next_actions(result):
    codes = {b['code'] for b in result['blockers']}
    actions = []
    if 'configuration' in codes or 'compatibility' in codes:
        actions.append('Fix the local aipipe configuration or upgrade the selected CLI before retrying status.')
    if 'role' in codes:
        actions.append('Refresh or correct the selected role credential; status reads only that role.')
    if 'remote' in codes or 'facts' in codes:
        actions.append('Retry status after GitHub access is available; do not infer task state from a partial read.')
    if 'ambiguous_association' in codes:
        actions.append('Resolve PR closing references so exactly one default-branch PR owns the Issue.')
    if 'pr_missing' in codes:
        if result.get('role', {}).get('requested') == 'developer':
            number = result.get('target', {}).get('number')
            actions.append('Start or continue branch aipipe/issue-'+str(number)+' and open a default-branch PR with exactly one Closes #'+str(number)+' line.')
        else:
            actions.append('Wait for Developer to submit the linked PR, or hand the task back to the develop workflow.')
    if 'draft' in codes:
        actions.append('Mark the PR ready for review after implementation is reviewable.')
    if 'cancelled' in codes:
        actions.append('Reopen or replace the closed-unmerged PR before continuing the handoff.')
    if 'head_missing' in codes or 'head_changed' in codes:
        actions.append('Rerun status and bind any later write to the newly observed head.')
    if 'merge_state' in codes:
        actions.append('Inspect GitHub mergeability and branch protection before treating the PR as ready.')
    if 'checks' in codes:
        actions.append('Wait for required checks or fix failing checks; status does not approve or merge.')
    if 'reviews' in codes:
        actions.append('Address requested changes or wait for an independent approval.')
    if 'merged_main_checks' in codes:
        actions.append('Inspect the merge commit required checks before claiming delivery complete.')
    if not actions:
        actions.append('Proceed with the appropriate develop or review workflow; writes must recheck head and rules.')
    return actions


def describe_ref(obj, key='number'):
    if not isinstance(obj, dict):
        return 'unknown'
    if obj.get('status') == 'missing':
        return 'missing'
    value = obj.get(key)
    return str(value) if value is not None else obj.get('status', 'unknown')


def output(result, as_json=False):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    target = result['target']['kind']+' #'+str(result['target'].get('number'))
    repo = result.get('repository') if isinstance(result.get('repository'), str) else result.get('repository', {}).get('value', 'unknown')
    checkout = result.get('checkout') if isinstance(result.get('checkout'), dict) else {}
    role = result.get('role', {})
    print(result.get('status', 'unknown')+': '+target+' in '+str(repo))
    print('checkout: '+str(checkout.get('branch'))+' @ '+str(checkout.get('head')))
    print('role: '+str(role.get('requested'))+' '+str(role.get('status'))+((' as '+role.get('identity')) if role.get('identity') else ''))
    print('issue: '+describe_ref(result.get('issue'))+'; pr: '+describe_ref(result.get('pr'))+'; head: '+str(result.get('head')))
    stage = result.get('stage', {}) if isinstance(result.get('stage'), dict) else {}
    print('stage: '+str(stage.get('value', stage.get('status', 'unknown')))+' from '+str(stage.get('source', 'unknown')))
    reviews = result.get('reviews', {}) if isinstance(result.get('reviews'), dict) else {}
    print('reviews: '+str(reviews.get('status', 'unknown'))+'; native: '+str(reviews.get('native_decision')))
    checks = result.get('checks', {}) if isinstance(result.get('checks'), dict) else {}
    print('checks: '+str(checks.get('status', 'unknown'))+' @ '+str(checks.get('head')))
    for item in checks.get('required', []):
        raw = item.get('conclusion') or item.get('state') or item.get('reason') or 'unobserved'
        print('- check '+item.get('context', 'unknown')+': '+item.get('status', 'unknown')+' ('+str(raw)+')')
    for blocker in result['blockers']:
        print('- '+blocker['severity']+': '+blocker['code']+((': '+blocker['detail']) if blocker.get('detail') else ''))
    for action in result['next_actions']:
        print('next: '+action)


def load_local(args, result, create=False):
    root, path = context.resolve(getattr(args, 'project', None), args.config, create=create)
    data, root = config.read_config(path) if path.is_file() else ({'schema_version':1}, root)
    runtime = compatibility.describe(root, data)
    result['cli'] = runtime
    result['checkout'] = local_checkout(root)
    if not runtime['compatible']:
        add_blocker(result, 'compatibility', 'failed')
        return root, path, data, None
    compatibility.enforce(root, data)
    repo = config.repository(data)
    result['repository'] = repo
    return root, path, data, repo


def offline_status(args, result):
    try:
        root, _, data, repo = load_local(args, result, create=True)
        result['configured_commands'] = sorted(data.get('commands', {}))
        result['role'] = {'requested':args.role, 'status':'unknown', 'detail':'offline; credential not read'}
        result['issue'] = unknown(error={'category':'offline'})
        result['pr'] = unknown(error={'category':'offline'})
        result['stage'] = unknown(error={'category':'offline'})
        result['reviews'] = unknown(error={'category':'offline'})
        result['checks'] = unknown(error={'category':'offline'})
        result['remote_access_evaluated'] = False
        add_blocker(result, 'remote', 'unknown', 'offline mode does not read GitHub')
    except STRUCTURED_ERRORS as exc:
        add_blocker(result, 'configuration', 'failed')
        result['configuration_error'] = clean_error(exc, 'configuration')
    return finalize(result)


def role_status(data, root, repo, role, registry, env):
    entry = data.get('apps', {}).get(role, {})
    for key in ('app_id', 'installation_id', 'slug', 'credential_ref'):
        if not entry.get(key):
            raise ValueError(role+': App binding incomplete')
    gh = Gh(env=authenticated_env(data, root, role, registry, env), cwd=root)
    visible = gh.request('installation/repositories?per_page=100')
    repos = visible.get('repositories', []) if isinstance(visible, dict) else []
    if not isinstance(visible, dict) or visible.get('total_count') != 1 or len(repos) != 1 or repos[0].get('full_name', '').lower() != repo.lower():
        raise ValueError(role+': token must be installation-scoped to this repository only')
    viewer = json.loads(gh.command(['api', 'graphql', '--input', '-'], {'query':'query { viewer { login } }'}))
    login = viewer.get('data', {}).get('viewer', {}).get('login')
    if login != entry['slug']+'[bot]':
        raise ValueError(role+': credential belongs to a different identity')
    return gh, login


def summarize_issue(issue):
    return {'status':'known', 'number':issue.get('number'), 'state':issue.get('state'),
            'title':issue.get('title'), 'milestone':metadata.milestone(issue),
            'labels':sorted(metadata.labels(issue))}


def summarize_pr(pr):
    if not pr:
        return {'status':'missing'}
    return {'status':'known', 'number':pr.get('number'), 'state':pr.get('state'), 'draft':bool(pr.get('draft')),
            'merged':bool(pr.get('merged') or pr.get('merged_at')), 'base':(pr.get('base') or {}).get('ref'),
            'head':((pr.get('head') or {}).get('sha')), 'merge_commit_sha':pr.get('merge_commit_sha'),
            'mergeable_state':pr.get('mergeable_state'), 'title':pr.get('title'),
            'labels':sorted(metadata.labels(pr)), 'milestone':metadata.milestone(pr)}


def native_pr_fields(client, repo, number):
    owner, name = repo.split('/')
    query = '''query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewDecision mergeStateStatus}}}'''
    data = json.loads(client.command(['api', 'graphql', '--input', '-'],
                    {'query':query, 'variables':{'owner':owner, 'name':name, 'number':int(number)}}))
    pr = data.get('data', {}).get('repository', {}).get('pullRequest') or {}
    return {'review_decision':pr.get('reviewDecision'), 'merge_state_status':pr.get('mergeStateStatus')}


def summarize_reviews(reviews, head, decision=None):
    latest = {}
    for review in sorted(reviews, key=lambda r:r.get('id', 0)):
        state = review.get('state')
        user = (review.get('user') or {}).get('login') or 'unknown'
        if state in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[user] = {'user':user, 'state':state, 'commit_id':review.get('commit_id'),
                            'current_head':review.get('commit_id') == head if review.get('commit_id') else None}
    values = list(latest.values())
    if decision == 'CHANGES_REQUESTED' or any(r['state'] == 'CHANGES_REQUESTED' and r.get('current_head') is not False for r in values):
        status = 'failed'
    elif decision == 'APPROVED':
        status = 'succeeded'
    elif decision == 'REVIEW_REQUIRED':
        status = 'pending'
    elif decision is None:
        status = 'unknown'
    else:
        status = 'pending'
    return {'status':status, 'native_decision':decision, 'latest':values}


def configured_and_visible_checks(client, repo, branch, data):
    expected = required_checks(data)
    by_context = {item['context']:dict(item) for item in expected}
    conflicts = []
    visibility = 'configured_only'
    try:
        for rule in effective(client, repo, branch):
            if rule.get('type') != 'required_status_checks':
                continue
            visibility = 'configured_and_visible_rules'
            for item in rule.get('parameters', {}).get('required_status_checks', []):
                context_name = item.get('context')
                integration_id = item.get('integration_id')
                if not context_name:
                    continue
                if context_name in by_context:
                    configured = by_context[context_name].get('integration_id')
                    configured_wild = configured in (None, -1)
                    visible_wild = integration_id in (None, -1)
                    if not configured_wild and not visible_wild and configured != integration_id:
                        conflicts.append({'context':context_name, 'configured_integration_id':configured,
                                          'visible_integration_id':integration_id})
                    elif configured_wild and not visible_wild:
                        by_context[context_name] = {'context':context_name, 'integration_id':integration_id}
                else:
                    by_context[context_name] = {'context':context_name, 'integration_id':integration_id}
    except GhError:
        visibility = 'unknown; visible rules unavailable'
    except STRUCTURED_ERRORS:
        visibility = 'unknown; visible rules malformed'
    return list(by_context.values()), conflicts, visibility


def commit_rollup(client, repo, sha):
    owner, name = repo.split('/')
    query = '''query($owner:String!,$name:String!,$expression:String!,$cursor:String){repository(owner:$owner,name:$name){object(expression:$expression){... on Commit{oid statusCheckRollup{state contexts(first:100,after:$cursor){totalCount pageInfo{hasNextPage endCursor} nodes{__typename ... on CheckRun{databaseId name status conclusion startedAt completedAt detailsUrl checkSuite{app{databaseId slug} commit{oid}}} ... on StatusContext{context state targetUrl}}}}}}}}'''
    nodes = []
    cursor = None
    seen = set()
    oid = None
    rollup_state = None
    total = None
    while True:
        data = json.loads(client.command(['api', 'graphql', '--input', '-'],
            {'query':query, 'variables':{'owner':owner, 'name':name, 'expression':sha, 'cursor':cursor}}))
        if data.get('errors'):
            raise ValueError('GitHub statusCheckRollup query failed')
        commit = data.get('data', {}).get('repository', {}).get('object')
        if not isinstance(commit, dict) or commit.get('oid') != sha:
            raise ValueError('GitHub statusCheckRollup response did not match requested commit')
        oid = commit.get('oid')
        rollup = commit.get('statusCheckRollup')
        if not isinstance(rollup, dict):
            raise ValueError('GitHub statusCheckRollup response missing for commit')
        rollup_state = rollup.get('state')
        contexts = rollup.get('contexts')
        if not isinstance(contexts, dict):
            raise ValueError('GitHub statusCheckRollup contexts missing')
        batch = contexts.get('nodes')
        if not isinstance(batch, list):
            raise ValueError('GitHub statusCheckRollup nodes missing')
        nodes.extend(batch)
        if total is None:
            total = contexts.get('totalCount')
        page = contexts.get('pageInfo') or {}
        if not page.get('hasNextPage'):
            if isinstance(total, int) and len(nodes) < total:
                raise ValueError('GitHub statusCheckRollup pagination ended before totalCount')
            return {'oid':oid, 'state':rollup_state, 'nodes':nodes}
        cursor = page.get('endCursor')
        if not cursor or cursor in seen:
            raise ValueError('incomplete statusCheckRollup pagination')
        seen.add(cursor)


def split_rollup(rollup, sha):
    runs = []
    statuses = {}
    for item in rollup['nodes']:
        typename = item.get('__typename')
        if typename == 'CheckRun':
            suite = item.get('checkSuite') or {}
            commit = suite.get('commit') or {}
            if commit.get('oid') != sha:
                raise ValueError('statusCheckRollup CheckRun belongs to a different commit')
            app = suite.get('app') or {}
            runs.append({'id':item.get('databaseId'), 'name':item.get('name'),
                         'status':str(item.get('status') or '').lower(),
                         'conclusion':str(item.get('conclusion') or '').lower() or None,
                         'app':{'id':app.get('databaseId'), 'slug':app.get('slug')},
                         'started_at':item.get('startedAt'), 'completed_at':item.get('completedAt'),
                         'details_url':item.get('detailsUrl')})
        elif typename == 'StatusContext':
            context_name = item.get('context')
            if context_name and context_name not in statuses:
                statuses[context_name] = {'context':context_name, 'state':str(item.get('state') or '').lower(),
                                          'target_url':item.get('targetUrl')}
    return runs, statuses

def evaluate_checks(client, repo, sha, data, branch=None):
    if not sha:
        return {'status':'unknown', 'head':sha, 'required':[], 'error':{'category':'missing_head'}}
    checks, conflicts, visibility = configured_and_visible_checks(client, repo, branch or data.get('default_branch', 'main'), data)
    rollup = commit_rollup(client, repo, sha)
    runs, statuses = split_rollup(rollup, sha)
    observed = []
    for conflict in conflicts:
        observed.append({'context':conflict['context'], 'status':'failed', 'reason':'conflicting_required_check_source', **conflict})
    for check in checks:
        context_name = check['context']
        integration_id = check.get('integration_id')
        matches = [r for r in runs if r.get('name') == context_name]
        exact = [r for r in matches if integration_id in (None, -1)
                 or (r.get('app') or {}).get('id') == integration_id
                 or ((r.get('check_suite') or {}).get('app') or {}).get('id') == integration_id]
        status_item = statuses.get(context_name)
        if not exact and matches:
            observed.append({'context':context_name, 'expected_integration_id':integration_id, 'status':'failed', 'reason':'wrong_source'})
            continue
        run_item = None
        run_status = None
        if exact:
            run_item = sorted(exact, key=lambda r:((r.get('id') is not None), r.get('id') or 0, r.get('started_at') or '', r.get('completed_at') or ''))[-1]
            state = run_item.get('status')
            conclusion = run_item.get('conclusion')
            if state != 'completed':
                run_status = 'pending'
            elif conclusion in ACCEPTABLE_CHECK_CONCLUSIONS:
                run_status = 'succeeded'
            else:
                run_status = 'failed'
        commit_status = None
        if status_item:
            raw_state = status_item.get('state')
            if raw_state in ACCEPTABLE_STATUS_STATES:
                commit_status = 'succeeded'
            elif raw_state in ('pending', 'expected'):
                commit_status = 'pending'
            else:
                commit_status = 'failed'
        if run_item and status_item:
            final_state = 'succeeded'
            if 'failed' in (run_status, commit_status):
                final_state = 'failed'
            elif 'pending' in (run_status, commit_status):
                final_state = 'pending'
            observed.append({'context':context_name, 'integration_id':integration_id, 'status':final_state,
                             'check_run_status':run_status, 'commit_status':commit_status,
                             'check_run_id':run_item.get('id'), 'conclusion':run_item.get('conclusion'),
                             'state':status_item.get('state'), 'head':sha})
        elif run_item:
            observed.append({'context':context_name, 'integration_id':integration_id, 'status':run_status,
                             'check_run_id':run_item.get('id'), 'conclusion':run_item.get('conclusion'), 'head':sha})
        elif status_item:
            observed.append({'context':context_name, 'integration_id':integration_id, 'status':commit_status,
                             'state':status_item.get('state'), 'head':sha, 'source':'commit_status'})
        else:
            observed.append({'context':context_name, 'expected_integration_id':integration_id,
                             'status':'failed', 'reason':'missing'})
    overall = 'succeeded'
    if visibility.startswith('unknown'):
        overall = 'unknown'
    if any(i['status'] == 'failed' for i in observed):
        overall = 'failed'
    elif any(i['status'] == 'unknown' for i in observed):
        overall = 'unknown'
    elif any(i['status'] == 'pending' for i in observed):
        overall = 'pending'
    return {'status':overall, 'head':sha, 'required':observed, 'visibility':visibility, 'rollup_state':rollup.get('state')}


def find_pr_for_issue(prs):
    active = [pr for pr in prs if pr.get('state') == 'open']
    merged = [pr for pr in prs if pr.get('merged') or pr.get('merged_at')]
    if active:
        return active[0]
    if merged:
        return sorted(merged, key=lambda pr:pr.get('number', 0))[-1]
    return prs[0] if prs else None


def issue_status(result, service, client, repo, data, number):
    try:
        facts = service.facts(number)
        issue, prs, reviews_by_pr, branch_exists = facts
        result['issue'] = summarize_issue(issue)
        pr_obj = find_pr_for_issue(prs)
        result['pr'] = summarize_pr(pr_obj)
        desired = metadata.plan(issue, prs, reviews_by_pr, branch_exists)
        key = pr_obj['number'] if pr_obj else issue['number']
        result['stage'] = {'status':'known', 'value':desired[key]['stage'], 'source':'github_facts'}
        if not pr_obj:
            add_blocker(result, 'pr_missing', 'pending', 'No default-branch PR linked to this Issue')
            return None
        return pr_obj, reviews_by_pr.get(pr_obj['number'], [])
    except GhError as exc:
        add_blocker(result, 'facts', 'unknown')
        result['stage'] = unknown(error=clean_error(exc, 'remote'))
    except ValueError:
        add_blocker(result, 'ambiguous_association', 'failed')
        result['stage'] = unknown(error={'category':'association'})
    except (OSError, KeyError, TypeError, AttributeError) as exc:
        add_blocker(result, 'facts', 'unknown')
        result['stage'] = unknown(error=clean_error(exc, 'remote'))
    return None


def pr_status(result, service, repo, number):
    try:
        pr_obj = service.get('pulls/'+str(number))
        issue_number = metadata.linked_issue(pr_obj)
        facts = service.facts(issue_number)
        issue, prs, reviews_by_pr, branch_exists = facts
        if number not in {p['number'] for p in prs}:
            raise ValueError('PR cross-reference not visible or not owned by this Issue')
        current = [p for p in prs if p['number'] == number][0]
        desired = metadata.plan(issue, prs, reviews_by_pr, branch_exists)
        result['issue'] = summarize_issue(issue)
        result['pr'] = summarize_pr(current)
        result['stage'] = {'status':'known', 'value':desired[number]['stage'], 'source':'github_facts'}
        return current, reviews_by_pr.get(number, [])
    except GhError as exc:
        add_blocker(result, 'facts', 'unknown')
        result['stage'] = unknown(error=clean_error(exc, 'remote'))
    except ValueError:
        add_blocker(result, 'ambiguous_association', 'failed')
        result['stage'] = unknown(error={'category':'association'})
    except (OSError, KeyError, TypeError, AttributeError) as exc:
        add_blocker(result, 'facts', 'unknown')
        result['stage'] = unknown(error=clean_error(exc, 'remote'))
    return None


def online_status(args, result):
    env = os.environ
    try:
        root, path, data, repo = load_local(args, result)
        if repo is None:
            return finalize(result)
    except STRUCTURED_ERRORS as exc:
        add_blocker(result, 'configuration', 'failed')
        result['configuration_error'] = clean_error(exc, 'configuration')
        return finalize(result)
    try:
        verify_remote(data, root)
        client, login = role_status(data, root, repo, args.role, args.credentials, env)
        result['role'] = {'requested':args.role, 'status':'succeeded', 'identity':login}
    except GhError as exc:
        add_blocker(result, 'role', 'failed')
        result['role'] = {'requested':args.role, 'status':'failed', 'error':clean_error(exc, 'credential')}
        return finalize(result)
    except STRUCTURED_ERRORS as exc:
        add_blocker(result, 'role', 'failed')
        result['role'] = {'requested':args.role, 'status':'failed', 'error':clean_error(exc, 'credential')}
        return finalize(result)
    service = metadata.Reconciler(client, repo)
    selected = issue_status(result, service, client, repo, data, args.issue) if args.issue else pr_status(result, service, repo, args.pr)
    if isinstance(selected, tuple):
        pr_obj, reviews = selected
    else:
        pr_obj, reviews = None, []
    if not pr_obj:
        return finalize(result)
    initial_head = ((pr_obj.get('head') or {}).get('sha'))
    result['head'] = initial_head
    result['base'] = (pr_obj.get('base') or {}).get('ref')
    if not initial_head:
        add_blocker(result, 'head_missing', 'unknown')
    if pr_obj.get('draft'):
        add_blocker(result, 'draft', 'pending')
    if pr_obj.get('state') == 'closed' and not (pr_obj.get('merged') or pr_obj.get('merged_at')):
        add_blocker(result, 'cancelled', 'failed', 'PR is closed without a merge')
    native = {}
    if pr_obj.get('state') == 'open':
        try:
            native = native_pr_fields(client, repo, pr_obj['number'])
            result['merge_state_status'] = native.get('merge_state_status')
        except GhError:
            result['merge_state_status'] = 'unknown'
            add_blocker(result, 'merge_state', 'unknown')
        except STRUCTURED_ERRORS:
            result['merge_state_status'] = 'unknown'
            add_blocker(result, 'merge_state', 'unknown')
        merge_state = native.get('merge_state_status')
        if merge_state in ('BLOCKED', 'UNKNOWN'):
            add_blocker(result, 'merge_state', 'unknown' if merge_state == 'UNKNOWN' else 'failed', merge_state)
        elif merge_state in ('DIRTY', 'BEHIND', 'DRAFT', 'UNSTABLE'):
            add_blocker(result, 'merge_state', 'pending', merge_state)
        review_summary = summarize_reviews(reviews, initial_head, native.get('review_decision'))
        result['reviews'] = review_summary
        if review_summary['status'] == 'failed':
            add_blocker(result, 'reviews', 'failed', 'changes requested')
        elif review_summary['status'] == 'pending':
            add_blocker(result, 'reviews', 'pending', 'no current approval')
        elif review_summary['status'] == 'unknown':
            add_blocker(result, 'reviews', 'unknown', 'native reviewDecision unavailable')
        try:
            check_summary = evaluate_checks(client, repo, initial_head, data, result.get('base'))
            result['checks'] = check_summary
            if check_summary['status'] != 'succeeded':
                add_blocker(result, 'checks', check_summary['status'])
        except GhError as exc:
            result['checks'] = unknown(error=clean_error(exc, 'checks'))
            add_blocker(result, 'checks', 'unknown')
        except STRUCTURED_ERRORS as exc:
            result['checks'] = unknown(error=clean_error(exc, 'checks'))
            add_blocker(result, 'checks', 'unknown')
    elif pr_obj.get('merged') or pr_obj.get('merged_at'):
        try:
            branch = client.request('repos/'+repo+'/branches/'+quote(data.get('default_branch', 'main'), safe=''))
            result['main'] = {'branch':data.get('default_branch'), 'head':((branch.get('commit') or {}).get('sha'))}
            merge_sha = pr_obj.get('merge_commit_sha')
            check_summary = evaluate_checks(client, repo, merge_sha, data, data.get('default_branch'))
            result['checks'] = check_summary
            if check_summary['status'] != 'succeeded':
                add_blocker(result, 'merged_main_checks', check_summary['status'])
        except GhError as exc:
            result['checks'] = unknown(error=clean_error(exc, 'checks'))
            add_blocker(result, 'merged_main_checks', 'unknown')
        except STRUCTURED_ERRORS as exc:
            result['checks'] = unknown(error=clean_error(exc, 'checks'))
            add_blocker(result, 'merged_main_checks', 'unknown')
    try:
        latest = service.get('pulls/'+str(pr_obj['number']))
        latest_head = ((latest.get('head') or {}).get('sha'))
        result['head_observed_at_end'] = latest_head
        if not latest_head:
            add_blocker(result, 'head_changed', 'unknown', 'final PR head readback lacked a head SHA')
        elif initial_head and latest_head != initial_head:
            add_blocker(result, 'head_changed', 'failed')
    except GhError:
        result['head_observed_at_end'] = None
        add_blocker(result, 'head_changed', 'unknown')
    except STRUCTURED_ERRORS:
        result['head_observed_at_end'] = None
        add_blocker(result, 'head_changed', 'unknown')
    return finalize(result)


def run(args):
    result = base_result(args)
    result = offline_status(args, result) if args.offline else online_status(args, result)
    output(result, args.json)
    return 0 if result['status'] == 'ready' else 1
