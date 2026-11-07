"""Create reviewed source and private-runtime archives; never train or commit."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (".gitattributes", ".gitignore", ".env.example", "README.md", "pyproject.toml",
              "requirements.lock", "docs/api_contract.md", "docs/CHANGELOG.md",
              "docs/architecture.md", "docs/data_dictionary.md", "docs/limitations.md")
RUNTIME_FILES = (
    "models/grade_regressor.txt", "models/fail_risk_classifier.txt", "models/model_metadata.json",
    "models/shortlist/grade_model.txt", "models/shortlist/fail_model.txt",
    "models/shortlist/category_levels.json", "models/shortlist/manifest.json",
    "models/shortlist_training/grade_regressor.txt", "models/shortlist_training/fail_risk_classifier.txt",
    "models/shortlist_training/category_levels.json", "models/shortlist_training/model_metadata.json",
    "data/artifacts/category_levels.json", "data/artifacts/build_manifest.json",
    "data/artifacts/history/as_of_20243/course_history_state.pkl",
    "data/artifacts/history/as_of_20243/metadata.json",
    "data/artifacts/history/as_of_20251/course_history_state.pkl",
    "data/artifacts/history/as_of_20251/metadata.json",
    "data/raw/v_acs_grade.parquet", "data/clean/degree_course.parquet",
    "data/clean/student_course.parquet", "data/clean/student_status.parquet",
    "data/clean/registration_roster.parquet",
    "data/evaluation/plan_gpa_course_predictions_2025.parquet",
    "data/evaluation/plan_gpa_metrics_2025.json",
)


def valid_relative(name):
    value = PurePosixPath(name)
    return bool(name and not value.is_absolute() and ".." not in value.parts
                and "\\" not in name and ":" not in name and name == value.as_posix())


def source_allowed(name):
    parts = PurePosixPath(name).parts
    return valid_relative(name) and (name in ROOT_FILES or
        (len(parts) > 1 and parts[0] in {"src", "tools", "tests"}
         and name.endswith(".py") and "__pycache__" not in parts))


def source_files(root):
    root = Path(root)
    files = [name for name in ROOT_FILES if (root / name).is_file()]
    for directory in ("src", "tools", "tests"):
        files.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob("*.py")
                     if p.is_file() and "__pycache__" not in p.parts)
    return sorted(files)


def git(root, *arguments):
    return subprocess.check_output(["git", "--no-optional-locks", "-c",
        f"safe.directory={Path(root).resolve().as_posix()}", *arguments], cwd=root)


def reviewed_source(root, files):
    tracked = set(git(root, "ls-files", "-z").decode().split("\0")) - {""}
    prohibited = [name for name in tracked if Path(name).name in {".env", ".env.local"}
                  or (name.startswith(("data/", "models/", "release/", ".api-state/"))
                      and not name.endswith(".gitkeep"))]
    if prohibited:
        raise ValueError("Private/generated paths remain in the Git index: " + ", ".join(prohibited))
    missing = set(files) - tracked
    if missing:
        raise ValueError("Source files must be staged/tracked before packaging: " + ", ".join(sorted(missing)))
    if git(root, "diff", "--name-only", "--", *files).strip():
        raise ValueError("Stage the reviewed source changes before packaging.")
    return {name: git(root, "show", ":" + name) for name in files}


def write_archive(root, destination, files, *, kind, snapshot, blobs=None):
    files = list(files)
    allowed = source_allowed if kind == "source" else lambda name: name in RUNTIME_FILES
    if kind not in {"source", "runtime-private"} or len(files) != len(set(files)):
        raise ValueError("Invalid package kind or duplicate package members.")
    if any(not valid_relative(name) or not allowed(name) for name in files):
        raise ValueError("Package contains a private, unexpected or escaping member.")
    root = Path(root).resolve()
    content = {}
    for name in sorted(files):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Package member is linked outside the project.")
        content[name] = blobs[name] if blobs is not None else path.read_bytes()
    manifest = {"schema_version": 1, "kind": kind, "source_snapshot_sha256": snapshot,
        "classification": "student-data-private" if kind == "runtime-private" else "source-only",
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                  for name, data in content.items()}}
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in {**content, "RELEASE-MANIFEST.json":
                           json.dumps(manifest, sort_keys=True, indent=2).encode()}.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return manifest


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(not valid_relative(name) for name in names):
            raise ValueError("Unsafe or duplicate archive member.")
        manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
        files, kind = manifest["files"], manifest["kind"]
        if manifest["schema_version"] != 1 or set(names) != set(files) | {"RELEASE-MANIFEST.json"}:
            raise ValueError("Archive contains unlisted or missing files.")
        if kind == "source":
            if not all(source_allowed(name) for name in files):
                raise ValueError("Source archive contains private content.")
        elif kind == "runtime-private":
            if set(files) != set(RUNTIME_FILES):
                raise ValueError("Runtime archive is incomplete or includes unexpected files.")
        else:
            raise ValueError("Unknown package kind.")
        for name, expected in files.items():
            data = archive.read(name)
            if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ValueError("Archive content hash mismatch: " + name)
        return manifest


def extract_archive(path, target):
    manifest = verify_archive(path)
    target = Path(target).resolve()
    with zipfile.ZipFile(path) as archive:
        for name in manifest["files"]:
            destination = target / name
            if not destination.resolve().is_relative_to(target):
                raise ValueError("Archive destination escapes the project.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(archive.read(name))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    files = source_files(ROOT)
    if args.list:
        print("SOURCE / GIT:\n" + "\n".join(files))
        print("\nRUNTIME PRIVATE / NEVER GIT:\n" + "\n".join(RUNTIME_FILES))
        return
    blobs = reviewed_source(ROOT, files)
    signature = {name: hashlib.sha256(data).hexdigest() for name, data in blobs.items()}
    snapshot = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    for name in RUNTIME_FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError("Required runtime asset missing: " + name)
    # Loading performs validation only; no rebuild, fitting, publishing or history update.
    from src.recommendation.two_stage_engine import TwoStagePlanRecommender
    from src.features.frozen_history import load_frozen_history
    engine = TwoStagePlanRecommender.load()
    for cutoff in (20243, 20251):
        load_frozen_history(cutoff, dataset_version="V2")
    for evidence in engine.artifacts.manifest["ranking_policy"]["human_approval"]["evidence"].values():
        if hashlib.sha256(blobs[evidence["path"]]).hexdigest() != evidence["sha256"]:
            raise ValueError("Packaged approval evidence differs from the pinned bytes.")
    output = args.output_dir.resolve()
    if output == ROOT or not output.is_relative_to(ROOT):
        raise ValueError("Release output must be a dedicated directory inside Stable.")
    source, runtime = output / "academic-advisor-stable-source.zip", output / "academic-advisor-stable-runtime-private.zip"
    if source.exists() or runtime.exists():
        raise FileExistsError("Release packages already exist; choose a new output directory.")
    output.mkdir(parents=True, exist_ok=True)
    write_archive(ROOT, source, files, kind="source", snapshot=snapshot, blobs=blobs)
    write_archive(ROOT, runtime, RUNTIME_FILES, kind="runtime-private", snapshot=snapshot)
    for path in (source, runtime):
        manifest = verify_archive(path)
        print(f"{path.relative_to(ROOT)}: {len(manifest['files'])} files; {path.stat().st_size} bytes; "
              f"SHA256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("Prepared from the Git index; no commit, push, training, or legacy access performed.")


if __name__ == "__main__":
    main()
