"""Offline tests for market.py and how prices and shares join the bundle.

Run from the repo root: py -B -m pytest research-center/test_market.py -q
(conftest.py at the repo root puts engine/ and research-center/ on sys.path)
"""

import shutil
from datetime import date, datetime

import pandas as pd
import pytest

import collect as c
import engine as e
import market as m
import pipeline as p
from test_pipeline import PROMPTS, URL, fake_bundle, fake_gemini, page_data

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
    meta = dict(level=2, source="테스트 종가", source_url="https://example.com", reliability="중", basis=c.NOT_APPLICABLE,
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


def test_until_the_official_api_is_connected_prices_are_absent_with_their_reason():
    sources, rows, reason = p.append_source(fake_bundle("004370", 2025, 2, "key").sources,
                                            lambda: m.price_records("004370", "농심", [2024, 2025], NOW))

    assert rows.empty and len(sources) == 1 and reason == "공식 API 연결 전, 주가 없음"


def run_with(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", lambda *args: bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)
    return p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])


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
    result = run_with(market_bundle(price_error=m.NO_PRICE, shares=False),
                      tmp_path, monkeypatch)

    assert result.report is not None and not [s for s in result.status if s[1] == "❌"]
    verification = result.verification.read_text(encoding="utf-8")
    assert "- [ ] 주가 없음, 밸류에이션 괴리율 계산 불가: 공식 API 연결 전, 주가 없음" in verification
    assert "- [ ] 주식수 없음: DART 013" in verification
    assert "현재 주가: 없음 (공식 API 연결 전, 주가 없음). 밸류에이션 괴리율 계산 불가" in result.report.read_text(encoding="utf-8")


def owner_rows(net_income=170132973883, equity=2830704457688, basic_eps=29342):
    """Parent owners' rows as owner_records leaves them, tagged with the bundle's DART S1."""
    table = pd.DataFrame({"항목": ["지배주주순이익(연간)", "지배주주자본", "기본주당이익(연간)"],
                          "값": [net_income, equity, basic_eps], "기준일": "2025-12-31", "출처 URL": URL})
    rows = e.with_ids(c.finalize(table, level=1, source=m.DART_SOURCE, reliability="상", basis="연결", unit="원",
                                 disclosed="20260311", stock_code="004370", stock_name="농심"))
    return rows.assign(source_id="S1")


def test_owner_rows_come_from_the_income_statement_and_keep_the_filings_existing_source_number(monkeypatch):
    listed = [{"account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "sj_div": "SCE", "thstrm_amount": "1", "rcept_no": "20260311000001"},
              {"account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "sj_div": "IS", "thstrm_amount": "170132973883", "rcept_no": "20260311000001"},
              {"account_id": "ifrs-full_EquityAttributableToOwnersOfParent", "sj_div": "BS", "thstrm_amount": "2830704457688", "rcept_no": "20260311000001"}]
    body = {"status": "000", "list": listed}
    monkeypatch.setattr(m, "dart_corp", lambda code, key: ("00108241", "농심"))
    monkeypatch.setattr(m, "http_get", lambda url, params: type("Resp", (), {"json": lambda self: body})())
    sources = fake_bundle("004370", 2025, 2, "key").sources.assign(출처=m.DART_SOURCE)

    rows = m.owner_records("004370", "농심", 2025, "key", sources)

    assert rows[["항목", "값", "source_id"]].values.tolist() == [
        ["지배주주순이익(연간)", 170132973883, "S1"], ["지배주주자본", 2830704457688, "S1"], ["기본주당이익(연간)", None, "S1"]]
    assert "표준 계정(ifrs-full_BasicEarningsLossPerShare)을 못 찾음" in rows["비고"].iloc[2]


def metrics_for(prices_days=("2026-11-19",), price=345000, **owner):
    bundle = market_bundle(price_days=prices_days)
    prices = bundle.prices.assign(값=float(price))
    records = pd.concat([bundle.records, owner_rows(**owner)], ignore_index=True)
    stale = m.price_problem(prices, NOW.date())
    return m.valuation_metrics(records, prices, bundle.shares, stale, 2025, 2)


def test_valuation_metrics_follow_valuation_md_and_are_numbered_after_the_engine_metrics():
    metrics = metrics_for().set_index("지표")

    assert metrics["metric_id"].tolist() == ["M2", "M3", "M4", "M5", "M6"]
    eps, bps = 170132973883 / 5834188, 2830704457688 / 5834188
    assert metrics.loc["EPS", "값"] == pytest.approx(eps) and metrics.loc["BPS", "값"] == pytest.approx(bps)
    assert metrics.loc["시가총액", "값"] == 345000 * 6082642
    assert metrics.loc["PER", "값"] == pytest.approx(345000 / eps) and metrics.loc["PBR", "값"] == pytest.approx(345000 / bps)
    assert "PER보다 4.26% 큼" in metrics.loc["시가총액", "계산식"] and "4.26%" in metrics.loc["PER", "계산식"]
    assert (metrics["상태"] == e.COMPUTED).all()


def test_a_stale_close_blocks_only_the_price_based_metrics():
    metrics = metrics_for(prices_days=("2026-11-12",)).set_index("지표")

    assert metrics.loc[["EPS", "BPS"], "값"].notna().all()
    assert metrics.loc[["시가총액", "PER", "PBR"], "값"].isna().all()
    assert metrics.loc["PER", "이유"].startswith("주가 검증 실패: 종가 기준일 2026-11-12")


def test_a_loss_keeps_a_negative_eps_but_holds_per():
    metrics = metrics_for(net_income=-1000000000).set_index("지표")

    assert metrics.loc["EPS", "값"] < 0
    assert metrics.loc["PER", "값"] is None and "지배주주순이익이(가) 0 이하라 PER 보류" in metrics.loc["PER", "이유"]
    assert metrics.loc["PBR", "값"] is not None


def test_no_price_leaves_a_reason_instead_of_a_number():
    bundle = market_bundle(price_error=m.NO_PRICE)
    records = pd.concat([bundle.records, owner_rows()], ignore_index=True)
    metrics = m.valuation_metrics(records, bundle.prices, bundle.shares, "", 2025, 2).set_index("지표")

    assert metrics.loc[["시가총액", "PER", "PBR"], "이유"].tolist() == ["주가 없음"] * 3
    assert metrics.loc[["시가총액", "PER", "PBR"], "값"].isna().all()
    assert metrics.loc[["EPS", "BPS"], "값"].notna().all() and (metrics.loc[["EPS", "BPS"], "상태"] == e.COMPUTED).all()


def test_a_per_written_from_the_metric_table_is_judged_by_the_number_check():
    bundle = market_bundle()
    records = pd.concat([bundle.records, owner_rows()], ignore_index=True)
    metrics = pd.concat([bundle.metrics, metrics_for()], ignore_index=True)
    per = metrics[metrics["지표"] == "PER"].iloc[0]
    claims = [{"claim_id": "C-1", "문장": "PER 11.83배", "근거": [[per["metric_id"], "11.83", "배"]]},
              {"claim_id": "C-2", "문장": "PER 13배", "근거": [[per["metric_id"], "13", "배"]]}]

    checked = e.check_claims(claims, metrics, records)

    assert checked["판정"].tolist() == [e.PASS, e.FIX]


def test_the_computed_eps_is_shown_next_to_darts_basic_eps_without_judging_the_gap():
    bundle = market_bundle()
    records = pd.concat([bundle.records, owner_rows()], ignore_index=True)
    metrics = pd.concat([bundle.metrics, metrics_for()], ignore_index=True)

    line = p.eps_line(p.Bundle("004370", "농심", 2025, records, metrics, bundle.sources))

    print(line)
    assert line == ("EPS 대조: 계산 EPS 29,161.38원(M2, 연말 유통주식수 기준) / "
                    "DART 기본주당이익 29,342원(가중평균 주식수 기준) / 차이 -0.62%")
