"""KFA study team 1: closing prices (FinanceDataReader) and common share counts (DART) as shared-table rows.

Both are appended after the engine's numbering by pipeline.build_bundle, so no existing rid or S# moves.

[한국어 안내] 이 파일은 고치지 않고 실행만 해요.
    price_records()   실행일 기준 마지막 거래일 종가와 분석 연도들의 연말 종가를 받아요
    share_records()   사업보고서의 보통주 발행주식수, 자기주식수, 유통주식수를 받아요
    price_problem()   종가가 실행일보다 7일 넘게 오래됐는지 봐요
"""

from datetime import date, time

import pandas as pd

from collect import (DART_REPORT, DART_URL, NOT_APPLICABLE, SAME_AS_DATE, CollectError, _dart_status,
                     collect_table, dart_corp, finalize, http_get, to_number)

PRICE_SOURCE = "FinanceDataReader (네이버 금융 경유, 원천 한국거래소)"
PRICE_URL = "https://github.com/FinanceData/FinanceDataReader"
SHARES_SOURCE = "DART 주식총수 현황 API"
PRICE_ITEM = "종가"
SHARES_ITEMS = ("발행주식수(보통주)", "자기주식수(보통주)", "유통주식수(보통주)")
# Same value as the rule in prompts/valuation.md (4-1 현재 주가).
STALE_DAYS = 7
MARKET_CLOSE = time(15, 30)


def pick_closes(prices, years, now):
    """Rows of a daily price table (date index) to keep: each finished year's last trading day, and the last
    trading day before `now`. Today's row before the close is an intraday price, so it is dropped."""
    days = prices.index.normalize()
    today = pd.Timestamp(now.date())
    settled = prices[(days < today) | ((days == today) & (now.time() >= MARKET_CLOSE))]
    if settled.empty:
        raise CollectError("확정된 종가가 하나도 없어요")
    picked = [settled[settled.index.year == y].index.max() for y in years if date(y, 12, 31) < now.date()]
    picked = sorted({d for d in picked if not pd.isna(d)} | {settled.index.max()})
    return settled.loc[picked]


def price_records(stock_code, stock_name, years, now):
    """Closing prices as shared-table rows (item 종가, unit 원), one per picked trading day."""
    try:
        import FinanceDataReader as fdr
        prices = fdr.DataReader(stock_code, f"{years[0]}-12-01")
    except Exception as err:  # a third-party library: any failure means no price, and the run goes on
        raise CollectError(f"FinanceDataReader에서 주가를 받지 못했어요 ({type(err).__name__}: {err})") from None
    if prices is None or prices.empty or "Close" not in prices.columns:
        raise CollectError("FinanceDataReader가 빈 주가 표를 줬어요. 종목코드를 확인해 주세요")
    return collect_table(pick_closes(prices, years, now), {"Close": (PRICE_ITEM, "원")}, level=2,
                         source=PRICE_SOURCE, source_url=PRICE_URL, reliability="중", basis=NOT_APPLICABLE,
                         disclosed=SAME_AS_DATE, stock_code=stock_code, stock_name=stock_name)


def current_price(prices):
    """The latest close row, or None."""
    return None if prices.empty else prices.loc[prices["기준일"].idxmax()]


def price_problem(prices, today):
    """'' when the latest close is at most STALE_DAYS old, else the reason the valuation gap cannot be trusted."""
    row = current_price(prices)
    days = (today - date.fromisoformat(row["기준일"])).days
    if days <= STALE_DAYS:
        return ""
    return f"종가 기준일 {row['기준일']}이 실행일 {today}보다 {days}일 오래됨({STALE_DAYS}일 넘음)"


def _count(row, key):
    value, problem = to_number(row.get(key))
    return None if problem else value


def share_records(stock_code, stock_name, year, api_key):
    """Common shares at the year's annual-report date: issued (Ⅳ), treasury (Ⅴ), outstanding = issued - treasury.
    DART's own outstanding figure (Ⅵ) must equal that difference, or the rows are not used."""
    corp_code = dart_corp(stock_code, api_key)[0]
    data = http_get(f"{DART_URL}/stockTotqySttus.json", {"crtfc_key": api_key, "corp_code": corp_code,
                                                         "bsns_year": str(year), "reprt_code": DART_REPORT[4]}).json()
    _dart_status(data)
    common = [r for r in data.get("list") or [] if (r.get("se") or "").strip() == "보통주"]
    if len(common) != 1:
        raise CollectError(f"DART 주식총수 현황에 보통주 줄이 {len(common)}개예요")
    row = common[0]
    # isu_stock_totqy is the charter's authorized total (Ⅰ), not the issued count; istc_totqy is Ⅳ.
    issued, outstanding = _count(row, "istc_totqy"), _count(row, "distb_stock_co")
    treasury = _count(row, "tesstk_co")
    if treasury is None and issued is not None and issued == outstanding:
        treasury = 0
    if None in (issued, treasury, outstanding):
        raise CollectError(f"DART 주식총수 현황의 보통주 숫자를 읽지 못했어요: 발행 {row.get('istc_totqy')}, "
                           f"자기주식 {row.get('tesstk_co')}, 유통 {row.get('distb_stock_co')}")
    if issued - treasury != outstanding:
        raise CollectError(f"DART 유통주식수 {outstanding:,.0f}가 발행 {issued:,.0f} - 자기주식 {treasury:,.0f}와 달라요")
    rcept_no = row["rcept_no"]
    table = pd.DataFrame({"항목": SHARES_ITEMS, "값": (issued, treasury, outstanding)})
    return finalize(table, level=1, source=SHARES_SOURCE,
                    source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}", reliability="상",
                    basis=NOT_APPLICABLE, base_date=row["stlm_dt"], disclosed=rcept_no[:8], unit="주",
                    stock_code=stock_code, stock_name=stock_name,
                    note="유통주식수는 발행주식수 - 자기주식수로 계산, DART 유통주식수와 같음")
