from datetime import UTC, datetime
from typing import Any

import re2 as re


def make_date_uniform(*, date_str: Any) -> str | None:
    """
    Convert various date formats to uniform YYYY-MM-DD format.

    Supports multiple date formats including:
    - ISO format: 2024-01-15, 2024/01/15
    - US format: 01/15/2024, 01-15-2024
    - European format: 15/01/2024, 15-01-2024
    - Text format: January 15, 2024, 15 Jan 2024
    - Compact format: 20240115

    Args:
        date_str: Date string in various formats

    Returns:
        Date string in YYYY-MM-DD format, or None if parsing fails

    Examples:
        >>> make_date_uniform(date_str="01/15/2024")
        '2024-01-15'
        >>> make_date_uniform(date_str="15-Jan-2024")
        '2024-01-15'
        >>> make_date_uniform(date_str="2024/01/15")
        '2024-01-15'
    """
    if not date_str:
        return None

    value_str = str(date_str).strip()
    if not value_str:
        return None

    # Pattern 1: Already in YYYY-MM-DD format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value_str):
        return value_str

    # Pattern 2: YYYY/MM/DD format
    match = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", value_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # Pattern 3: MM/DD/YYYY or DD/MM/YYYY format (ambiguous - assume MM/DD/YYYY for US)
    match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", value_str)
    if match:
        first, second, year = match.groups()
        # Heuristic: if first > 12, it's DD/MM/YYYY, otherwise MM/DD/YYYY
        if int(first) > 12:
            day, month = first, second
        else:
            month, day = first, second
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # Pattern 4: Compact format YYYYMMDD
    match = re.match(r"^(\d{4})(\d{2})(\d{2})$", value_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"

    # Pattern 5: Text formats with month names
    # Try common text formats
    text_formats = [
        "%B %d, %Y",  # January 15, 2024
        "%b %d, %Y",  # Jan 15, 2024
        "%d %B %Y",  # 15 January 2024
        "%d %b %Y",  # 15 Jan 2024
        "%B %d %Y",  # January 15 2024
        "%b %d %Y",  # Jan 15 2024
        "%d-%b-%Y",  # 15-Jan-2024
        "%d-%B-%Y",  # 15-January-2024
        "%Y %B %d",  # 2024 January 15
        "%Y %b %d",  # 2024 Jan 15
    ]

    for fmt in text_formats:
        try:
            dt = datetime.strptime(value_str, fmt).replace(tzinfo=UTC)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Pattern 6: Try datefinder as fallback (if available)
    try:
        import datefinder

        matches = list(datefinder.find_dates(value_str))
        if matches:
            return matches[0].strftime("%Y-%m-%d")
    except ImportError:
        pass
    except Exception:  # nosec B110 — intentional: date parsing is best-effort; any failure returns None
        pass

    # If all parsing attempts fail, return None
    return None
