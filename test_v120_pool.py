"""Bitset correctness, bounded retention, scope safety and fail-closed persistence."""
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from activation import achieved
from candidate_groups import group_hits
from candidate_pool import CandidatePool,condition_key


def hit(i,points=10,status='active'):
    return {'build':{'armor':{p:{'item':f'{p}:{i//3}','level':'L1','jewels':[f'j:{i}'] if p=='head' else []}
                            for p in ('head','body','arm','waist','leg')},'cuffs':[]},
            'evaluation':{'valid':True,'skills':[{'id':'normal:a','threshold':points,'status':status}],
                          'automatic':[],'zenith':[]},'new_jewels':1}


class PoolTests(unittest.TestCase):
    def test_candidate_reader_does_not_import_the_solver(self):
        subprocess.run([sys.executable,'-c',"import candidate_reader,sys; assert 'scipy' not in sys.modules"],check=True)

    def test_scope_retains_required_optional_and_display_changes_but_not_restriction_changes(self):
        q={'weapon_type':'MS','required':[],'optional':[],'limit':5}
        for key,value in [('required',[{'skill':'normal:a','points':20}]),('optional',[{'skill':'normal:b','points':10,'weight':4}]),('limit',30),('objective','optional')]:
            self.assertEqual(condition_key(q),condition_key({**q,key:value}))
        for key,value in [('weapon',{'virtual':True,'slots':3,'slot_mode':'decoration'}),('cuffs',[]),('inventory',{'head:1':1}),('exclude',['head:1']),('forbidden',[{'skill':'normal:a','points':10}])]:
            self.assertNotEqual(condition_key(q),condition_key({**q,key:value}))

    def test_index_matches_naive_filter_and_counts_for_signed_thresholds(self):
        rng=random.Random(120);pool=CandidatePool('db');q={'weapon_type':'MS','required':[]}
        hits=[]
        for i in range(180):
            h=hit(i,rng.choice([-10,0,10,20,30]),rng.choice(['active','overlap','overflow','wrong_weapon','not_reached']))
            h['evaluation']['zenith']=[{'id':'zenith:b','level':rng.randrange(3),'has_base_skill':rng.choice([True,False])}]
            hits.append(h)
        pool.ingest(q,hits)
        targets=[('normal:a',pt) for pt in (-10,10,20,30)]+[('zenith:b',1),('zenith:b',2)]
        for required in ({},{'normal:a':10},{'normal:a':-10},{'zenith:b':1},{'normal:a':20,'zenith:b':2}):
            result=pool.query(q,required,targets,limit=512)
            expected=[h for h in hits if all(achieved(h['evaluation'],sid,pt) for sid,pt in required.items())]
            self.assertEqual(result['confirmed_builds'],len(expected))
            for sid,pt in targets:
                self.assertEqual(result['candidate_counts'][f'{sid}|{pt}'],sum(achieved(h['evaluation'],sid,pt) for h in expected))

    def test_display_limit_does_not_limit_index_or_restore_on_skill_removal(self):
        pool=CandidatePool('db');q={'required':[]};pool.ingest(q,[hit(i,20 if i%2 else 10) for i in range(80)])
        narrow=pool.query(q,{'normal:a':20},limit=5)
        self.assertEqual(len(narrow['results']),5);self.assertEqual(narrow['confirmed_builds'],40)
        broad=pool.query(q,{},limit=5);self.assertEqual(broad['confirmed_builds'],80)
        self.assertEqual(broad['distinct_armor'],27);self.assertEqual(broad['decoration_variants'],53)

    def test_retention_and_byte_budget_remain_bounded_after_evictions(self):
        pool=CandidatePool('db',capacity=24,scope_capacity=12,max_bytes=50000)
        for scope in range(6):pool.ingest({'weapon_type':str(scope)},[hit(i) for i in range(20)])
        self.assertLessEqual(sum(len(s['hits']) for s in pool.scopes.values()),24)
        self.assertLessEqual(len(pool.scopes),4)
        for key,scope in pool.scopes.items():
            self.assertLessEqual(len(scope['hits']),12)
            self.assertTrue(all(bits.bit_length()<=12 for tiers in scope['postings'].values() for bits in tiers.values()))

    def test_persisted_builds_are_not_trusted_reports_or_indexed_until_revalidation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cache.json';q={'required':[]};pool=CandidatePool('db',p);pool.ingest(q,[hit(1)]);pool.save()
            raw=json.loads(p.read_text());self.assertNotIn('evaluation',json.dumps(raw))
            loaded=CandidatePool('db',p)
            self.assertEqual(loaded.query(q,{})['confirmed_builds'],0)
            self.assertTrue(loaded.restored)
            self.assertFalse(CandidatePool('updated-db',p).restored)

    def test_armor_groups_preserve_alternative_jewel_witnesses(self):
        groups=group_hits([hit(i) for i in range(9)])
        self.assertEqual(len(groups),3)
        self.assertTrue(all(h['variant_count']==3 and len(h['variants'])==2 for h in groups))
        self.assertEqual(groups[1]['armor_distance'],5)


if __name__=='__main__':unittest.main()
