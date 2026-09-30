"""Deterministic salary extraction and normalization."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Currency symbol mapping
_CURRENCY_MAP: dict[str, str] = {
    "$": "USD",
    "usd": "USD",
    "cad": "CAD",
    "c$": "CAD",
    "£": "GBP",
    "gbp": "GBP",
    "€": "EUR",
    "eur": "EUR",
}

# Period normalization mapping
_PERIOD_MAP: dict[str, str] = {
    "year": "year",
    "yr": "year",
    "annually": "year",
    "annual": "year",
    "per year": "year",
    "p.a.": "year",
    "pa": "year",
    "hour": "hour",
    "hr": "hour",
    "hourly": "hour",
    "per hour": "hour",
    "month": "month",
    "mo": "month",
    "monthly": "month",
    "per month": "month",
    "day": "day",
    "daily": "day",
    "per day": "day",
    "week": "week",
    "weekly": "week",
    "per week": "week",
}

# Pattern for salary ranges: "$120,000 - $160,000 per year", "$120k-$160k/yr", "$70 - $90/hr"
_SALARY_RANGE_RE = re.compile(
    r"(?P<curr>[$£€]|USD|CAD|GBP|EUR)?\s*"
    r"(?P<min>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?P<min_k>[kK])?\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?P<curr2>[$£€]|USD|CAD|GBP|EUR)?\s*"
    r"(?P<max>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?P<max_k>[kK])?\s*"
    r"(?:(?P<curr3>USD|CAD|GBP|EUR)\b)?"
    r"(?:\s*(?:per|\/|a)\s*(?P<period>year|yr|annually|annual|hour|hr|hourly|month|mo|monthly|day|week))?",
    re.IGNORECASE,
)

# Pattern for single salary: "$150,000 annually", "$120k/year", "$80/hr", "$150,000"
_SALARY_SINGLE_RE = re.compile(
    r"(?P<curr>[$£€]|USD|CAD|GBP|EUR)?\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?P<k>[kK])?\s*"
    r"(?:(?P<curr2>USD|CAD|GBP|EUR)\b)?"
    r"(?:\s*(?:(?:per|\/|a)\s*(?P<period>year|yr|annually|annual|hour|hr|hourly|month|mo|monthly|day|week)|(?P<period_adv>annually|annual|hourly|monthly|daily|weekly)))?",
    re.IGNORECASE,
)


def _parse_amount(raw_str: str, has_k: bool) -> Decimal | None:
    """Convert number string to Decimal, scaling if 'k' suffix is present."""
    clean = raw_str.replace(",", "").strip()
    try:
        val = Decimal(clean)
        if has_k:
            val *= 1000
        return val
    except (ValueError, TypeError, InvalidOperation):
        return None


def _detect_period(period_raw: str | None, amount_hint: Decimal | None) -> str | None:
    if period_raw:
        lowered = period_raw.casefold().strip()
        if lowered in _PERIOD_MAP:
            return _PERIOD_MAP[lowered]

    # Heuristic based on magnitude if period is not explicitly mentioned:
    # >= 20000 is typically yearly, <= 300 is typically hourly
    if amount_hint is not None:
        if amount_hint >= 20000:
            return "year"
        if amount_hint <= 300:
            return "hour"

    return None


def parse_salary(
    text: str | None,
) -> tuple[Decimal | None, Decimal | None, str | None, str | None, str | None]:
    """Parse salary string or text into structured components.

    Returns:
        (salary_min, salary_max, salary_currency, salary_period, salary_text)
        All None if not found or text is empty.
    """
    if not text:
        return None, None, None, None, None

    # 1. Try range matches
    for match in _SALARY_RANGE_RE.finditer(text):
        has_curr = bool(match.group("curr") or match.group("curr2") or match.group("curr3"))
        has_k = bool(match.group("min_k") or match.group("max_k"))
        has_period = bool(match.group("period"))

        # Range must have currency, 'k' multiplier, or explicit salary period (e.g. /hr, per year)
        if not (has_curr or has_k or has_period):
            continue

        # If no currency, make sure it is not an experience range like "3-5 years"
        end_pos = match.end()
        tail = text[end_pos : end_pos + 25].lstrip().casefold()
        exp_prefixes = ("year", "yr", "month", "day", "week", "yoe")
        if not has_curr and not has_period and tail.startswith(exp_prefixes):
            continue

        min_raw = match.group("min")
        max_raw = match.group("max")
        min_k = bool(match.group("min_k"))
        max_k = bool(match.group("max_k"))
        if max_k and not min_k and min_raw and Decimal(min_raw.replace(",", "")) < 1000:
            # e.g. "120 - 160k" -> min is also k
            min_k = True

        min_val = _parse_amount(min_raw, min_k)
        max_val = _parse_amount(max_raw, max_k)

        if min_val is not None and max_val is not None:
            # Minimum sanity check: an annual salary without k is at least 1000
            # and an hourly salary is at least 5
            if not has_curr and min_val < 5:
                continue

            if min_val > max_val:
                min_val, max_val = max_val, min_val

            curr_raw = match.group("curr") or match.group("curr2") or match.group("curr3") or "$"
            currency = _CURRENCY_MAP.get(curr_raw.casefold(), "USD")
            period = _detect_period(match.group("period"), max_val)

            raw_matched = match.group(0).strip()
            return min_val, max_val, currency, period, raw_matched

    # 2. Try single salary match
    for match_single in _SALARY_SINGLE_RE.finditer(text):
        has_curr = bool(match_single.group("curr") or match_single.group("curr2"))
        has_k = bool(match_single.group("k"))
        period_matched = match_single.group("period") or match_single.group("period_adv")
        has_period = bool(period_matched)

        # Single salary must have currency, or 'k' with period. Never match plain number + year!
        if not (has_curr or (has_k and has_period)):
            continue

        amt_raw = match_single.group("amount")
        has_k_flag = bool(match_single.group("k"))
        amt = _parse_amount(amt_raw, has_k_flag)

        if amt is not None:
            # Avoid matching small numbers like "$5" or "$1" as salaries if no period/k
            if amt < 10 and not has_period:
                continue

            curr_raw = match_single.group("curr") or match_single.group("curr2") or "$"
            currency = _CURRENCY_MAP.get(curr_raw.casefold(), "USD")
            period = _detect_period(period_matched, amt)
            raw_matched = match_single.group(0).strip()
            return amt, amt, currency, period, raw_matched

    return None, None, None, None, None
