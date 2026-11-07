"""Target definitions and the current training weight policy."""

import pandas as pd


TARGET_GRADE = "final_mark"
TARGET_FAIL = "is_fail"


def training_weights(frame):
    year = pd.to_numeric(frame["part_id"], errors="coerce").floordiv(10)
    return year.lt(2022).map({True: 0.25, False: 1.0}).astype("float32")
