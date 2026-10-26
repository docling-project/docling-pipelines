"""Utility functions for displaying global configuration information to users."""

from docpipe.core.orchestration.global_config_metadata import GlobalConfigMetadata, GlobalConfigParam


def _group_params_by_category(
    params: dict[str, GlobalConfigParam],
    *,
    category_filter: str | None,
) -> dict[str, list[tuple[str, GlobalConfigParam]]]:
    """Group params by category, applying an optional category filter."""
    by_category: dict[str, list[tuple[str, GlobalConfigParam]]] = {}
    for key, param in params.items():
        if category_filter and param.category != category_filter:
            continue
        by_category.setdefault(param.category, []).append((key, param))
    return by_category


def _format_param_detail(key: str, param: GlobalConfigParam) -> list[str]:
    """Return the detail lines for a single parameter."""
    lines = [
        f"\n{'-' * 100}",
        f"Parameter: {key}",
        f"{'-' * 100}",
        f"Name: {param.name}",
        f"Type: {param.type}",
        f"Required: {'Yes' if param.required else 'No'}",
    ]
    if param.default is not None:
        lines.append(f"Default: {param.default}")
    lines += ["\nDescription:", f"  {param.description}"]
    return lines


def format_global_config_details(params: dict[str, GlobalConfigParam], *, category_filter: str | None = None) -> str:
    """
    Format global configuration parameters into a human-readable detailed view.

    Args:
        params: Dictionary of parameter name to GlobalConfigParam
        category_filter: Optional category to filter by

    Returns:
        Formatted string representation of the parameters
    """
    by_category = _group_params_by_category(params, category_filter=category_filter)

    if not by_category:
        if category_filter:
            return f"\nNo parameters found in category: {category_filter}"
        return "\nNo global configuration parameters found"

    lines: list[str] = []
    for category in sorted(by_category.keys()):
        lines += [f"\n{'=' * 100}", f"CATEGORY: {category}", f"{'=' * 100}"]
        for key, param in sorted(by_category[category], key=lambda item: item[1].name):
            lines += _format_param_detail(key, param)

    return "\n".join(lines)


def _truncate_default(value: object) -> str:
    """Return a display-safe string for a default value, capped at 22 characters."""
    if value is None:
        return ""
    text = str(value)
    return text[:19] + "..." if len(text) > 22 else text


def _empty_summary_message(*, category_filter: str | None) -> str:
    """Return the appropriate message when no parameters match the filter."""
    if category_filter:
        return "\n".join(
            [
                f"\nNo parameters found in category: {category_filter}",
                f"\nAvailable categories: {', '.join(GlobalConfigMetadata.get_categories())}",
            ]
        )
    return "\nNo global configuration parameters found"


def display_global_config_summary(*, category_filter: str | None = None) -> str:
    """
    Display a summary table of global configuration parameters.

    Args:
        category_filter: Optional category to filter by

    Returns:
        Formatted summary table
    """
    params = GlobalConfigMetadata.get_all_config_metadata()

    filtered_params = {
        name: param for name, param in params.items() if not category_filter or param.category == category_filter
    }

    if not filtered_params:
        return _empty_summary_message(category_filter=category_filter)

    title = (
        f"GLOBAL CONFIGURATION PARAMETERS - CATEGORY: {category_filter}"
        if category_filter
        else "GLOBAL CONFIGURATION PARAMETERS SUMMARY"
    )

    lines = [title, "=" * 120]
    lines.append(f"\n{'Parameter':<63} {'Type':<15} {'Category':<30} {'Required':<10} {'Default':<25}")
    lines.append("-" * 130)

    sorted_items = sorted(filtered_params.items(), key=lambda item: (item[1].category, item[1].name))

    for key, param in sorted_items:
        required_str = "Yes" if param.required else "No"
        display_name = f"{param.name} ({key})"
        lines.append(
            f"{display_name:<63} {param.type:<15} {param.category:<30} {required_str:<10} {_truncate_default(param.default):<25}"
        )

    lines.append("-" * 130)
    lines.append(f"\nTotal parameters: {len(filtered_params)}")

    if not category_filter:
        lines.append(f"\nAvailable categories: {', '.join(GlobalConfigMetadata.get_categories())}")
        lines.append("Use --list-global-config --category <name> to filter by category")

    lines.append("Use --list-global-config --verbose for detailed information")
    lines.append("=" * 130)

    return "\n".join(lines)


def list_global_config(*, verbose: bool = False, category: str | None = None) -> str:
    """
    List all global configuration parameters with their details.

    Display modes:
    1. Summary (verbose=False, default): Shows summary table
    2. Detailed (verbose=True): Shows full parameter details

    Args:
        verbose: If True, show detailed information for each parameter
        category: Optional category to filter by

    Returns:
        Formatted string with global configuration information
    """
    params = GlobalConfigMetadata.get_all_config_metadata()

    if verbose:
        return format_global_config_details(params, category_filter=category)
    return display_global_config_summary(category_filter=category)


# For testing
def main():  # pragma: no cover
    """Run a quick demo of all global config display modes."""
    print("=== SUMMARY VIEW ===")
    print(list_global_config(verbose=False))
    print("\n\n=== DETAILED VIEW ===")
    print(list_global_config(verbose=True))
    print("\n\n=== CATEGORY FILTER: Orchestration configuration ===")
    print(list_global_config(verbose=False, category="Orchestration configuration"))


if __name__ == "__main__":  # pragma: no cover
    main()
