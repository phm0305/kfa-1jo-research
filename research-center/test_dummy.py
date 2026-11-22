"""Offline tests for a member's dummy rows (dummy.py) through pipeline.run with fake Gemini answers.

Run from the repo root: py -B -m pytest research-center/test_dummy.py -q
"""

import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import collect as c
import dummy as d
import engine as e
import market as m
import pipeline as p
from test_pipeline import PROMPTS, fake_bundle, fake_gemini, page_data

LATER = ("claims", "qa", "cross_exam")
TODAY = datetime.now(c.KST).date()


def rich_bundle(stock_code, year, n_years, api_key, prices=None):
    """fake_bundle plus share counts and the five valuation metrics, priced from `prices` when given."""
    bundle = fake_bundle(stock_code, year, n_years, api_key)
    rows = pd.DataFrame({"항목": m.SHARES_ITEMS, "값": (1000, 100, 900), "기준일": "2025-12-31"})
    shares = c.finalize(rows, level=1, source=m.SHARES_SOURCE, source_url="https://dart.example/shares", reliability="상",
                        basis=c.NOT_APPLICABLE, unit="주", disclosed="20260311", stock_code="004370", stock_name="농심")
    sources, shares, _ = p.append_source(bundle.sources, lambda: shares)
    prices = pd.DataFrame() if prices is None else prices
    if not prices.empty:
        sources, prices, _ = p.append_source(sources, lambda: prices)
    metrics = pd.concat([bundle.metrics, m.valuation_metrics(bundle.records, prices, shares, "", 2025,
                                                             len(bundle.metrics) + 1)], ignore_index=True)
    return replace(bundle, sources=sources, shares=shares, prices=prices, metrics=metrics)


def dummy_csv(path, *rows):
    """A dummy file in the member's format: the 15 columns, the four source columns left blank."""
    base = {col: "" for col in c.COLUMNS} | {"종목코드": "004370", "종목명": "농심", "기준": "해당 없음", "공시일": "해당 없음",
                                             "단위": "원", "수집 시각": "2026-11-22 10:00", "상태": c.PASSED}
    pd.DataFrame([base | row for row in rows], columns=c.COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def close(day):
    return {"항목": d.CLOSE, "값": "342000", "기준일": day.isoformat()}


def asked(tmp_path, monkeypatch, name, dummy_data=None):
    """{stage file stem: question} of one fake run, with its result."""
    monkeypatch.setattr(p, "build_bundle", rich_bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    questions, real = {}, p.ask_claims
    monkeypatch.setattr(p, "ask_claims", lambda prompt, key, path, *rest: (questions.setdefault(Path(path).stem, prompt),
                                                                             real(prompt, key, path, *rest)))
    prompts = tmp_path / name / "prompts"
    shutil.copytree(PROMPTS, prompts)
    result = p.run("004370", 2025, [prompts], tmp_path / name / "run", "key", "dart", quota_dirs=[tmp_path / name],
                   dummy_data=dummy_data)
    return questions, result


def changed_stages(before, after):
    return {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}


def test_a_valuation_dummy_changes_only_the_valuation_question_and_the_stages_after_it(tmp_path, monkeypatch):
    plain, _ = asked(tmp_path, monkeypatch, "plain")
    csv = dummy_csv(tmp_path / "dummy_data.csv", close(TODAY - timedelta(days=1)))
    with_dummy, result = asked(tmp_path, monkeypatch, "dummy", ("valuation", csv))

    changed = changed_stages(plain, with_dummy)
    assert "valuation_r0" in changed
    assert all(s.startswith(("valuation", "center", *LATER)) for s in changed), changed
    assert "## 더미 데이터" in with_dummy["valuation_r0"] and "더미" not in with_dummy["industry_r0"]
    assert "현재 주가: 342,000원" in with_dummy["valuation_r0"]
    verification = result.verification.read_text(encoding="utf-8")
    assert "더미 데이터 | ⚠ |" in verification and "- [ ] 더미 데이터 [S" in verification
    html = page_data((result.verification.parent / "report.html").read_text(encoding="utf-8"))
    assert "더미" in html["summary"]["upside_note"]
    assert any(s["name"] == d.SOURCE for s in html["sources"])


def test_a_center_dummy_close_gives_the_center_question_market_metrics_and_changes_nothing_before_it(tmp_path, monkeypatch):
    plain, _ = asked(tmp_path, monkeypatch, "plain")
    csv = dummy_csv(tmp_path / "dummy_data.csv", close(TODAY - timedelta(days=1)))
    with_dummy, _ = asked(tmp_path, monkeypatch, "dummy", ("center", csv))

    changed = changed_stages(plain, with_dummy)
    assert "center_r0" in changed
    assert all(s.startswith(("center", *LATER)) for s in changed), changed
    block = with_dummy["center_r0"].split("## 더미 데이터")[1]
    assert f"시가총액,{TODAY - timedelta(days=1)},{342000 * 1000:.2f},원" in block


def test_a_dummy_close_is_turned_into_market_cap_per_and_pbr_keeping_every_metric_number(tmp_path):
    bundle = rich_bundle("004370", 2025, 2, "dart")
    csv = dummy_csv(tmp_path / "dummy_data.csv", close(TODAY - timedelta(days=1)))
    attached, status = d.attach(bundle, "valuation", csv)
    metrics = attached.metrics.set_index("지표")
    assert list(attached.metrics["metric_id"]) == list(bundle.metrics["metric_id"])
    assert metrics.loc["시가총액", "값"] == 342000 * 1000
    assert d.source_id(attached) in metrics.loc["PER", "source_id"]
    assert attached.dummy.empty and len(attached.prices) == 1
    assert "다시 계산" in status[-1][2]


def test_real_values_win_over_dummy_rows_and_leave_a_warning(tmp_path):
    real = c.finalize(pd.DataFrame([{"항목": d.CLOSE, "값": 350000, "기준일": TODAY.isoformat()}]), level=1, source="공식 시세 API",
                      source_url="https://data.example/price", reliability="상", basis=c.NOT_APPLICABLE, unit="원",
                      disclosed=c.NOT_APPLICABLE, stock_code="004370", stock_name="농심")
    bundle = rich_bundle("004370", 2025, 2, "dart", prices=real)
    csv = dummy_csv(tmp_path / "dummy_data.csv", close(TODAY), {"항목": "매출액(연간)", "값": "1", "기준일": "2025-12-31"},
                    {"항목": "목표 PER", "값": "12", "단위": "배", "기준일": "2026-11-20"})

    attached, status = d.attach(bundle, "valuation", csv)

    memos = [s[2] for s in status]
    assert "더미 무시: 진짜 값 있음 (종가)" in memos and "더미 무시: 진짜 값 있음 (매출액(연간))" in memos
    assert attached.prices.equals(bundle.prices) and attached.metrics.equals(bundle.metrics)
    assert list(attached.dummy["항목"]) == ["목표 PER"]


def test_a_dummy_close_older_than_seven_days_shows_the_reason_in_the_run_status(tmp_path, monkeypatch):
    csv = dummy_csv(tmp_path / "dummy_data.csv", close(TODAY - timedelta(days=30)))
    _, result = asked(tmp_path, monkeypatch, "stale", ("valuation", csv))

    price = next(memo for step, mark, memo in result.status if step == "주가")
    assert "괴리율: 검증 실패" in price and "7일 넘음" in price


def test_only_citations_naming_a_dummy_source_metric_or_row_are_marked():
    text = "PER은 9.8배 (M7). 종가는 342,000원 [S3, 004370|종가|해당 없음|2026-11-19]. 매출 성장률은 10% [S1] (M1)."
    marked = d.mark_text(text, {"tokens": {"S3", "M7"}, "rids": set()})
    assert marked == ("PER은 9.8배 (더미) (M7). 종가는 342,000원 (더미) [S3, 004370|종가|해당 없음|2026-11-19]. "
                      "매출 성장률은 10% [S1] (M1).")
    assert d.mark_text("근거 [S5, 004370|목표 PER|해당 없음|2026-11-20]", {"tokens": set(), "rids": {"004370|목표 PER|해당 없음|2026-11-20"}}) \
        == "근거 (더미) [S5, 004370|목표 PER|해당 없음|2026-11-20]"


def test_the_example_file_and_a_copy_without_bom_load_the_same(tmp_path):
    example = Path(__file__).resolve().parent.parent / "members" / "valuation" / "dummy_data.example.csv"
    assert example.read_bytes().startswith(b"\xef\xbb\xbf")
    plain = tmp_path / "dummy_data.csv"
    plain.write_bytes(example.read_bytes()[3:])
    with_bom, without_bom = d.load(example, "004370"), d.load(plain, "004370")
    assert list(with_bom.columns) == c.COLUMNS and with_bom.drop(columns="출처 URL").equals(without_bom.drop(columns="출처 URL"))
    assert with_bom["값"].iloc[0] == 342000


def test_a_file_saved_as_plain_excel_csv_in_cp949_loads_and_unreadable_bytes_stop_with_a_hint(tmp_path):
    example = Path(__file__).resolve().parent.parent / "members" / "valuation" / "dummy_data.example.csv"
    cp949 = tmp_path / "dummy_data.csv"
    cp949.write_bytes(example.read_text(encoding="utf-8-sig").encode("cp949"))
    assert d.load(cp949, "004370").drop(columns="출처 URL").equals(d.load(example, "004370").drop(columns="출처 URL"))
    broken = tmp_path / "broken.csv"
    broken.write_bytes(b"\xff\xfe\xff\n")
    with pytest.raises(c.CollectError, match="CSV UTF-8"):
        d.load(broken, "004370")
