"""Read existing GitHub protections without rewriting or weakening them."""
from urllib.parse import quote
from . import config
from .github import GhError, paginate


def required_checks(data):
    ci = data.get('ci', {})
    values = ci.get('required_checks')
    if values is None:
        values = [{'context':ci.get('required_check'), 'integration_id':ci.get('integration_id')}]
    if not isinstance(values, list) or not values:
        raise ValueError('configure ci.required_checks (or the legacy required_check and integration_id)')
    seen = set()
    for item in values:
        if (not isinstance(item, dict) or not isinstance(item.get('context'), str) or not item['context'].strip()
                or type(item.get('integration_id')) is not int or item['integration_id'] <= 0
                or item['context'] in seen):
            raise ValueError('each required check needs a unique context and positive integration_id')
        seen.add(item['context'])
    return [{'context':i['context'],'integration_id':i['integration_id']} for i in values]


def effective(gh, repo, branch):
    return paginate(gh,'repos/'+repo+'/rules/branches/'+quote(branch, safe=''))


def legacy_quality(protection):
    if not protection:
        return []
    review = protection.get('required_pull_request_reviews') or {}
    bypass = review.get('bypass_pull_request_allowances') or {}
    if (not protection.get('enforce_admins', {}).get('enabled') or any(bypass.values())):
        return []
    rules = []
    if not protection.get('allow_force_pushes', {}).get('enabled', False):rules.append({'type':'non_fast_forward'})
    if not protection.get('allow_deletions', {}).get('enabled', False):rules.append({'type':'deletion'})
    rules.append({'type':'pull_request','parameters':{
        'required_approving_review_count':review.get('required_approving_review_count',0),
        'dismiss_stale_reviews_on_push':review.get('dismiss_stale_reviews',False),
        'require_last_push_approval':review.get('require_last_push_approval',False)}})
    status = protection.get('required_status_checks') or {}
    rules.append({'type':'required_status_checks','parameters':{
        'strict_required_status_checks_policy':status.get('strict',False),
        'required_status_checks':[{'context':i.get('context'),'integration_id':i.get('app_id')}
                                  for i in status.get('checks',[])]}})
    return rules


def quality_ok(rules, checks):
    types = {r['type'] for r in rules}
    review = any(r['type']=='pull_request' and r.get('parameters',{}).get('required_approving_review_count',0)>=1
                 and r.get('parameters',{}).get('dismiss_stale_reviews_on_push')
                 and r.get('parameters',{}).get('require_last_push_approval') for r in rules)
    actual = [i for r in rules if r['type']=='required_status_checks'
              and r.get('parameters',{}).get('strict_required_status_checks_policy')
              for i in r.get('parameters',{}).get('required_status_checks',[])]
    return review and {'deletion','non_fast_forward'} <= types and all(i in actual for i in checks)


def audit(data, gh, owner_view=True):
    repo = config.repository(data); branch = data['default_branch']; checks = required_checks(data)
    main = effective(gh,repo,branch)
    feature = effective(gh,repo,'aipipe/issue-1')
    details = {}
    for rule in main+feature:
        ident=rule.get('ruleset_id')
        if ident is None:raise ValueError('effective rule has no source ruleset ID')
        if ident not in details:
            source = rule.get('ruleset_source_type','Repository')
            if source not in ('Repository','Organization'):raise ValueError('unsupported ruleset source '+source)
            endpoint = ('orgs/'+rule['ruleset_source'] if source=='Organization' else 'repos/'+repo)+'/rulesets/'+str(ident)
            details[ident] = gh.request(endpoint)
            if owner_view and 'bypass_actors' not in details[ident]:
                raise ValueError('Owner cannot inspect bypass actors for ruleset '+str(ident))
    protection = None
    if owner_view:
        try:protection=gh.request('repos/'+repo+'/branches/'+quote(branch,safe='')+'/protection')
        except GhError as exc:
            if exc.status!=404:raise
    safe = [r for r in main if not owner_view or details[r['ruleset_id']]['bypass_actors']==[]]
    safe += legacy_quality(protection)
    observed_checks=[i for r in safe if r['type']=='required_status_checks' for i in r.get('parameters',{}).get('required_status_checks',[])]
    for context in {i.get('context') for i in observed_checks}:
        sources={i.get('integration_id') for i in observed_checks if i.get('context')==context and i.get('integration_id') not in (None,-1)}
        if len(sources)>1:raise ValueError('conflicting required check sources: '+str(context))
    full_quality = quality_ok(safe,checks)
    if not full_quality:
        if owner_view:raise ValueError('quality policy lacks strict source-bound checks, stale/last-push review protection, force/delete protection, or has a bypass')
        metadata=gh.request('repos/'+repo+'/branches/'+quote(branch,safe=''))
        if not metadata.get('protected'):raise ValueError('target branch is not protected')
    def permits(rule, role, mode):
        if not owner_view:return True
        actors=details[rule['ruleset_id']]['bypass_actors']
        return any(a.get('actor_type')=='Integration' and a.get('actor_id')==data['apps'][role]['app_id']
                   and a.get('bypass_mode') in ('always',mode) for a in actors)
    def writer(rules, kind, role, mode):
        candidates=[r for r in rules if r['type']==kind]
        if not candidates:return False
        for r in candidates:
            if r.get('parameters',{}).get('update_allows_fetch_and_merge'):
                raise ValueError('ruleset '+str(r['ruleset_id'])+' allows fetch-and-merge updates')
            if not permits(r,role,mode):
                raise ValueError('ruleset '+str(r['ruleset_id'])+' blocks '+role+' '+kind)
        if not owner_view:return True
        expected={'actor_type':'Integration','actor_id':data['apps'][role]['app_id'],'bypass_mode':mode}
        return any(details[r['ruleset_id']]['bypass_actors']==[expected] for r in candidates)
    main_writer=writer(main,'update','delivery','pull_request')
    if protection:
        restrictions=protection.get('restrictions')
        if restrictions:
            app_ids=[a['id'] for a in restrictions.get('apps',[])]
            if data['apps']['delivery']['app_id'] not in app_ids:raise ValueError('legacy branch restrictions block Delivery')
            main_writer = main_writer or (protection.get('enforce_admins',{}).get('enabled') and app_ids==[data['apps']['delivery']['app_id']]
                                          and not restrictions.get('users') and not restrictions.get('teams'))
        if protection.get('lock_branch',{}).get('enabled'):raise ValueError('legacy target branch is locked')
    if not main_writer and not owner_view:
        metadata=gh.request('repos/'+repo+'/branches/'+quote(branch,safe=''))
        main_writer=bool(metadata.get('protected'))
    if any(r['type']=='deletion' for r in feature):
        raise ValueError('feature deletion policy may block post-merge branch cleanup; inspect it explicitly')
    if not main_writer:raise ValueError('missing Delivery-only main writer policy')
    if not writer(feature,'creation','developer','always') or not writer(feature,'update','developer','always'):
        raise ValueError('missing Developer-only feature writer policy')
    # A representative effective branch proves application there, not coverage of the full namespace.
    if owner_view:
        expected={'actor_type':'Integration','actor_id':data['apps']['developer']['app_id'],'bypass_mode':'always'}
        qualified=[d for d in details.values() if d.get('bypass_actors')==[expected]
                   and d.get('conditions',{}).get('ref_name')=={'include':['refs/heads/aipipe/issue-*'],'exclude':[]}]
        if not any({'creation','update'} <= {r['type'] for r in d.get('rules',[])} for d in qualified):
            raise ValueError('feature writer must cover the entire aipipe/issue-* namespace without exclusions')
    extra=sorted({r['type'] for r in main+feature}-{'pull_request','required_status_checks','non_fast_forward','deletion','creation','update'})
    return {'quality_visibility':'complete' if owner_view else 'visible_rules_only; legacy and bypass audit belongs to Owner',
            'required_checks':checks,'ruleset_ids':sorted(details),'legacy_protection':bool(protection),
            'additional_constraints':extra,
            'additional_required_checks':[i for i in observed_checks if i not in checks],
            'review_requirements':[r.get('parameters',{}) for r in safe if r['type']=='pull_request'],
            'business_acceptance_evaluated':False}
