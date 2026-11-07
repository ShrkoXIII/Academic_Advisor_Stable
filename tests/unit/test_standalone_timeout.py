import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tools.verify_standalone import run_process


def test_timeout_stops_owned_descendants_before_temporary_cleanup(tmp_path):
    marker = tmp_path / "surviving-worker.txt"
    worker = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).write_text('unexpected worker')"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{worker!r}]); time.sleep(4)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", parent], cwd=tmp_path, env=os.environ.copy(), timeout=0.5)
    time.sleep(2.2)
    assert not marker.exists()
