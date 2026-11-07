"""ETF groups that give the whole-market view (architecture §5.6). Every symbol here is in
`config/settings.yaml → data.reference_symbols`, so it gets daily prices like any stock."""
from __future__ import annotations

GROUPS: dict[str, dict[str, str]] = {
    "index": {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Small caps (Russell 2000)", "DIA": "Dow Jones",
              "RSP": "S&P 500 equal-weight (the average stock)", "MDY": "Mid caps"},
    "sector": {"XLK": "Technology", "XLV": "Healthcare", "XLF": "Financials", "XLE": "Energy", "XLI": "Industrials",
               "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials",
               "XLRE": "Real Estate", "XLC": "Communication Services"},
    "theme": {"SMH": "Semiconductors", "SOXX": "Semiconductors (broad)", "IGV": "Software", "CIBR": "Cybersecurity",
              "SKYY": "Cloud", "BOTZ": "Robotics & AI", "XBI": "Biotech", "IBB": "Biotech (large)", "ITA": "Aerospace & defense",
              "KRE": "Regional banks", "XHB": "Homebuilders", "XRT": "Retail", "JETS": "Airlines", "XOP": "Oil & gas producers",
              "TAN": "Solar", "URA": "Uranium & nuclear", "LIT": "Lithium & batteries", "COPX": "Copper miners",
              "PAVE": "Infrastructure", "ARKK": "Speculative growth"},
    "style": {"IWF": "Large growth", "IWD": "Large value", "MTUM": "Momentum", "QUAL": "Quality", "USMV": "Low volatility"},
    "rates_credit": {"SHY": "Short-term Treasuries (1–3 yr)", "IEF": "10-year Treasuries", "TLT": "20+ year Treasuries",
                     "TIP": "Inflation-protected Treasuries", "LQD": "Investment-grade corporate bonds",
                     "HYG": "High-yield (junk) bonds"},
    "commodity_fx": {"GLD": "Gold", "SLV": "Silver", "USO": "Crude oil", "UNG": "Natural gas", "DBC": "Commodities basket",
                     "CPER": "Copper", "UUP": "US dollar", "IBIT": "Bitcoin", "VIXY": "Volatility (fear gauge futures)"},
    "global": {"VGK": "Europe", "EWJ": "Japan", "FXI": "China large caps", "INDA": "India", "EWZ": "Brazil",
               "EWY": "South Korea", "EWT": "Taiwan", "EEM": "Emerging markets"},
}

ALL = [s for g in GROUPS.values() for s in g]
NAME = {s: n for g in GROUPS.values() for s, n in g.items()}
