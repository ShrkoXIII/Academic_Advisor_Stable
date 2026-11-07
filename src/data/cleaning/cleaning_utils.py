import pandas as pd


NULL_TEXT = ["", "nan", "none", "null", "<na>"]


def clean_column_names(df): 
    df = df.copy()
    df.columns = (
        df.columns.astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", "_", regex=True)
    )
    return df


def clean_id(series):
    values = series.astype("string").str.strip()
    values = values.mask(values.str.lower().isin(NULL_TEXT), pd.NA) # [nulls] -> pd.
    values = values.str.replace(r"^(\d+)\.0+$", r"\1", regex=True) ## 123.0 -> 123
    return values


def clean_id_columns(df, columns):
    df = df.copy()
    for column in columns:
        df[column] = clean_id(df[column])
    return df


def extract_university_id(series):
    values = clean_id(series)
    return values.str.extract(r"\.([^.]+)$", expand=False).astype("string") # 123.111 [111]


def to_integer(series):
    return pd.to_numeric(series).astype("Int64")


def to_float(series):
    return pd.to_numeric(series).astype("Float64")
