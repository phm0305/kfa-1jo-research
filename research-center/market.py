"""KFA study team 1: closing prices (official API not connected yet) and common share counts (DART) as shared-table rows.

Both are appended after the engine's numbering by pipeline.build_bundle, so no existing rid or S# moves.

[한국어 안내] 이 파일은 고치지 않고 실행만 해요.
    price_records()   공식 API 연결 전이라 지금은 항상 "주가 없음"을 남겨요
    share_records()   사업보고서의 보통주 발행주식수, 자기주식수, 유통주식수를 받아요
    price_problem()   종가가 실행일보다 7일 넘게 오래됐는지 봐요
    owner_records()   지배주주순이익, 지배주주자본, 기본주당이익을 DART에서 받아요
    valuation_metrics()  EPS, BPS, 시가총액, PER, PBR을 계산해 지표 표 뒤에 붙여요
"""

from datetime import date, time

import pandas as pd

from collect import (DART_REPORT, DART_URL, NOT_APPLICABLE, REVIEW, CollectError, _dart_status, dart_corp, finalize,
                     http_get, is_blank, to_number)
from engine import COMPUTED, METRIC_COLUMNS, with_ids

NO_PRICE = "공식 API 연결 전, 주가 없음"
SHARES_SOURCE = "DART 주식총수 현황 API"
SHARES_ITEMS = ("발행주식수(보통주)", "자기주식수(보통주)", "유통주식수(보통주)")
# Same value as the rule in prompts/valuation.md (4-1 현재 주가).
STALE_DAYS = 7
MARKET_CLOSE = time(15, 30)
DART_SOURCE = "DART 단일회사 전체 재무제표 API"
VALUATION_NAMES = ("EPS", "BPS", "시가총액", "PER", "PBR")
PER_SHARE_ITEMS = ("기본주당이익(연간)",)
# account_id -> (row name, statements it may come from); the same accounts also appear in SCE with other meanings.
OWNER_ITEMS = {
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": ("지배주주순이익(연간)", ("IS", "CIS")),
    "ifrs-full_EquityAttributableToOwnersOfParent": ("지배주주자본", ("BS",)),
    "ifrs-full_BasicEarningsLossPerShare": ("기본주당이익(연간)", ("IS", "CIS")),
}


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
    """Closing prices as shared-table rows. Not connected yet, so it always raises and the run goes on without a price.
    The only planned source is the official FSC stock price API (data.go.kr), see docs/traps.md."""
    raise CollectError(NO_PRICE)


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


def owner_records(stock_code, stock_name, year, api_key, sources):
    """Consolidated rows the engine does not pick: the parent owners' net income and equity, and basic EPS.
    They come from the same annual-report filing as the engine's rows, so they carry that filing's existing S#."""
    corp_code = dart_corp(stock_code, api_key)[0]
    data = http_get(f"{DART_URL}/fnlttSinglAcntAll.json", {"crtfc_key": api_key, "corp_code": corp_code,
                                                            "bsns_year": str(year), "reprt_code": DART_REPORT[4],
                                                            "fs_div": "CFS"}).json()
    _dart_status(data)
    out = []
    for account, (name, statements) in OWNER_ITEMS.items():
        hit = next((r for r in data.get("list") or [] if r.get("account_id") == account and r.get("sj_div") in statements), None)
        rcept_no = (hit or {}).get("rcept_no") or data["list"][0].get("rcept_no", "")
        out.append({"항목": name, "값": hit.get("thstrm_amount") if hit else None, "단위": "원",
                    "기준일": f"{year}-12-31", "공시일": rcept_no[:8],
                    "출처 URL": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                    "비고": "기준일은 12월 결산 가정" if hit else f"이 회사 공시에서 표준 계정({account})을 못 찾음"})
    rows = with_ids(finalize(pd.DataFrame(out), level=1, source=DART_SOURCE, reliability="상", basis="연결",
                             stock_code=stock_code, stock_name=stock_name))
    ids = {(s["출처"], s["출처 URL"]): s["source_id"] for _, s in sources.iterrows()}
    rows["source_id"] = [ids.get((r["출처"], r["출처 URL"])) for _, r in rows.iterrows()]
    if rows["source_id"].isna().any():
        raise CollectError(f"{year} 사업보고서 출처 번호를 못 찾았어요: {rows['출처 URL'].iloc[0]}")
    return rows


def _one(table, item, base_date=None):
    if table.empty:
        return None
    hit = table[(table["항목"] == item) & ((table["기준일"] == base_date) if base_date else True)]
    return hit.iloc[0] if len(hit) == 1 else None


def valuation_metrics(records, prices, shares, stale, year, first_number, missing_note=""):
    """EPS, BPS (parent owners' share over outstanding common shares, as prompts/valuation.md defines them),
    market cap (close x issued common shares), PER and PBR, as engine metric rows numbered from first_number.
    A metric without a usable input keeps no value and says why; a stale close blocks only the price-based three.
    Inputs that are flagged but have a value still give a value, marked 확인 필요 so a claim citing it is not passed."""
    base = f"{year}-12-31"
    ni, equity = _one(records, "지배주주순이익(연간)", base), _one(records, "지배주주자본", base)
    issued, outstanding = _one(shares, SHARES_ITEMS[0]), _one(shares, SHARES_ITEMS[2])
    price = current_price(prices)
    gap = ("" if issued is None or outstanding is None else
           f". 시가총액은 발행주식수, PER은 유통주식수 기준이라 시가총액 ÷ 지배주주순이익은 PER보다 "
           f"{(issued['값'] / outstanding['값'] - 1) * 100:.2f}% 큼(자기주식 때문)")
    specs = [
        ("EPS", "원", "지배주주순이익(연간) ÷ 유통주식수(보통주)", {"지배주주순이익": ni, "유통주식수": outstanding},
         ("유통주식수",), lambda v: v["지배주주순이익"] / v["유통주식수"], base),
        ("BPS", "원", "지배주주자본 ÷ 유통주식수(보통주)", {"지배주주자본": equity, "유통주식수": outstanding},
         ("유통주식수",), lambda v: v["지배주주자본"] / v["유통주식수"], base),
        ("시가총액", "원", "종가 × 발행주식수(보통주)" + gap, {"주가": price, "발행주식수": issued},
         ("발행주식수",), lambda v: v["주가"] * v["발행주식수"], None),
        ("PER", "배", "종가 ÷ EPS (EPS = 지배주주순이익(연간) ÷ 유통주식수)" + gap,
         {"주가": price, "지배주주순이익": ni, "유통주식수": outstanding}, ("지배주주순이익", "유통주식수"),
         lambda v: v["주가"] / (v["지배주주순이익"] / v["유통주식수"]), None),
        ("PBR", "배", "종가 ÷ BPS (BPS = 지배주주자본 ÷ 유통주식수)",
         {"주가": price, "지배주주자본": equity, "유통주식수": outstanding}, ("지배주주자본", "유통주식수"),
         lambda v: v["주가"] / (v["지배주주자본"] / v["유통주식수"]), None),
    ]
    out = []
    for n, (name, unit, formula, inputs, positive, compute, base_date) in enumerate(specs, first_number):
        found = [row for row in inputs.values() if row is not None]
        missing = [label for label, row in inputs.items() if row is None or is_blank(row["값"])]
        reasons = [f"{label} 없음" for label in missing]
        if missing_note and set(missing) & {"지배주주순이익", "지배주주자본"}:
            reasons.append(missing_note)
        if price is not None and "주가" in inputs and stale:
            reasons.append(f"주가 검증 실패: {stale}")
        reasons += [f"{label}이(가) 0 이하라 {name} 보류" for label in positive
                    if label not in missing and float(inputs[label]["값"]) <= 0]
        value = None if reasons else float(compute({k: float(r["값"]) for k, r in inputs.items()}))
        flagged = [row["항목"] for row in found if row["상태"] == REVIEW]
        if flagged:
            reasons.append(f"입력 줄이 확인 필요: {', '.join(flagged)}")
        out.append({"metric_id": f"M{n}", "지표": name, "값": value, "단위": unit, "계산식": formula,
                    "입력 rid": [row["rid"] for row in found],
                    "source_id": sorted({row["source_id"] for row in found}, key=lambda s: int(s[1:])),
                    "기준일": base_date or (price["기준일"] if price is not None else base),
                    "상태": REVIEW if reasons else COMPUTED, "이유": "; ".join(reasons)})
    metrics = pd.DataFrame(out, columns=METRIC_COLUMNS)
    metrics["값"] = pd.Series([row["값"] for row in out], dtype=object)
    return metrics
