"""Entity curation transform: monetary amounts (with magnitude suffixes) to plain decimal strings."""

from decimal import Decimal

import re2 as re


def currency_to_numeric(*, amount: str | None, locale: str = "en_US") -> str | None:
    """Converts a locale-formatted monetary string to a plain numeric string.

    If amount is None, returns None without attempting conversion.

    This function parses a monetary value that may contain locale-specific
    grouping and decimal symbols (e.g., "$1 234,56" for fr_FR) and
    returns a plain numeric string suitable for further numeric processing.

    Supports multi-language magnitude suffixes including:
    - English: K, M, B, T, thousand, million, billion, trillion
    - Chinese: 千 (qian), 万 (wan), 亿 (yi)
    - Japanese: 千 (sen), 万 (man), 億 (oku), 兆 (chou)
    - Korean: 천 (cheon), 만 (man), 억 (eok), 조 (jo)
    - Spanish: mil, millón, billón
    - French: mille, million, milliard
    - German: tausend, Million, Milliarde
    - Portuguese: mil, milhão, bilhão
    - Italian: mila, milione, miliardo
    - Russian: тысяча, миллион, миллиард

    Args:
        amount: The monetary string to convert. It may include currency symbols,
            grouping separators, locale-specific decimal separators, and
            magnitude suffixes (multi-language support).
        locale: A locale identifier understood by Babel (e.g., en_US,
            de_DE). The locale is used to determine the appropriate
            grouping and decimal symbols.

    Returns:
        A string representing the numeric value without any grouping symbols.
        The decimal separator is always "." (dot) to conform to the
        standard Decimal string representation.

    Raises:
        ImportError: If the Babel library is not installed.
        ValueError: If the provided locale is unsupported or the value
            cannot be parsed as a monetary amount.

    Examples:
        >>> currency_to_numeric(amount="$1,234.56")
        '1234.560000'
        >>> currency_to_numeric(amount="€1.234,56", locale="de_DE")
        '1234.560000'
        >>> currency_to_numeric(amount="$10K")
        '10000.000000'
        >>> currency_to_numeric(amount="¥100万")  # Japanese: 100 man = 1,000,000
        '1000000.000000'
    """
    # Handle None input gracefully
    if amount is None:
        return None

    # Lazy import of Babel components. This raises a clear error if Babel is
    # missing, while keeping module import safe.
    try:
        from babel.core import Locale, UnknownLocaleError
        from babel.numbers import parse_decimal
    except ImportError as exc:
        raise ImportError(
            "The 'Babel' library is required for currency parsing. Install it via 'pip install Babel'."
        ) from exc

    # Validate locale early to provide a clear error message and obtain a Locale object.
    try:
        Locale.parse(locale)
    except (UnknownLocaleError, ValueError) as exc:
        raise ValueError(f"Unsupported locale '{locale}': {exc}") from exc

    # Define multi-language magnitude multipliers
    # Note: Unicode characters are already decoded by json.loads() before this function is called
    magnitude_map = {
        # English - Single letters
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
        "B": Decimal("1000000000"),
        "T": Decimal("1000000000000"),
        # English - Full words
        "THOUSAND": Decimal("1000"),
        "MILLION": Decimal("1000000"),
        "BILLION": Decimal("1000000000"),
        "TRILLION": Decimal("1000000000000"),
        # Chinese
        "千": Decimal("1000"),  # qian (thousand)
        "万": Decimal("10000"),  # wan (ten thousand)
        "億": Decimal("100000000"),  # yi (hundred million)
        "亿": Decimal("100000000"),  # yi (simplified)
        # Japanese (same characters as Chinese but included for clarity)
        "兆": Decimal("1000000000000"),  # chou (trillion)
        # Korean
        "천": Decimal("1000"),  # cheon
        "만": Decimal("10000"),  # man
        "억": Decimal("100000000"),  # eok
        "조": Decimal("1000000000000"),  # jo
        # Spanish
        "MIL": Decimal("1000"),
        "MILLÓN": Decimal("1000000"),
        "MILLON": Decimal("1000000"),
        "BILLÓN": Decimal("1000000000"),
        "BILLON": Decimal("1000000000"),
        # French
        "MILLE": Decimal("1000"),
        # Note: 'MILLION' already defined in English section
        "MILLIARD": Decimal("1000000000"),
        # German
        "TAUSEND": Decimal("1000"),
        # Note: 'MILLION' already defined in English section
        "MILLIARDE": Decimal("1000000000"),
        # Portuguese
        # Note: 'MIL' already defined in Spanish section
        "MILHÃO": Decimal("1000000"),
        "MILHAO": Decimal("1000000"),
        "BILHÃO": Decimal("1000000000"),
        "BILHAO": Decimal("1000000000"),
        # Italian
        "MILA": Decimal("1000"),
        "MILIONE": Decimal("1000000"),
        "MILIARDO": Decimal("1000000000"),
        # Russian
        "ТЫСЯЧА": Decimal("1000"),
        "ТЫСЯЧИ": Decimal("1000"),
        "ТЫСЯЧ": Decimal("1000"),
        "МИЛЛИОН": Decimal("1000000"),
        "МИЛЛИОНА": Decimal("1000000"),
        "МИЛЛИОНОВ": Decimal("1000000"),
        "МИЛЛИАРД": Decimal("1000000000"),
        "МИЛЛИАРДА": Decimal("1000000000"),
        "МИЛЛИАРДОВ": Decimal("1000000000"),
    }

    # Build regex pattern for all suffixes (sorted by length, longest first)
    suffix_patterns = sorted(magnitude_map.keys(), key=len, reverse=True)
    escaped_patterns = [re.escape(s) for s in suffix_patterns]
    pattern = r"(" + "|".join(escaped_patterns) + r")\s*$"

    # Extract magnitude suffix if present
    magnitude_match = re.search("(?i)" + pattern, amount)
    multiplier = Decimal("1")

    if magnitude_match:
        suffix = magnitude_match.group(1)
        # All keys are upper case (upper() leaves non-Latin scripts unchanged)
        multiplier = magnitude_map.get(suffix.upper(), multiplier)
        # Remove the suffix from the amount
        amount = amount[: magnitude_match.start()].strip()

    # Clean the input by removing any characters that are not digits,
    # decimal separators, grouping separators, or a leading sign.
    cleaned_value = re.sub(r"[^\d.,\s]", "", amount).strip()

    # parse_decimal parses a locale-aware numeric string.
    try:
        number = parse_decimal(cleaned_value, locale=locale)
        # Apply magnitude multiplier
        number = number * multiplier
        # parse_decimal returns a Decimal; format it as a plain string.
        return format(number, "f")
    except ValueError:
        return None
