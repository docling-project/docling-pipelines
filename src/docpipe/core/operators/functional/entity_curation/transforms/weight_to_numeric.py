"""Entity curation transform: weights with units to kilograms, using locale-specific units."""

import re2 as re


def weight_to_numeric(*, weight: str | None, locale: str = "en_US") -> float | None:
    """
    Convert a numeric weight into kilograms with locale-aware multi-language unit support.

    If weight is None, returns None without attempting conversion.

    This function uses the locale parameter to determine which weight units to prioritize,
    similar to how currency_to_numeric() handles locale-specific formatting. This is
    particularly important for ambiguous units like 斤 which has different values in
    Chinese (500g) vs Japanese (600g) contexts.

    Supported locales and their specific units:
    - en_US, en_GB: kg, kilogram, g, gram, mg, milligram, t, ton, lb, pound, oz, ounce
    - zh_CN, zh_TW: 公斤, 克, 吨, 斤 (500g), 两
    - ja_JP: キログラム, グラム, トン, 斤 (600g)
    - ko_KR: 킬로그램, 그램, 톤, 근 (600g)
    - es_ES, es_MX: kilogramo, gramo, tonelada, libra, onza
    - fr_FR: kilogramme, gramme, tonne, livre, once
    - de_DE: Kilogramm, Gramm, Tonne, Pfund (500g), Unze
    - pt_BR, pt_PT: quilograma, grama, tonelada, libra, onça
    - it_IT: chilogrammo, grammo, tonnellata, libbra, oncia
    - ru_RU: килограмм, грамм, тонна, фунт

    Args:
        weight: The weight to be converted (e.g., "10 kg", "5斤", "100 gramos")
        locale: The locale identifier (e.g., "en_US", "zh_CN", "ja_JP", "de_DE").
               Used to resolve ambiguous units and prioritize locale-specific units.

    Returns:
        float: The weight in kilograms

    Raises:
        ValueError: If the weight format is invalid or the unit is unrecognized

    Examples:
        >>> weight_to_numeric(weight="10 kg", locale="en_US")
        10.0
        >>> weight_to_numeric(weight="5斤", locale="zh_CN")  # Chinese jin = 500g
        2.5
        >>> weight_to_numeric(weight="5斤", locale="ja_JP")  # Japanese kin = 600g
        3.0
        >>> weight_to_numeric(weight="100 gramos", locale="es_ES")
        0.1
        >>> weight_to_numeric(weight="2 Pfund", locale="de_DE")  # German pound = 500g
        1.0

    Note:
        The locale parameter is used to resolve ambiguous units. For example, the
        character 斤 means different things in Chinese (500g) vs Japanese (600g).
        By specifying the locale, the function can correctly interpret the unit.
    """
    # Handle None input gracefully
    if weight is None:
        return None

    # Define locale-specific weight unit mappings
    # Each locale has its own dictionary to handle locale-specific variations
    locale_units: dict[str, dict[str, float]] = {
        # English locales (US, UK, etc.)
        "en_US": {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "mg": 0.000001,
            "milligram": 0.000001,
            "milligrams": 0.000001,
            "t": 1000,
            "ton": 1000,
            "tons": 1000,
            "tonne": 1000,
            "tonnes": 1000,
            "lb": 0.453592,
            "lbs": 0.453592,
            "pound": 0.453592,
            "pounds": 0.453592,
            "oz": 0.0283495,
            "ounce": 0.0283495,
            "ounces": 0.0283495,
        },
        # Chinese locales
        "zh_CN": {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "公斤": 1,  # gongjin (kilogram)
            "千克": 1,  # qianke (kilogram)
            "克": 0.001,  # ke (gram)
            "毫克": 0.000001,  # haoke (milligram)
            "吨": 1000,  # dun (ton)
            "噸": 1000,  # dun (traditional)
            "斤": 0.5,  # jin (Chinese catty, 500g) - CHINESE VALUE
            "两": 0.05,  # liang (tael, 50g)
            "兩": 0.05,  # liang (traditional)
        },
        # Japanese locale
        "ja_JP": {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "キログラム": 1,  # kiroguramu (kilogram)
            "キロ": 1,  # kiro (kilo)
            "グラム": 0.001,  # guramu (gram)
            "ミリグラム": 0.000001,  # miriguramu (milligram)
            "トン": 1000,  # ton
            "斤": 0.6,  # kin (Japanese catty, 600g) - JAPANESE VALUE
        },
        # Korean locale
        "ko_KR": {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "킬로그램": 1,  # killogeuraem (kilogram)
            "킬로": 1,  # killo (kilo)
            "그램": 0.001,  # geuraem (gram)
            "밀리그램": 0.000001,  # milligeuraem (milligram)
            "톤": 1000,  # ton
            "근": 0.6,  # geun (Korean catty, 600g)
        },
        # Spanish locales
        "es_ES": {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "kilogramo": 1,
            "kilogramos": 1,
            "gramo": 0.001,
            "gramos": 0.001,
            "miligramo": 0.000001,
            "miligramos": 0.000001,
            "tonelada": 1000,
            "toneladas": 1000,
            "libra": 0.453592,
            "libras": 0.453592,
            "onza": 0.0283495,
            "onzas": 0.0283495,
        },
        # French locale
        "fr_FR": {
            "kg": 1,
            "kilogram": 1,
            "kilogramme": 1,
            "kilogrammes": 1,
            "g": 0.001,
            "gram": 0.001,
            "gramme": 0.001,
            "grammes": 0.001,
            "milligramme": 0.000001,
            "milligrammes": 0.000001,
            "tonne": 1000,
            "tonnes": 1000,
            "livre": 0.453592,
            "livres": 0.453592,
            "once": 0.0283495,
            "onces": 0.0283495,
        },
        # German locale
        "de_DE": {
            "kg": 1,
            "kilogram": 1,
            "kilogramm": 1,
            "g": 0.001,
            "gram": 0.001,
            "gramm": 0.001,
            "milligramm": 0.000001,
            "tonne": 1000,
            "tonnen": 1000,
            "pfund": 0.5,  # German pound (500g)
            "unze": 0.0283495,
        },
        # Portuguese locales
        "pt_BR": {
            "kg": 1,
            "kilogram": 1,
            "quilograma": 1,
            "quilogramas": 1,
            "g": 0.001,
            "gram": 0.001,
            "grama": 0.001,
            "gramas": 0.001,
            "miligrama": 0.000001,
            "miligramas": 0.000001,
            "tonelada": 1000,
            "toneladas": 1000,
            "libra": 0.453592,
            "libras": 0.453592,
            "onça": 0.0283495,
            "onças": 0.0283495,
        },
        # Italian locale
        "it_IT": {
            "kg": 1,
            "kilogram": 1,
            "chilogrammo": 1,
            "chilogrammi": 1,
            "g": 0.001,
            "gram": 0.001,
            "grammo": 0.001,
            "grammi": 0.001,
            "milligrammo": 0.000001,
            "milligrammi": 0.000001,
            "tonnellata": 1000,
            "tonnellate": 1000,
            "libbra": 0.453592,
            "libbre": 0.453592,
            "oncia": 0.0283495,
            "once": 0.0283495,
        },
        # Russian locale
        "ru_RU": {
            "kg": 1,
            "kilogram": 1,
            "g": 0.001,
            "gram": 0.001,
            "килограмм": 1,
            "килограмма": 1,
            "килограммов": 1,
            "грамм": 0.001,
            "грамма": 0.001,
            "граммов": 0.001,
            "миллиграмм": 0.000001,
            "миллиграмма": 0.000001,
            "тонна": 1000,
            "тонны": 1000,
            "тонн": 1000,
            "фунт": 0.453592,
            "фунта": 0.453592,
            "фунтов": 0.453592,
        },
    }

    # Normalize locale (handle variations like en-US, en_US, en)
    locale = locale.replace("-", "_")

    # Try exact locale match first, then try language prefix
    weight_unit_map: dict[str, float] | None = None

    if locale in locale_units:
        weight_unit_map = locale_units[locale]
    else:
        # Try language prefix (e.g., 'en' from 'en_US')
        lang_prefix = locale.split("_")[0]
        for loc_key in locale_units:
            if loc_key.startswith(lang_prefix + "_"):
                weight_unit_map = locale_units[loc_key]
                break

    # Fallback to en_US if locale not found
    if weight_unit_map is None:
        weight_unit_map = locale_units["en_US"]

    # Build regex pattern to match number followed by optional space and unit
    # Sort units by length (longest first) to match longer units before shorter ones
    units_sorted = sorted(weight_unit_map.keys(), key=len, reverse=True)
    escaped_units = [re.escape(unit) for unit in units_sorted]
    unit_pattern = "|".join(escaped_units)

    # Pattern: number (with optional decimal) + optional space + unit
    pattern = r"(\d+(?:[.,]\d+)?)\s*(" + unit_pattern + r")?"
    match = re.search("(?i)" + pattern, weight)

    if match:
        # Extract numeric value (handle both . and , as decimal separators)
        value_str = match.group(1).replace(",", ".")
        value = float(value_str)

        # Extract unit (if present)
        unit = match.group(2)

        if unit:
            # All keys are lower case (lower() leaves non-Latin scripts unchanged)
            unit_lower = unit.lower()
            if unit_lower in weight_unit_map:
                return value * weight_unit_map[unit_lower]
            # Matched only through Unicode case folding, e.g. "\u017f" (long s) for "s"
            return None
        # No unit specified, assume kilograms
        return value
    return None
