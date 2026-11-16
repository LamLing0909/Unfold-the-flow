"""Check that the standalone page is generated deterministically from source."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('build.py', 'index.template.html', 'style.css', 'diagram.py', 'app.py', 'index.html')


class BuildTest(unittest.TestCase):
    def test_build_and_stale_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for name in FILES:
                shutil.copy2(ROOT / name, dest / name)
            def run(*args):
                return subprocess.run([sys.executable, 'build.py', *args], cwd=dest,
                                      capture_output=True, text=True)
            self.assertEqual(run('--check').returncode, 0)
            app = dest / 'app.py'
            app.write_text(app.read_text(encoding='utf-8') + '\n# unique build test\n', encoding='utf-8')
            self.assertNotEqual(run('--check').returncode, 0)
            self.assertEqual(run().returncode, 0)
            html = (dest / 'index.html').read_text(encoding='utf-8')
            self.assertIn('# unique build test', html)
            self.assertIn((dest / 'diagram.py').read_text(encoding='utf-8'), html)
            self.assertNotIn('from diagram import Diagram\n', html)
            self.assertEqual(run('--check').returncode, 0)
            first = (dest / 'index.html').read_bytes()
            self.assertEqual(run().returncode, 0)
            self.assertEqual(first, (dest / 'index.html').read_bytes())

    def test_reject_embedded_closing_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for name in FILES:
                shutil.copy2(ROOT / name, dest / name)
            with (dest / 'app.py').open('a', encoding='utf-8') as f:
                f.write('\n# </script>\n')
            result = subprocess.run([sys.executable, 'build.py'], cwd=dest,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('closing tag', result.stderr)

if __name__ == '__main__':
    unittest.main()
