"""OpenLineage dataset identity: maps an adapter config to a ``(namespace, name)`` pair.

Sources and sinks both go through :func:`get_dataset_info`, so the same physical location gets the same
dataset ID whichever side of a flow it appears on. Providers whose identity is just "some config fields
slotted into a template" are described by a :class:`_Rule`; providers that need real logic (local paths,
Google Drive, web URLs, Milvus ``auth_type``) have a small dedicated function.

Constants are imported lazily: ``docpipe.core.constants.constants`` imports this package while it loads,
so a module-level import here would be circular.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Any
from urllib.parse import urlparse

# Placeholder used in a dataset ID when the config does not say (e.g. no bucket configured).
_UNKNOWN = "unknown"
# Dataset name used by the fallback for an unrecognised provider with nothing configured to name it.
_ROLE_DEFAULT_NAMES: dict[str, str] = {"source": "source", "destination": "output"}

# Provider names the adapters accept for a place another provider already names. Without an alias the name
# misses every rule and falls to ``_generic_info``, which ignores the config, so all such flows share one ID.
# - box_driver: the Box source registers as ``box_driver``, the Box destination as ``box``.
# - ibm_cos: aliased to ``s3`` in both adapter factories. Shares ``s3://{bucket}`` with AWS S3 (``endpoint_url``
#   is not part of the ID).
# ``onedrive`` is not mapped to ``sharepoint`` on purpose: it has its own rule and namespace.
_PROVIDER_ALIASES: dict[str, str] = {"box_driver": "box", "ibm_cos": "s3"}

_Info = tuple[str, str]


@dataclass(frozen=True)
class _Rule:
    """Declarative naming rule: config fields slotted into a namespace template and a name.

    ``namespace`` may contain ``{placeholders}``; each is filled from the first non-empty config field of
    ``namespace_fields[placeholder]`` (a ``(field aliases, default)`` pair). The name is the first
    non-empty field of ``name_fields`` (a path when ``is_path``, so trailing "/" is dropped), else
    ``default_name``.
    """

    namespace: str
    name_fields: tuple[str, ...] = ()
    default_name: str = "/"
    is_path: bool = False
    namespace_fields: dict[str, tuple[tuple[str, ...], str]] = field(default_factory=dict)


def _first(*, config: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first truthy value among ``keys`` in ``config``, or None."""
    return next((config[k] for k in keys if config.get(k)), None)


def _path_name(*, path: Any) -> str:
    """Return a dataset name for a folder/file path or key prefix ("/" when empty).

    A ``file_path`` may be a URL; its query and fragment are dropped because they can hold share tokens.
    """
    text = str(path).split("?", 1)[0].split("#", 1)[0].rstrip("/") if path else ""
    return text or "/"


def _apply_rule(*, rule: _Rule, config: dict[str, Any]) -> _Info:
    values = {
        placeholder: str(_first(config=config, keys=keys) or default)
        for placeholder, (keys, default) in rule.namespace_fields.items()
    }
    name = _first(config=config, keys=rule.name_fields)
    if name is None:
        return (rule.namespace.format(**values), rule.default_name)
    return (rule.namespace.format(**values), _path_name(path=name) if rule.is_path else str(name))


def _file_info(*, config: dict[str, Any], role: str | None) -> _Info:
    """Local file system: ``root_path`` (destination), or ``paths`` / ``path`` (source)."""
    from docpipe.core.constants.constants import LineageConstants

    paths = config.get("paths") or []
    root = config.get("root_path") or (paths[0] if paths else None) or config.get("path")
    name = str(root).rstrip("/") if root else _ROLE_DEFAULT_NAMES.get(role or "", _UNKNOWN)
    return (LineageConstants.NAMESPACE_FILE, name or "/")


def _google_drive_info(*, config: dict[str, Any]) -> _Info:
    """Google Drive: ``drive_id`` scopes the namespace; ``file_id``, else ``folder_id``, else ``folder_path`` names it.

    ``file_id`` comes first because the adapter ignores the folder fields when it is set.
    """
    from docpipe.core.constants.constants import LineageConstants

    base = LineageConstants.NAMESPACE_GOOGLE_DRIVE
    namespace = f"{base}/{config['drive_id']}" if config.get("drive_id") else base
    if config.get("file_id"):
        return (namespace, str(config["file_id"]))
    if config.get("folder_id"):
        return (namespace, str(config["folder_id"]))
    if config.get("folder_path"):
        return (namespace, _path_name(path=config["folder_path"]))
    return (namespace, "root")


def _web_info(*, config: dict[str, Any]) -> _Info | None:
    """Web source: the first entry of ``urls`` (host and port only, never user info); None if unusable."""
    urls = config.get("urls") or []
    parsed = urlparse(str(urls[0])) if urls else None
    if parsed is None or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return (f"{parsed.scheme or 'https'}://{parsed.hostname}{port}", _path_name(path=parsed.path))


def _milvus_info(*, config: dict[str, Any]) -> _Info:
    """Milvus following the adapter's ``auth_type`` rules.

    - ``lite``: ``uri`` is a local ``.db`` file, which is the endpoint.
    - ``uri`` (or no ``host``): host and port are parsed out of ``uri``. The URI can embed an API key
      (``https://ibmlhapikey_<user>:<key>@host:port``), so only the host and port are ever used.
    - otherwise: ``host`` and ``port``.
    """
    from docpipe.core.constants.constants import LineageConstants

    uri, host, auth_type = config.get("uri"), config.get("host"), config.get("auth_type")
    collection = config.get("collection_name") or config.get("index_name") or "default_collection"
    name = f"{config.get('database') or 'default'}.{collection}"

    if auth_type == "lite" and uri:
        return (f"{LineageConstants.NAMESPACE_MILVUS_LITE}/{uri}", name)
    if uri and (auth_type == "uri" or not host):
        parsed = urlparse(str(uri))
        return (f"milvus://{parsed.hostname or _UNKNOWN}:{parsed.port or 19530}", name)
    return (f"milvus://{host or 'localhost'}:{config.get('port') or 19530}", name)


def _generic_info(*, dataset_type: str, config: dict[str, Any], role: str | None) -> _Info:
    """Fallback for a type with no rule.

    Uses ``{type}://{host}[:{port}]`` when a host is configured. Otherwise the namespace is
    ``{type}://{role}`` so an unrecognised provider used as both source and sink does not become one
    dataset (that would put the sink's output upstream of the ingest and close a cycle).
    """
    host = config.get("host")
    if host:
        port = config.get("port")
        name = config.get("index_name") or config.get("collection_name") or _UNKNOWN
        return (f"{dataset_type}://{host}{f':{port}' if port else ''}", str(name))
    paths = config.get("paths") or []
    path = paths[0] if paths else config.get("path")
    default_name = _ROLE_DEFAULT_NAMES.get(role or "", _UNKNOWN)
    return (f"{dataset_type}://{role or _UNKNOWN}", str(path).rstrip("/") if path else default_name)


@cache
def _rules() -> dict[str, _Rule]:
    """Rules for providers that are plain field-to-template mappings (built lazily, see module docstring)."""
    from docpipe.core.constants.constants import LineageConstants as C
    from docpipe.core.constants.operator_constants import OperatorConstants

    return {
        # bucket + prefix (source) or key_prefix (destination)
        C.PROVIDER_S3: _Rule(
            "s3://{bucket}",
            name_fields=("key_prefix", "prefix"),
            is_path=True,
            namespace_fields={"bucket": (("bucket",), _UNKNOWN)},
        ),
        # Adapters expose no enterprise ID (it is inside the JWT file): fixed host, folder_id makes it unique.
        # file_id (single-file ingest) wins over folder_id, as in the adapter.
        C.PROVIDER_BOX: _Rule("box://app.box.com:443/default", name_fields=("file_id", "folder_id"), default_name="0"),
        # The Microsoft Graph drive ID replaces {site}: document_library_id (source) / drive_id (destination).
        # file_path (single-file ingest) wins over folder_path for SharePoint, OneDrive and Dropbox.
        C.PROVIDER_SHAREPOINT: _Rule(
            "mssharepoint://graph.microsoft.com:443/{drive}",
            name_fields=("file_path", "folder_path"),
            is_path=True,
            namespace_fields={"drive": (("drive_id", "document_library_id"), _UNKNOWN)},
        ),
        C.PROVIDER_ONEDRIVE: _Rule(
            "onedrive://graph.microsoft.com:443/{drive}",
            name_fields=("file_path", "folder_path"),
            is_path=True,
            namespace_fields={"drive": (("drive_id",), _UNKNOWN)},
        ),
        # The config holds no account identifier (only tokens), so accounts cannot be told apart.
        C.PROVIDER_DROPBOX: _Rule(C.NAMESPACE_DROPBOX, name_fields=("file_path", "folder_path"), is_path=True),
        C.PROVIDER_OPENSEARCH: _Rule(
            "opensearch://{host}:{port}",
            name_fields=("index_name",),
            default_name="default_index",
            namespace_fields={"host": (("host",), "localhost"), "port": (("port",), "9200")},
        ),
        OperatorConstants.Operators.DOCUMENT_SET: _Rule(
            C.NAMESPACE_DOCUMENT_SET, name_fields=("document_set_name",), default_name="document_set"
        ),
    }


def get_dataset_info(*, dataset_type: str, config: dict[str, Any], role: str | None = None) -> _Info:
    """Return the OpenLineage ``(namespace, name)`` for a dataset of ``dataset_type``.

    ``config`` holds the adapter's own field names (the operator's ``provider_config``). ``${VAR}``
    placeholders are resolved the way the adapters resolve them; an unset variable is kept as written so
    lineage never fails a flow. ``role`` (``"source"`` or ``"destination"``) is only used by the fallback.
    """
    from docpipe.core.constants.constants import LineageConstants as C

    # Normalise the provider the way IngestSourceOperator does (``.lower()``, plus ``.strip()`` for stray
    # whitespace), then apply aliases. Without this, "Box_Driver" or " S3 " would miss every rule below.
    dataset_type = str(_resolve_value(value=dataset_type)).strip().lower()
    dataset_type = _PROVIDER_ALIASES.get(dataset_type, dataset_type)
    resolved = _resolve_config(config=config)

    info: _Info | None = None
    if dataset_type in (C.PROVIDER_FILESYSTEM, C.PROVIDER_LOCAL, C.PROVIDER_FILE):
        info = _file_info(config=resolved, role=role)
    elif dataset_type == C.PROVIDER_GOOGLE_DRIVE:
        info = _google_drive_info(config=resolved)
    elif dataset_type == C.PROVIDER_WEB:
        info = _web_info(config=resolved)
    elif dataset_type == C.PROVIDER_MILVUS:
        info = _milvus_info(config=resolved)
    elif dataset_type in _rules():
        info = _apply_rule(rule=_rules()[dataset_type], config=resolved)
    return info or _generic_info(dataset_type=dataset_type, config=resolved, role=role)


def _resolve_value(*, value: Any) -> Any:
    """Resolve ``${VAR}`` / ``$VAR`` the way the adapters do, leaving unset variables as written."""
    from docpipe.core.operators.operator_utils import resolve_env_var

    if isinstance(value, list):
        return [_resolve_value(value=v) for v in value]
    try:
        return resolve_env_var(value)
    except ValueError:
        return value


def _resolve_config(*, config: Any) -> dict[str, Any]:
    """Return a shallow copy of a config dict with string (and list-of-string) values resolved."""
    if not isinstance(config, dict):
        return {}
    return {k: _resolve_value(value=v) for k, v in config.items()}
