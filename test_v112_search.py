"""1.1.2 regressions: real imported DB, independent manual replay, no embedded DB."""
import copy
import json
import os
import sqlite3
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from search_engine import Searcher

FIXTURES=json.loads((Path(__file__).parent/'ci/regression_builds.json').read_text(encoding='utf-8'))


@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class Search112Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']); cls.s=Searcher(cls.db)

    @classmethod
    def tearDownClass(cls): cls.db.close()

    def request(self, tier=2, **kwargs):
        return dict(weapon_type='MS',sex='男',g_poogie=True,premium_poogie_clothes=True,
                    required=[{'skill':x} for x in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6',f'一閃+{tier}']],
                    search_strategy='adaptive',seconds=20,limit=2,**kwargs)

    def verify(self, response, req):
        self.assertTrue(response['results'], response)
        self.assertFalse(response['complete_game_search'])
        for h in response['results']:
            manual=self.s.e.evaluate(h['build'])
            self.assertEqual(manual,h['evaluation']); self.assertTrue(manual['valid'])
            for sid,pt in self.s.requirements(req['required']).items():
                self.assertTrue(self.s.achieved(manual,sid,pt),(sid,pt))
            self.assertFalse(self.s.forbidden_hit(manual,self.s.conflicts(req)))
            for a in manual['slots']['equipment']:
                self.assertLessEqual(a['used']+a.get('sigils',0),a['capacity'])

    def test_reported_four_skills_and_higher_flash(self):
        for tier in (2,3):
            with self.subTest(tier=tier):
                q=self.request(tier); r=self.s.search(q); self.verify(r,q)
                self.assertEqual(r['rejected'],0)

    def test_known_non_ravi_manual_and_automatic(self):
        f=FIXTURES['non-ravi']; b=copy.deepcopy(f['build'])
        manual=self.s.e.evaluate(b); self.assertTrue(manual['valid'])
        for sid,pt in self.s.requirements(f['required']).items(): self.assertTrue(self.s.achieved(manual,sid,pt))
        self.assertTrue(all('ラヴィ' not in self.s.items[a['item']]['ja'] for a in b['armor'].values()))
        for a in b['armor'].values(): a['jewels']=[]
        q={**b,'required':f['required'],'seconds':10,'limit':2}
        r=self.s.search(q); self.verify(r,q)
        for h in r['results']:
            jewels=[j for a in h['build']['armor'].values() for j in a['jewels']]
            self.assertTrue(any('ラヴィ' in self.s.items[j]['ja'] for j in jewels))

    def test_true_secret_jewels_without_secret_cuff(self):
        f=FIXTURES['true-secret']; b=copy.deepcopy(f['build'])
        self.assertTrue(self.s.e.evaluate(b)['valid'])
        for a in b['armor'].values(): a['jewels']=[]
        q={**b,'required':f['required'],'jewel_candidates':['真磁星珠・白虎'],'seconds':10,'limit':1}
        r=self.s.search(q); self.verify(r,q)
        js=[j for a in r['results'][0]['build']['armor'].values() for j in a['jewels']]
        self.assertEqual(len(js),5); self.assertEqual(r['results'][0]['build']['cuffs'],[])

    def optional_request(self, weights):
        f=FIXTURES['optional']
        return {**copy.deepcopy(f['build']), 'required':[{'skill':'磁斬鎚技【磁星】'}],
                'jewel_candidates':[c[0] for c in f['choices']],
                'optional':[{'skill':c[1],'points':c[2],'weight':w} for c,w in zip(f['choices'],weights)],
                'seconds':10,'limit':1}

    def test_optional_changes_default_objective_and_priority(self):
        q=self.optional_request([100,1]); baseline=self.s.search({**q,'optional':[]})
        self.verify(baseline,q); self.assertEqual(baseline['results'][0]['new_jewels'],0)
        for weights in ([100,1],[1,100]):
            q=self.optional_request(weights); r=self.s.search(q); self.verify(r,q)
            chosen=weights.index(100); opts=r['results'][0]['metrics']['optional']
            self.assertTrue(opts[chosen]['achieved']); self.assertFalse(opts[1-chosen]['achieved'])
            self.assertEqual(r['results'][0]['new_jewels'],1)
            self.assertEqual(r['results'][0]['metrics']['optional_score'],100)

    def test_unachievable_optional_does_not_remove_valid_build(self):
        q=self.optional_request([100,1]); q['jewel_candidates']=[]
        r=self.s.search(q); self.verify(r,q); self.assertEqual(r['results'][0]['metrics']['optional_score'],0)

    def test_forbidden_fixed_and_inventory(self):
        q=self.optional_request([100,1]); denied=q['jewel_candidates'][0]; q['jewel_limits']={denied:0}
        r=self.s.search(q); self.verify(r,q)
        self.assertFalse(r['results'][0]['metrics']['optional'][0]['achieved'])
        q=self.optional_request([100,1]); q['forbidden']=[q['optional'][0]]
        r=self.s.search(q); self.verify(r,q)
        for part,a in q['armor'].items():
            hit=r['results'][0]['build']['armor'][part]
            self.assertEqual(hit['item'],self.s.e.equipment(a['item'],part)['id'])
            self.assertEqual(hit['level'],a['level'])
            self.assertTrue(Counter(a['jewels']) <= Counter(self.s.items[j]['ja'] for j in hit['jewels']))

    def test_live_manual_consistency(self):
        q=self.request(); manual=self.s.search(q); live=self.s.search({**q,'live_preview':True})
        self.verify(manual,q); self.verify(live,q)
        self.assertEqual([self.s.build_key(h['build']) for h in manual['results']],
                         [self.s.build_key(h['build']) for h in live['results']])

    def test_overlap_is_distinct_from_missing_overflow_wrong_weapon(self):
        f=FIXTURES['non-ravi']; r=self.s.e.evaluate(f['build']); sid,pt=self.s.requirement({'skill':'一閃+3'})
        flash=next(s for s in r['skills'] if s['id']==sid)
        self.assertEqual(flash['status'],'overlap'); self.assertTrue(self.s.achieved(r,sid,pt))
        for status in ('overflow','wrong_weapon','not_reached'):
            flash['status']=status; self.assertFalse(self.s.achieved(r,sid,pt))
        flash['status']='overlap'; flash['threshold']=10; self.assertFalse(self.s.achieved(r,sid,pt))

    def test_final_validation_rejections_have_reproducible_reasons(self):
        f=FIXTURES['non-ravi']; q={**copy.deepcopy(f['build']),'required':f['required'],
                                  'jewel_candidates':[],'seconds':5,'limit':1}
        evaluate=self.s.e.evaluate
        def invalid(build):
            r=evaluate(build)
            if len(build.get('armor',{}))==5:
                r['valid']=False; r['errors'].append('injected validation failure')
            return r
        with patch.object(self.s.e,'evaluate',side_effect=invalid): r=self.s.search(q)
        self.assertFalse(r['results']); self.assertEqual(r['rejected'],1)
        self.assertEqual(r['rejection_reasons'],{'invalid_equipment':1})
        self.assertEqual(len(r['rejection_log']),1)
        self.assertEqual(r['rejection_log'][0]['reasons'][0]['detail'],'injected validation failure')
        self.assertEqual(self.s.build_key(r['rejection_samples'][0]['build']),self.s.build_key(f['build']))


if __name__=='__main__': unittest.main()
