"""Reconcile GitHub task metadata from branches, PRs and native reviews."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
try:
    from .github import Gh, GhError, paginate
except ImportError:  # Generated standalone workflow bundle.
    from github import Gh, GhError, paginate

STAGES = {'aipipe:'+name for name in ('ready', 'active', 'review', 'changes-requested', 'blocked', 'done', 'cancelled')}
COLORS = {'ready':'d4c5f9', 'active':'1d76db', 'review':'fbca04', 'changes-requested':'d93f0b',
          'blocked':'b60205', 'done':'0e8a16', 'cancelled':'cfd3d7'}


def labels(item):
    return {x['name'] for x in item.get('labels', [])}


def milestone(item):
    value = item.get('milestone')
    return value['number'] if value else None


# One grammar is shared by acceptance and refusal, including inline/qualified references.
KEYWORD = r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b'
REFERENCE = r'(?:https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/[0-9]+\b|(?:[\w.-]+/[\w.-]+)?#[0-9]+\b)'
CLOSING = re.compile(KEYWORD+r'\s*:?\s*(?P<refs>'+REFERENCE+r'(?:\s*(?:,|\band\b|&)\s*'+REFERENCE+r')*)', re.I)
CANONICAL = re.compile(r'^[ \t]*'+KEYWORD+r'[ \t]+#([1-9][0-9]*)[ \t]*\r?$', re.I | re.M)


def closing_references(pr):
    """Collect closing references across the entire body, before accepting any one line.

    Conservative text validation, not a Markdown renderer: quoted/code examples of
    closing instructions also count. Ordinary mentions without a closing keyword do not.
    """
    result = []
    for clause in CLOSING.finditer(pr.get('body') or ''):
        for match in re.finditer(REFERENCE, clause['refs'], re.I):
            value = match[0]
            if value.lower().startswith('https://github.com/'):
                parts = value.split('/')
                repo, number = '/'.join(parts[3:5]), parts[6]
            else:
                repo, number = value.split('#')
            result.append({'repository':repo.lower() or None, 'number':int(number), 'start':clause.start()})
    return result


def linked_issue(pr):
    body = pr.get('body') or ''
    lines = list(CANONICAL.finditer(body))
    references = closing_references(pr)
    if len(lines) != 1 or len(references) != 1:
        raise ValueError('PR must contain exactly one standalone local Closes #N line and no additional closing references')
    reference = references[0]
    line = lines[0]
    keyword_start = line.start() + len(line[0]) - len(line[0].lstrip(' \t'))
    if reference['repository'] is not None or reference['number'] != int(line[1]) or reference['start'] != keyword_start:
        raise ValueError('PR closing reference must be the standalone local Closes #N line')
    return reference['number']


def closing_mentions_issue(pr, repo, number):
    """Use the same references for refusal; never silently drop a disputed task."""
    return any(ref['number'] == number and ref['repository'] in (None, repo.lower())
               for ref in closing_references(pr))


def pr_stage(pr, reviews):
    if pr.get('merged') or pr.get('merged_at'):
        return 'done'
    if pr['state'] == 'closed':
        return 'cancelled'
    if pr.get('draft'):
        return 'active'
    latest = {}
    for review in sorted(reviews, key=lambda r:r['id']):
        if review['state'] in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[review['user']['login']] = review
    # A request for changes remains work to do after new commits until a new review resolves it.
    if any(r['state'] == 'CHANGES_REQUESTED' for r in latest.values()):
        return 'changes-requested'
    return 'review'  # Approval is not delivery: CI and merge remain authoritative.


def plan(issue, prs, reviews, branch_exists):
    if 'pull_request' in issue:
        raise ValueError('linked number is a PR, not an Issue')
    active = [pr for pr in prs if pr['state'] == 'open']
    if len(active) > 1:
        raise ValueError('multiple active PRs for one Issue; resolve ownership before syncing')
    merged = [pr for pr in prs if pr.get('merged') or pr.get('merged_at')]
    if issue['state'] == 'closed':
        stage = 'done' if merged else 'cancelled'
    elif active:
        stage = pr_stage(active[0], reviews.get(active[0]['number'], []))
    else:
        stage = 'active' if branch_exists else 'ready'
    if 'aipipe:blocked' in labels(issue) and issue['state'] == 'open':
        stage = 'blocked'
    result = {issue['number']:{'stage':stage}}
    inherited = labels(issue) - STAGES
    for pr in prs:
        current_stage = pr_stage(pr, reviews.get(pr['number'], []))
        if pr['state'] == 'open' and stage == 'blocked':
            current_stage = 'blocked'
        result[pr['number']] = {'stage':current_stage, 'milestone':None, 'inherit':inherited}
    return result


class Reconciler:
    def __init__(self, client, repo):
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            raise ValueError('invalid repository')
        self.client = client
        self.base = 'repos/'+repo
        self.repo = repo
        self._repo_info = None

    def request(self, path, method='GET', payload=None):
        # Include the REST resource, never credentials or request bodies, in diagnostics.
        try:
            return self.client.request(path, method, payload)
        except GhError as exc:
            raise GhError(method+' '+path, code=exc.code, status=exc.status) from None

    def remove_label(self, path, label):
        try:
            self.request(path+'/labels/'+quote(label, safe=''), 'DELETE')
        except GhError as exc:
            if exc.status != 404:
                raise
            # Another synchronizer may have removed it after our facts snapshot.
            # A 404 alone is not proof: require a complete, successful readback.
            current = paginate(self, path+'/labels')
            if any(item['name'].casefold() == label.casefold() for item in current):
                raise
            # No write retry; reconcile() still checks all current lifecycle facts.

    def get(self, path):
        return self.request(self.base+'/'+path)

    def repository_info(self):
        if self._repo_info is None:
            self._repo_info = self.request(self.base)
        return self._repo_info

    def default_branch(self):
        return self.repository_info()['default_branch']

    def branch(self, number):
        try:
            self.get('git/ref/heads/aipipe/issue-'+str(number))
            return True
        except GhError as exc:
            if exc.status == 404:
                return False
            raise

    def facts(self, number):
        if number < 1:
            raise ValueError('Issue number must be positive')
        issue = self.get('issues/'+str(number))
        if 'pull_request' in issue:
            raise ValueError('linked number is a PR, not an Issue')
        default_branch = self.default_branch()
        # Search all PRs explicitly linked to this Issue using GitHub's closing references.
        # REST head filtering would silently miss a renamed/Owner-maintained branch.
        query = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){timelineItems(first:100,after:$cursor,itemTypes:[CROSS_REFERENCED_EVENT]){pageInfo{hasNextPage endCursor} nodes{... on CrossReferencedEvent{source{... on PullRequest{number repository{nameWithOwner}}}}}}}}}'''
        owner, name = self.repo.split('/')
        found = set(); cursor = None; seen = set()
        while True:
            data = json.loads(self.client.command(['api', 'graphql', '--input', '-'],
                {'query':query, 'variables':{'owner':owner,'name':name,'number':number,'cursor':cursor}}))
            if data.get('errors'):
                raise ValueError('GitHub Issue cross-reference query failed')
            timeline = data['data']['repository']['issue']['timelineItems']
            for node in timeline['nodes']:
                source = (node or {}).get('source', {})
                if source.get('repository', {}).get('nameWithOwner', '').lower() == self.repo.lower():
                    found.add(source['number'])
            page = timeline['pageInfo']
            if not page['hasNextPage']:
                break
            cursor = page['endCursor']
            if not cursor or cursor in seen:
                raise ValueError('incomplete cross-reference pagination')
            seen.add(cursor)
        prs = []
        for n in sorted(found):
            pr = self.get('pulls/'+str(n))
            if pr['base']['ref'] != default_branch:
                continue
            try:
                if linked_issue(pr) == number:
                    prs.append(pr)
            except ValueError as exc:
                if closing_mentions_issue(pr, self.repo, number):
                    raise ValueError('PR #'+str(n)+' has invalid or ambiguous closing directives for Issue #'+str(number)+'; resolve the PR association before retrying') from exc
                # Ordinary mentions and closing references to other tasks are unrelated.
                continue
        reviews = {pr['number']:paginate(self.client, self.base+'/pulls/'+str(pr['number'])+'/reviews')
                   for pr in prs if pr['state'] == 'open'}
        branch_exists = None if any(pr['state'] == 'open' for pr in prs) or issue['state'] == 'closed' else self.branch(number)
        return issue, prs, reviews, bool(branch_exists)

    def reconcile(self, number, apply=False, actor=None, expected_pr=None):
        facts = self.facts(number)
        issue, prs, _, _ = facts
        if expected_pr is not None and expected_pr not in {p['number'] for p in prs}:
            raise ValueError('PR cross-reference not yet visible; retry after GitHub indexes Closes #N')
        desired = plan(*facts)
        originals = {x['number']:x for x in [issue, *prs]}
        changes = []
        for n, target in desired.items():
            item = originals[n]
            add = {'aipipe:'+target['stage']} | target.get('inherit', set())
            remove = (labels(item) & STAGES) - add
            add -= labels(item)
            change = {'number':n, 'add_labels':sorted(add), 'remove_labels':sorted(remove)}
            if 'milestone' in target and milestone(item) != target['milestone']:
                change['milestone'] = target['milestone']
            if add or remove or 'milestone' in change:
                changes.append(change)
        if not apply or not changes:
            return changes
        inventory = {x['name'] for x in paginate(self.client, self.base+'/labels')}
        for change in changes:
            for label in change['add_labels']:
                if label not in inventory:
                    if label not in STAGES:
                        raise ValueError('source label disappeared; inspect before retrying')
                    self.request(self.base+'/labels', 'POST', {'name':label,
                        'color':COLORS[label.split(':')[1]], 'description':'aipipe task stage: '+label.split(':')[1]})
                    inventory.add(label)
            path = self.base+'/issues/'+str(change['number'])
            if change['add_labels']:
                self.request(path+'/labels', 'POST', {'labels':change['add_labels']})
            for label in change['remove_labels']:
                self.remove_label(path, label)
            if 'milestone' in change:
                self.request(path, 'PATCH', {'milestone':change['milestone']})
        # Re-read facts, not only the mutation response. A concurrent lifecycle change is a failure.
        remaining = self.reconcile(number, expected_pr=expected_pr)
        if remaining:
            raise ValueError('metadata changed during synchronization; inspect and rerun, no blind retry')
        if actor:
            from .identity import block
            body = '已按 GitHub 分支、PR、Review 状态同步阶段标签；里程碑只统计 Issue，PR 不重复计数。\n\n'+block(actor, 'metadata-sync')
            self.request(self.base+'/issues/'+str(number)+'/comments', 'POST', {'body':body})
        return changes


def run(args):
    from . import context, config, identity, compatibility
    from .credentials import authenticated_env
    from .github import owner, verify_remote
    root, path = context.resolve(args.project, args.config)
    data, root = config.read_config(path)
    compatibility.enforce(root, data)
    repo = identity.project_repo(root, data)
    if args.apply and args.role == 'developer':
        raise ValueError('Developer may check metadata but cannot write Issue labels; use workflow or Delivery')
    actor = identity.load(args.identity, repo, args.role)
    if args.apply:
        if not actor:
            raise ValueError('metadata writes require --identity FILE')
        identity.required(data, actor)
    verify_remote({**data, 'repository':repo}, root)
    client = owner() if args.role == 'owner' else Gh(env=authenticated_env(data, root, args.role, args.credentials, os.environ), cwd=root)
    service = Reconciler(client, repo)
    number = args.issue if args.issue else linked_issue(service.get('pulls/'+str(args.pr)))
    changes = service.reconcile(number, args.apply, actor, args.pr)
    missing_milestone = milestone(service.get('issues/'+str(number))) is None
    print(json.dumps({'issue':number, 'applied':args.apply, 'milestone_missing':missing_milestone, 'changes':changes}, ensure_ascii=False, indent=2))
    return 1 if missing_milestone or (changes and not args.apply) else 0


SCAN_OPEN_PAGES = 10
SCAN_RECENT_CLOSED_PAGES = 2
SCAN_HISTORY_CLOSED_PAGES = 10
RECENT_CLOSED_DAYS = 14


def recent_closed_since(now=None):
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=RECENT_CLOSED_DAYS)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def scan_issue_pages(service, query, max_pages, scope):
    """Collect visible tasks and report truncation as a separate failure."""
    separator = '&' if '?' in query else '?'
    targets = set()
    failures = []
    seen = set()
    for page in range(1, max_pages + 1):
        path = f"{query}{separator}per_page=100&page={page}"
        try:
            values = service.get(path)
        except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError) as exc:
            failures.append({'scan':scope, 'status':'failed', 'reason':'scan_unavailable', 'error':str(exc)})
            return targets, failures
        if not isinstance(values, list):
            failures.append({'scan':scope, 'status':'failed', 'reason':'invalid_scan_response'})
            return targets, failures
        fingerprint = json.dumps(values, sort_keys=True, separators=(',', ':'))
        if values and fingerprint in seen:
            failures.append({'scan':scope, 'status':'failed', 'reason':'scan_repeated_page'})
            return targets, failures
        seen.add(fingerprint)
        for issue in values:
            if isinstance(issue, dict) and 'pull_request' not in issue and labels(issue) & STAGES:
                targets.add(issue['number'])
        if len(values) < 100:
            return targets, failures
    failures.append({'scan':scope, 'status':'failed', 'reason':'scan_truncated', 'max_pages':max_pages})
    return targets, failures


def workflow_issue_scan(service, closed_scope='recent'):
    targets = set()
    failures = []
    found, errors = scan_issue_pages(service, 'issues?state=open', SCAN_OPEN_PAGES, 'open')
    targets.update(found); failures.extend(errors)
    if closed_scope == 'recent':
        found, errors = scan_issue_pages(service, 'issues?state=closed&sort=updated&direction=desc&since='+quote(recent_closed_since(), safe=':-TZ'),
                                         SCAN_RECENT_CLOSED_PAGES, 'recent_closed')
    elif closed_scope == 'history':
        found, errors = scan_issue_pages(service, 'issues?state=closed&sort=updated&direction=desc',
                                         SCAN_HISTORY_CLOSED_PAGES, 'history_closed')
    elif closed_scope in (None, 'none'):
        found, errors = set(), []
    else:
        found, errors = set(), [{'scan':'closed', 'status':'failed', 'reason':'invalid_closed_scope', 'value':closed_scope}]
    targets.update(found); failures.extend(errors)
    return sorted(targets), failures


def pr_event_target(service, number):
    pr = service.get('pulls/'+str(number))
    if not (pr['head']['repo'] and pr['head']['repo']['full_name'].lower() == service.repo.lower()):
        return [], [{'event':'pull_request', 'number':number, 'status':'skipped', 'reason':'cross_repository'}], None
    if pr['base']['ref'] != service.default_branch():
        return [], [{'event':'pull_request', 'number':number, 'status':'skipped', 'reason':'non_default_base'}], None
    return [linked_issue(pr)], [], number


def workflow_run_target(service, event):
    payload_run = event.get('workflow_run') or {}
    run_id = payload_run.get('id')
    if not isinstance(run_id, int) or run_id < 1:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'run_id_unavailable'}]
    run = service.get('actions/runs/'+str(run_id))
    name = run.get('name')
    if name is None:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'workflow_name_unavailable', 'run_id':run_id}]
    if name != 'aipipe review signal':
        return [], [{'event':'workflow_run', 'status':'skipped', 'reason':'unrelated_workflow', 'run_id':run_id}], None, []
    event_name = run.get('event')
    if event_name is None:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'workflow_event_unavailable', 'run_id':run_id}]
    if event_name != 'pull_request_review':
        return [], [{'event':'workflow_run', 'status':'skipped', 'reason':'unrelated_event', 'run_id':run_id}], None, []
    conclusion = run.get('conclusion')
    if conclusion is None:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'signal_run_incomplete', 'run_id':run_id}]
    if conclusion != 'success':
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'signal_run_not_successful', 'run_id':run_id}]
    repo_name = ((run.get('repository') or {}).get('full_name'))
    if repo_name is None:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'repository_unavailable', 'run_id':run_id}]
    if repo_name.lower() != service.repo.lower():
        return [], [{'event':'workflow_run', 'status':'skipped', 'reason':'cross_repository', 'run_id':run_id}], None, []
    prs = run.get('pull_requests')
    if not isinstance(prs, list) or len(prs) != 1:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'pr_association_unavailable',
                               'count':len(prs) if isinstance(prs, list) else None, 'run_id':run_id}]
    pr_info = prs[0] or {}
    number = pr_info.get('number')
    if not isinstance(number, int) or number < 1:
        return [], [], None, [{'event':'workflow_run', 'status':'unknown', 'reason':'pr_association_unavailable', 'run_id':run_id}]
    targets, skipped, expected = pr_event_target(service, number)
    return targets, skipped, expected, []


def workflow_targets(service, event, name):
    if name == 'pull_request_target':
        return (*pr_event_target(service, event['number']), [])
    if name == 'workflow_run':
        return workflow_run_target(service, event)
    if name == 'pull_request_review':
        return [], [{'event':'pull_request_review', 'status':'skipped', 'reason':'signal_only'}], None, []
    if name == 'issues':
        issue = service.get('issues/'+str(event['issue']['number']))
        return ([issue['number']] if labels(issue) & STAGES else []), [], None, []
    if name in ('create', 'delete'):
        if event.get('ref_type') != 'branch':
            return [], [{'event':name, 'status':'skipped', 'reason':'not_a_branch'}], None, []
        match = re.fullmatch(r'aipipe/issue-([1-9][0-9]*)', event.get('ref', ''))
        return ([int(match[1])] if match else []), [], None, []
    if name == 'schedule':
        targets, errors = workflow_issue_scan(service, closed_scope='recent')
        return targets, [], None, errors
    if name == 'workflow_dispatch':
        closed_scope = ((event.get('inputs') or {}).get('closed_scope') or 'recent').strip().lower()
        targets, errors = workflow_issue_scan(service, closed_scope=closed_scope)
        return targets, [], None, errors
    return [], [{'event':name, 'status':'skipped', 'reason':'unrelated_event'}], None, []


def workflow():
    """Entrypoint for trusted default-branch workflow code; no project/App secrets."""
    from pathlib import Path
    service = Reconciler(Gh(), os.environ['GITHUB_REPOSITORY'])
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    name = os.environ['GITHUB_EVENT_NAME']
    try:
        targets, skipped, expected_pr, errors = workflow_targets(service, event, name)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError) as exc:
        print(json.dumps({'event':name, 'status':'failed', 'error':str(exc)}, ensure_ascii=False))
        return 1
    failures = list(errors)
    for item in skipped:
        print(json.dumps(item, ensure_ascii=False))
    for item in errors:
        print(json.dumps(item, ensure_ascii=False))
    for number in sorted(set(targets)):
        try:
            print(json.dumps({'issue':number, 'status':'succeeded',
                              'changes':service.reconcile(number, apply=True, expected_pr=expected_pr)}, ensure_ascii=False))
        except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError) as exc:
            failure = {'issue':number, 'status':'failed', 'error':str(exc)}
            failures.append(failure)
            print(json.dumps(failure, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(workflow())
