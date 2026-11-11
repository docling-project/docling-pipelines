# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""A declared secret-capable field without a conformance entry fails the suite (task E.1)."""

import pytest

from tests.unit.secrets_conformance.catalog import Entry, FieldKey, declared_fields, entries, missing_entries


def test_every_declared_field_has_a_conformance_entry() -> None:
    problems = missing_entries(declared=declared_fields(), catalog=entries())

    assert not problems, "secret conformance catalog is out of step with the declarations:\n" + "\n".join(problems)


def test_the_declarations_are_not_empty() -> None:
    # Guards the guard: an empty declaration set would make the check above pass vacuously.
    declared = declared_fields()

    assert len(declared) > 50
    assert {"ingest_source", "storage_output", "vectordb", "acl_operator"} <= {key[0] for key in declared}


def test_a_new_declared_field_without_an_entry_is_reported_with_operator_and_field() -> None:
    new_field: FieldKey = ("my_operator", None, None, "provider_config.api_key")

    problems = missing_entries(declared=declared_fields() | {new_field}, catalog=entries())

    assert problems == ["my_operator: secret-capable field 'provider_config.api_key' has no conformance entry"]


def test_a_new_provider_scoped_field_names_the_provider() -> None:
    new_field: FieldKey = ("ingest_source", "provider", "newcloud", "provider_config.token")

    problems = missing_entries(declared=declared_fields() | {new_field}, catalog=entries())

    assert len(problems) == 1
    assert "ingest_source" in problems[0] and "provider_config.token" in problems[0] and "newcloud" in problems[0]


def test_removing_an_entry_is_reported() -> None:
    catalog = dict(entries())
    key = sorted(catalog, key=str)[0]
    del catalog[key]

    problems = missing_entries(declared=declared_fields(), catalog=catalog)

    assert len(problems) == 1
    assert key[0] in problems[0] and key[3] in problems[0]


def test_an_entry_for_a_field_that_is_no_longer_declared_is_reported() -> None:
    catalog: dict[FieldKey, Entry] = dict(entries())
    key = sorted(catalog, key=str)[0]

    problems = missing_entries(declared=declared_fields() - {key}, catalog=catalog)

    assert len(problems) == 1
    assert "matches no declared" in problems[0] and key[3] in problems[0]


@pytest.mark.parametrize("key", sorted(entries(), key=str), ids=lambda key: f"{key[0]}:{key[2] or 'any'}:{key[3]}")
def test_each_entry_builds_a_config_with_the_reference_at_its_field(*, key: FieldKey) -> None:
    entry = entries()[key]

    config = entry.build_config(reference="vault://fake/p#v")

    node = config
    for segment in entry.concrete_path.split("."):
        node = node[segment]
    assert node == "vault://fake/p#v"
