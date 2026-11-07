import unittest
from pathlib import Path
import tempfile

import pandas as pd

from src.features.feature_contract import (
    CATEGORICAL_FEATURES,
    FEATURE_ENGINEERING_VERSION,
    LEAKAGE_COLUMNS,
    NUMERIC_FEATURES,
    RAW_ID_COLUMNS,
    learn_category_levels,
    load_category_levels,
    prepare_model_matrix,
    save_category_levels,
)


class FeatureContractResponsibilitiesTests(unittest.TestCase):
    def test_saved_training_levels_keep_unseen_serving_values_unknown(self):
        train = pd.DataFrame({column: ["ب", None, "A"] for column in CATEGORICAL_FEATURES})
        serving = pd.DataFrame({
            **{column: [1, 2, 3] for column in NUMERIC_FEATURES},
            **{column: ["A", None, "new"] for column in CATEGORICAL_FEATURES},
        }, index=[10, 20, 30])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "levels.json"
            save_category_levels(learn_category_levels(train), path)
            levels = load_category_levels(path)
        matrix = prepare_model_matrix(serving, levels)
        self.assertEqual(matrix.index.tolist(), [10, 20, 30])
        for column in CATEGORICAL_FEATURES:
            self.assertEqual(matrix[column].tolist(), ["A", "__MISSING__", "__UNKNOWN__"])
            self.assertEqual(matrix[column].cat.categories.tolist(), [
                "__MISSING__", "__UNKNOWN__", "A", "ب",
            ])

    def test_base_matrix_preserves_schema_and_category_handling(self):
        from src.features import feature_contract

        self.assertTrue(hasattr(feature_contract, "BASE_FEATURES"))
        BASE_FEATURES = feature_contract.BASE_FEATURES
        fit = pd.DataFrame(
            {
                **{column: ["1", "bad"] for column in NUMERIC_FEATURES},
                **{column: ["known", None] for column in CATEGORICAL_FEATURES},
            }
        )
        source = pd.DataFrame(
            {
                **{column: ["2", "bad"] for column in NUMERIC_FEATURES},
                **{column: [None, "new"] for column in CATEGORICAL_FEATURES},
            }
        )
        result = prepare_model_matrix(source, learn_category_levels(fit))

        self.assertEqual(FEATURE_ENGINEERING_VERSION, 2)
        self.assertEqual(BASE_FEATURES, [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES])
        self.assertEqual(result.columns.tolist(), BASE_FEATURES)
        self.assertTrue(set(BASE_FEATURES).isdisjoint(LEAKAGE_COLUMNS))
        self.assertTrue(set(BASE_FEATURES).isdisjoint(RAW_ID_COLUMNS))
        self.assertEqual(result[NUMERIC_FEATURES[0]].tolist()[0], 2.0)
        self.assertTrue(pd.isna(result[NUMERIC_FEATURES[0]].iloc[1]))
        self.assertEqual(str(result[NUMERIC_FEATURES[0]].dtype), "float32")
        category = result[CATEGORICAL_FEATURES[0]]
        self.assertEqual(category.tolist(), ["__MISSING__", "__UNKNOWN__"])
        self.assertEqual(category.cat.categories.tolist(), ["__MISSING__", "__UNKNOWN__", "known"])

    def test_modeling_targets_and_training_weights_preserve_values(self):
        from src.modeling import training_config

        TARGET_GRADE = training_config.TARGET_GRADE
        TARGET_FAIL = training_config.TARGET_FAIL
        training_weights = training_config.training_weights
        self.assertEqual((TARGET_GRADE, TARGET_FAIL), ("final_mark", "is_fail"))
        frame = pd.DataFrame({"part_id": [20213, 20221, None]})
        result = training_weights(frame)
        self.assertEqual(result.tolist(), [0.25, 1.0, 1.0])
        self.assertEqual(str(result.dtype), "float32")


if __name__ == "__main__":
    unittest.main()
