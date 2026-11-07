"""Keep private runtime data and local credentials outside the source delivery."""
import json
from pathlib import Path
import zipfile

import pytest


def test_source_inventory_excludes_credentials_data_and_old_reports(tmp_path):
    from tools import prepare_release as release
    for name in ("src/main.py", "tests/test_example.py", "tools/build.py", "README.md",
                 ".env.example", ".env", ".env.local", "data/raw/private.parquet",
                 "models/private.txt", "release/old.zip", "docs/migration/old.xml"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test content", encoding="utf-8")
    assert set(release.source_files(tmp_path)) == {
        "src/main.py", "tests/test_example.py", "tools/build.py", "README.md", ".env.example"}


@pytest.mark.parametrize("name", [".env", ".env.local", "data/raw/private.parquet", "../escape.py"])
def test_source_archive_refuses_a_private_or_escaping_member(tmp_path, name):
    from tools import prepare_release as release
    with pytest.raises(ValueError):
        release.write_archive(tmp_path, tmp_path / "source.zip", [name], kind="source", snapshot="test")
    assert not (tmp_path / "source.zip").exists()


def test_archive_validation_rejects_changed_bytes_and_unlisted_members(tmp_path):
    from tools import prepare_release as release
    (tmp_path / "README.md").write_text("reviewed source", encoding="utf-8")
    good = tmp_path / "source.zip"
    release.write_archive(tmp_path, good, ["README.md"], kind="source", snapshot="test")
    assert release.verify_archive(good)["kind"] == "source"
    with zipfile.ZipFile(good) as archive:
        manifest = archive.read("RELEASE-MANIFEST.json")
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(changed, "w") as archive:
        archive.writestr("RELEASE-MANIFEST.json", manifest)
        archive.writestr("README.md", "unreviewed replacement")
    with pytest.raises(ValueError, match="hash"):
        release.verify_archive(changed)
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(extra, "w") as archive:
        archive.writestr("RELEASE-MANIFEST.json", manifest)
        archive.writestr("README.md", "reviewed source")
        archive.writestr("../outside", "unlisted file")
    with pytest.raises(ValueError):
        release.verify_archive(extra)


def test_source_review_refuses_even_an_empty_tracked_environment_file(tmp_path):
    from tools import prepare_release as release
    release.git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("source", encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    release.git(tmp_path, "add", "--", "README.md", ".env")
    with pytest.raises(ValueError, match="Private/generated"):
        release.reviewed_source(tmp_path, ["README.md"])
