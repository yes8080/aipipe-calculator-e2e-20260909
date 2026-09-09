import copy
import unittest
from test_publish_batch import FakeGitHub, example_plan, publisher, TEMPLATE, REPO, SHA

class CompleteBatchTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeGitHub(); self.plan=example_plan()
        publisher.publish(self.plan,REPO,SHA,TEMPLATE,self.api,output=lambda _:None)
        self.api.calls.clear()

    def verify(self):
        return publisher.verify_complete(self.plan,REPO,SHA,TEMPLATE,self.api,1)

    def test_complete_batch_is_verified_without_any_writes(self):
        self.assertEqual(len(self.verify()),2);self.assertEqual(self.api.writes,[])

    def test_editor_final_newline_does_not_change_milestone_contract(self):
        self.api.data['milestones'][0]['description']+='\n'
        before=copy.deepcopy(self.api.data)
        self.assertEqual(len(self.verify()),2)
        self.assertEqual(self.api.data,before);self.assertEqual(self.api.writes,[])

    def test_missing_duplicate_unmarked_and_changed_dependency_cannot_release(self):
        original=copy.deepcopy(self.api.data)
        for variant in ('missing','duplicate','unmarked','dependency'):
            with self.subTest(variant=variant):
                self.api.data=copy.deepcopy(original)
                if variant=='missing':self.api.data['issues'].pop()
                if variant=='duplicate':
                    other=copy.deepcopy(self.api.data['issues'][0]);other['number']=3;self.api.data['issues'].append(other)
                if variant=='unmarked':self.api.data['issues'].append({'number':3,'body':'foreign task','milestone':{'number':1}})
                if variant=='dependency':self.api.data['issues'][1]['body']=self.api.data['issues'][1]['body'].replace('#1','#99')
                with self.assertRaises(publisher.PublishError):self.verify()
                self.assertEqual(self.api.writes,[])

    def test_wrong_milestone_or_invalid_plan_is_rejected(self):
        self.api.data['milestones'][0]['description']='another batch'
        with self.assertRaises(publisher.PublishError):self.verify()
        self.assertEqual(self.api.writes,[])

    def test_read_transport_never_retries_or_repairs_a_failed_read(self):
        self.api.hidden_issue_list_reads=1
        with self.assertRaises(publisher.PublishError):self.verify()
        self.assertEqual(self.api.writes,[])
