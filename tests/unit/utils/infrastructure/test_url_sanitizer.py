# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the URL credential sanitizer."""

import pytest

from docpipe.utils.infrastructure.url_sanitizer import (
    REDACTED,
    is_sensitive_param_name,
    sanitize_url,
    sanitize_urls_in_text,
    split_text_and_urls,
)

FAKE_TEMPAUTH = "FAKE-TEMPAUTH-VALUE-0123456789"
DOWNLOAD_URL = (
    "https://tenant-my.sharepoint.com/personal/user_example_com/_layouts/15/download.aspx"
    f"?UniqueId=de35d52f-620f-41eb-b5d7-2b3b38350814&Translate=false&tempauth={FAKE_TEMPAUTH}&ApiVersion=2.0"
)


class TestSanitizeUrl:
    """Test sanitize_url()."""

    def test_tempauth_is_redacted_and_other_parts_are_kept(self):
        """The Microsoft Graph download URL keeps host, path and non-sensitive params."""
        result = sanitize_url(DOWNLOAD_URL)

        assert FAKE_TEMPAUTH not in result
        assert "tempauth=***REDACTED***" in result
        assert result.startswith(
            "https://tenant-my.sharepoint.com/personal/user_example_com/_layouts/15/download.aspx?"
        )
        assert "UniqueId=de35d52f-620f-41eb-b5d7-2b3b38350814" in result
        assert "Translate=false" in result
        assert "ApiVersion=2.0" in result

    def test_parameter_order_is_preserved(self):
        """Redaction does not reorder the query string."""
        result = sanitize_url(DOWNLOAD_URL)

        assert (
            result.index("UniqueId") < result.index("Translate") < result.index("tempauth") < result.index("ApiVersion")
        )

    @pytest.mark.parametrize(
        "param",
        [
            "tempauth",
            "TempAuth",
            "access_token",
            "token",
            "sig",
            "X-Amz-Signature",
            "X-Amz-Credential",
            "api_key",
            "apikey",
            "subscription-key",
            "access_key",
            "private_key",
            "pwd",
            "jwt",
            "session",
            "sid",
            "auth",
            "key",
            "code",
        ],
    )
    def test_credential_parameter_names_are_redacted(self, param):
        """Common credential parameter names are redacted regardless of case or separators."""
        result = sanitize_url(f"https://example.com/file?id=1&{param}=SECRETVALUE")

        assert "SECRETVALUE" not in result
        assert f"{param}=***REDACTED***" in result
        assert "id=1" in result

    @pytest.mark.parametrize(
        "param",
        ["UniqueId", "Translate", "ApiVersion", "page", "name", "format", "author", "authority", "keyword", "monkey"],
    )
    def test_non_sensitive_parameters_are_kept(self, param):
        """Parameters that are not credentials, including names that merely contain 'auth', are left unchanged."""
        url = f"https://example.com/file?{param}=value"

        assert sanitize_url(url) == url

    def test_url_without_query_is_unchanged(self):
        """A URL without a query string is returned as is."""
        url = "https://graph.microsoft.com/v1.0/drives/abc/root/children"

        assert sanitize_url(url) == url

    def test_relative_path_with_query(self):
        """A path without scheme or host is sanitized too."""
        assert sanitize_url("/download?tempauth=SECRETVALUE&a=1") == "/download?tempauth=***REDACTED***&a=1"

    def test_userinfo_is_dropped(self):
        """Embedded user:password credentials are removed from the URL."""
        result = sanitize_url("https://user:hunter2@example.com/path?a=1")  # pragma: allowlist secret

        assert "hunter2" not in result
        assert result == "https://example.com/path?a=1"

    def test_fragment_credentials_are_redacted(self):
        """Credentials in the URL fragment are redacted."""
        result = sanitize_url("https://example.com/cb#access_token=SECRETVALUE&state=xyz")

        assert "SECRETVALUE" not in result
        assert "state=xyz" in result

    def test_valueless_parameter_is_kept(self):
        """A parameter without a value has nothing to redact."""
        assert sanitize_url("https://example.com/f?token") == "https://example.com/f?token"

    def test_custom_redact_value(self):
        """The substitute string can be changed."""
        assert sanitize_url("https://example.com/f?tempauth=SECRETVALUE", redact_value="<hidden>").endswith(
            "tempauth=<hidden>"
        )

    def test_unparseable_url_fails_closed(self):
        """A URL that cannot be parsed is replaced entirely."""
        assert sanitize_url("http://[invalid/f?tempauth=SECRETVALUE") == REDACTED

    def test_non_string_input_fails_closed(self):
        """A value that is not a string is replaced instead of raising inside a logging call."""
        assert sanitize_url(object()) == REDACTED  # type: ignore[arg-type]

    def test_json_escaped_ampersand_separator(self):
        """A query whose '&' is JSON-escaped as \\u0026 is split into parameters."""
        result = sanitize_url("https://example.com/f?UniqueId=1\\u0026tempauth=SECRETVALUE\\u0026ApiVersion=2.0")

        assert "SECRETVALUE" not in result
        assert result == "https://example.com/f?UniqueId=1\\u0026tempauth=***REDACTED***\\u0026ApiVersion=2.0"

    def test_html_escaped_ampersand_separator(self):
        """A query whose '&' is HTML-escaped as &amp; is split into parameters."""
        result = sanitize_url("https://example.com/f?a=1&amp;tempauth=SECRETVALUE&amp;b=2")

        assert result == "https://example.com/f?a=1&amp;tempauth=***REDACTED***&amp;b=2"


class TestIsSensitiveParamName:
    """Test is_sensitive_param_name()."""

    @pytest.mark.parametrize("name", ["tempauth", "Access-Token", "X_Amz_Signature", "client.secret", "%74oken"])
    def test_sensitive(self, name):
        """Names are normalized before matching."""
        assert is_sensitive_param_name(name=name)

    @pytest.mark.parametrize("name", ["author", "authority", "page", "UniqueId", "monkey"])
    def test_not_sensitive(self, name):
        """Harmless names are not redacted."""
        assert not is_sensitive_param_name(name=name)


class TestSanitizeUrlsInText:
    """Test sanitize_urls_in_text() and split_text_and_urls()."""

    def test_urls_in_text_are_redacted(self):
        """Every URL in free text such as an exception message is sanitized."""
        text = f"403 Client Error: Forbidden for url: {DOWNLOAD_URL} (retrying {DOWNLOAD_URL})"
        result = sanitize_urls_in_text(text)

        assert FAKE_TEMPAUTH not in result
        assert result.count("tempauth=***REDACTED***") == 2
        assert result.startswith("403 Client Error: Forbidden for url: https://tenant-my.sharepoint.com/")

    def test_request_path_in_urllib3_message_is_redacted(self):
        """urllib3 style messages report the path and query without a host."""
        text = "Max retries exceeded with url: /download.aspx?tempauth=SECRETVALUE&a=1 (Caused by X)"
        result = sanitize_urls_in_text(text)

        assert "SECRETVALUE" not in result
        assert "with url: /download.aspx?tempauth=***REDACTED***&a=1" in result

    def test_json_escaped_url_in_body_is_redacted(self):
        """A URL inside a JSON body that escapes '&' is redacted as one URL, not one giant parameter."""
        text = '{"url": "https://example.com/f?UniqueId=1\\u0026tempauth=SECRETVALUE\\u0026a=2"}'
        result = sanitize_urls_in_text(text)

        assert "SECRETVALUE" not in result
        assert result.endswith('a=2"}')

    @pytest.mark.parametrize("closer", ["}", "]", ")", "'", '"'])
    def test_closing_characters_are_not_swallowed(self, closer):
        """A URL followed by a closing bracket or quote keeps that character."""
        result = sanitize_urls_in_text(f"{{'u': https://example.com/f?tempauth=SECRETVALUE{closer}")

        assert "SECRETVALUE" not in result
        assert result.endswith(f"tempauth=***REDACTED***{closer}")

    def test_text_without_urls_is_unchanged(self):
        """Text that holds no URL is returned unchanged."""
        assert sanitize_urls_in_text("Connection error") == "Connection error"

    def test_split_text_and_urls_round_trips(self):
        """The segments concatenate back to the input."""
        text = f"before {DOWNLOAD_URL} after"
        segments = split_text_and_urls(text=text)

        assert "".join(segment for segment, _ in segments) == text
        assert [is_url for _, is_url in segments] == [False, True, False]
