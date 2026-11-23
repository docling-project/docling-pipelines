# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ACL query builder."""

from docpipe.api.auth.dependencies import LOCAL_PRINCIPAL_USERNAME
from docpipe.api.services.acl_query_builder import ACLQueryBuilder


class TestACLQueryBuilder:
    """Test suite for ACLQueryBuilder."""

    def test_build_acl_filter(self):
        """Test building ACL filter for allowed_users."""
        username = "john.doe"
        filter_dict = ACLQueryBuilder.build_acl_filter(username=username)

        assert filter_dict == {"term": {"allowed_users": "john.doe"}}

    def test_build_document_query(self):
        """Test building document query with ACL enforcement."""
        document_id = "doc-123"
        username = "john.doe"

        query = ACLQueryBuilder.build_document_query(
            document_id=document_id,
            username=username,
        )

        assert "query" in query
        assert "bool" in query["query"]
        assert "must" in query["query"]["bool"]
        assert len(query["query"]["bool"]["must"]) == 2

        # Check document ID filter
        assert {"term": {"_id": "doc-123"}} in query["query"]["bool"]["must"]

        # Check ACL filter
        assert {"term": {"allowed_users": "john.doe"}} in query["query"]["bool"]["must"]

    def test_build_search_query_text_only(self):
        """Test building search query with text search only."""
        username = "john.doe"
        query_text = "machine learning"

        query = ACLQueryBuilder.build_search_query(
            username=username,
            query_text=query_text,
        )

        assert "query" in query
        assert "bool" in query["query"]
        must_clauses = query["query"]["bool"]["must"]

        # Should have ACL filter and text search
        assert len(must_clauses) == 2

        # Check ACL filter
        assert {"term": {"allowed_users": "john.doe"}} in must_clauses

        # Check text search
        text_search = next(
            (c for c in must_clauses if "multi_match" in c),
            None,
        )
        assert text_search is not None
        assert text_search["multi_match"]["query"] == "machine learning"

    def test_build_search_query_with_filters(self):
        """Test building search query with field filters."""
        username = "john.doe"
        filters = {"category": "tech", "status": "published"}

        query = ACLQueryBuilder.build_search_query(
            username=username,
            filters=filters,
        )

        must_clauses = query["query"]["bool"]["must"]

        # Should have ACL filter + 2 field filters
        assert len(must_clauses) == 3

        # Check filters are present
        assert {"term": {"category": "tech"}} in must_clauses
        assert {"term": {"status": "published"}} in must_clauses

    def test_build_search_query_with_array_filter(self):
        """Test building search query with array filter values."""
        username = "john.doe"
        filters = {"category": ["tech", "science"]}

        query = ACLQueryBuilder.build_search_query(
            username=username,
            filters=filters,
        )

        must_clauses = query["query"]["bool"]["must"]

        # Check array filter uses 'terms' instead of 'term'
        array_filter = next(
            (c for c in must_clauses if "terms" in c),
            None,
        )
        assert array_filter is not None
        assert array_filter["terms"]["category"] == ["tech", "science"]

    def test_build_search_query_with_sort(self):
        """Test building search query with sorting."""
        username = "john.doe"
        sort = [{"created_at": "desc"}, {"title": "asc"}]

        query = ACLQueryBuilder.build_search_query(
            username=username,
            sort=sort,
        )

        assert "sort" in query
        assert query["sort"] == sort

    def test_build_search_query_complete(self):
        """Test building search query with all parameters."""
        username = "john.doe"
        query_text = "artificial intelligence"
        filters = {"category": "tech", "tags": ["ai", "ml"]}
        sort = [{"created_at": "desc"}]

        query = ACLQueryBuilder.build_search_query(
            username=username,
            query_text=query_text,
            filters=filters,
            sort=sort,
        )

        must_clauses = query["query"]["bool"]["must"]

        # ACL + text search + 2 filters = 4 clauses
        assert len(must_clauses) == 4
        assert "sort" in query

    def test_build_exists_query(self):
        """Test building query to check document existence."""
        username = "john.doe"

        query = ACLQueryBuilder.build_exists_query(username=username)

        assert query["query"] == {"term": {"allowed_users": "john.doe"}}
        assert query["size"] == 0

    def test_validate_allowed_users_valid(self):
        """Test validation of valid allowed_users field."""
        allowed_users = ["john.doe", "jane.smith"]

        result = ACLQueryBuilder.validate_allowed_users(allowed_users=allowed_users)

        assert result is True

    def test_validate_allowed_users_none(self):
        """Test validation fails for None allowed_users."""
        result = ACLQueryBuilder.validate_allowed_users(allowed_users=None)

        assert result is False

    def test_validate_allowed_users_empty(self):
        """Test validation fails for empty allowed_users."""
        result = ACLQueryBuilder.validate_allowed_users(allowed_users=[])

        assert result is False

    def test_validate_allowed_users_not_list(self):
        """Test validation fails for non-list allowed_users."""
        result = ACLQueryBuilder.validate_allowed_users(
            allowed_users="john.doe"  # type: ignore
        )

        assert result is False

    def test_user_has_access_granted(self):
        """Test user has access when in allowed_users."""
        username = "john.doe"
        allowed_users = ["john.doe", "jane.smith"]

        result = ACLQueryBuilder.user_has_access(
            username=username,
            allowed_users=allowed_users,
        )

        assert result is True

    def test_user_has_access_denied(self):
        """Test user denied access when not in allowed_users."""
        username = "bob.jones"
        allowed_users = ["john.doe", "jane.smith"]

        result = ACLQueryBuilder.user_has_access(
            username=username,
            allowed_users=allowed_users,
        )

        assert result is False

    def test_user_has_access_none_allowed_users(self):
        """Test user denied access when allowed_users is None."""
        username = "john.doe"

        result = ACLQueryBuilder.user_has_access(
            username=username,
            allowed_users=None,
        )

        assert result is False

    def test_user_has_access_empty_allowed_users(self):
        """Test user denied access when allowed_users is empty."""
        username = "john.doe"

        result = ACLQueryBuilder.user_has_access(
            username=username,
            allowed_users=[],
        )

        assert result is False


class TestLocalPrincipal:
    """The reserved local principal is handled explicitly."""

    def test_acl_filter_for_local_principal_matches_nothing(self):
        """The reserved name must not match an allowed_users entry that happens to list it."""
        filter_dict = ACLQueryBuilder.build_acl_filter(username=LOCAL_PRINCIPAL_USERNAME)

        assert filter_dict == {"bool": {"must_not": [{"match_all": {}}]}}

    def test_document_query_for_local_principal_matches_nothing(self):
        query = ACLQueryBuilder.build_document_query(document_id="doc-1", username=LOCAL_PRINCIPAL_USERNAME)

        assert {"term": {"allowed_users": LOCAL_PRINCIPAL_USERNAME}} not in query["query"]["bool"]["must"]
        assert {"bool": {"must_not": [{"match_all": {}}]}} in query["query"]["bool"]["must"]

    def test_exists_query_for_local_principal_matches_nothing(self):
        query = ACLQueryBuilder.build_exists_query(username=LOCAL_PRINCIPAL_USERNAME)

        assert query["query"] == {"bool": {"must_not": [{"match_all": {}}]}}

    def test_user_has_access_denies_local_principal_even_when_listed(self):
        assert (
            ACLQueryBuilder.user_has_access(
                username=LOCAL_PRINCIPAL_USERNAME,
                allowed_users=[LOCAL_PRINCIPAL_USERNAME, "john.doe"],
            )
            is False
        )

    def test_bypass_acl_drops_the_allowed_users_filter_from_document_query(self):
        query = ACLQueryBuilder.build_document_query(
            document_id="doc-1", username=LOCAL_PRINCIPAL_USERNAME, bypass_acl=True
        )

        assert query["query"]["bool"]["must"] == [{"term": {"_id": "doc-1"}}]

    def test_bypass_acl_search_without_criteria_matches_all(self):
        query = ACLQueryBuilder.build_search_query(username=LOCAL_PRINCIPAL_USERNAME, bypass_acl=True)

        assert query["query"]["bool"]["must"] == [{"match_all": {}}]

    def test_bypass_acl_search_keeps_text_and_filters(self):
        query = ACLQueryBuilder.build_search_query(
            username=LOCAL_PRINCIPAL_USERNAME,
            query_text="ml",
            filters={"category": "tech"},
            bypass_acl=True,
        )

        must = query["query"]["bool"]["must"]
        assert not any("allowed_users" in str(clause) for clause in must)
        assert {"term": {"category": "tech"}} in must
        assert any("multi_match" in clause for clause in must)

    def test_default_still_enforces_the_acl(self):
        query = ACLQueryBuilder.build_search_query(username="john.doe")

        assert query["query"]["bool"]["must"] == [{"term": {"allowed_users": "john.doe"}}]
