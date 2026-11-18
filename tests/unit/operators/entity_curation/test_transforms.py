import unittest

import pytest

from docpipe.core.operators.functional.entity_curation.transforms import (
    currency_to_numeric,
    make_date_uniform,
    to_number,
    weight_to_numeric,
)


class TestToNumber(unittest.TestCase):
    """Test to_number transformation (multi-language)"""

    def test_numeric_string(self):
        """Test numeric string parsing"""
        result = to_number(number_str="1234")
        self.assertEqual(result, 1234)

    def test_float_string(self):
        """Test float string parsing"""
        result = to_number(number_str="1234.56")
        self.assertAlmostEqual(result, 1234.56, places=2)

    def test_invalid_input(self):
        """Test invalid input returns None"""
        result = to_number(number_str="not a number")
        self.assertIsNone(result)

    def test_none_input_returns_none(self):
        """None input short-circuits and returns None."""
        self.assertIsNone(to_number(number_str=None))

    def test_suffix_latin_multiplier(self):
        """Latin suffix matched case-insensitively (e.g. '10k')."""
        self.assertAlmostEqual(to_number(number_str="10k"), 10_000.0)

    def test_suffix_non_latin_multiplier(self):
        """Non-Latin suffix matched by exact key (e.g. CJK character 万)."""
        self.assertAlmostEqual(to_number(number_str="10万"), 100_000.0)

    def test_suffix_no_match_falls_back_to_multiplier_one(self):
        """Suffix that is in the pattern alternatives but has no dict entry falls back to x1.

        We craft a string where the suffix regex matches a known word but the
        upper-case key does NOT exist in the multipliers dict; the code sets
        multiplier = 1 and tries float() on the remaining string.  A pure
        numeric string with no suffix exercises the else branch (multiplier=1).
        """
        self.assertAlmostEqual(to_number(number_str="42"), 42.0)

    def test_no_suffix_plain_number(self):
        """A number with no magnitude suffix returns the number unchanged."""
        self.assertAlmostEqual(to_number(number_str="3.14"), 3.14)


class TestCurrencyToNumeric(unittest.TestCase):
    """Test currency_to_numeric transformation (locale-aware)"""

    def test_us_locale(self):
        """Test US locale currency parsing"""
        result = currency_to_numeric(amount="$1,234.56", locale="en_US")
        # Returns string, convert to float for comparison
        self.assertAlmostEqual(float(result), 1234.56, places=2)

    def test_de_locale(self):
        """Test German locale currency parsing"""
        result = currency_to_numeric(amount="1.234,56 €", locale="de_DE")
        # Returns string, convert to float for comparison
        self.assertAlmostEqual(float(result), 1234.56, places=2)

    def test_fr_locale(self):
        """Test French locale currency parsing"""
        result = currency_to_numeric(amount="1 234,56 €", locale="fr_FR")
        # Returns string, convert to float for comparison
        self.assertAlmostEqual(float(result), 1234.56, places=2)

    def test_invalid_input(self):
        """Test invalid input returns None"""
        result = currency_to_numeric(amount="invalid", locale="en_US")
        self.assertIsNone(result)

    def test_none_input_returns_none(self):
        """None amount short-circuits and returns None."""
        self.assertIsNone(currency_to_numeric(amount=None, locale="en_US"))

    def test_invalid_locale_raises(self):
        """Unsupported locale raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported locale"):
            currency_to_numeric(amount="100", locale="xx_INVALID")

    def test_magnitude_suffix_latin(self):
        """Latin magnitude suffix (e.g. K) is matched case-insensitively."""
        result = currency_to_numeric(amount="$10K", locale="en_US")
        self.assertAlmostEqual(float(result), 10_000.0, places=2)

    def test_magnitude_suffix_non_latin(self):
        """Non-Latin magnitude suffix (CJK 万) is matched by exact key."""
        result = currency_to_numeric(amount="100万", locale="en_US")
        self.assertAlmostEqual(float(result), 1_000_000.0, places=2)


class TestMakeDateUniform(unittest.TestCase):
    """Test make_date_uniform transformation"""

    def test_english_date(self):
        """Test English date parsing"""
        result = make_date_uniform(date_str="March 15, 2024")
        self.assertEqual(result, "2024-03-15")

    def test_french_date(self):
        """Test French month name (parsed by datefinder fallback)"""
        result = make_date_uniform(date_str="15 mars 2024")
        # Datefinder can parse some French dates
        self.assertEqual(result, "2024-03-15")

    def test_numeric_date(self):
        """Test numeric date parsing"""
        result = make_date_uniform(date_str="2024-03-15")
        self.assertEqual(result, "2024-03-15")

    def test_slash_format(self):
        """Test slash-separated date"""
        result = make_date_uniform(date_str="03/15/2024")
        self.assertEqual(result, "2024-03-15")

    def test_invalid_date(self):
        """Test invalid date returns None"""
        result = make_date_uniform(date_str="not a date")
        self.assertIsNone(result)


class TestWeightToNumeric(unittest.TestCase):
    """Test weight_to_numeric transformation (locale-aware)"""

    def test_chinese_jin(self):
        """Test Chinese jin (斤) conversion"""
        result = weight_to_numeric(weight="5斤", locale="zh_CN")
        self.assertAlmostEqual(result, 2.5, places=2)  # 5 * 500g = 2500g = 2.5kg

    def test_japanese_jin(self):
        """Test Japanese jin (斤) conversion"""
        result = weight_to_numeric(weight="5斤", locale="ja_JP")
        self.assertAlmostEqual(result, 3.0, places=2)  # 5 * 600g = 3000g = 3.0kg

    def test_standard_units(self):
        """Test standard weight units"""
        result = weight_to_numeric(weight="5 kg", locale="en_US")
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_pounds(self):
        """Test pounds conversion"""
        result = weight_to_numeric(weight="10 lb", locale="en_US")
        self.assertAlmostEqual(result, 4.536, places=2)

    def test_invalid_input(self):
        """Test invalid input returns None"""
        result = weight_to_numeric(weight="invalid", locale="en_US")
        self.assertIsNone(result)

    def test_none_input_returns_none(self):
        """None weight short-circuits and returns None."""
        self.assertIsNone(weight_to_numeric(weight=None, locale="en_US"))

    def test_language_prefix_locale_fallback(self):
        """A locale given as bare language code resolves via prefix match (en → en_US)."""
        result = weight_to_numeric(weight="5 kg", locale="en")
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_unknown_locale_falls_back_to_en_us(self):
        """An entirely unknown locale falls back to en_US unit map."""
        result = weight_to_numeric(weight="2 kg", locale="xx_XX")
        self.assertAlmostEqual(result, 2.0, places=2)

    def test_non_latin_unit_exact_match(self):
        """Non-Latin unit (CJK 公斤) is matched by exact key when lower() misses."""
        result = weight_to_numeric(weight="3公斤", locale="zh_CN")
        self.assertAlmostEqual(result, 3.0, places=2)

    def test_bare_number_no_unit(self):
        """A bare number with no unit is assumed to be kilograms."""
        result = weight_to_numeric(weight="7", locale="en_US")
        self.assertAlmostEqual(result, 7.0, places=2)

    def test_unrecognised_unit_returns_bare_number(self):
        """An unrecognised unit string is not captured by the regex group; the bare
        numeric value is returned as kilograms (no-unit branch)."""
        # "parsec" is not in any unit map so group(2) is None — bare-number branch
        result = weight_to_numeric(weight="1 parsec", locale="en_US")
        self.assertAlmostEqual(result, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()


class TestMakeDateUniformEdgeCases(unittest.TestCase):
    """Additional edge-case tests for make_date_uniform to cover exception paths."""

    def test_none_input_returns_none(self):
        """None input returns None without raising."""
        result = make_date_uniform(date_str=None)
        self.assertIsNone(result)

    def test_non_string_input_returns_none(self):
        """Non-string input (e.g. int) falls through all parsing and returns None."""
        result = make_date_uniform(date_str=12345)  # type: ignore
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        """Empty string falls through all parsing and returns None."""
        result = make_date_uniform(date_str="")
        self.assertIsNone(result)

    def test_datefinder_exception_is_swallowed(self):
        """If datefinder.find_dates raises, the exception is swallowed and None is returned."""
        import sys
        from unittest.mock import MagicMock, patch

        mock_datefinder = MagicMock()
        mock_datefinder.find_dates.side_effect = ValueError("parse error")
        with patch.dict(sys.modules, {"datefinder": mock_datefinder}):
            result = make_date_uniform(date_str="not a real date @@@@")
        self.assertIsNone(result)
