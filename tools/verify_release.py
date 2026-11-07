"""Verify the two delivery archives in a fresh environment, without rebuilding or training."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen
import venv

from tools.prepare_release import ROOT, extract_archive, verify_archive
from tools.verify_standalone import run_process


def build_example(catalog):
    """Fictional student/registration, bound to the delivered degree catalog only."""
    import pandas as pd
    from tests.synthetic_api import sample_request
    eligible = catalog.dropna(subset=["degree_id", "course_id", "course_credits", "credits_count",
                                      "requirement_type_id", "course_type_id", "year_order", "semester_order"]).copy()
    credits = pd.to_numeric(eligible.course_credits)
    eligible = eligible[(credits > 0) & (credits <= 6)
                        & (pd.to_numeric(eligible.credits_count) >= 2 * credits)]
    selected = None
    for _, group in eligible.groupby(["degree_id", "course_credits"], sort=True):
        if len(group) >= 4:
            selected = group.sort_values("course_id", kind="stable").head(4)
            break
    if selected is None:
        raise ValueError("The delivered catalog lacks four compatible courses for the documented synthetic probe.")
    request = sample_request()
    student, degree = "release-synthetic-student", str(selected.degree_id.iloc[0])
    request.update(student_id=student, degree_id=degree,
                   target_credits=2 * float(selected.course_credits.iloc[0]))
    for context in request["source_contexts"].values():
        context.update(student_id=student, degree_id=degree)
    data = request["student_api_response"]["data"]
    for row in [data["studentDegreeInfo"], *data["studentSummaryInfo"]]:
        row.update(STUDENT_ID=student, DEGREE_ID=degree)
    template = request["courses_api_response"]["data"]["availableCourses"][0]
    rows, modes = [], {}
    for index, row in enumerate(selected.to_dict("records")):
        group = f"release-group-{index}"
        modes[group] = "strict_remaining"
        rows.append(dict(template, COURSE_ID=str(row["course_id"]),
            COURSE_NAME_SL="Synthetic release course " + str(index + 1),
            COURSE_CREDITS=float(row["course_credits"]), REQUIREMENT_TYPE_ID=str(row["requirement_type_id"]),
            REQUIREMENT_ID=group, CREDITS_COUNT=float(row["credits_count"]), REQUIREMENT_PASSED_CREDITS=0,
            YEAR_ORDER=int(row["year_order"]), SEMESTER_ORDER=int(row["semester_order"])))
    request["courses_api_response"]["data"]["availableCourses"] = rows
    request["integration_context"]["registration_policy"]["requirement_group_modes"] = modes
    registration = {key: request[key] for key in ("student_id", "degree_id", "part_id")}
    registration.update(source="synthetic-release-registration-not-university-evidence",
        courses=[{"course_id": row["COURSE_ID"], "course_credits": row["COURSE_CREDITS"]} for row in rows[:2]])
    return request, registration


def probe(api_url, streamlit_url):
    """Real HTTP and real fitted models; no mocked transport or model objects."""
    import pandas as pd
    import requests
    from streamlit.testing.v1 import AppTest
    from src import paths
    from src.features.frozen_history import load_frozen_history
    from src.recommendation.two_stage_engine import TwoStagePlanRecommender
    from tools.academic_advisor_streamlit.ui_client import Config
    config = Config.from_env()
    engine = TwoStagePlanRecommender.load()
    for cutoff in (20243, 20251):
        load_frozen_history(cutoff, dataset_version="V2")
    print("Four delivered models, both frozen prefixes and approval contracts loaded", flush=True)
    assert requests.get(api_url + "/health", timeout=15).json()["recommendation_readiness"]["ready"]
    assert requests.get(streamlit_url + "/_stcore/health", timeout=15).text == "ok"
    request, registration = build_example(pd.read_parquet(paths.CLEAN_DEGREE_COURSE_PATH))
    response = requests.post(api_url + "/api/v1/recommendations", json=request,
        headers={"X-API-Key": config.service_key}, timeout=60)
    if response.status_code != 200:
        raise AssertionError(f"Delivered API rejected synthetic contract: {response.status_code}: {response.text}")
    result = response.json()
    assert result["status"] == "ok" and len(result["recommendations"]) == 3
    for plan in result["recommendations"]:
        assert math.isfinite(plan["expected_plan_gpa"]) and math.isfinite(plan["projected_cumulative_gpa"])
        assert len(plan["courses"]) == 2
        for course in plan["courses"]:
            assert 0 <= course["predicted_mark"] <= 100
            assert 0 <= course["expected_points"] <= 4
    print("Real HTTP JSON contract returned three plans with marks, points and GPAs", flush=True)
    app = AppTest.from_file(str(ROOT / "tools/academic_advisor_streamlit/streamlit_app.py"), default_timeout=60).run()
    assert not app.exception
    app.text_area[0].set_value(json.dumps(request))
    app.button(key="run_evaluation").click().run()
    assert not app.exception and len(app.session_state["evaluation"]["result"]["recommendations"]) == 3
    # AppTest does not provide file-upload injection. Supply the parsed, explicitly fictional
    # registration through session state; scoring and rendering remain the real application.
    state = dict(app.session_state["evaluation"])
    state["registration"] = registration
    app.session_state["evaluation"] = state
    app.run()
    assert not app.exception
    assert not any("تعذر استكمال" in warning.value for warning in app.warning)
    observed = app.dataframe[0].value
    assert len(observed) == 2 and {"predicted_mark", "expected_points", "expected_grade"}.issubset(observed.columns)
    comparison = app.dataframe[-1].value
    assert comparison["plan"].tolist() == ["Actual registered plan", "Top 1", "Top 2", "Top 3"]
    assert comparison["predicted_semester_gpa"].notna().all()
    assert comparison["predicted_cumulative_gpa"].notna().all()
    assert comparison["actual_semester_gpa"].isna().all()
    print("Streamlit rendered observed-plan predictions, three alternatives, marks and GPA comparison", flush=True)
    print("Synthetic student/registration only; no university connection or real-student acceptance established", flush=True)


def stop_owned(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()


def free_port():
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        return endpoint.getsockname()[1]


def wait_ready(process, url):
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Owned verification service exited during startup.")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("Verification service did not become ready.")


def verify_delivery(source, runtime):
    manifests = [verify_archive(path) for path in (source, runtime)]
    if ([m["kind"] for m in manifests] != ["source", "runtime-private"]
            or manifests[0]["source_snapshot_sha256"] != manifests[1]["source_snapshot_sha256"]):
        raise ValueError("Source and runtime packages do not belong to the same release snapshot.")
    temporary = Path(tempfile.mkdtemp(prefix="academic-advisor-release-")).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not temporary.is_relative_to(temp_root) or temporary == temp_root:
        raise ValueError("Unsafe verification workspace.")
    processes, logs = [], []
    try:
        target, guard = temporary / "project", temporary / "guard"
        for path in (source, runtime):
            extract_archive(path, target)
        guard.mkdir()
        attempts = guard / "forbidden-access.log"
        blocked = [os.path.normcase(str(ROOT)), os.path.normcase(str(ROOT.parent / "Academic_Advisor_Simple"))]
        (guard / "sitecustomize.py").write_text(f'''import os, sys
blocked = {blocked!r}
def check(event, args):
    if event not in ("open", "os.listdir", "os.scandir") or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = os.path.normcase(os.path.realpath(os.path.abspath(os.fsdecode(args[0]))))
    if any(path == root or path.startswith(root + os.sep) for root in blocked):
        with open({str(attempts)!r}, "a") as stream:
            stream.write("Forbidden original repository access\\n")
        raise RuntimeError("Original repositories are unavailable in release verification")
sys.addaudithook(check)
sys._stable_guard_active = True
''', encoding="utf-8")
        print("Creating fresh environment from source + private runtime archives; no data build or training", flush=True)
        environment = target / ".venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = {k: v for k, v in os.environ.items() if not k.startswith("ADVISOR_")}
        env.update(PYTHONPATH=str(guard), PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   OMP_NUM_THREADS="4", STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")

        def run(label, args, timeout=600):
            print(label, flush=True)
            result = run_process([str(python), "-B", *args], cwd=target, env=env, timeout=timeout)
            print("\n".join(result.stdout.splitlines()[-12:]), flush=True)
            if result.returncode:
                raise RuntimeError(f"Release verification failed: {label} ({result.returncode})")

        run("Checking Python access guard", ["-c", "import sys; assert sys._stable_guard_active"])
        run("Installing locked dependencies and the source package", ["-m", "pip", "install", "--timeout", "120",
            "--retries", "3", "-r", "requirements.lock", "-e", ".[api,ui,dev]"], timeout=1200)
        run("Checking dependency consistency", ["-m", "pip", "check"])
        for key in ("ADVISOR_API_KEY", "ADVISOR_ADMIN_API_KEY", "ADVISOR_FINALIZATION_API_KEY"):
            env[key] = secrets.token_urlsafe(32)
        api_port, ui_port = free_port(), free_port()
        while ui_port == api_port:
            ui_port = free_port()
        api_url, ui_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
        env["ADVISOR_UI_FASTAPI_URL"] = api_url
        (target / ".env.local").write_text("\n".join(f"{key}={env[key]}" for key in
            ("ADVISOR_API_KEY", "ADVISOR_ADMIN_API_KEY", "ADVISOR_FINALIZATION_API_KEY", "ADVISOR_UI_FASTAPI_URL")), encoding="utf-8")
        commands = (["-m", "uvicorn", "src.api.app:create_app", "--factory", "--env-file", ".env.local",
                     "--host", "127.0.0.1", "--port", str(api_port)],
                    ["-m", "streamlit", "run", "tools/academic_advisor_streamlit/streamlit_app.py",
                     "--server.address", "127.0.0.1", "--server.port", str(ui_port),
                     "--server.headless", "true", "--browser.gatherUsageStats", "false"])
        for name, command, health in zip(("api", "streamlit"), commands,
                                        (api_url + "/health", ui_url + "/_stcore/health")):
            print("Starting delivered " + name, flush=True)
            log = (temporary / (name + ".log")).open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen([str(python), "-B", *command], cwd=target, env=env,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
            processes.append(process)
            wait_ready(process, health)
        run("Exercising real HTTP, delivered models and Streamlit rendering", ["-m", "tools.verify_release",
            "--probe", "--api-url", api_url, "--streamlit-url", ui_url])
        run("Running the delivered regression suite", ["-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--tb=short", "-rs"])
        for manifest in manifests:
            for name, expected in manifest["files"].items():
                if hashlib.sha256((target / name).read_bytes()).hexdigest() != expected["sha256"]:
                    raise ValueError("Verification changed a delivered file: " + name)
        if attempts.exists():
            raise RuntimeError("An audited Python access to an original repository occurred.")
        print("PASS: clean delivery export, fresh installation, four existing models, frozen history, real HTTP/Streamlit, observed-plan prediction; no retraining", flush=True)
    finally:
        for process in reversed(processes):
            stop_owned(process)
        for log in logs:
            log.close()
        if temporary.is_relative_to(temp_root) and temporary != temp_root:
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "release/academic-advisor-stable-source.zip")
    parser.add_argument("--runtime", type=Path, default=ROOT / "release/academic-advisor-stable-runtime-private.zip")
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--streamlit-url", default="http://127.0.0.1:8501")
    args = parser.parse_args()
    if args.probe:
        probe(args.api_url, args.streamlit_url)
    else:
        verify_delivery(args.source.resolve(), args.runtime.resolve())


if __name__ == "__main__":
    main()
