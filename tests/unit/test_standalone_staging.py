from tools.verify_standalone import stage_project


def test_staging_copies_source_and_raw_but_never_generated_data_or_secrets(tmp_path):
    source, target = tmp_path / "source", tmp_path / "independent"
    files = {"src/__init__.py": b"", "data/raw/source.parquet": b"original raw bytes",
             "data/clean/old.parquet": b"do not copy", "data/features/old.parquet": b"do not copy",
             "models/old.txt": b"do not copy", ".env": b"private secret"}
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    stage_project(source, target)
    assert (target / "src/__init__.py").is_file()
    assert (target / "data/raw/source.parquet").read_bytes() == files["data/raw/source.parquet"]
    assert not (target / "models").exists()
    assert not (target / "data/clean").exists()
    assert not (target / "data/features").exists()
    assert not (target / ".env").exists()
