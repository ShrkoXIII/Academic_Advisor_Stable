from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class GradeScale:
    pass_bands: pd.DataFrame

    @classmethod
    def from_parquet(cls, path):
        grades = pd.read_parquet(path)
        return cls(grades[grades["finish_status"].eq("P")].copy())

    def validate_versions(self, grade_version_ids):
        """Return numeric versions only when every ID has loaded passing bands."""
        raw_versions = pd.Series(
            [None] if grade_version_ids is None else grade_version_ids, dtype=object
        )
        versions = pd.to_numeric(raw_versions, errors="coerce").to_numpy(dtype="float64")
        supported = pd.to_numeric(
            self.pass_bands["grade_version_id"], errors="coerce"
        ).to_numpy(dtype="float64")
        invalid = ~np.isfinite(versions) | ~np.isin(versions, supported)
        if invalid.any():
            rejected = raw_versions.iloc[np.flatnonzero(invalid)].tolist()
            raise ValueError(f"Unsupported or invalid grade_version_id: {rejected!r}.")
        return versions

    def convert(self, predicted_marks, grade_version_ids):
        marks = np.asarray(predicted_marks, dtype="float64")
        versions = self.validate_versions(grade_version_ids)
        if len(versions) != len(marks):
            raise ValueError(f"Supply one grade_version_id per mark; received {grade_version_ids!r}.")
        points = np.zeros(len(marks), dtype="float64")
        grade_labels = np.full(len(marks), "F", dtype=object)

        for version in np.unique(versions[~np.isnan(versions)]):
            bands = self.pass_bands[
                pd.to_numeric(
                    self.pass_bands["grade_version_id"], errors="coerce"
                ).eq(version)
            ].sort_values("from_percent")
            thresholds = bands["from_percent"].to_numpy(dtype="float64")
            band_points = bands["points"].to_numpy(dtype="float64")
            band_labels = bands["grade_show"].astype("string").to_numpy(dtype=object)

            row_mask = versions == version
            row_positions = np.flatnonzero(row_mask)
            selected = np.searchsorted(
                thresholds,
                marks[row_mask],
                side="right",
            ) - 1
            passed = selected >= 0
            points[row_positions[passed]] = band_points[selected[passed]]
            grade_labels[row_positions[passed]] = band_labels[selected[passed]]

        return points, grade_labels
