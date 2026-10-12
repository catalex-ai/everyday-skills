"""Native helper startup regression: exercise a real symlinked venv offline."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import runtime_python


class RuntimePythonTests(unittest.TestCase):
    def test_missing_environment_leaves_interpreter_unchanged(self):
        with tempfile.TemporaryDirectory() as root, patch.object(runtime_python.os, 'execv') as execute:
            runtime_python.ensure_package_interpreter(root)
            execute.assert_not_called()

    def test_symlinked_environment_reexecs_even_with_global_dependencies(self):
        with tempfile.TemporaryDirectory(prefix='clinic startup ') as root:
            environment=Path(root)/'.venv';binary=environment/'bin'/'python'
            binary.parent.mkdir(parents=True)
            binary.symlink_to(sys.executable)
            with patch.object(runtime_python.sys, 'prefix', str(Path(root)/'base')), patch.object(runtime_python.sys, 'argv', ['server.py','--role','patient']), patch.object(runtime_python.os, 'execv') as execute:
                runtime_python.ensure_package_interpreter(root)
                execute.assert_called_once_with(str(binary),[str(binary),'server.py','--role','patient'])

    def test_already_in_environment_does_not_reexec(self):
        with tempfile.TemporaryDirectory() as root:
            environment=Path(root)/'.venv';binary=environment/'bin'/'python'
            binary.parent.mkdir(parents=True);binary.symlink_to(sys.executable)
            with patch.object(runtime_python.sys, 'prefix', str(environment)), patch.object(runtime_python.os, 'execv') as execute:
                runtime_python.ensure_package_interpreter(root)
                execute.assert_not_called()

    def test_real_symlinked_venv_starts_once_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix='clinic startup ') as root:
            environment=Path(root)/'.venv'
            subprocess.run([sys.executable,'-m','venv','--without-pip','--symlinks',str(environment)],check=True,capture_output=True)
            program=Path(root)/'probe.py'
            program.write_text('import sys,json\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(TOOLS))+')\nfrom runtime_python import ensure_package_interpreter\nensure_package_interpreter(Path(__file__).parent)\nprint(json.dumps({"prefix":sys.prefix,"argv":sys.argv[1:]}))\n')
            for binary in (sys.executable,str(environment/'bin'/'python')):
                result=subprocess.run([binary,str(program),'value with spaces','--role','patient'],check=True,capture_output=True,text=True,timeout=15)
                data=json.loads(result.stdout)
                self.assertEqual(Path(data['prefix']).resolve(),environment.resolve())
                self.assertEqual(data['argv'],['value with spaces','--role','patient'])


if __name__=='__main__':unittest.main()
