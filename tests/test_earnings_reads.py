"""Earnings release reader: text preparation, masking, surprise maths and the point-in-time release features
(no network, no AI; the feature query is replaced with synthetic rows)."""
from datetime import datetime, timezone

import numpy as np
import pytest

from core.features import releases
from core.jobs.earnings_reads import html_to_text, mask, name_variants, pick_release, surprises
from tests.test_strategy import _market


def test_table_rows_become_one_line():
    raw = ("<p>Revenue grew.</p><table><tr><td><p>Revenue</p></td><td>$</td><td><p>90,400</p></td>"
           "<td>83,600</td></tr><tr><td>Net loss</td><td>(13,200</td><td>)</td></tr></table><script>x()</script>")
    t = html_to_text(raw)
    assert "Revenue | 90,400 | 83,600" in t and "Net loss | (13,200" in t and "x()" not in t


def test_mask_hides_company_ticker_people_links_and_years():
    text = ("Fulgent Reports Third Quarter 2026 Results. EL MONTE, CA, November 5, 2026 — Fulgent Genetics, Inc. "
            "(NASDAQ: FLGT) (“Fulgent,” or the “Company”) today announced results. Ming Hsieh, Chief Executive "
            "Officer, said “Great quarter.” Hsieh added more. Full-year 2027 outlook vs 2025. See www.fulgentgenetics.com "
            "or ir@fulgentgenetics.com. FY26 guidance.")
    m = mask(text, "Fulgent Genetics, Inc. Common Stock", "FLGT", 2026)
    for leak in ("Fulgent", "FLGT", "Hsieh", "2026", "2027", "fulgentgenetics", "FY26"):
        assert leak not in m, leak
    assert "Y0" in m and "Y+1" in m and "Y-1" in m and "TICKER" in m and "[executive]" in m


def test_name_variants_strip_share_class_and_skip_common_first_words():
    assert "Fulgent" in name_variants("Fulgent Genetics, Inc. Common Stock")
    v = name_variants("American Express Company Common Stock")
    assert "American Express" in v and "American" not in v
    assert mask("ON Semiconductor beat; results ON track", "", "ON", 2026).count("ON") == 2   # 2-letter ticker kept


def test_pick_release_prefers_exhibit_99_1():
    docs = [{"type": "8-K", "url": "a.htm"}, {"type": "EX-99.2", "url": "b.htm"}, {"type": "EX-99.1", "url": "c.htm"},
            {"type": "EX-99.1", "url": "d.jpg"}]
    assert pick_release(docs)["url"] == "c.htm"
    assert pick_release([{"type": "8-K", "url": "a.htm"}]) is None


def test_surprises_guard_units_and_tiny_estimates():
    e, r = surprises({"eps_adjusted": 1.10, "eps_gaap": 0.5, "revenue_millions": 105, "currency": "USD"},
                     {"eps_estimate": 1.0, "revenue_estimate": 100e6})
    assert e == pytest.approx(0.10) and r == pytest.approx(0.05)
    assert surprises({"eps_gaap": 0.05, "revenue_millions": 105_000, "currency": "USD"},
                     {"eps_estimate": 0.01, "revenue_estimate": 100e6}) == (None, None)       # tiny estimate; unit slip
    assert surprises({"eps_adjusted": None, "eps_gaap": -0.5, "revenue_millions": 105, "currency": "EUR"},
                     {"eps_estimate": -0.25, "revenue_estimate": 100e6}) == (pytest.approx(-1.0), None)


def _rows(m):
    d = m.dates

    def at(i, hour):           # ET hour on trading day i → UTC timestamp (November-style offset, 5 h)
        return datetime(d[i].year, d[i].month, d[i].day, hour + 5, 5, tzinfo=timezone.utc)
    return [  # S1: read release after the close on day 100 → visible from day 101; day 160 release unread → blank
        {"symbol": "S1", "accepted_at": at(100, 16), "timing": "after_close", "status": "ok", "tone": 2,
         "guidance": "raised", "rev_surprise": 0.04},
        {"symbol": "S1", "accepted_at": at(160, 7), "timing": "before_open", "status": None, "tone": None,
         "guidance": None, "rev_surprise": None},
        # S2: before-open release on day 120 → visible the same day; an amendment the same morning was not read
        {"symbol": "S2", "accepted_at": at(120, 7), "timing": "before_open", "status": "ok", "tone": -1,
         "guidance": "lowered", "rev_surprise": None},
        {"symbol": "S2", "accepted_at": at(120, 8), "timing": "before_open", "status": None, "tone": None,
         "guidance": None, "rev_surprise": None},
    ]


def test_release_features_are_point_in_time(monkeypatch):
    m = _market(T=200, N=4)
    rows = _rows(m)
    monkeypatch.setattr(releases, "query", lambda sql, params: [r for r in rows if r["accepted_at"].replace(tzinfo=None) < params[2]])
    f = releases.compute(m)
    j1, j2 = m.symbols.index("S1"), m.symbols.index("S2")
    assert np.isnan(f["release_tone"][100, j1]) and f["release_tone"][101, j1] == 2
    assert f["guidance_change"][159, j1] == 1 and f["rev_surprise"][150, j1] == pytest.approx(0.04)
    assert np.isnan(f["release_tone"][160, j1])                   # the next (unread) release replaces the old read
    assert f["release_tone"][120, j2] == -1 and f["guidance_change"][130, j2] == -1
    assert np.isnan(f["release_tone"][119, j2])
    # truncating the market at day 110 gives the same values up to 110 (no look-ahead)
    from core.lab.evaluate import slice_market
    cut = slice_market(m, str(m.dates[0].date()), str(m.dates[110].date()))
    g = releases.compute(cut)
    assert np.array_equal(np.nan_to_num(g["release_tone"], nan=-9), np.nan_to_num(f["release_tone"][:111], nan=-9))
