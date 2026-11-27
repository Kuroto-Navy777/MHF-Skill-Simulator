"""Enumerate every packing in a tiny model and compare the complete MILP result set."""
import copy
import itertools
import json
import os
from pathlib import Path
import sqlite3
import unittest
from search_engine import Searcher


@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class ExhaustiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(':memory:')
        with sqlite3.connect(os.environ['MHF_TEST_DB']) as source:source.backup(cls.db)
        original=Searcher(cls.db)
        fixture=json.loads((Path(__file__).parent/'ci/regression_builds.json').read_text(encoding='utf-8'))['non-ravi']['build']
        cls.base={**copy.deepcopy(fixture),'weapon':{'virtual':True,'slots':0,'slot_mode':'decoration','sigils':0,'jewels':[]},'cuffs':[]}
        cls.parts=list(cls.base['armor']);first=cls.base['armor']['head']['item']
        other=next(eid for eid,row in original.by_kind['head'].items() if eid!=first and row['job'] in (None,'共','剣士')
                   and row['sex'] in (None,'共','男') and row['group_name']!='SP' and row['class_code'] not in ('(未)','(不)')
                   and any(level[0]=='L1' for level in original.levels[eid]))
        cls.heads=[first,other];cls.jewels=['jewel:0:126','jewel:0:127']
        selected=[a['item'] for a in cls.base['armor'].values()]+[other]+cls.jewels
        # Only this private in-memory copy is altered. Real equipment metadata and
        # skill rules remain present; points/capacities define a fully enumerable case.
        for eid in selected:
            cls.db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,))
            cls.db.execute('DELETE FROM abilities WHERE equipment_id=?',(eid,))
        cls.g=original.e.names['normal','剛撃'];cls.flash=original.e.names['normal','一閃'];cls.soul=original.e.names['normal','喝']
        for eid,points in [(first,42),(other,44),(cls.jewels[0],4),(cls.jewels[1],7)]:
            cls.db.execute('INSERT INTO equipment_skills VALUES(?,?,?)',(eid,cls.g,points))
        cls.db.execute('INSERT INTO equipment_skills VALUES(?,?,?)',(cls.jewels[0],cls.flash,4))
        cls.db.execute('INSERT INTO equipment_skills VALUES(?,?,?)',(cls.jewels[1],cls.soul,-5))
        cls.db.execute('UPDATE equipment SET slots=1 WHERE id=?',(cls.jewels[0],))
        cls.db.execute('UPDATE equipment SET slots=2 WHERE id=?',(cls.jewels[1],))
        cls.capacities=[2,1,0,0,0]
        for i,p in enumerate(cls.parts):
            a=cls.base['armor'][p];a['jewels']=[]
            cls.db.execute('UPDATE levels SET slots=? WHERE equipment_id=? AND level=?',(cls.capacities[i],a['item'],'L1'))
        cls.db.execute('UPDATE levels SET slots=2 WHERE equipment_id=? AND level=?',(other,'L1'))
        cls.db.commit();cls.s=Searcher(cls.db)

    @classmethod
    def tearDownClass(cls):cls.db.close()

    def key(self,b):
        jewels=[j for a in list(b['armor'].values())+[b['weapon']] for j in a['jewels']]
        return b['armor']['head']['item'],jewels.count(self.jewels[0]),jewels.count(self.jewels[1])

    def test_all_packings_match_solver_with_signed_points_bans_and_inventory(self):
        checked=0
        for slots in range(4):
            capacities=self.capacities+[slots]
            choices=[[(a,b) for a in range(3) for b in range(3) if a+2*b<=cap] for cap in capacities]
            for extra in ('none','negative','forbidden'):
                q=copy.deepcopy(self.base);q['armor']={};q['weapon']['slots']=slots
                q.update(required=[{'skill':self.g,'points':50}],armor_level_mode='first',g_armor_only=False,
                         armor_candidates={p:(self.heads if p=='head' else [self.base['armor'][p]['item']]) for p in self.parts},
                         jewel_candidates=self.jewels,jewel_limits={j:2 for j in self.jewels},
                         seconds=10,limit=30,search_strategy='full')
                if extra=='negative':q['required'].append({'skill':'青魂'})
                if extra=='forbidden':q['forbidden']=[{'skill':self.flash,'points':10}]
                expected=set()
                for head,packing in itertools.product(self.heads,itertools.product(*choices)):
                    a=sum(x[0] for x in packing);b=sum(x[1] for x in packing)
                    if a>2 or b>2:continue
                    build=copy.deepcopy(self.base);build['armor']['head']['item']=head;build['weapon']['slots']=slots
                    for target,(na,nb) in zip([*build['armor'].values(),build['weapon']],packing):
                        target['jewels']=[self.jewels[0]]*na+[self.jewels[1]]*nb
                    report=self.s.e.evaluate(build);checked+=1
                    valid=report['valid'] and all(self.s.achieved(report,sid,pt) for sid,pt in self.s.requirements(q['required']).items())
                    if valid and not self.s.forbidden_hit(report,self.s.conflicts(q)):expected.add(self.key(build))
                result=self.s.search(q)
                actual={self.key(h['build']) for h in result['results']}
                self.assertEqual(actual,expected,(slots,extra,result['status']))
                self.assertEqual(result['status'],'model_exhausted')
        self.assertGreater(checked,200)


if __name__=='__main__':unittest.main()
