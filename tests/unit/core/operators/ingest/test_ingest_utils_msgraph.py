# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Branch tests for the Microsoft Graph helpers in ingest_utils.

The Graph API is replaced by an in-process fake REST client that answers by exact URL,
so every test states exactly which endpoints succeed and which fail.
"""

import base64

from docpipe.core.operators.ingest.ingest_utils import (
    extract_msgraph_file_id_from_url,
    resolve_msgraph_file_id_to_item_id,
)

ORIGINAL_URL = "https://contoso.sharepoint.com/sites/team/doc.docx"


def _shares_url(original_url: str) -> str:
    """Return the /shares endpoint the resolver builds for a given URL."""
    token = base64.urlsafe_b64encode(original_url.encode()).decode().rstrip("=")
    return f"/shares/u!{token}/driveItem"


class FakeGraphClient:
    """Fake RestClient that answers ``call_rest_json`` from a URL -> response mapping.

    A response that is an exception instance is raised instead of returned; a URL without
    a mapping raises ``LookupError`` (a stand-in for a 404).
    """

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[dict] = []

    def call_rest_json(self, *, method, url, headers, query_params=None):
        """Record the call and return or raise the configured response."""
        self.calls.append({"method": method, "url": url, "headers": headers, "query_params": query_params})
        if url not in self.responses:
            raise LookupError(f"no fake response for {url}")
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def urls(self) -> list[str]:
        """Return the requested URLs in call order."""
        return [call["url"] for call in self.calls]


def _resolve(client: FakeGraphClient, file_id: str, **kwargs):
    """Call the resolver with a fixed drive and token."""
    return resolve_msgraph_file_id_to_item_id(
        file_id=file_id, drive_id="drive-1", rest_client=client, token="tok", **kwargs
    )


class TestResolvePathViaShares:
    """Path-style file ids combined with the /shares endpoint."""

    def test_shares_hit_without_drive_id_keeps_configured_drive(self):
        """A /shares answer without parentReference.driveId falls back to the configured drive."""
        client = FakeGraphClient({_shares_url(ORIGINAL_URL): {"id": "item-9"}})

        assert _resolve(client, "/sites/team/doc.docx", original_url=ORIGINAL_URL) == ("item-9", "drive-1")
        assert client.urls == [_shares_url(ORIGINAL_URL)]
        assert client.calls[0]["headers"] == {"Authorization": "Bearer tok"}

    def test_shares_answer_without_id_falls_back_to_path_api(self):
        """A /shares answer without an item id is ignored and the path API is used."""
        client = FakeGraphClient(
            {
                _shares_url(ORIGINAL_URL): {"parentReference": {"driveId": "other"}},
                "/drives/drive-1/root:/sites/team/doc.docx": {"id": "item-path"},
            }
        )

        assert _resolve(client, "/sites/team/doc.docx", original_url=ORIGINAL_URL) == ("item-path", "drive-1")
        assert client.urls == [_shares_url(ORIGINAL_URL), "/drives/drive-1/root:/sites/team/doc.docx"]

    def test_shares_error_falls_back_to_path_api(self):
        """A failing /shares call does not abort resolution; the path API is tried next."""
        client = FakeGraphClient(
            {
                _shares_url(ORIGINAL_URL): RuntimeError("403 forbidden"),
                "/drives/drive-1/root:/doc.docx": {"id": "item-path"},
            }
        )

        assert _resolve(client, "/doc.docx", original_url=ORIGINAL_URL) == ("item-path", "drive-1")
        assert client.urls[-1] == "/drives/drive-1/root:/doc.docx"


class TestResolvePathPrefixStripping:
    """Retrying the path API with library prefixes removed."""

    def test_skips_non_matching_prefix_and_tries_next(self):
        """Prefixes that do not match the path are skipped without an API call."""
        client = FakeGraphClient({"/drives/drive-1/root:/report.pdf": {"id": "item-stripped"}})

        result = _resolve(
            client,
            "/Documents/report.pdf",
            strip_path_prefixes=["Shared Documents/", "Documents/"],
        )

        assert result == ("item-stripped", "drive-1")
        assert client.urls == ["/drives/drive-1/root:/Documents/report.pdf", "/drives/drive-1/root:/report.pdf"]

    def test_failed_stripped_path_continues_with_next_prefix(self):
        """When a stripped path also fails, the next matching prefix is tried."""
        client = FakeGraphClient({"/drives/drive-1/root:/report.pdf": {"id": "item-second"}})

        result = _resolve(
            client,
            "/Shared Documents/report.pdf",
            strip_path_prefixes=["Shared ", "Shared Documents/"],
        )

        assert result == ("item-second", "drive-1")
        assert client.urls == [
            "/drives/drive-1/root:/Shared Documents/report.pdf",
            "/drives/drive-1/root:/Documents/report.pdf",
            "/drives/drive-1/root:/report.pdf",
        ]

    def test_all_prefixes_failing_returns_none(self):
        """If the original and every stripped path fail, resolution reports (None, None)."""
        client = FakeGraphClient({})

        result = _resolve(client, "/Shared Documents/missing.pdf", strip_path_prefixes=["Shared Documents/"])

        assert result == (None, None)
        assert client.urls == [
            "/drives/drive-1/root:/Shared Documents/missing.pdf",
            "/drives/drive-1/root:/missing.pdf",
        ]


class TestResolveGuid:
    """GUID-style file ids: /shares, direct access and search fallbacks."""

    def test_shares_hit_without_drive_id_keeps_configured_drive(self):
        """A /shares answer for a GUID without driveId uses the configured drive."""
        client = FakeGraphClient({_shares_url(ORIGINAL_URL): {"id": "item-guid"}})

        assert _resolve(client, "1234-abcd", original_url=ORIGINAL_URL) == ("item-guid", "drive-1")
        assert client.urls == [_shares_url(ORIGINAL_URL)]

    def test_shares_answer_without_id_falls_back_to_direct_access(self):
        """A /shares answer without an id is ignored and direct item access is attempted."""
        client = FakeGraphClient(
            {
                _shares_url(ORIGINAL_URL): {},
                "/drives/drive-1/items/1234-abcd": {"id": "1234-abcd"},
            }
        )

        assert _resolve(client, "1234-abcd", original_url=ORIGINAL_URL) == ("1234-abcd", "drive-1")
        assert client.urls == [_shares_url(ORIGINAL_URL), "/drives/drive-1/items/1234-abcd"]

    def test_shares_error_falls_back_to_direct_access(self):
        """A failing /shares call for a GUID falls back to direct item access."""
        client = FakeGraphClient(
            {
                _shares_url(ORIGINAL_URL): RuntimeError("boom"),
                "/drives/drive-1/items/1234-abcd": {"id": "direct"},
            }
        )

        assert _resolve(client, "1234-abcd", original_url=ORIGINAL_URL) == ("direct", "drive-1")

    def test_search_returns_first_match(self):
        """When direct access fails, the drive search is queried and its first hit is used."""
        client = FakeGraphClient(
            {"/drives/drive-1/root/search": {"value": [{"id": "hit-1"}, {"id": "hit-2"}]}},
        )

        assert _resolve(client, "1234-abcd") == ("hit-1", "drive-1")
        assert client.urls == ["/drives/drive-1/items/1234-abcd", "/drives/drive-1/root/search"]
        assert client.calls[-1]["query_params"] == {"q": "1234-abcd"}

    def test_empty_search_result_returns_none(self):
        """An empty search result means the GUID cannot be resolved."""
        client = FakeGraphClient({"/drives/drive-1/root/search": {"value": []}})

        assert _resolve(client, "1234-abcd") == (None, None)


class TestExtractMsgraphFileIdErrors:
    """Error handling in extract_msgraph_file_id_from_url."""

    def test_unparseable_url_returns_none(self):
        """A URL that urlparse rejects (unterminated IPv6 host) yields None instead of raising."""
        assert extract_msgraph_file_id_from_url("https://[::1/?id=/a.docx") is None

    def test_id_parameter_is_url_decoded(self):
        """The 'id' query value is returned URL-decoded."""
        url = "https://contoso.sharepoint.com/?id=%2Fsites%2Fteam%2FShared%20Documents%2Fa.docx"

        assert extract_msgraph_file_id_from_url(url) == "/sites/team/Shared Documents/a.docx"
