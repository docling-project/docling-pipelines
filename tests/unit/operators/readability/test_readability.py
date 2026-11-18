"""Unit tests for ReadabilityOperator using pyphen-based implementation."""

import inspect
import unittest

import pyarrow as pa

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.readability.readability_operator import (
    DEFAULT_READABILITY_SCORES,
    ReadabilityOperator,
)


class TestReadabilityOperator(unittest.TestCase):
    def test_init(self):
        config = {
            "doc_column": "content",
            "readability_score_list": ["flesch_reading_ease", "flesch_kincaid_grade"],
        }
        operator = ReadabilityOperator(config=config)
        self.assertIsNotNone(operator, "Readability Operator is not None")
        self.assertEqual(operator.contents_column_name, "content")
        self.assertIn("flesch_reading_ease", operator.score_list)

    def test_readability_metadata(self):
        operator = ReadabilityOperator(config={"readability_score_list": ["flesch_reading_ease"]})
        metadata = operator.get_metadata()

        self.assertIn(OperatorConstants.Misc.SDK, metadata)
        self.assertTrue(metadata[OperatorConstants.Misc.SDK])
        self.assertIn(OperatorConstants.Misc.CATEGORY, metadata)
        self.assertIn(OperatorConstants.Misc.LABEL, metadata)
        self.assertEqual(metadata[OperatorConstants.Misc.LABEL], "Readability Operator")
        self.assertIn(OperatorConstants.Config.FEATURES, metadata)
        self.assertIn("flesch_reading_ease", metadata[OperatorConstants.Config.FEATURES])

    def test_readability_transform(self):
        config = {
            "doc_column": "content",
            "readability_score_list": ["flesch_reading_ease", "flesch_kincaid_grade"],
        }
        operator = ReadabilityOperator(config=config)

        content = pa.array(
            [
                "The cat sat on the mat. It was a sunny day.",
                "Python is a high-level programming language used for web development.",
                "The implementation of sophisticated algorithms necessitates comprehensive understanding.",
            ]
        )
        test_table = pa.Table.from_arrays([content], names=["content"])

        table_list, metadata = operator.transform(table=test_table)

        self.assertEqual(len(table_list), 1)
        transformed_table = table_list[0]

        self.assertIn("flesch_reading_ease", transformed_table.column_names)
        self.assertIn("flesch_kincaid_grade", transformed_table.column_names)

        self.assertIn(Metrics.External.PROCESSED_DOCS, metadata)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 3)

    def test_readability_required_features(self):
        config = {
            "doc_column": "content",
            "readability_score_list": ["flesch_reading_ease", "flesch_kincaid_grade"],
        }
        operator = ReadabilityOperator(config=config)
        required_features = operator.get_required_features()

        self.assertEqual(len(required_features), 1)
        self.assertIn("content", required_features)

    def test_readability_validation_warning(self):
        operator = ReadabilityOperator(config={"readability_score_list": []})
        errors: list[str] = []
        warnings: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=["content"])

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("at least one readability score must be selected", warnings[0].lower())

    def test_readability_all_scores(self):
        config = {
            "doc_column": "content",
            "readability_score_list": DEFAULT_READABILITY_SCORES,
        }

        operator = ReadabilityOperator(config=config)
        content = pa.array(["This is a simple test sentence."])
        test_table = pa.Table.from_arrays([content], names=["content"])

        table_list, _ = operator.transform(table=test_table)
        transformed_table = table_list[0]
        for score in DEFAULT_READABILITY_SCORES:
            self.assertIn(score, transformed_table.column_names)


class TestReadabilityOperatorEdgeCases(unittest.TestCase):
    def test_empty_table(self):
        data: dict[str, list[str]] = {"content": []}
        empty_table = pa.table(data)

        operator = ReadabilityOperator(
            config={
                "doc_column": "content",
                "readability_score_list": ["flesch_reading_ease"],
            }
        )

        result_tables, metadata = operator.transform(table=empty_table)
        self.assertEqual(result_tables[0].num_rows, 0)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 0)

    def test_custom_column_name(self):
        custom_col = "my_text"
        content = pa.array(["Test document content."])
        test_table = pa.Table.from_arrays([content], names=[custom_col])

        operator = ReadabilityOperator(
            config={
                "doc_column": custom_col,
                "readability_score_list": ["flesch_reading_ease"],
            }
        )

        result_tables, _ = operator.transform(table=test_table)

        self.assertEqual(result_tables[0].num_rows, 1)
        self.assertIn("flesch_reading_ease", result_tables[0].column_names)

    def test_validation_invalid_scores(self):
        operator = ReadabilityOperator(config={"readability_score_list": ["invalid_score", "another_invalid"]})
        errors: list[str] = []
        warnings: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=["content"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("invalid", warnings[0].lower())

    def test_multiple_documents_varying_complexity(self):
        content = pa.array(
            [
                "Cat.",
                "The quick brown fox jumps over the lazy dog.",
                "Python is a high-level programming language.",
                "The implementation of sophisticated algorithms necessitates comprehensive understanding.",
            ]
        )
        test_table = pa.Table.from_arrays([content], names=["content"])

        operator = ReadabilityOperator(
            config={
                "doc_column": "content",
                "readability_score_list": [
                    "flesch_reading_ease",
                    "flesch_kincaid_grade",
                    "gunning_fog",
                ],
            }
        )

        result_tables, metadata = operator.transform(table=test_table)
        result_table = result_tables[0]

        self.assertEqual(result_table.num_rows, 4)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 4)
        self.assertIn("flesch_reading_ease", result_table.column_names)
        self.assertIn("flesch_kincaid_grade", result_table.column_names)
        self.assertIn("gunning_fog", result_table.column_names)


class TestReadabilityMetrics(unittest.TestCase):
    """Test the underlying readability metrics implementation."""

    def test_syllable_counting(self):
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        metrics = ReadabilityMetrics()

        # Test syllable counting
        self.assertEqual(metrics.count_syllables(word="hello"), 2)
        self.assertEqual(metrics.count_syllables(word="cat"), 1)
        self.assertEqual(metrics.count_syllables(word="programming"), 3)
        self.assertEqual(metrics.count_syllables(word=""), 0)
        self.assertEqual(metrics.count_syllables(word="a"), 1)  # At least 1 syllable

    def test_easy_words_list(self):
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        metrics = ReadabilityMetrics()

        # Verify word list is loaded
        self.assertGreater(len(metrics.easy_words), 0)
        self.assertGreaterEqual(len(metrics.easy_words), 2900)  # Should have ~2940 words

        # Common words should be in the list
        self.assertIn("the", metrics.easy_words)
        self.assertIn("cat", metrics.easy_words)

        # Complex words should not be in easy word list
        self.assertNotIn("sophisticated", metrics.easy_words)
        self.assertNotIn("implementation", metrics.easy_words)


class TestReadabilityMetricsStaticMethods(unittest.TestCase):
    """Verify formula methods are static and callable without an instance."""

    STATIC_FORMULA_METHODS = (
        "get_words",
        "count_characters",
        "flesch_reading_ease",
        "flesch_kincaid_grade",
        "gunning_fog",
        "smog_index",
        "coleman_liau_index",
        "automated_readability_index",
        "dale_chall_readability_score",
        "difficult_words",
        "text_standard",
        "spache_readability",
        "mcalpine_eflaw",
        "reading_time",
    )

    def test_formula_methods_are_static(self):
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        for method_name in self.STATIC_FORMULA_METHODS:
            with self.subTest(method=method_name):
                self.assertIsInstance(inspect.getattr_static(ReadabilityMetrics, method_name), staticmethod)

    def test_formula_methods_callable_on_class_without_instance(self):
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        stats = ReadabilityMetrics().text_stats(text="The cat sat on the mat. It was sunny.")

        # Every static formula must be invocable directly on the class.
        for method_name in self.STATIC_FORMULA_METHODS:
            method = getattr(ReadabilityMetrics, method_name)
            with self.subTest(method=method_name):
                if method_name == "get_words":
                    result = method(text="Hello world")
                elif method_name == "count_characters":
                    result = method(words=["hello", "world"])
                elif method_name == "reading_time":
                    result = method(stats=stats, wpm=200)
                else:
                    result = method(stats=stats)
                self.assertIsNotNone(result)

    def test_instance_and_class_calls_agree(self):
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        metrics = ReadabilityMetrics()
        stats = metrics.text_stats(text="The cat sat on the mat. It was sunny.")

        self.assertEqual(
            metrics.flesch_reading_ease(stats=stats),
            ReadabilityMetrics.flesch_reading_ease(stats=stats),
        )
        self.assertEqual(
            metrics.text_standard(stats=stats),
            ReadabilityMetrics.text_standard(stats=stats),
        )

    def test_syllable_methods_remain_instance_methods(self):
        """count_syllables/count_syllables_in_text use self.dic and must stay instance-bound."""
        from docpipe.core.operators.quality.readability.readability_metrics import ReadabilityMetrics

        self.assertNotIsInstance(inspect.getattr_static(ReadabilityMetrics, "count_syllables"), staticmethod)
        self.assertNotIsInstance(inspect.getattr_static(ReadabilityMetrics, "count_syllables_in_text"), staticmethod)

        metrics = ReadabilityMetrics()
        self.assertEqual(metrics.count_syllables(word="hello"), 2)
        self.assertEqual(metrics.count_syllables_in_text(words=["hello", "cat"]), 3)


if __name__ == "__main__":
    unittest.main()
