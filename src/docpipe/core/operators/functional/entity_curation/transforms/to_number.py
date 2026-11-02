"""Entity curation transform: numbers with magnitude suffixes (k, M, billion, ...) to floats."""

import re2 as re


def to_number(*, number_str: str | None) -> float | None:
    """Convert a human-readable number represented as a string to a machine-readable number.

    If number_str is None, returns None without attempting conversion.

    Supports multi-language number suffixes including:
    - English: K, M, B, T, thousand, million, billion, trillion
    - Chinese: 千 (qian), 万 (wan), 亿 (yi)
    - Japanese: 千 (sen), 万 (man), 億 (oku), 兆 (chou)
    - Korean: 천 (cheon), 만 (man), 억 (eok), 조 (jo)
    - Spanish: mil, millón, billón, trillón
    - French: mille, million, milliard, billion
    - German: tausend, Million, Milliarde, Billion
    - Portuguese: mil, milhão, bilhão, trilhão
    - Italian: mila, milione, miliardo, bilione
    - Russian: тысяча (tysyacha), миллион (million), миллиард (milliard)

    Args:
        number_str: The human-readable number as a string

    Returns:
        float: The machine-readable number

    Raises:
        ValueError: If the number format is invalid

    Examples:
        >>> to_number(number_str="10K")
        10000.0
        >>> to_number(number_str="10 thousand")
        10000.0
        >>> to_number(number_str="2.5M")
        2500000.0
        >>> to_number(number_str="10万")  # Chinese: 10 wan = 100,000
        100000.0
        >>> to_number(number_str="5億")  # Japanese: 5 oku = 500,000,000
        500000000.0
        >>> to_number(number_str="3 millón")  # Spanish
        3000000.0
    """
    # Handle None input gracefully
    if number_str is None:
        return None

    # Remove commas and spaces from the input string
    number_str = number_str.replace(",", "").strip()

    # Define multipliers for multi-language suffixes
    # Note: Unicode characters are already decoded by json.loads() before this function is called
    multipliers = {
        # English - Single letter abbreviations
        "K": 1e3,
        "M": 1e6,
        "G": 1e9,
        "B": 1e9,
        "T": 1e12,
        # English - Full words
        "THOUSAND": 1e3,
        "KILO": 1e3,
        "MILLION": 1e6,
        "MEGA": 1e6,
        "BILLION": 1e9,
        "GIGA": 1e9,
        "TRILLION": 1e12,
        "TERA": 1e12,
        # Chinese & Japanese (shared characters)
        "千": 1e3,  # qian (Chinese thousand) / sen (Japanese thousand)
        "万": 1e4,  # wan (Chinese ten thousand) / man (Japanese ten thousand)
        "億": 1e8,  # yi (Chinese hundred million) / oku (Japanese hundred million)
        "亿": 1e8,  # yi (simplified Chinese)
        "兆": 1e12,  # chou (Japanese trillion)
        # Korean
        "천": 1e3,  # cheon (thousand)
        "만": 1e4,  # man (ten thousand)
        "억": 1e8,  # eok (hundred million)
        "조": 1e12,  # jo (trillion)
        # Spanish
        "MIL": 1e3,
        "MILLÓN": 1e6,
        "MILLON": 1e6,
        "MILLONES": 1e6,
        "BILLÓN": 1e9,
        "BILLON": 1e9,
        "BILLONES": 1e9,
        "TRILLÓN": 1e12,
        "TRILLON": 1e12,
        "TRILLONES": 1e12,
        # French
        "MILLE": 1e3,
        # Note: 'MILLION' already defined in English section
        "MILLIONS": 1e6,
        "MILLIARD": 1e9,
        "MILLIARDS": 1e9,
        # Note: 'BILLION' already defined in English section
        "BILLIONS": 1e9,
        # German
        "TAUSEND": 1e3,
        # Note: 'MILLION' already defined in English section
        "MILLIONEN": 1e6,
        "MILLIARDE": 1e9,
        "MILLIARDEN": 1e9,
        # Note: 'BILLION' already defined in English section
        "BILLIONEN": 1e9,
        # Portuguese
        # Note: 'MIL' already defined in Spanish section
        "MILHÃO": 1e6,
        "MILHAO": 1e6,
        "MILHÕES": 1e6,
        "MILHOES": 1e6,
        "BILHÃO": 1e9,
        "BILHAO": 1e9,
        "BILHÕES": 1e9,
        "BILHOES": 1e9,
        "TRILHÃO": 1e12,
        "TRILHAO": 1e12,
        "TRILHÕES": 1e12,
        "TRILHOES": 1e12,
        # Italian
        "MILA": 1e3,
        "MILIONE": 1e6,
        "MILIONI": 1e6,
        "MILIARDO": 1e9,
        "MILIARDI": 1e9,
        "BILIONE": 1e12,
        "BILIONI": 1e12,
        # Russian
        "ТЫСЯЧА": 1e3,
        "ТЫСЯЧИ": 1e3,
        "ТЫСЯЧ": 1e3,
        "МИЛЛИОН": 1e6,
        "МИЛЛИОНА": 1e6,
        "МИЛЛИОНОВ": 1e6,
        "МИЛЛИАРД": 1e9,
        "МИЛЛИАРДА": 1e9,
        "МИЛЛИАРДОВ": 1e9,
        "ТРИЛЛИОН": 1e12,
        "ТРИЛЛИОНА": 1e12,
        "ТРИЛЛИОНОВ": 1e12,
    }

    # Build regex pattern for all suffixes
    # Sort by length (longest first) to match longer suffixes before shorter ones
    suffix_patterns = sorted(multipliers.keys(), key=len, reverse=True)
    # Escape special regex characters and join with |
    escaped_patterns = [re.escape(s) for s in suffix_patterns]
    pattern = r"(?i) ?(" + "|".join(escaped_patterns) + r") ?$"

    # Try to match a suffix at the end (case-insensitive for Latin scripts)
    match = re.search(pattern, number_str)

    if match:
        # Extract the suffix
        suffix = match.group(1)
        # All keys are upper case (upper() leaves non-Latin scripts unchanged)
        multiplier = multipliers.get(suffix.upper(), 1)
        # Remove the suffix from the number string
        number_str = number_str[: match.start()].strip()
    else:
        # If there's no suffix, the multiplier is 1
        multiplier = 1

    # Convert the numeric part to a float and apply the multiplier
    try:
        number = float(number_str) * multiplier
    except ValueError:
        return None

    return number
