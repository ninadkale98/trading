"""Map SEC SIC industry codes to 11 broad sectors (similar to the standard GICS sectors)."""
from __future__ import annotations

TECH = "Technology"
HEALTH = "Healthcare"
FIN = "Financials"
REIT = "Real Estate"
ENERGY = "Energy"
MATERIALS = "Materials"
INDUSTRIALS = "Industrials"
DISCRETIONARY = "Consumer Discretionary"
STAPLES = "Consumer Staples"
COMM = "Communication Services"
UTIL = "Utilities"

# (low, high, sector) — first match wins, so specific ranges come before broad ones
_RANGES: list[tuple[int, int, str]] = [
    (1311, 1389, ENERGY), (2911, 2999, ENERGY), (4610, 4619, ENERGY), (4920, 4925, ENERGY), (5171, 5172, ENERGY),
    (1000, 1499, MATERIALS), (2800, 2829, MATERIALS), (2840, 2899, MATERIALS), (2600, 2699, MATERIALS),
    (3300, 3399, MATERIALS), (2400, 2499, MATERIALS), (3200, 3299, MATERIALS),
    (2830, 2836, HEALTH), (3841, 3851, HEALTH), (8000, 8099, HEALTH), (5047, 5047, HEALTH), (5122, 5122, HEALTH),
    (8731, 8731, HEALTH),
    (3570, 3579, TECH), (3600, 3699, TECH), (3670, 3679, TECH), (3810, 3829, TECH), (7370, 7379, TECH),
    (5045, 5045, TECH), (3577, 3577, TECH), (3661, 3669, TECH),
    (4800, 4899, COMM), (2710, 2799, COMM), (7810, 7819, COMM), (7800, 7899, COMM),
    (4900, 4999, UTIL),
    (6798, 6798, REIT), (6500, 6599, REIT),
    (6000, 6799, FIN),
    (2000, 2199, STAPLES), (5400, 5499, STAPLES), (5140, 5149, STAPLES), (5912, 5912, STAPLES), (2840, 2844, STAPLES),
    (3710, 3716, DISCRETIONARY), (3750, 3751, DISCRETIONARY), (2300, 2399, DISCRETIONARY), (3140, 3149, DISCRETIONARY),
    (5000, 5999, DISCRETIONARY), (7000, 7099, DISCRETIONARY), (5800, 5899, DISCRETIONARY), (3630, 3639, DISCRETIONARY),
    (3940, 3949, DISCRETIONARY), (7900, 7999, DISCRETIONARY), (1520, 1549, DISCRETIONARY), (2500, 2599, DISCRETIONARY),
    (8200, 8299, DISCRETIONARY), (7200, 7299, DISCRETIONARY),
    (100, 999, STAPLES),
    (1500, 1799, INDUSTRIALS), (3400, 3599, INDUSTRIALS), (3700, 3799, INDUSTRIALS), (4000, 4799, INDUSTRIALS),
    (8700, 8799, INDUSTRIALS), (7300, 7399, INDUSTRIALS), (3800, 3899, INDUSTRIALS), (5000, 5099, INDUSTRIALS),
    (2000, 3999, INDUSTRIALS),
]


def sector_for_sic(sic: int | None) -> str | None:
    if not sic:
        return None
    for lo, hi, sector in _RANGES:
        if lo <= sic <= hi:
            return sector
    return None
