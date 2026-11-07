"""Read the delivered catalog using the API's existing string-ID representation."""
import pandas as pd

from src import paths
from src.data.cleaning.cleaning_utils import clean_id_columns


def load_catalog(path=None):
    # Parquet stores requirement_type_id as Int64 in the approved cleaner. Keep that
    # file untouched and normalize identifier representation at the serving boundary.
    frame = pd.read_parquet(path if path is not None else paths.CLEAN_DEGREE_COURSE_PATH)
    return clean_id_columns(frame, ["degree_id", "course_id", "course_type_id", "requirement_type_id"])
