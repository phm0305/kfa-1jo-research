"""Offline tests for market.py and how prices and shares join the bundle.

Run from the repo root: py -B -m pytest research-center/test_market.py -q
(engine/ and research-center/ must be on PYTHONPATH)
"""

import shutil
from datetime import date, datetime

import pandas as pd
import pytest

import collect as c
import engine as e
import market as m
import pipeline as p
from test_pipeline import PROMPTS, fake_bundle, fake_gemini, page_data

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=c.KST)


def daily(*days):
    return pd.DataFrame({"Close": [1000 + n for n in range(len(days))]}, index=pd.to_datetime(list(days)))


def test_closes_are_each_finished_years_last_day_and_the_last_settled_day():
    prices = daily("2024-12-30", "2025-12-29", "2025-12-30", "2026-11-19", "2026-11-20")

    picked = m.pick_closes(prices, [2024, 2025, 2026], NOW)

    # 11/20 10:00 is before the close, so 11/19 is the latest; 2026 has not ended, so no year-end row for it
    assert [d.strftime("%Y-%m-%d") for d in picked.index] == ["2024-12-30", "2025-12-30", "2026-11-19"]
    after_close = m.pick_closes(prices, [2025], NOW.replace(hour=16))
    assert after_close.index.max() == pd.Timestamp("2026-11-20")


def test_a_close_more_than_seven_days_old_fails_the_gap_check():
    prices = c.collect_table(daily("2026-11-12", "2026-11-13"), {"Close": ("종가", "원")}, level=2, source="x",
                             source_url="u", reliability="중", basis=c.NOT_APPLICABLE, disclosed=c.SAME_AS_DATE,
                             stock_code="004370", stock_name="농심")
    assert m.price_problem(prices, date(2026, 11, 20)) == ""
    assert "8일 오래됨" in m.price_problem(prices.iloc[:1], date(2026, 11, 20))


def fake_shares(issued="6,082,642", treasury="248,454", outstanding="5,834,188"):
    common = {"se": "보통주", "rcept_no": "20260311003892", "stlm_dt": "2025-12-31", "isu_stock_totqy": "12,000,000",
              "istc_totqy": issued, "tesstk_co": treasury, "distb_stock_co": outstanding}
    body = {"status": "000", "list": [{"se": "우선주"}, common]}
    return type("Resp", (), {"json": lambda self: body})()


def test_shares_are_issued_not_authorized_and_outstanding_must_equal_issued_minus_treasury(monkeypatch):
    monkeypatch.setattr(m, "dart_corp", lambda code, key: ("00108241", "농심"))
    monkeypatch.setattr(m, "http_get", lambda url, params: fake_shares())

    rows = m.share_records("004370", "농심", 2025, "key")

    assert rows[["항목", "값", "단위", "기준일", "공시일"]].values.tolist() == [
        ["발행주식수(보통주)", 6082642, "주", "2025-12-31", "2026-03-11"],
        ["자기주식수(보통주)", 248454, "주", "2025-12-31", "2026-03-11"],
        ["유통주식수(보통주)", 5834188, "주", "2025-12-31", "2026-03-11"]]
    assert (rows["상태"] == c.PASSED).all()
    monkeypatch.setattr(m, "http_get", lambda url, params: fake_shares(outstanding="5,834,000"))
    with pytest.raises(c.CollectError, match="유통주식수"):
        m.share_records("004370", "농심", 2025, "key")


def market_bundle(price_days=("2026-11-19",), price_error="", shares=True):
    """fake_bundle plus prices and shares appended the way build_bundle does."""
    bundle = fake_bundle("004370", 2025, 2, "key")
    meta = dict(level=2, source=m.PRICE_SOURCE, source_url=m.PRICE_URL, reliability="중", basis=c.NOT_APPLICABLE,
                disclosed=c.SAME_AS_DATE, stock_code="004370", stock_name="농심")
    sources, prices, _ = p.append_source(bundle.sources, lambda: c.collect_table(daily(*price_days), {"Close": ("종가", "원")}, **meta))
    if price_error:
        prices = pd.DataFrame()
    share_rows = c.finalize(pd.DataFrame({"항목": m.SHARES_ITEMS, "값": (6082642, 248454, 5834188)}), level=1,
                            source=m.SHARES_SOURCE, source_url="https://dart.fss.or.kr", reliability="상",
                            basis=c.NOT_APPLICABLE, base_date="2025-12-31", disclosed="20260311", unit="주",
                            stock_code="004370", stock_name="농심")
    sources, share_rows, _ = p.append_source(sources, lambda: share_rows) if shares else (sources, pd.DataFrame(), "")
    stale = "" if prices.empty else m.price_problem(prices, NOW.date())
    return p.Bundle("004370", "농심", 2025, bundle.records, bundle.metrics, sources, prices=prices,
                    price_error=price_error, price_stale=stale, shares=share_rows,
                    shares_error="" if shares else "DART 013: 조회된 데이터가 없어요")


def test_appending_prices_and_shares_keeps_every_existing_rid_and_source_number():
    before = fake_bundle("004370", 2025, 2, "key")

    after = market_bundle()

    assert after.records["rid"].tolist() == before.records["rid"].tolist()
    assert after.sources.iloc[:len(before.sources)].equals(before.sources)
    assert after.sources["source_id"].tolist()[len(before.sources):] == ["S2", "S3"]
    assert after.prices[["기준일", "source_id"]].values.tolist() == [["2026-11-19", "S2"]]
    assert set(after.shares["source_id"]) == {"S3"}


def test_a_failed_collection_returns_no_rows_and_its_reason():
    def broken():
        raise c.CollectError("FinanceDataReader에서 주가를 받지 못했어요")

    sources, rows, reason = p.append_source(fake_bundle("004370", 2025, 2, "key").sources, broken)

    assert rows.empty and len(sources) == 1 and "주가를 받지 못했어요" in reason


def run_with(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", lambda *args: bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)
    return p.run("004370", 2025, prompts, tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])


def test_the_price_shows_with_its_date_and_source_on_page_one_the_data_block_and_the_page(tmp_path, monkeypatch):
    result = run_with(market_bundle(), tmp_path, monkeypatch)

    line = "현재 주가: 1,000원 (기준일 2026-11-19, 출처 S2)"
    assert f"## 1쪽 투자 요약\n\n{line}\n" in result.report.read_text(encoding="utf-8")
    assert ("주가", "✅", line) in result.status
    assert line in (tmp_path / "run" / "bundle.txt").read_text(encoding="utf-8")
    summary = page_data((tmp_path / "run" / "report.html").read_text(encoding="utf-8"))["summary"]
    assert (summary["current_price"], summary["price_as_of"], summary["price_source"], summary["upside_note"]) == (
        1000, "2026-11-19", "S2", None)


def test_a_stale_close_marks_the_gap_as_failed_and_the_run_goes_on(tmp_path, monkeypatch):
    result = run_with(market_bundle(price_days=("2026-11-12",)), tmp_path, monkeypatch)

    assert result.report is not None and not [s for s in result.status if s[1] == "❌"]
    assert [s[1] for s in result.status if s[0] == "주가"] == ["⚠"]
    assert "- [ ] 괴리율 검증 실패: 종가 기준일 2026-11-12" in result.verification.read_text(encoding="utf-8")
    summary = page_data((tmp_path / "run" / "report.html").read_text(encoding="utf-8"))["summary"]
    assert summary["upside_note"] == "검증 실패"


def test_no_price_and_no_shares_leave_their_reasons_and_the_run_goes_on(tmp_path, monkeypatch):
    result = run_with(market_bundle(price_error="FinanceDataReader에서 주가를 받지 못했어요", shares=False),
                      tmp_path, monkeypatch)

    assert result.report is not None and not [s for s in result.status if s[1] == "❌"]
    verification = result.verification.read_text(encoding="utf-8")
    assert "- [ ] 주가 없음, 밸류에이션 괴리율 계산 불가: FinanceDataReader에서" in verification
    assert "- [ ] 주식수 없음: DART 013" in verification
    assert "현재 주가: 없음 (FinanceDataReader에서 주가를 받지 못했어요). 밸류에이션 괴리율 계산 불가" in result.report.read_text(encoding="utf-8")
