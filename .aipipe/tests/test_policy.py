import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from aipipe import policy, initialize, cli

DATA={'schema_version':1,'repository':'acme/repo','default_branch':'main',
      'apps':{'developer':{'app_id':10},'delivery':{'app_id':20}},
      'ci':{'required_checks':[{'context':'unit','integration_id':1},{'context':'integration','integration_id':2}]}}

class Policies:
    def __init__(self):
        self.calls=[];self.rules=initialize.quality_rules(DATA,'unit',1);self.legacy=None
        self.main=[dict(r,ruleset_id=i) for i in (0,1) for r in self.rules[i]['rules']]
        self.feature=[dict(r,ruleset_id=2) for r in self.rules[2]['rules']]
    def request(self,path,method='GET',payload=None):
        self.calls.append((path,method))
        if '/rules/branches/' in path:return self.feature if 'aipipe%2F' in path else self.main
        if '/rulesets/' in path:return self.rules[int(path.rsplit('/',1)[1])]
        if path.endswith('/protection'):return self.legacy
        if '/branches/' in path:return {'protected':True}
        raise AssertionError(path)

class PolicyTests(unittest.TestCase):
    def test_multiple_checks_and_rule_names_are_preserved_without_writes(self):
        gh=Policies();gh.rules[0]['name']='existing-quality';gh.rules[0]['conditions']['ref_name']['include']=['~DEFAULT_BRANCH']
        snapshot=copy.deepcopy(gh.rules)
        result=policy.audit(DATA,gh)
        self.assertEqual(result['required_checks'],DATA['ci']['required_checks'])
        self.assertEqual(gh.rules,snapshot);self.assertTrue(all(m=='GET' for _,m in gh.calls))

    def test_wrong_check_source_and_additional_writer_conflict_are_rejected(self):
        gh=Policies()
        for r in gh.main:
            if r['type']=='required_status_checks':r['parameters']['required_status_checks'][1]['integration_id']=9
        with self.assertRaises(ValueError):policy.audit(DATA,gh)
        gh=Policies();gh.rules.append(dict(gh.rules[1],bypass_actors=[]))
        gh.main.append({'type':'update','ruleset_id':3})
        with self.assertRaisesRegex(ValueError,'blocks delivery'):policy.audit(DATA,gh)

    def test_legacy_quality_with_feature_rules_can_be_audited_by_owner(self):
        gh=Policies();gh.main=[]
        gh.legacy={'enforce_admins':{'enabled':True},'required_pull_request_reviews':{
            'required_approving_review_count':2,'dismiss_stale_reviews':True,'require_last_push_approval':True},
            'required_status_checks':{'strict':True,'checks':[{'context':'unit','app_id':1},{'context':'integration','app_id':2}]},
            'restrictions':{'apps':[{'id':20}],'users':[],'teams':[]}}
        self.assertTrue(policy.audit(DATA,gh)['legacy_protection'])
        self.assertIn('visible_rules_only',policy.audit(DATA,gh,False)['quality_visibility'])
        gh.legacy['required_pull_request_reviews']['bypass_pull_request_allowances']={'apps':[{'id':10}]}
        with self.assertRaises(ValueError):policy.audit(DATA,gh)

    def test_org_rules_are_loaded_from_actual_source_and_missing_visibility_stops(self):
        gh=Policies()
        for r in gh.main:
            if r['ruleset_id']==0:r.update(ruleset_source_type='Organization',ruleset_source='acme')
        policy.audit(DATA,gh)
        self.assertTrue(any(p=='orgs/acme/rulesets/0' for p,_ in gh.calls))
        gh.rules[0].pop('bypass_actors')
        with self.assertRaisesRegex(ValueError,'cannot inspect'):policy.audit(DATA,gh)

    def test_extra_branch_constraints_are_reported_not_silently_discarded(self):
        gh=Policies();gh.main.append({'type':'required_signatures','ruleset_id':0})
        self.assertEqual(policy.audit(DATA,gh)['additional_constraints'],['required_signatures'])
        gh.feature.append({'type':'deletion','ruleset_id':2})
        with self.assertRaisesRegex(ValueError,'cleanup'):policy.audit(DATA,gh)

    def test_same_context_with_conflicting_sources_stops(self):
        gh=Policies();gh.main.append({'type':'required_status_checks','ruleset_id':0,
            'parameters':{'strict_required_status_checks_policy':True,'required_status_checks':[{'context':'unit','integration_id':999}]}})
        with self.assertRaisesRegex(ValueError,'conflicting'):policy.audit(DATA,gh)

    def test_audit_init_has_no_mutations_or_local_save(self):
        gh=Policies();args=cli.parser().parse_args(['init','checks','--audit'])
        with patch.object(initialize,'owner',return_value=gh),patch.object(initialize,'verify_remote'),patch('builtins.print'),patch.object(initialize.config,'save',side_effect=AssertionError('save')):
            initialize.init_checks(args,Path('/unused'),Path('/unused/project.json'),DATA)
        self.assertTrue(all(m=='GET' for _,m in gh.calls))
