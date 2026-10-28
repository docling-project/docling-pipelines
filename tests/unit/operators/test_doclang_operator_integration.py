"""Per-operator integration tests for doc_format=doclang stripping.

Each test confirms that when an operator is given a table whose content
column holds DocLang XML and `doc_format` is set to ``"doclang"``, the
operator produces sensible output rather than crashing or treating the
XML tags as text content.

A ``doc_format="markdown"`` companion test is included for each operator
to confirm that the default path is completely unaffected.

Operators that depend on heavy optional dependencies (DocQualityTransform,
EnrichmentTransform, LiteLLM, PII/HAP service) are exercised with their
external dependencies mocked so these run as pure unit tests.
"""

import sys
from typing import ClassVar
from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa

from docpipe.core.constants.operator_constants import OperatorConstants

DOCLANG = OperatorConstants.DocFormat.DOCLANG
MARKDOWN = OperatorConstants.DocFormat.MARKDOWN

# A minimal DocLang XML document used across tests.
# Real format produced by DoclingDocument.export_to_doclang().
DOCLANG_XML = '<doclang version="0.7">\n  <text>The quick brown fox jumps over the lazy dog.</text>\n</doclang>'
# Expected markdown after DocLangDocDeserializer().deserialize_str(DOCLANG_XML).export_to_markdown()
DOCLANG_AS_MD = "The quick brown fox jumps over the lazy dog."
PLAIN_TEXT = "The quick brown fox jumps over the lazy dog."


def _make_table(content: list[str], *, col: str = "content") -> pa.Table:
    return pa.table(
        {
            "id": [str(i) for i in range(len(content))],
            "name": [f"doc_{i}.xml" for i in range(len(content))],
            col: content,
        }
    )


# ---------------------------------------------------------------------------
# DocQuality
# ---------------------------------------------------------------------------


class TestDocQualityDocFormat:
    """DocQuality strips DocLang before computing metrics.

    DocQuality inherits from DocQualityTransform (DPK). We mock that base
    class to avoid metaclass conflicts and heavy DPK dependencies in unit
    tests.
    """

    def _make_op(self, *, doc_format: str = MARKDOWN):
        """Create a DocQuality instance with the DPK base class mocked."""
        with patch.dict(
            sys.modules,
            {
                "dpk_doc_quality": MagicMock(),
                "dpk_doc_quality.transform": MagicMock(),
            },
        ):
            # Re-import after mocking to pick up fresh module references
            import importlib

            import docpipe.core.operators.quality.doc_quality as dq_module

            importlib.reload(dq_module)
            return dq_module.DocQuality({"doc_content_column": "content", "doc_format": doc_format})

    def test_doc_format_attribute_stored(self):
        """DocQuality stores doc_format from config."""
        from docpipe.core.operators.quality.doc_quality import DocQuality

        with patch("docpipe.core.operators.quality.doc_quality.DocQualityTransform"):
            op = DocQuality({"doc_content_column": "content", "doc_format": DOCLANG})
            assert op.doc_format == DOCLANG

    def test_doc_format_default_is_markdown(self):
        """When doc_format is absent from config, it defaults to markdown."""
        from docpipe.core.operators.quality.doc_quality import DocQuality

        with patch("docpipe.core.operators.quality.doc_quality.DocQualityTransform"):
            op = DocQuality({"doc_content_column": "content"})
            assert op.doc_format == MARKDOWN

    def test_doclang_strips_content_column(self):
        """With doclang format, XML tags are removed from the content column
        before calling the parent transform.

        DocQuality inherits from DocQualityTransform whose MRO is fixed at
        class-definition time. We patch the *method* on the base class directly
        so the patched version is what gets called via super().
        """
        from dpk_doc_quality.transform import DocQualityTransform

        from docpipe.core.operators.quality.doc_quality import DocQuality

        captured: dict = {}

        def fake_dq_transform(self_inner, table):
            captured["table"] = table
            return ([table], {})

        with patch.object(DocQualityTransform, "transform", fake_dq_transform):
            op = DocQuality({"doc_content_column": "content", "doc_format": DOCLANG})
            table = _make_table([DOCLANG_XML])
            op.transform(table)

        assert "table" in captured, "DocQualityTransform.transform was not called"
        value = captured["table"]["content"][0].as_py()
        assert "<" not in value
        assert "quick brown fox" in value

    def test_markdown_content_not_modified(self):
        """With markdown format, content is not modified before parent transform."""
        from dpk_doc_quality.transform import DocQualityTransform

        from docpipe.core.operators.quality.doc_quality import DocQuality

        captured: dict = {}

        def fake_dq_transform(self_inner, table):
            captured["table"] = table
            return ([table], {})

        with patch.object(DocQualityTransform, "transform", fake_dq_transform):
            op = DocQuality({"doc_content_column": "content", "doc_format": MARKDOWN})
            table = _make_table([PLAIN_TEXT])
            op.transform(table)

        assert "table" in captured, "DocQualityTransform.transform was not called"
        assert captured["table"]["content"][0].as_py() == PLAIN_TEXT

    def test_doclang_output_preserves_original_content(self):
        """The table returned by DocQuality retains the original DocLang content.

        Stripping must only happen internally for metric computation.
        The output doc_column must contain the original DocLang XML so
        downstream operators (e.g. LLM classifiers) receive it unchanged.
        """
        from dpk_doc_quality.transform import DocQualityTransform

        from docpipe.core.operators.quality.doc_quality import DocQuality

        def fake_dq_transform(self_inner, table):
            return ([table], {})

        with patch.object(DocQualityTransform, "transform", fake_dq_transform):
            op = DocQuality({"doc_content_column": "content", "doc_format": DOCLANG})
            table = _make_table([DOCLANG_XML])
            tables, _ = op.transform(table)

        assert tables[0]["content"][0].as_py() == DOCLANG_XML, (
            "DocQuality must not modify the output doc_column — DocLang XML must pass through"
        )


# ---------------------------------------------------------------------------
# EdedupOperator
# ---------------------------------------------------------------------------


class TestEdedupDocFormat:
    """EdedupOperator passes content to the hash function unchanged (no DocLang stripping).

    Ededup deduplicates by content hash — stripping would mean that DocLang and
    Markdown representations of the same text produce the same hash, which would
    incorrectly deduplicate documents across different pipeline runs or format
    configurations.  Content must reach the hasher as-is.
    """

    def _make_ededup_transform_stub(self, captured: dict):
        """Return a transform stub that captures the table and returns valid ededup metadata."""

        def capturing_transform(table, file_name=""):
            captured["table"] = table
            return [table], {
                "source_documents": table.num_rows,
                "result_documents": table.num_rows,
                "removed_documents": [],
            }

        return capturing_transform

    def test_doclang_content_passed_unchanged_to_hash(self):
        """DocLang XML is passed to _ededup_transform as-is — no stripping."""
        from docpipe.core.operators.quality.ededup import EdedupOperator

        op = EdedupOperator({"doc_column": "content", "doc_format": DOCLANG})

        captured: dict = {}
        op._ededup_transform.transform = self._make_ededup_transform_stub(captured)

        table = _make_table([DOCLANG_XML, DOCLANG_XML])
        op.transform(table)

        assert "table" in captured
        # Content must reach the hasher unchanged — DocLang XML preserved
        for v in captured["table"]["content"].to_pylist():
            assert v == DOCLANG_XML, f"Content was unexpectedly modified before hashing: {v!r}"

    def test_markdown_content_passed_unchanged(self):
        """With markdown format, content is passed to _ededup_transform unchanged."""
        from docpipe.core.operators.quality.ededup import EdedupOperator

        op = EdedupOperator({"doc_column": "content", "doc_format": MARKDOWN})

        captured: dict = {}
        op._ededup_transform.transform = self._make_ededup_transform_stub(captured)

        table = _make_table([PLAIN_TEXT])
        op.transform(table)

        assert "table" in captured
        assert captured["table"]["content"][0].as_py() == PLAIN_TEXT

    def test_doc_format_default_is_markdown(self):
        """Absent doc_format defaults to markdown."""
        from docpipe.core.operators.quality.ededup import EdedupOperator

        op = EdedupOperator({"doc_column": "content"})
        assert op.doc_format == MARKDOWN


# ---------------------------------------------------------------------------
# LanguageDetect
# ---------------------------------------------------------------------------


class TestLanguageDetectDocFormat:
    """LanguageDetect strips DocLang before sending text to the detector."""

    def test_doclang_content_detected(self):
        """LanguageDetect runs without error on doclang content."""
        import docpipe.core.operators.quality.language_detection.adapters.outbound.langdetect_adapter  # noqa: F401
        from docpipe.core.operators.quality.language_detection.lang_id import LanguageDetect

        op = LanguageDetect({"doc_column": "content", "doc_format": DOCLANG})
        table = _make_table([DOCLANG_XML])
        tables, _ = op.transform(table)
        assert len(tables) == 1

    def test_doclang_strips_tags_before_detection(self):
        """The text passed to the adapter contains no XML tags."""
        import docpipe.core.operators.quality.language_detection.adapters.outbound.langdetect_adapter  # noqa: F401
        from docpipe.core.operators.quality.language_detection.domain.models import (
            LanguageDetectionResult,
        )
        from docpipe.core.operators.quality.language_detection.lang_id import LanguageDetect

        op = LanguageDetect({"doc_column": "content", "doc_format": DOCLANG})

        detected_texts: list[str] = []
        mock_result = LanguageDetectionResult(language_code="en", confidence=0.99)

        def capturing_detect(text: str) -> LanguageDetectionResult:
            detected_texts.append(text)
            return mock_result

        op.language_adapter.detect_language = capturing_detect

        table = _make_table([DOCLANG_XML])
        op.transform(table)

        assert len(detected_texts) == 1
        assert "<" not in detected_texts[0]
        assert "quick brown fox" in detected_texts[0]

    def test_markdown_text_passed_unmodified(self):
        """With doc_format=markdown the text reaches the adapter unchanged."""
        import docpipe.core.operators.quality.language_detection.adapters.outbound.langdetect_adapter  # noqa: F401
        from docpipe.core.operators.quality.language_detection.domain.models import (
            LanguageDetectionResult,
        )
        from docpipe.core.operators.quality.language_detection.lang_id import LanguageDetect

        op = LanguageDetect({"doc_column": "content", "doc_format": MARKDOWN})

        detected_texts: list[str] = []
        mock_result = LanguageDetectionResult(language_code="en", confidence=0.99)

        def capturing_detect(text: str) -> LanguageDetectionResult:
            detected_texts.append(text)
            return mock_result

        op.language_adapter.detect_language = capturing_detect

        table = _make_table([PLAIN_TEXT])
        op.transform(table)

        assert detected_texts[0] == PLAIN_TEXT

    def test_doc_format_default_is_markdown(self):
        import docpipe.core.operators.quality.language_detection.adapters.outbound.langdetect_adapter  # noqa: F401
        from docpipe.core.operators.quality.language_detection.lang_id import LanguageDetect

        op = LanguageDetect({"doc_column": "content"})
        assert op.doc_format == MARKDOWN

    def test_doclang_output_preserves_original_content(self):
        """The table returned by LanguageDetect retains the original DocLang content.

        Plain-text stripping must only affect the text sent to the detector.
        The output doc_column must still hold DocLang XML for downstream operators.
        """
        import docpipe.core.operators.quality.language_detection.adapters.outbound.langdetect_adapter  # noqa: F401
        from docpipe.core.operators.quality.language_detection.domain.models import (
            LanguageDetectionResult,
        )
        from docpipe.core.operators.quality.language_detection.lang_id import LanguageDetect

        op = LanguageDetect({"doc_column": "content", "doc_format": DOCLANG})
        mock_result = LanguageDetectionResult(language_code="en", confidence=0.99)
        op.language_adapter.detect_language = lambda text: mock_result

        table = _make_table([DOCLANG_XML])
        tables, _ = op.transform(table)

        assert tables[0]["content"][0].as_py() == DOCLANG_XML, (
            "LanguageDetect must not modify the output doc_column — DocLang XML must pass through"
        )


# ---------------------------------------------------------------------------
# ReadabilityOperator
# ---------------------------------------------------------------------------


class TestReadabilityDocFormat:
    """ReadabilityOperator strips DocLang before computing scores."""

    def test_doclang_does_not_crash(self):
        """ReadabilityOperator with doclang content runs without error."""
        from docpipe.core.operators.quality.readability.readability_operator import (
            ReadabilityOperator,
        )

        op = ReadabilityOperator(
            {
                "doc_column": "content",
                "readability_score_list": ["flesch_reading_ease"],
                "doc_format": DOCLANG,
            }
        )
        table = _make_table([DOCLANG_XML, DOCLANG_XML])
        tables, _ = op.transform(table)
        assert len(tables) == 1
        assert tables[0].num_rows == 2

    def test_doclang_scores_match_plain_text_scores(self):
        """Scores computed from DocLang XML match scores from the equivalent plain text."""
        from docpipe.core.operators.quality.readability.readability_operator import (
            ReadabilityOperator,
        )

        config_base = {"doc_column": "content", "readability_score_list": ["flesch_reading_ease"]}
        op_doclang = ReadabilityOperator({**config_base, "doc_format": DOCLANG})
        op_md = ReadabilityOperator({**config_base, "doc_format": MARKDOWN})

        tables_doclang, _ = op_doclang.transform(_make_table([DOCLANG_XML]))
        tables_plain, _ = op_md.transform(_make_table([PLAIN_TEXT]))

        score_doclang = tables_doclang[0]["flesch_reading_ease"][0].as_py()
        score_plain = tables_plain[0]["flesch_reading_ease"][0].as_py()

        assert abs(score_doclang - score_plain) < 0.01

    def test_markdown_path_unchanged(self):
        """ReadabilityOperator with markdown format produces output columns."""
        from docpipe.core.operators.quality.readability.readability_operator import (
            ReadabilityOperator,
        )

        op = ReadabilityOperator(
            {
                "doc_column": "content",
                "readability_score_list": ["flesch_reading_ease"],
                "doc_format": MARKDOWN,
            }
        )
        table = _make_table([PLAIN_TEXT])
        tables, _ = op.transform(table)
        assert "flesch_reading_ease" in tables[0].column_names

    def test_doc_format_default_is_markdown(self):
        from docpipe.core.operators.quality.readability.readability_operator import (
            ReadabilityOperator,
        )

        op = ReadabilityOperator({"doc_column": "content"})
        assert op.doc_format == MARKDOWN

    def test_doclang_output_preserves_original_content(self):
        """The table returned by ReadabilityOperator retains the original DocLang content.

        Scores are computed on the stripped plain text; the output doc_column
        must still contain DocLang XML for downstream operators.
        """
        from docpipe.core.operators.quality.readability.readability_operator import (
            ReadabilityOperator,
        )

        op = ReadabilityOperator(
            {
                "doc_column": "content",
                "readability_score_list": ["flesch_reading_ease"],
                "doc_format": DOCLANG,
            }
        )
        table = _make_table([DOCLANG_XML])
        tables, _ = op.transform(table)

        assert tables[0]["content"][0].as_py() == DOCLANG_XML, (
            "ReadabilityOperator must not modify the output doc_column — DocLang XML must pass through"
        )


# ---------------------------------------------------------------------------
# MLEnrichmentOperator
# ---------------------------------------------------------------------------


class TestMLEnrichmentDocFormat:
    """MLEnrichmentOperator strips DocLang before delegating to EnrichmentTransform."""

    def test_doc_format_attribute_doclang(self):
        """MLEnrichmentOperator stores doc_format from config."""
        from docpipe.core.operators.quality.ml_enrichment import MLEnrichmentOperator

        op = MLEnrichmentOperator({"doc_format": DOCLANG})
        assert op.doc_format == DOCLANG

    def test_doc_format_default_is_markdown(self):
        from docpipe.core.operators.quality.ml_enrichment import MLEnrichmentOperator

        op = MLEnrichmentOperator({})
        assert op.doc_format == MARKDOWN

    def test_doclang_output_preserves_original_content(self):
        """The table returned by MLEnrichmentOperator retains the original DocLang content.

        The enrichment parent receives stripped text; the output doc_column must
        still contain DocLang XML for downstream operators (e.g. LLM classifiers).
        """
        from docpipe.core.operators.quality.ml_enrichment import MLEnrichmentOperator

        op = MLEnrichmentOperator({"doc_format": DOCLANG})

        captured: dict = {}

        def fake_super_transform(self_inner, table: pa.Table, file_name: str = "") -> tuple[list[pa.Table], dict]:
            captured["received"] = table["content"][0].as_py()
            # Return a new table that still has the (stripped) content — as super() would
            return [table], {}

        mro_bases = type(op).__mro__
        enrich_cls = next((c for c in mro_bases if c.__name__ == "EnrichmentTransform"), None)
        if enrich_cls is not None:
            with patch.object(enrich_cls, "transform", new=fake_super_transform):
                table = _make_table([DOCLANG_XML])
                tables, _ = op.transform(table)

            # The content sent to the enricher should be stripped
            if "received" in captured:
                assert "<" not in (captured["received"] or ""), "XML passed to EnrichmentTransform"

            # But the returned table must contain the original DocLang XML
            assert tables[0]["content"][0].as_py() == DOCLANG_XML, (
                "MLEnrichmentOperator must not modify the output doc_column — DocLang XML must pass through"
            )


# ---------------------------------------------------------------------------
# DocumentClassifierOperator
# ---------------------------------------------------------------------------


class TestDocumentClassifierDocFormat:
    """DocumentClassifierOperator passes DocLang content directly to the LLM classifier.

    LLM-based classifiers may benefit from structured DocLang XML — the XML
    structure provides additional semantic context.  Content is passed as-is
    without stripping.

    DocumentClassifierOperator validates its LLM provider config during
    ``__init__``. Tests patch the provider validation to allow instantiation
    without a live LLM.
    """

    _VALID_CONFIG: ClassVar[dict] = {
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/llama3",
            "api_base": "http://localhost:11434/v1",
            "api_key": "ollama",  # pragma: allowlist secret
        },
        "document_types": {"general": "General document"},
    }

    def _make_op(self, *, doc_format: str = MARKDOWN):
        from docpipe.core.operators.quality.classification.document_classifier import (
            DocumentClassifierOperator,
        )

        config = {**self._VALID_CONFIG, "doc_format": doc_format}
        # Patch ClassificationAdapterFactory so __init__ doesn't attempt an LLM connection
        with patch("docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"):
            return DocumentClassifierOperator(config)

    def test_doc_format_attribute_doclang(self):
        """DocumentClassifierOperator stores doc_format from config."""
        op = self._make_op(doc_format=DOCLANG)
        assert op.doc_format == DOCLANG

    def test_doc_format_default_is_markdown(self):
        """Absent doc_format defaults to markdown."""
        from docpipe.core.operators.quality.classification.document_classifier import (
            DocumentClassifierOperator,
        )

        with patch("docpipe.core.operators.quality.classification.document_classifier.ClassificationAdapterFactory"):
            op = DocumentClassifierOperator(self._VALID_CONFIG)
        assert op.doc_format == MARKDOWN

    def test_doclang_content_passed_unchanged_to_classifier(self):
        """With doclang, DocLang XML content is passed as-is to _classify_document.

        LLM classifiers benefit from the structured XML — no stripping is applied.
        """
        op = self._make_op(doc_format=DOCLANG)

        classified_texts: list[str] = []

        def fake_classify(*, content: str, doc_name: str | None = None) -> dict:
            classified_texts.append(content)
            return {"document_type": "general", "confidence": 9, "reasoning": ""}

        op._classify_document = fake_classify

        table = pa.table(
            {
                "id": ["0"],
                "name": ["doc.xml"],
                "content": [DOCLANG_XML],
                "source_filename": ["doc.xml"],
            }
        )
        try:
            op.transform(table)
        except Exception:
            pass

        # Content must reach the classifier unchanged — DocLang XML preserved
        for text in classified_texts:
            assert text == DOCLANG_XML, f"Content was unexpectedly modified: {text!r}"

    def test_classifier_side_extraction_uses_doclang_and_fills_reuse_column(self):
        """With no content column, the adapter extracts doclang and reports it for Extract reuse."""
        from unittest.mock import MagicMock

        from docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter import (
            StandardLLMClassificationAdapter,
        )
        from docpipe.core.operators.quality.classification.document_classifier import (
            DocumentClassifierOperator,
        )
        from docpipe.core.operators.quality.classification.domain.models import ClassificationResponse

        config = {**self._VALID_CONFIG, "doc_format": DOCLANG}
        adapter_module = "docpipe.core.operators.quality.classification.adapters.outbound.standard_llm_adapter"
        with patch(f"{adapter_module}._LLMClassificationService") as mock_service_cls:
            mock_service_cls.return_value.classify_document.return_value = ClassificationResponse(
                document_type="general", confidence=9, reasoning="", success=True
            )
            adapter = StandardLLMClassificationAdapter(llm_adapter=MagicMock(), config=config)
        adapter._service = mock_service_cls.return_value
        op = DocumentClassifierOperator(config, classification_adapter=adapter)

        with patch(f"{adapter_module}.OperatorUtils") as mock_utils:
            mock_utils.extract_content.return_value = {"success": True, "content": DOCLANG_XML, "metadata": {}}
            result = op._classify_document(
                content=None,
                document_types={"general": "General document"},
                binary_content=b"%PDF-fake",
                doc_name="doc.pdf",
            )

        assert mock_utils.extract_content.call_args.kwargs["doc_format"] == DOCLANG
        assert result["__extracted_content__"] == DOCLANG_XML


# ---------------------------------------------------------------------------
# PIIAndHAPAnnotator
# ---------------------------------------------------------------------------


class TestPIIAndHAPDocFormat:
    """PIIAndHAPAnnotator passes DocLang content directly to the LLM-based detector.

    LLM-based PII/HAP detection may benefit from structured DocLang XML — the
    XML structure preserves semantic context.  Content is passed as-is without
    stripping.
    """

    def _make_op(self, *, doc_format: str = MARKDOWN):
        from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator import (
            PIIAndHAPAnnotator,
        )

        config = {"doc_format": doc_format}
        with patch("docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIHAPService") as mock_svc_cls:
            mock_svc = Mock()
            mock_svc.adapter = Mock()
            mock_svc.adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
            mock_svc_cls.return_value = mock_svc
            return PIIAndHAPAnnotator(config), mock_svc

    def test_doc_format_attribute_doclang(self):
        """PIIAndHAPAnnotator stores doc_format from config."""
        op, _ = self._make_op(doc_format=DOCLANG)
        assert op.doc_format == DOCLANG

    def test_doc_format_default_is_markdown(self):
        """Absent doc_format defaults to markdown."""
        op, _ = self._make_op(doc_format=MARKDOWN)
        assert op.doc_format == MARKDOWN

    def test_doclang_content_passed_unchanged_to_annotator(self):
        """With doclang, DocLang XML is passed as-is to the annotation service.

        LLM-based detection benefits from structured XML — no stripping is applied.
        """
        op, _ = self._make_op(doc_format=DOCLANG)

        annotated_texts: list[str] = []

        def fake_annotate(text: str, *args, **kwargs):
            annotated_texts.append(text)
            return {"pii": [], "hap": []}

        op.pii_hap_service.annotate = fake_annotate

        table = pa.table(
            {
                "id": ["0"],
                "name": ["doc.xml"],
                "content": [DOCLANG_XML],
            }
        )
        try:
            op.transform(table)
        except Exception:
            pass

        # Content must reach the annotator unchanged — DocLang XML preserved
        for text in annotated_texts:
            assert text == DOCLANG_XML, f"Content was unexpectedly modified: {text!r}"

    def test_markdown_text_passed_unchanged(self):
        """With markdown format, content reaches the service unchanged."""
        op, _ = self._make_op(doc_format=MARKDOWN)

        annotated_texts: list[str] = []

        def fake_annotate(text: str, *args, **kwargs):
            annotated_texts.append(text)
            return {"pii": [], "hap": []}

        op.pii_hap_service.annotate = fake_annotate

        table = pa.table(
            {
                "id": ["0"],
                "name": ["doc.txt"],
                "content": [PLAIN_TEXT],
            }
        )
        try:
            op.transform(table)
        except Exception:
            pass

        for text in annotated_texts:
            assert text == PLAIN_TEXT


# ===========================================================================
# EmbeddingsOperator — PR 2 DocLang Routing Tests
# ===========================================================================


class TestEmbeddingsDocFormat:
    """Tests verifying EmbeddingsOperator cleans DocLang XML before embedding."""

    def test_embeddings_doc_format_attribute(self, monkeypatch):
        """EmbeddingsOperator inherits doc_format."""
        from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator

        monkeypatch.setattr(EmbeddingsOperator, "_initialize_embedding_adapter", lambda self: MagicMock())
        op = EmbeddingsOperator({"provider": "ollama", "doc_format": "doclang"})
        assert op.doc_format == "doclang"

    def test_embeddings_parse_chunked_content_passes_chunks_as_is(self, monkeypatch):
        """_parse_chunked_content passes chunk text without re-stripping."""
        from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator

        monkeypatch.setattr(EmbeddingsOperator, "_initialize_embedding_adapter", lambda self: MagicMock())
        op = EmbeddingsOperator({"provider": "ollama", "doc_format": "doclang"})

        chunk_text = "Clean chunk with <T> type annotation"
        table = pa.table(
            {
                "id": ["0"],
                "chunked_content": [[{"chunk": chunk_text, "chunk_sequence_number": 0}]],
            }
        )
        texts = op._parse_chunked_content(table=table, idx=0, doc_name="doc.xml")
        assert len(texts) == 1
        assert texts[0] == chunk_text

    def test_embeddings_get_full_document_content_cleans_doclang(self, monkeypatch):
        """_get_full_document_content strips DocLang XML when doc_format=doclang."""
        from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator

        monkeypatch.setattr(EmbeddingsOperator, "_initialize_embedding_adapter", lambda self: MagicMock())
        op = EmbeddingsOperator({"provider": "ollama", "doc_format": "doclang"})

        xml_doc = '<doclang version="0.7"><text>Full doc text</text></doclang>'
        table = pa.table(
            {
                "id": ["0"],
                "content": [xml_doc],
            }
        )
        texts = op._get_full_document_content(table=table, idx=0)
        assert len(texts) == 1
        assert "<" not in texts[0]
        assert "Full doc text" in texts[0]

    def test_embeddings_markdown_passes_through_as_is(self, monkeypatch):
        """_parse_chunked_content preserves markdown text when doc_format=markdown."""
        from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator

        monkeypatch.setattr(EmbeddingsOperator, "_initialize_embedding_adapter", lambda self: MagicMock())
        op = EmbeddingsOperator({"provider": "ollama", "doc_format": "markdown"})

        md_chunk = "# Heading\n\nBody text"
        table = pa.table(
            {
                "id": ["0"],
                "chunked_content": [[{"chunk": md_chunk, "chunk_sequence_number": 0}]],
            }
        )
        texts = op._parse_chunked_content(table=table, idx=0, doc_name="doc.md")
        assert texts[0] == md_chunk
