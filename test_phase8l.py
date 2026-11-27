"""Verify safe solver bounds, expanded search and the reorganized workbench."""
import copy
import itertools
import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import Counter
from lxml import html
from search_engine import DecisionBounds, Searcher


class Phase8LTests(unittest.TestCase):
    def test_group_bounds_cover_all_feasible_assignments(self):
        # Exactly one armor per part, at most three jewel slots and two cuff instances.
        armor={'head':{0:None,1:None},'body':{2:None,3:None}}
        jewels={'a':{4:1,5:2},'b':{6:1}}
        cuffs={'c':{7:1,8:2}}
        bounds=DecisionBounds(armor,jewels,cuffs,{'a':{'slots':1},'b':{'slots':2}},3)
        row={0:-4,1:6,2:3,4:-3,5:-6,6:7,7:2,8:4}
        lo,hi=bounds.interval(row,5)
        for bits in itertools.product((0,1),repeat=9):
            if bits[0]+bits[1]!=1 or bits[2]+bits[3]!=1: continue
            if bits[4]+2*bits[5]+2*bits[6]>3 or bits[7]+2*bits[8]>2: continue
            score=5+sum(bits[i]*v for i,v in row.items())
            self.assertLessEqual(lo,score);self.assertGreaterEqual(hi,score)

    def test_adaptive_expands_after_empty_prioritized_pool(self):
        s=Searcher.__new__(Searcher)
        response={'status':'model_exhausted','results':[],'attempts':1,'rejected':0,'duplicates':0}
        with patch.object(s,'search_fixed',side_effect=[copy.deepcopy(response),copy.deepcopy(response)]) as fn:
            r=s.search_with_strategy({'search_strategy':'adaptive','seconds':10,'limit':2})
        self.assertEqual(fn.call_count,2)
        self.assertEqual(fn.call_args_list[0].args[0]['_fast_armor_cap'],240)
        self.assertTrue(fn.call_args_list[1].args[0]['full_jewel_pool'])
        self.assertEqual(fn.call_args_list[1].args[0]['_fast_armor_cap'],0)
        self.assertEqual([p['pool'] for p in r['search_passes']],['prioritized','full'])

    def test_full_does_not_use_shortlist(self):
        s=Searcher.__new__(Searcher)
        with patch.object(s,'search_fixed',return_value={}) as fn:
            s.search_with_strategy({'search_strategy':'full'})
        self.assertTrue(fn.call_args.args[0]['full_jewel_pool'])
        self.assertNotIn('_fast_armor_cap',fn.call_args.args[0])

    def test_workbench_controls_are_unique_and_preserved(self):
        doc=html.parse('web/index.html');ids=doc.xpath('//@id')
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(doc.xpath('//*[@data-workspace-tab]')),4)
        for id_,panel in [('required','skills'),('armorRows','gear'),('min_Fire','conditions'),('extMeal','external'),('fullJewels','conditions'),('forbidden','skills')]:
            node=doc.getroot().get_element_by_id(id_)
            self.assertEqual(node.xpath('ancestor::*[@data-workspace]/@data-workspace'),[panel])
        for id_ in ('wt','sex','run','cancel','probe','saveProfile','backupSave'):
            self.assertIn(id_,ids)


@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'user generated database required')
class Phase8LData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def test_real_prioritized_search(self):
        req=json.loads(Path('example_auto_search.json').read_text())
        req.update(seconds=20,limit=1,search_strategy='adaptive',armor_level_mode='first')
        r=self.s.search(req)
        self.assertTrue(r['results'],r['status'])
        for h in r['results']:
            self.assertTrue(h['evaluation']['valid'])
            self.assertTrue(all(self.s.achieved(h['evaluation'],sid,pt) for sid,pt in self.s.requirements(req['required']).items()))
        self.assertTrue(r['search_passes'])
        print('Phase 8L adaptive:',r['elapsed_seconds'],r['pool_counts'],r['model_variables'])
    def test_full_keeps_all_eligible_armor(self):
        req=json.loads(Path('example_auto_search.json').read_text())
        req.update(seconds=15,limit=1,search_strategy='full',armor_level_mode='first')
        r=self.s.search(req)
        self.assertEqual(r['pool_mode'],'full')
        self.assertEqual({k:r['pool_counts'][k] for k in r['eligible_armor']},r['eligible_armor'])
        self.assertEqual(r['pool_counts']['jewel'],r['eligible_jewels_in_mode'])
        self.assertEqual(r['pool_counts']['cuff'],r['eligible_cuffs_in_mode'])
        self.assertTrue(r['results'],r['status'])
        print('Phase 8L full:',r['elapsed_seconds'],r['pool_counts'],r['model_variables'])

if __name__=='__main__':unittest.main()
