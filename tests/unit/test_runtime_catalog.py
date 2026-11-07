import pandas as pd
import pytest


@pytest.mark.parametrize("requirement", [2, "2"])
def test_runtime_catalog_preserves_identifier_values_across_parquet_dtypes(tmp_path, requirement):
    from src.api.catalog import load_catalog
    path = tmp_path / "catalog.parquet"
    frame = pd.DataFrame({"degree_id": ["d"], "course_id": ["c"], "course_type_id": ["3"],
                          "requirement_type_id": [requirement], "course_credits": [3.0], "credits_count": [12.0]})
    frame.to_parquet(path, index=False)
    original = path.read_bytes()
    loaded = load_catalog(path)
    assert loaded.requirement_type_id.tolist() == ["2"]
    assert loaded.course_credits.tolist() == [3.0]
    assert loaded.credits_count.tolist() == [12.0]
    assert loaded.course_id.tolist() == ["c"]
    assert path.read_bytes() == original
