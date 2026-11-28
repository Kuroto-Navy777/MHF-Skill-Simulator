"""Enumerate the remaining sockets with per-part pins, including a two-slot jewel."""
import copy,itertools,os,unittest
import test_v120_exhaustive as exhaustive

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class PartialExhaustive140Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):exhaustive.ExhaustiveTests.setUpClass.__func__(cls)
 @classmethod
 def tearDownClass(cls):cls.db.close()
 key=exhaustive.ExhaustiveTests.key
 def test_pinned_multislot_jewels_match_all_remaining_packings(self):
  for slots in range(4):
   for negative in (False,True):
    q=copy.deepcopy(self.base);q['armor']={};q['weapon']['slots']=slots
    q.update(required=[{'skill':self.g,'points':50}]+([{'skill':'青魂'}] if negative else []),armor_level_mode='first',g_armor_only=False,
     armor_candidates={p:(self.heads if p=='head' else [self.base['armor'][p]['item']]) for p in self.parts},
     pinned_jewels={'head':[self.jewels[1]],'body':[self.jewels[0]]},jewel_candidates=self.jewels,jewel_limits={j:2 for j in self.jewels},seconds=5,limit=30,search_strategy='full')
    expected=set()
    for head,na,nb in itertools.product(self.heads,range(2),range(2)):
     if na+2*nb>slots:continue
     b=copy.deepcopy(self.base);b['armor']['head']['item']=head;b['armor']['head']['jewels']=[self.jewels[1]];b['armor']['body']['jewels']=[self.jewels[0]];b['weapon'].update(slots=slots,jewels=[self.jewels[0]]*na+[self.jewels[1]]*nb)
     r=self.s.e.evaluate(b)
     if r['valid'] and all(self.s.achieved(r,sid,pt) for sid,pt in self.s.requirements(q['required']).items()):expected.add(self.key(b))
    found=self.s.search(q);self.assertEqual({self.key(h['build']) for h in found['results']},expected,(slots,negative,found['status']))
    for h in found['results']:
     self.assertIn(self.jewels[1],h['build']['armor']['head']['jewels']);self.assertIn(self.jewels[0],h['build']['armor']['body']['jewels'])

if __name__=='__main__':unittest.main()
