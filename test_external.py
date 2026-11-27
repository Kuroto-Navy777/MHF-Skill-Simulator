import unittest
from defense import evaluate_stats, satisfies
from external import normalize, road_cost, upper_bonus, weapon_preview, weapon_delta

class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.base={'defense':1954,'Fire':4,'Water':19,'Thunder':58,'Ice':19,'Dragon':19}

    # A sample build using all resistance food and targeted Road levels.
    def test_road_meal(self):
        e={'meal':'all','quality':3,'road':{'all':3,'Fire':2,'Water':1,'Ice':1,'Dragon':1}}
        r=evaluate_stats([self.base],[],e)
        self.assertEqual(r['external']['Fire'],54)
        self.assertEqual(r['external']['Water'],64)
        self.assertEqual(r['external']['Thunder'],93)
        self.assertEqual(r['road_cost'],95)
        self.assertFalse(satisfies({'defense_stats':r},{'min_stats':{'Fire':55},'stat_mode':'external'}))
        self.assertTrue(satisfies({'defense_stats':r},{'min_stats':{'Water':55},'stat_mode':'external'}))

    def test_same_family(self):
        r=evaluate_stats([self.base],['各耐性+10','火耐性+30'],{'meal':'all','quality':3})
        self.assertEqual(r['external']['Fire'],54)
        self.assertEqual(r['external_bonus']['Fire'],10)
        r=evaluate_stats([self.base],['火耐性+30'],{'meal':'Fire','quality':2})
        self.assertEqual(r['external_bonus']['Fire'],0)

    def test_sigil(self):
        e=normalize({'sigil':{'attack':45,'element':15,'affinity':-5,'defense':10}})
        self.assertEqual(weapon_delta(e)['element_display'],150)
        self.assertEqual(weapon_preview(e,'MS',3034,0)['sigil_attack_estimate'],3277)
        self.assertEqual(weapon_preview(e,'MS',3034,0)['sigil_affinity_estimate'],-5)
        self.assertEqual(evaluate_stats([self.base],[],e)['external']['defense'],1964)

    def test_validation(self):
        for e in ({'quality':4},{'road':{'all':4}},{'sigil':{'attack':True}},{'meal':'bad'}):
            with self.assertRaises(ValueError): normalize(e)
        self.assertGreater(road_cost(normalize({'road':{k:3 for k in ['all','Fire','Water','Thunder','Ice','Dragon']}})),130)

    def test_optimistic_bound(self):
        e=normalize({'meal':'all','quality':3,'road':{'all':2}})
        r=evaluate_stats([self.base],['各耐性+10'],e)
        self.assertEqual(upper_bonus(e)['Fire'],30)
        self.assertEqual(r['external_bonus']['Fire'],20)

    def test_missing_data(self):
        r=evaluate_stats([{**self.base,'Fire':None}],[],{'meal':'all','quality':3})
        self.assertIsNone(r['external']['Fire'])
