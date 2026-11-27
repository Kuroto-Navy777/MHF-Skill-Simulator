import unittest
from ferias_import import category_mode, resolve_zenith, validate_slots

class WeaponRulesTests(unittest.TestCase):
    # Shared slots must not be allocated twice.
    def test_shared(self):
        self.assertTrue(validate_slots('shared',3,1,2)['valid'])
        self.assertFalse(validate_slots('shared',3,2,2)['valid'])
        self.assertFalse(validate_slots('shared',2,3,0)['valid'])

    # G weapons take sigils; normal equipment takes decorations.
    def test_exclusive(self):
        self.assertFalse(validate_slots('sigil',3,1,0)['valid'])
        self.assertTrue(validate_slots('sigil',2,0,2)['valid'])
        self.assertFalse(validate_slots('decoration',3,0,1)['valid'])

    # Tower and unresolved families are not accepted as verified ordinary slots.
    def test_special(self):
        self.assertFalse(validate_slots('tower_special',3,1,0)['valid'])
        self.assertFalse(validate_slots('tower_special',3,0,0)['complete'])
        self.assertFalse(validate_slots('unknown',3,0,0)['complete'])

    def test_bad_counts(self):
        with self.assertRaises(ValueError):
            validate_slots('shared',3,-1,0)
        self.assertFalse(validate_slots('shared',None,0,0)['valid'])

    def test_category(self):
        self.assertEqual(category_mode('s','','GR 1',['example']),('zenith_evolution','shared'))
        self.assertEqual(category_mode('main','祈歌武器','GR 1',[]),('prayer_g','sigil'))
        self.assertEqual(category_mode('main','準G級武器','GR 1',[]),('quasi_g','unknown'))

    def test_translation(self):
        lookup={'Hearing Protection Up+1':('test-ear',1),'Stylish Up':('test-style',1),'Skill Slots Up+1':('test-slot',1)}
        self.assertEqual(resolve_zenith('Zenith Skill：Earplugs Up+1',lookup),('test-ear',1))
        self.assertEqual(resolve_zenith('Zenith Skill：Stylish Up+',lookup),('test-style',1))
        self.assertEqual(resolve_zenith('Zenith Skill：Unknown+1',lookup),(None,None))

if __name__=='__main__': unittest.main()
