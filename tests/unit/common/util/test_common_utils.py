# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

import json
import unittest

from docpipe.utils.core.collections import (
    batch_list,
    get_index,
    get_list_from_map,
    get_map_from_map,
    lowercase_keys,
    process_in_batches,
)
from docpipe.utils.core.patterns import Singleton
from docpipe.utils.core.strings import (
    escape_query_value,
    get_truncated_text,
    is_null_or_empty,
    split_text_into_chunks,
    trim_whitespace_span,
)
from docpipe.utils.core.validation import (
    is_date_time_as_per_format,
    is_value_in_range,
    to_bool,
)


class TestSingleton(unittest.TestCase):
    """Test the Singleton metaclass."""

    def test_singleton_creates_single_instance(self):
        """Test that Singleton ensures only one instance is created."""

        class TestClass(metaclass=Singleton):
            def __init__(self, value=None):
                self.value = value

        instance1 = TestClass(value=10)
        instance2 = TestClass(value=20)

        # Both should be the same instance
        self.assertIs(instance1, instance2)
        # Value should be from first instantiation
        self.assertEqual(instance1.value, 10)
        self.assertEqual(instance2.value, 10)

    def test_singleton_different_classes(self):
        """Test that different classes have different singleton instances."""

        class ClassA(metaclass=Singleton):
            pass

        class ClassB(metaclass=Singleton):
            pass

        instance_a = ClassA()
        instance_b = ClassB()

        self.assertNotEqual(type(instance_a), type(instance_b))


class TestLowercaseKeys(unittest.TestCase):
    """Test the lowercase_keys function."""

    def test_lowercase_keys_basic(self):
        """Test basic key lowercasing."""
        input_dict = {"Name": "John", "AGE": 30, "City": "NYC"}
        result = lowercase_keys(input_dict=input_dict)
        expected = {"name": "John", "age": 30, "city": "NYC"}
        self.assertEqual(result, expected)

    def test_lowercase_keys_empty_dict(self):
        """Test with empty dictionary."""
        result = lowercase_keys(input_dict={})
        self.assertEqual(result, {})

    def test_lowercase_keys_already_lowercase(self):
        """Test with already lowercase keys."""
        input_dict = {"name": "John", "age": 30}
        result = lowercase_keys(input_dict=input_dict)
        self.assertEqual(result, input_dict)


class TestBatchList(unittest.TestCase):
    """Test the batch_list function."""

    def test_batch_list_even_division(self):
        """Test batching with even division."""
        input_list = list(range(10))
        result = batch_list(input_list=input_list, batch_size=5)
        expected = [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
        self.assertEqual(result, expected)

    def test_batch_list_uneven_division(self):
        """Test batching with uneven division."""
        input_list = list(range(7))
        result = batch_list(input_list=input_list, batch_size=3)
        expected = [[0, 1, 2], [3, 4, 5], [6]]
        self.assertEqual(result, expected)

    def test_batch_list_default_size(self):
        """Test batching with default batch size."""
        input_list = list(range(25))
        result = batch_list(input_list=input_list)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 20)
        self.assertEqual(len(result[1]), 5)

    def test_batch_list_empty(self):
        """Test batching empty list."""
        result = batch_list(input_list=[], batch_size=5)
        self.assertEqual(result, [])


class TestProcessInBatches(unittest.TestCase):
    """Test the process_in_batches function."""

    def test_process_in_batches_basic(self):
        """Test basic batch processing."""

        def processor(batch, batch_number, start_index_offset):
            return [x * 2 for x in batch]

        input_list = [1, 2, 3, 4, 5]
        result = process_in_batches(processor=processor, input_list=input_list, batch_size=2)
        expected = [2, 4, 6, 8, 10]
        self.assertEqual(result, expected)

    def test_process_in_batches_with_kwargs(self):
        """Test batch processing with additional kwargs."""

        def processor(batch, batch_number, start_index_offset, multiplier=1):
            return [x * multiplier for x in batch]

        input_list = [1, 2, 3, 4]
        result = process_in_batches(processor=processor, input_list=input_list, batch_size=2, multiplier=3)
        expected = [3, 6, 9, 12]
        self.assertEqual(result, expected)

    def test_process_in_batches_none_results(self):
        """Test batch processing when processor returns None."""

        def processor(batch, batch_number, start_index_offset):
            return None

        input_list = [1, 2, 3]
        result = process_in_batches(processor=processor, input_list=input_list, batch_size=2)
        self.assertEqual(result, [])

    def test_process_in_batches_non_list_input(self):
        """Test batch processing with non-list input (e.g., tuple)."""

        def processor(batch, batch_number, start_index_offset):
            return list(batch)

        input_tuple = (1, 2, 3, 4)
        result = process_in_batches(processor=processor, input_list=input_tuple, batch_size=2)
        expected = [1, 2, 3, 4]
        self.assertEqual(result, expected)


class TestSplitTextIntoChunks(unittest.TestCase):
    """Test the split_text_into_chunks function."""

    def test_split_text_basic(self):
        """Test basic text splitting."""
        text = "Para1\n\nPara2\n\nPara3"
        result = split_text_into_chunks(text=text, min_size=5, max_size=15)
        self.assertIsInstance(result, list)
        self.assertTrue(all(isinstance(chunk, str) for chunk in result))

    def test_split_text_single_paragraph(self):
        """Test with single paragraph."""
        text = "This is a single paragraph"
        result = split_text_into_chunks(text=text, min_size=10, max_size=100)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], text)

    def test_split_text_empty(self):
        """Test with empty text."""
        result = split_text_into_chunks(text="", min_size=10, max_size=100)
        self.assertEqual(result, [])

    def test_split_text_large_paragraph(self):
        """Test with paragraph larger than max_size."""
        text = "A" * 5000 + "\n\n" + "B" * 5000
        result = split_text_into_chunks(text=text, min_size=3000, max_size=4000)
        self.assertTrue(len(result) >= 2)


class TestGetIndex(unittest.TestCase):
    """Test the get_index function."""

    def test_get_index_found(self):
        """Test finding an element in list."""
        items = ["a", "b", "c", "d"]
        result = get_index(items=items, key="c")
        self.assertEqual(result, 2)

    def test_get_index_not_found(self):
        """Test element not in list."""
        items = ["a", "b", "c"]
        result = get_index(items=items, key="z")
        self.assertEqual(result, -1)

    def test_get_index_first_element(self):
        """Test finding first element."""
        items = [1, 2, 3]
        result = get_index(items=items, key=1)
        self.assertEqual(result, 0)

    def test_get_index_empty_list(self):
        """Test with empty list."""
        result = get_index(items=[], key="a")
        self.assertEqual(result, -1)


class TestToBool(unittest.TestCase):
    """Test the to_bool function."""

    def test_to_bool_true_boolean(self):
        """Test with boolean True."""
        self.assertTrue(to_bool(True))

    def test_to_bool_false_boolean(self):
        """Test with boolean False."""
        self.assertFalse(to_bool(False))

    def test_to_bool_string_true(self):
        """Test with string 'true'."""
        self.assertTrue(to_bool("true"))
        self.assertTrue(to_bool("TRUE"))
        self.assertTrue(to_bool("  true  "))

    def test_to_bool_string_false(self):
        """Test with string 'false'."""
        self.assertFalse(to_bool("false"))
        self.assertFalse(to_bool("FALSE"))

    def test_to_bool_numeric(self):
        """Test with numeric values."""
        self.assertFalse(to_bool(1))
        self.assertFalse(to_bool(0))
        self.assertFalse(to_bool(1.5))

    def test_to_bool_none(self):
        """Test with None."""
        self.assertFalse(to_bool(None))

    def test_to_bool_other_strings(self):
        """Test with other string values."""
        self.assertFalse(to_bool("yes"))
        self.assertFalse(to_bool("1"))
        self.assertFalse(to_bool(""))


class TestIsDateTimeAsPerFormat(unittest.TestCase):
    """Test the is_date_time_as_per_format function."""

    def test_valid_date_format(self):
        """Test with valid date matching format."""
        self.assertTrue(is_date_time_as_per_format("2024-01-15", "%Y-%m-%d"))
        self.assertTrue(is_date_time_as_per_format("15/01/2024", "%d/%m/%Y"))

    def test_invalid_date_format(self):
        """Test with date not matching format."""
        self.assertFalse(is_date_time_as_per_format("2024-01-15", "%d/%m/%Y"))
        self.assertFalse(is_date_time_as_per_format("15/01/2024", "%Y-%m-%d"))

    def test_invalid_date_value(self):
        """Test with invalid date value."""
        self.assertFalse(is_date_time_as_per_format("2024-13-45", "%Y-%m-%d"))
        self.assertFalse(is_date_time_as_per_format("not-a-date", "%Y-%m-%d"))

    def test_datetime_with_time(self):
        """Test with datetime including time."""
        self.assertTrue(is_date_time_as_per_format("2024-01-15 14:30:00", "%Y-%m-%d %H:%M:%S"))


class TestIsNullOrEmpty(unittest.TestCase):
    """Test the is_null_or_empty function."""

    def test_null_value(self):
        """Test with None."""
        self.assertTrue(is_null_or_empty(None))

    def test_empty_string(self):
        """Test with empty string."""
        self.assertTrue(is_null_or_empty(""))

    def test_whitespace_string(self):
        """Test with whitespace (should return False - no trimming)."""
        self.assertFalse(is_null_or_empty("   "))

    def test_non_empty_string(self):
        """Test with non-empty string."""
        self.assertFalse(is_null_or_empty("hello"))
        self.assertFalse(is_null_or_empty(" hello "))


class TestTrimWhitespaceSpan(unittest.TestCase):
    """Test the trim_whitespace_span function."""

    def test_trims_leading_and_trailing_spaces(self):
        """Spaces on both sides are excluded from the span."""
        text = "  hello  "
        start, end = trim_whitespace_span(text=text, start=0, end=len(text))
        self.assertEqual((start, end), (2, 7))
        self.assertEqual(text[start:end], "hello")

    def test_trims_newlines_and_tabs_inside_a_larger_text(self):
        """Offsets point into the original text, and newlines and tabs count as whitespace."""
        text = "a\n\tb c \n"
        start, end = trim_whitespace_span(text=text, start=1, end=8)
        self.assertEqual(text[start:end], "b c")

    def test_leaves_span_without_surrounding_whitespace_unchanged(self):
        """A span that starts and ends on non-whitespace keeps its offsets."""
        self.assertEqual(trim_whitespace_span(text="already", start=0, end=7), (0, 7))

    def test_collapses_whitespace_only_span(self):
        """A whitespace-only span collapses to an empty span inside its bounds."""
        start, end = trim_whitespace_span(text="x   y", start=1, end=4)
        self.assertEqual(start, end)
        self.assertTrue(1 <= start <= 4)

    def test_empty_span_stays_empty(self):
        """An empty span is returned unchanged."""
        self.assertEqual(trim_whitespace_span(text="", start=0, end=0), (0, 0))


class TestGetListFromMap(unittest.TestCase):
    """Test the get_list_from_map function."""

    def test_get_list_valid(self):
        """Test getting valid list of dicts."""
        obj = {"items": [{"id": 1}, {"id": 2}]}
        result = get_list_from_map(obj, "items")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])

    def test_get_list_mixed_types(self):
        """Test with mixed types in list (filters non-dicts)."""
        obj = {"items": [{"id": 1}, "string", 123, {"id": 2}]}
        result = get_list_from_map(obj, "items")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])

    def test_get_list_not_list(self):
        """Test when value is not a list."""
        obj = {"items": "not a list"}
        result = get_list_from_map(obj, "items")
        self.assertEqual(result, [])

    def test_get_list_missing_key(self):
        """Test with missing key."""
        obj: dict[str, list] = {"other": []}
        result = get_list_from_map(obj, "items")
        self.assertEqual(result, [])


class TestGetMapFromMap(unittest.TestCase):
    """Test the get_map_from_map function."""

    def test_get_map_valid(self):
        """Test getting valid dict."""
        obj = {"config": {"key": "value"}}
        result = get_map_from_map(obj, "config")
        self.assertEqual(result, {"key": "value"})

    def test_get_map_not_dict(self):
        """Test when value is not a dict."""
        obj = {"config": "not a dict"}
        result = get_map_from_map(obj, "config")
        self.assertEqual(result, {})

    def test_get_map_missing_key(self):
        """Test with missing key."""
        obj: dict[str, dict] = {"other": {}}
        result = get_map_from_map(obj, "config")
        self.assertEqual(result, {})


class TestGetTruncatedText(unittest.TestCase):
    """Test the get_truncated_text function."""

    def test_truncate_plain_text(self):
        """Test truncating plain text."""
        text = "A" * 2000
        result = get_truncated_text(text_string=text, n_chars=100)
        self.assertEqual(len(result), 100)
        self.assertEqual(result, "A" * 100)

    def test_truncate_json_list_of_dicts(self):
        """Test truncating JSON list of dicts."""
        data = [{"id": i, "name": f"item{i}"} for i in range(10)]
        text = json.dumps(data)
        result = get_truncated_text(text_string=text, n_json_entries=3)
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["id"], 0)

    def test_truncate_json_list_of_primitives(self):
        """Test with JSON list of non-dict items."""
        text = json.dumps([1, 2, 3, 4, 5])
        result = get_truncated_text(text_string=text, n_chars=10)
        self.assertEqual(len(result), 10)

    def test_truncate_json_object(self):
        """Test with single JSON object."""
        text = json.dumps({"key": "value" * 100})
        result = get_truncated_text(text_string=text, n_chars=50)
        self.assertEqual(len(result), 50)

    def test_truncate_invalid_json(self):
        """Test with invalid JSON."""
        text = "not valid json" * 100
        result = get_truncated_text(text_string=text, n_chars=50)
        self.assertEqual(len(result), 50)

    def test_truncate_non_string(self):
        """Test with non-string input."""
        result = get_truncated_text(text_string=123, n_chars=10)
        self.assertEqual(result, 123)


class TestIsValueInRange(unittest.TestCase):
    """Test the is_value_in_range function."""

    def test_value_in_range(self):
        """Test value within range."""
        self.assertTrue(is_value_in_range(value=5, min_value=1, max_value=10))
        self.assertTrue(is_value_in_range(value=5.5, min_value=1.0, max_value=10.0))

    def test_value_at_boundaries(self):
        """Test value at range boundaries."""
        self.assertTrue(is_value_in_range(value=1, min_value=1, max_value=10))
        self.assertTrue(is_value_in_range(value=10, min_value=1, max_value=10))

    def test_value_outside_range(self):
        """Test value outside range."""
        self.assertFalse(is_value_in_range(value=0, min_value=1, max_value=10))
        self.assertFalse(is_value_in_range(value=11, min_value=1, max_value=10))

    def test_negative_range(self):
        """Test with negative values."""
        self.assertTrue(is_value_in_range(value=-5, min_value=-10, max_value=0))
        self.assertFalse(is_value_in_range(value=-11, min_value=-10, max_value=0))


class TestEscapeQueryValue(unittest.TestCase):
    """Test the escape_query_value function."""

    def test_escape_basic_string(self):
        """Test escaping basic string."""
        result = escape_query_value("hello world")
        self.assertEqual(result, '"hello world"')

    def test_escape_with_quotes(self):
        """Test escaping string with quotes."""
        result = escape_query_value('say "hello"')
        self.assertEqual(result, '"say \\"hello\\""')

    def test_escape_with_backslashes(self):
        """Test escaping string with backslashes."""
        result = escape_query_value("path\\to\\file")
        self.assertEqual(result, '"path\\\\to\\\\file"')

    def test_escape_with_special_chars(self):
        """Test escaping string with special characters."""
        result = escape_query_value("Flow: Test 2024-01-01T12:00:00Z")
        self.assertEqual(result, '"Flow: Test 2024-01-01T12:00:00Z"')

    def test_escape_empty_string(self):
        """Test escaping empty string."""
        result = escape_query_value("")
        self.assertEqual(result, '""')


if __name__ == "__main__":
    unittest.main()
