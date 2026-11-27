"""Source completeness and launcher packaging regression tests."""
from pathlib import Path
import tempfile
import unittest

from build_windows import (REQUIRED_BUILD_FILES, validate_build_sources,
                           build_command, launcher_command)


class BuildFixTests(unittest.TestCase):
    def test_missing_safety_module_fails_early(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED_BUILD_FILES:
                if name == 'desktop_safety.py':
                    continue
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with self.assertRaisesRegex(ValueError, r'desktop_safety\.py'):
                validate_build_sources(root)
            (root / 'desktop_safety.py').touch()
            validate_build_sources(root)

    def test_complete_source_passes(self):
        validate_build_sources(Path(__file__).resolve().parent)

    def test_required_hidden_imports(self):
        root = Path(__file__).resolve().parent
        for command, names in ((launcher_command(root, root/'stage'), ('desktop_safety', 'update_progress')),
                               (build_command(root, root/'stage'), ('desktop_safety', 'worker_control'))):
            imports = [command[i+1] for i, item in enumerate(command) if item == '--hidden-import']
            for name in names:
                self.assertIn(name, imports)


if __name__ == '__main__':
    unittest.main()
