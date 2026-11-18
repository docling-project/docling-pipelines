import time

import pyarrow as pa

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.redaction import RedactionOperator


class TestRedactionOperator:
    """Test cases for RedactionOperator"""

    def test_redaction_with_simple_word(self):
        """Test redacting a simple word"""
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "X",
            "redaction_regex": "John",
        }
        operator = RedactionOperator(config=config)

        content = pa.array(["John Doe is here", "Mary Smith is there", "John and John again"])
        names = pa.array(["doc1", "doc2", "doc3"])
        ids = pa.array([1, 2, 3])
        input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

        table_list, metadata = operator.transform(input_table)

        assert len(table_list) == 1
        output_table = table_list[0]

        # Check redacted content
        redacted_content = output_table["content"].to_pylist()
        assert redacted_content[0] == "XXXX Doe is here"
        assert redacted_content[1] == "Mary Smith is there"  # No match
        assert redacted_content[2] == "XXXX and XXXX again"

        # Check redaction stats
        stats = output_table["redaction_stats"].to_pylist()
        assert stats[0] == 1
        assert stats[1] == 0
        assert stats[2] == 2

        # Check metadata — PROCESSED_DOCS counts all rows that passed through the operator
        assert metadata[Metrics.External.PROCESSED_DOCS] == 3
        assert metadata["total_redactions"] == 3

    def test_redaction_with_regex_pattern(self):
        """Test redacting with a regex pattern (SSN)"""
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "*",
            "redaction_regex": r"\d{3}-\d{2}-\d{4}",
        }
        operator = RedactionOperator(config=config)

        content = pa.array(["SSN: 123-45-6789", "No SSN here", "Multiple: 111-22-3333 and 444-55-6666"])
        names = pa.array(["doc1", "doc2", "doc3"])
        ids = pa.array([1, 2, 3])
        input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

        table_list, _ = operator.transform(input_table)

        output_table = table_list[0]
        redacted_content = output_table["content"].to_pylist()

        assert redacted_content[0] == "SSN: ***********"
        assert redacted_content[1] == "No SSN here"
        assert redacted_content[2] == "Multiple: *********** and ***********"

        stats = output_table["redaction_stats"].to_pylist()
        assert stats[0] == 1
        assert stats[1] == 0
        assert stats[2] == 2

    def test_redaction_with_no_pattern(self):
        """Test operator behavior when no pattern is provided"""
        config = {"doc_column": "content", "stats_column": "redaction_stats"}
        operator = RedactionOperator(config=config)

        content = pa.array(["Some content"])
        names = pa.array(["doc1"])
        ids = pa.array([1])
        input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

        table_list, metadata = operator.transform(input_table)

        # Should return original table unchanged
        assert len(table_list) == 1
        assert table_list[0] == input_table
        assert metadata[Metrics.External.NODE_STATUS] == "CompletedWithWarnings"

    def test_redaction_with_custom_masking_character(self):
        """Test redaction with custom masking character"""
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "#",
            "redaction_regex": "secret",
        }
        operator = RedactionOperator(config=config)

        content = pa.array(["This is a secret message"])
        names = pa.array(["doc1"])
        ids = pa.array([1])
        input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

        table_list, _metadata = operator.transform(input_table)

        output_table = table_list[0]
        redacted_content = output_table["content"].to_pylist()
        assert redacted_content[0] == "This is a ###### message"

    def test_get_metadata(self):
        """Test get_metadata returns correct structure"""
        config = {"doc_column": "content", "redaction_regex": "test"}
        operator = RedactionOperator(config=config)
        metadata = operator.get_metadata()

        assert OperatorConstants.Misc.CATEGORY in metadata
        assert OperatorConstants.Misc.LABEL in metadata
        assert metadata[OperatorConstants.Misc.LABEL] == "Redaction"
        assert OperatorConstants.Config.FEATURES in metadata
        assert OperatorConstants.Config.ATTRIBUTES in metadata

    def test_get_required_features(self):
        """Test get_required_features returns default doc_column"""
        config = {"doc_column": "my_content", "redaction_regex": "test"}
        operator = RedactionOperator(config=config)
        required = operator.get_required_features()

        assert required == ["content"]  # Returns default column name

    def test_validate_with_empty_pattern(self):
        """Test validation warns when pattern is empty"""
        config = {"doc_column": "content", "redaction_regex": ""}
        operator = RedactionOperator(config=config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content"]

        operator.validate(errors, warnings, available_features)

        assert len(warnings) == 1
        assert "empty" in warnings[0].lower()

    def test_validate_with_unsupported_pattern(self):
        """Test validation errors when pattern uses RE2-unsupported constructs (e.g. lookaheads)."""
        config = {"doc_column": "content", "redaction_regex": r"(?<=\s)\w+"}
        operator = RedactionOperator(config=config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features = ["content"]

        operator.validate(errors, warnings, available_features)

        assert len(errors) == 1
        assert "unsupported" in errors[0].lower()

    def test_unsupported_pattern_falls_back_to_literal_match(self):
        """When RE2 rejects a pattern (e.g. lookbehind), it falls back to literal string matching."""
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "*",
            "redaction_regex": r"(?<=\s)\w+",  # lookbehind — unsupported by RE2
        }
        operator = RedactionOperator(config=config)

        # The literal string r"(?<=\s)\w+" should not match anything in normal text
        content = pa.array(["hello world", "no match here"])
        names = pa.array(["doc1", "doc2"])
        ids = pa.array([1, 2])
        input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

        table_list, metadata = operator.transform(input_table)

        assert len(table_list) == 1
        # No matches expected — content is unchanged
        assert table_list[0]["content"].to_pylist() == ["hello world", "no match here"]
        assert metadata["total_redactions"] == 0

    def test_catastrophic_pattern_completes_in_linear_time(self):
        """Patterns that cause catastrophic backtracking in stdlib re must complete quickly under re2."""
        large_doc = "a" * 100_000
        for pattern in ["(a+)+b", "([a-zA-Z]+)*\\d"]:
            config = {
                "doc_column": "content",
                "stats_column": "redaction_stats",
                "redaction_regex": pattern,
            }
            operator = RedactionOperator(config=config)
            content = pa.array([large_doc])
            names = pa.array(["doc1"])
            ids = pa.array([1])
            input_table = pa.Table.from_arrays([ids, names, content], names=["id", "name", "content"])

            t0 = time.perf_counter()
            table_list, _ = operator.transform(input_table)
            elapsed = time.perf_counter() - t0

            assert elapsed < 1.0, f"Pattern '{pattern}' took {elapsed:.2f}s on 100KB input — ReDoS regression"
            assert len(table_list) == 1

    def test_doclang_xml_redaction_preserves_dom_structure(self):
        """Test that doc_format=doclang redacts text inside XML tags while preserving tags and attributes."""
        xml_content = (
            '<doc lang="en">'
            '<paragraph id="1">Customer John Doe submitted report.</paragraph>'
            '<paragraph id="2">Contact: John at test@example.com</paragraph>'
            "</doc>"
        )
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "*",
            "redaction_regex": "John",
            "doc_format": "doclang",
        }
        operator = RedactionOperator(config=config)

        input_table = pa.Table.from_arrays(
            [pa.array([1]), pa.array(["doc1"]), pa.array([xml_content])],
            names=["id", "name", "content"],
        )

        table_list, metadata = operator.transform(input_table)
        assert len(table_list) == 1
        output_table = table_list[0]

        redacted_content = output_table["content"].to_pylist()[0]
        # Tags and attributes must be intact
        assert '<doc lang="en">' in redacted_content
        assert '<paragraph id="1">' in redacted_content
        assert '<paragraph id="2">' in redacted_content
        # Target word "John" redacted inside tags
        assert "Customer **** Doe submitted report." in redacted_content
        assert "Contact: **** at test@example.com" in redacted_content
        assert "John" not in redacted_content

        assert output_table["redaction_stats"].to_pylist()[0] == 2
        assert metadata["total_redactions"] == 2

    def test_doclang_xml_redaction_handles_tail_text(self):
        """Test that text in element.tail is also redacted."""
        xml_content = "<root><bold>John</bold> Doe is here</root>"
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "X",
            "redaction_regex": "Doe",
            "doc_format": "doclang",
        }
        operator = RedactionOperator(config=config)

        input_table = pa.Table.from_arrays(
            [pa.array([1]), pa.array(["doc1"]), pa.array([xml_content])],
            names=["id", "name", "content"],
        )

        table_list, metadata = operator.transform(input_table)
        redacted_content = table_list[0]["content"].to_pylist()[0]

        assert "<root><bold>John</bold> XXX is here</root>" == redacted_content
        assert metadata["total_redactions"] == 1

    def test_doclang_malformed_xml_fallback(self):
        """Test that malformed XML falls back to standard text redaction without raising an exception."""
        malformed_xml = "<doc><unclosed>John Doe"
        config = {
            "doc_column": "content",
            "stats_column": "redaction_stats",
            "redaction_masking_character": "*",
            "redaction_regex": "John",
            "doc_format": "doclang",
        }
        operator = RedactionOperator(config=config)

        input_table = pa.Table.from_arrays(
            [pa.array([1]), pa.array(["doc1"]), pa.array([malformed_xml])],
            names=["id", "name", "content"],
        )

        table_list, metadata = operator.transform(input_table)
        redacted_content = table_list[0]["content"].to_pylist()[0]
        assert "<doc><unclosed>**** Doe" == redacted_content
        assert metadata["total_redactions"] == 1
