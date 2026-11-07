"""Rebuild in a fresh temporary checkout/environment containing only code and raw inputs."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import venv


def run_process(command, *, cwd, env, timeout):
    process = subprocess.Popen(command, cwd=cwd, env=env, text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt")
    try:
        output, _ = process.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, output)


def stage_project(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("src", "tools", "tests"):
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "requirements.lock", "README.md"):
        if (source / name).is_file():
            shutil.copyfile(source / name, target / name)
    contract = source / "docs/api_contract.md"
    if contract.is_file():
        (target / "docs").mkdir(exist_ok=True)
        shutil.copyfile(contract, target / "docs/api_contract.md")
    raw = target / "data/raw"
    raw.mkdir(parents=True)
    for item in (source / "data/raw").iterdir():
        if item.is_file():
            shutil.copyfile(item, raw / item.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--approval-date", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    temporary = Path(tempfile.mkdtemp(prefix="academic-advisor-cleanroom-")).resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if not temporary.is_relative_to(temporary_root) or temporary == temporary_root:
        raise RuntimeError("Verification workspace is outside the expected temporary root.")
    target, guard = temporary / "project", temporary / "guard"
    try:
        print("Staging source and unchanged raw inputs only", flush=True)
        stage_project(source, target)
        guard.mkdir()
        denied = [os.path.normcase(str(source)),
                  os.path.normcase(str(source.parent / "Academic_Advisor_Simple"))]
        attempts = guard / "forbidden-access.log"
        code = f'''import os, sys
blocked = {denied!r}
def check(event, args):
    if event not in ("open", "os.listdir", "os.scandir") or not args:
        return
    value = args[0]
    if not isinstance(value, (str, bytes, os.PathLike)):
        return
    path = os.path.normcase(os.path.realpath(os.path.abspath(os.fsdecode(value))))
    if any(path == root or path.startswith(root + os.sep) for root in blocked):
        with open({str(attempts)!r}, "a", encoding="utf-8") as stream:
            stream.write("Forbidden original repository access\\n")
        raise RuntimeError("Original repositories are unavailable during standalone verification")
sys.addaudithook(check)
sys._stable_guard_active = True
'''
        (guard / "sitecustomize.py").write_text(code, encoding="utf-8")
        environment = target / ".venv"
        print("Creating independent Python environment", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = {**os.environ, "PYTHONPATH": str(guard), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "OMP_NUM_THREADS": "4",
               "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"}

        def run(label, arguments, *, cwd=target, timeout=600):
            print(label, flush=True)
            result = run_process([str(python), "-B", *arguments], cwd=cwd, env=env, timeout=timeout)
            print("\n".join(result.stdout.splitlines()[-8:]), flush=True)
            if result.returncode:
                raise RuntimeError(f"Standalone stage failed: {label} ({result.returncode})")

        run("Checking isolation guard", ["-c", "import sys; assert getattr(sys, '_stable_guard_active', False)"])
        run("Installing locked dependencies in the new environment",
            ["-m", "pip", "install", "--no-cache-dir", "--timeout", "120", "--retries", "3",
             "-r", "requirements.lock", "-e", "."], timeout=1200)
        run("Checking installed dependencies", ["-m", "pip", "check"])
        from src.main import PIPELINE
        for section in ("data", "features"):
            for step in PIPELINE[section]:
                if step.standard:
                    run("Rebuilding " + step.name, ["-m", step.module])
        for cutoff in (20243, 20251):
            run("Building frozen prefix " + str(cutoff), ["-m", "src.features.build_frozen_history",
                "--as-of-part", str(cutoff), "--finalized-through-part", str(cutoff)])
        for step in PIPELINE["modeling"]:
            if step.standard:
                run("Training " + step.name, ["-m", step.module], timeout=1800)
        run("Publishing newly trained assets", ["-m", "src.modeling.build_artifact_manifest",
            "--approval-reference", args.approval_reference, "--approval-date", args.approval_date])
        for step in PIPELINE["evaluation"]:
            if step.standard:
                run("Evaluating " + step.name, ["-m", step.module])
        run("Checking real API readiness", ["-c", "from src.api.service import ApiService; a=ApiService(); a.initialize(); assert a.health()['recommendation_readiness']['ready']; print('Fresh API assets ready')"])
        unrelated = temporary / "unrelated-working-directory"
        unrelated.mkdir()
        run("Checking a different current directory", ["-m", "src.main", "--list"], cwd=unrelated)
        run("Running the complete standalone tests", ["-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--tb=short", "-rs"], timeout=600)
        if attempts.exists():
            raise RuntimeError("A process attempted to use an original repository.")
        for original in (source / "data/raw").iterdir():
            if original.is_file():
                copied = target / "data/raw" / original.name
                if hashlib.sha256(original.read_bytes()).digest() != hashlib.sha256(copied.read_bytes()).digest():
                    raise RuntimeError("Raw input content changed during verification.")
        print("PASS: code + raw only; fresh environment/data/history/four models/API/UI tests; no audited Python access to original repositories", flush=True)
    finally:
        # This generated, validated OS-temporary directory contains only this verification's files.
        if temporary.is_relative_to(temporary_root) and temporary != temporary_root:
            shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
