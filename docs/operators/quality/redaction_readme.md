# RedactionOperator

Masks text matching a word or regex pattern with a configurable character. Short name: `redaction` · Category: Quality

## Overview

The RedactionOperator scans each document's content column for text matching a given regular expression and replaces every matched character with a masking character. Use it to redact PII, sensitive keywords, or any structured pattern (emails, phone numbers, SSNs) before storing or embedding documents. Chain multiple instances for different patterns.

## Key Features

- Regex and literal-word matching
- Configurable masking character (`*`, `#`, `X`, etc.)
- Tracks the number of redactions per document in an output column
- Chain multiple redaction operators for different PII types
- Works on any text content column

## Operator Configuration

```json
{
  "name": "redact_emails",
  "type": "redaction",
  "depends_on": ["extract"],
  "config": {
    "redaction_regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
    "redaction_masking_character": "*"   // optional, default "*"
  }
}
```

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `redaction_regex` | `string` | Yes | — | Regex pattern or literal word to match for redaction. Double-escape backslashes in JSON (e.g. `\\d`). |
| `redaction_masking_character` | `string` | No | `"*"` | Single character used to replace each matched character. |

## Output Columns

| Column | Type | Description |
| --- | --- | --- |
| `redaction_stats` | `int` | Count of matches found and redacted in the document. Column name is the value of `stats_column` parameter (default: `redaction_stats`). |

The operator also modifies the content column in-place, replacing matched text with the masking character.

## Examples

### Example 1: Redact email addresses

```json
{
  "name": "redact_emails",
  "type": "redaction",
  "depends_on": ["extract"],
  "config": {
    "redaction_regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
    "redaction_masking_character": "*"
  }
}
```

### Example 2: Chain two redaction operators for email and phone

```json
{
  "flow": [
    {
      "name": "redact_emails",
      "type": "redaction",
      "depends_on": ["extract"],
      "config": {
        "redaction_regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
        "redaction_masking_character": "*"
      }
    },
    {
      "name": "redact_phones",
      "type": "redaction",
      "depends_on": ["redact_emails"],
      "config": {
        "redaction_regex": "\\b\\d{3}-\\d{3}-\\d{4}\\b",
        "redaction_masking_character": "#"
      }
    }
  ]
}
```

## Common patterns

| Target | Pattern |
| --- | --- |
| Email address | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}` |
| US phone (dashes) | `\\b\\d{3}-\\d{3}-\\d{4}\\b` |
| SSN | `\\b\\d{3}-\\d{2}-\\d{4}\\b` |
| 16-digit credit card | `\\b\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}\\b` |
| IPv4 address | `\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b` |
| Keyword (case-insensitive) | `(?i)\\b(confidential\|secret\|private)\\b` |

## DocLang XML Considerations & Limitations

When `doc_format == "doclang"`, `RedactionOperator` performs DOM-aware redaction:
- Text content is parsed into an XML element tree, and redaction is applied individually to `element.text` and `element.tail` nodes.
- XML tags, attributes, and element hierarchies are preserved intact.

**Known limitation (Cross-node PII)**:
Redaction is scoped to individual DOM text nodes. Target patterns or words split across separate XML tags (for example, `<text>John </text><bold>Doe</bold>`) cannot be matched across the tag boundary.

## Troubleshooting

**Pattern matches nothing** — verify the regex in a tool like [regex101.com](https://regex101.com) with a sample document. Remember to double-escape backslashes in JSON (`\\d` not `\d`).

**Too many false positives** — use word boundary anchors (`\\b`) to avoid partial matches.

**`redaction_masking_character` longer than one character** — only single characters are accepted. Using a multi-character string will raise a validation error.

## Sample Flow

See [`sample_flows/operators/pii_hap_detection.json`](../../../sample_flows/operators/pii_hap_detection.json) for a complete example using PII detection with redaction.
