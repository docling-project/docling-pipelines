# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""ACL query builder for OpenSearch with allowed_users enforcement."""

import logging
from typing import Any

from docpipe.api.auth.dependencies import LOCAL_PRINCIPAL_USERNAME

logger = logging.getLogger(__name__)


class ACLQueryBuilder:
    """Builder for OpenSearch queries with ACL enforcement.

    This class constructs OpenSearch queries that automatically filter
    results based on the allowed_users field, ensuring users can only
    access documents they are authorized to view.

    Security Model:
    - Documents without allowed_users field: NOT accessible (fail-closed)
    - Documents with empty allowed_users array: NOT accessible
    - Documents with username in allowed_users: accessible
    - The reserved local principal never matches an allowed_users entry, so a document
      that lists it is not made reachable (it only sees documents when ``bypass_acl`` is
      set, which callers do only while authentication is disabled)
    """

    @staticmethod
    def build_acl_filter(*, username: str) -> dict[str, Any]:
        """Create OpenSearch filter for allowed_users field.

        Args:
            username: Username to check in allowed_users field

        Returns:
            OpenSearch query filter dict. For the reserved local principal this matches
            nothing, instead of matching documents that list the reserved name.
        """
        if username == LOCAL_PRINCIPAL_USERNAME:
            return {"bool": {"must_not": [{"match_all": {}}]}}
        return {"term": {"allowed_users": username}}

    @staticmethod
    def build_document_query(
        *,
        document_id: str,
        username: str,
        bypass_acl: bool = False,
    ) -> dict[str, Any]:
        """Build query for single document retrieval with ACL enforcement.

        Args:
            document_id: Document ID to retrieve
            username: Username for ACL check
            bypass_acl: Skip the allowed_users filter (authentication disabled)

        Returns:
            OpenSearch query dict with ACL filter
        """
        must_clauses: list[dict[str, Any]] = [{"term": {"_id": document_id}}]
        if not bypass_acl:
            must_clauses.append(ACLQueryBuilder.build_acl_filter(username=username))
        query = {"query": {"bool": {"must": must_clauses}}}

        logger.debug(
            "Built document query for doc_id=%s, user=%s",
            document_id,
            username,
        )
        return query

    @staticmethod
    def build_search_query(
        *,
        username: str,
        query_text: str | None = None,
        filters: dict[str, Any] | None = None,
        sort: list[dict[str, str]] | None = None,
        bypass_acl: bool = False,
    ) -> dict[str, Any]:
        """Build search query with ACL filtering.

        Args:
            username: Username for ACL check
            query_text: Optional full-text search query
            filters: Optional field filters (e.g., {"category": "tech"})
            sort: Optional sort specification (e.g., [{"created_at": "desc"}])
            bypass_acl: Skip the allowed_users filter (authentication disabled)

        Returns:
            OpenSearch query dict with ACL filter and search criteria
        """
        # Start with ACL filter as a must clause
        must_clauses: list[dict[str, Any]] = []
        if not bypass_acl:
            must_clauses.append(ACLQueryBuilder.build_acl_filter(username=username))

        # Add full-text search if provided
        if query_text:
            must_clauses.append(
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["text", "content", "title"],
                        "type": "best_fields",
                        "operator": "or",
                    }
                }
            )

        # Add field filters if provided
        if filters:
            for field, value in filters.items():
                if isinstance(value, list):
                    # Handle array values with terms query
                    must_clauses.append({"terms": {field: value}})
                else:
                    # Handle single values with term query
                    must_clauses.append({"term": {field: value}})

        # Build the complete query
        query: dict[str, Any] = {"query": {"bool": {"must": must_clauses or [{"match_all": {}}]}}}

        # Add sorting if provided
        if sort:
            query["sort"] = sort

        logger.debug(
            "Built search query for user=%s, text=%s, filters=%s",
            username,
            query_text,
            filters,
        )
        return query

    @staticmethod
    def build_exists_query(*, username: str) -> dict[str, Any]:
        """Build query to check if user has any accessible documents.

        Args:
            username: Username for ACL check

        Returns:
            OpenSearch query dict
        """
        return {
            "query": ACLQueryBuilder.build_acl_filter(username=username),
            "size": 0,  # We only need the count
        }

    @staticmethod
    def validate_allowed_users(*, allowed_users: list[str] | None) -> bool:
        """Validate if allowed_users field grants access.

        Args:
            allowed_users: The allowed_users field from a document

        Returns:
            True if field is valid and non-empty, False otherwise
        """
        if allowed_users is None:
            logger.debug("allowed_users is None - access denied")
            return False

        if not isinstance(allowed_users, list):
            logger.warning(
                "allowed_users is not a list: %s - access denied",
                type(allowed_users),
            )
            return False

        if not allowed_users:
            logger.debug("allowed_users is empty - access denied")
            return False

        return True

    @staticmethod
    def user_has_access(
        *,
        username: str,
        allowed_users: list[str] | None,
    ) -> bool:
        """Check if user has access based on allowed_users field.

        Args:
            username: Username to check
            allowed_users: The allowed_users field from a document

        Returns:
            True if user has access, False otherwise
        """
        if not ACLQueryBuilder.validate_allowed_users(allowed_users=allowed_users):
            return False

        # Type narrowing: at this point allowed_users is guaranteed to be list[str]
        if (
            allowed_users is None
        ):  # pragma: no cover — validate_allowed_users already guards this; defensive narrowing for type checker
            raise RuntimeError("allowed_users unexpectedly None after validation")
        has_access = username != LOCAL_PRINCIPAL_USERNAME and username in allowed_users
        logger.debug(
            "User %s access check: %s (allowed_users=%s)",
            username,
            has_access,
            allowed_users,
        )
        return has_access
