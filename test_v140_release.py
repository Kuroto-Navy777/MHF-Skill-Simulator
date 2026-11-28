"""A revised partial-editor build may replace a draft, never a public release."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from ci import release

class Draft140Tests(unittest.TestCase):
 def test_published_release_cannot_be_replaced(self):
  with patch.object(release.subprocess,'check_output',return_value=json.dumps({'isDraft':False,'targetCommitish':'a'*40}).encode()),patch.object(release,'run') as run:
   with self.assertRaises(ValueError):release.register_release('1.4.0','b'*40,[Path('safe.zip')],replace_draft=True)
   run.assert_not_called()
 def test_draft_replacement_requires_ancestor_and_keeps_draft_until_ci(self):
  with patch.object(release.subprocess,'check_output',return_value=json.dumps({'isDraft':True,'targetCommitish':'a'*40}).encode()),patch.object(release,'run') as run,patch.object(release,'wait_ci') as wait:
   release.register_release('1.4.0','b'*40,[Path('safe.zip')],replace_draft=True)
   self.assertEqual(run.call_args_list[0].args[:3],('git','merge-base','--is-ancestor'));self.assertIn('--clobber',run.call_args_list[2].args);wait.assert_not_called()
   self.assertFalse(any('--draft=false' in call.args for call in run.call_args_list))

if __name__=='__main__':unittest.main()
