"""Check dotenv initialization without importing the heavyweight application."""

import os
from pathlib import Path
import subprocess
import sys


def test_package_loads_local_dotenv_before_submodules(tmp_path: Path) -> None:
    """Load local defaults while preserving launcher or shell overrides."""
    package = tmp_path / 'backend'
    package.mkdir()
    source = Path(__file__).resolve().parents[1] / '__init__.py'
    (package / '__init__.py').write_bytes(source.read_bytes())
    (tmp_path / '.env').write_text('DOTENV_TEST_LOCAL=local\nDOTENV_TEST_OVERRIDE=file\n')
    environment = {**os.environ, 'DOTENV_TEST_OVERRIDE': 'process'}
    environment.pop('DOTENV_TEST_LOCAL', None)
    subprocess.run(
        [sys.executable, '-c',
         "import backend, os; "
         "assert os.environ['DOTENV_TEST_LOCAL'] == 'local'; "
         "assert os.environ['DOTENV_TEST_OVERRIDE'] == 'process'"],
        cwd=tmp_path, env=environment, check=True,
    )
