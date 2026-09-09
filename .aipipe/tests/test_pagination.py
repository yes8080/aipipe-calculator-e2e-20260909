import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aipipe.github import paginate, GhError
from aipipe import initialize, cli
from test_policy import DATA

class PaginationTests(unittest.TestCase):
    def test_list_and_check_runs_read_later_pages_preserving_filters(self):
        for key in (None,'check_runs'):
            calls=[]
            class API:
                def request(self,path):
                    query=parse_qs(urlsplit(path).query);calls.append(query)
                    self_page=int(query['page'][0])
                    values=[{'id':i} for i in (range(100) if self_page==1 else [100])]
                    return {key:values,'total_count':101} if key else values
            result=paginate(API(),'repos/a/b/items?state=all&per_page=2',key)
            self.assertEqual(len(result),101);self.assertEqual(result[-1]['id'],100)
            self.assertEqual(calls[-1],{'state':['all'],'per_page':['100'],'page':['2']})

    def test_failed_repeated_or_truncated_later_page_never_returns_partial_results(self):
        for mode in ('failure','repeat','truncated','limit'):
            class API:
                def request(self,path):
                    page=int(parse_qs(urlsplit(path).query)['page'][0])
                    if page==2 and mode=='failure':raise GhError('api',status=403)
                    values=[{'id':i} for i in range(100)] if page==1 or mode=='repeat' else []
                    return {'check_runs':values,'total_count':101}
            with self.subTest(mode=mode),self.assertRaises(ValueError):paginate(API(),'path',key='check_runs',max_pages=1 if mode=='limit' else 10)

    def test_rule_on_later_page_prevents_any_initialization_mutation(self):
        calls=[]
        class API:
            def request(self,path,method='GET',payload=None):
                calls.append((path,method))
                route=urlsplit(path).path;page=int(parse_qs(urlsplit(path).query).get('page',['1'])[0])
                if route.endswith('/check-runs'):
                    return {'check_runs':[{'name':'unrelated-'+str(i),'app':{'id':1}} for i in range(100)] if page==1 else [{'name':'ci','app':{'id':15368}}]}
                if route.endswith('/rulesets'):
                    return [{'id':i,'enforcement':'active'} for i in range(100)] if page==1 else [{'id':100,'enforcement':'active'}]
                if '/rulesets/' in route:
                    return {'target':'branch','enforcement':'active','conditions':{'ref_name':{'include':['refs/heads/main'],'exclude':[]}},'rules':[],'bypass_actors':[{'actor_id':999}]}
                raise AssertionError(path)
            def command(self,args):raise AssertionError('mutation')
        data={'schema_version':1,'repository':'acme/repo','default_branch':'main','apps':DATA['apps']}
        args=cli.parser().parse_args(['init','checks','--rules','--check-name','ci','--check-sha','a'*40,'--apply','--non-interactive'])
        with patch.object(initialize,'owner',return_value=API()),patch.object(initialize,'verify_remote'),patch('builtins.print'),self.assertRaises(ValueError):
            initialize.init_checks(args,Path('/unused'),Path('/unused/project.json'),data)
        self.assertTrue(any('/rulesets/100' in p for p,_ in calls))
        self.assertTrue(all(m=='GET' for _,m in calls))
