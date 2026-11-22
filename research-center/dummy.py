"""Dummy rows a member writes to try an engine request before the engine supplies that data.

Temporary: docs/plans/remove-dummy.md lists everything to delete once the requests are in the engine.
members/<part>/dummy_data.csv is read only when run.py runs that part. Its rows get one new S# after every
engine source, so no existing rid, S# or M# moves. Only that part's question carries them (the other parts are
asked from the bundle as it was before attach), and every number resting on them is marked 더미 in
report.html and verification.md.
"""

import re
from dataclasses import replace
from datetime import datetime

import pandas as pd

from collect import COLUMNS, KST, CollectError, check_records, is_blank
from engine import build_sources, with_ids
from market import PRICE_METRICS, VALUATION_NAMES, price_problem, valuation_metrics

SOURCE = "더미(엔진 요청 시험용)"
FIXED = {"출처": SOURCE, "신뢰도": "하", "수집 방법": "5 수동 입력"}
CLOSE = "종가"
# Parts whose prompt reasons with market cap, PER and PBR, so a dummy close is turned into those metrics for them.
PRICE_READERS = ("valuation", "center")
MARK = "(더미)"
STEP = "더미 데이터"
TOKEN = re.compile(r"(?<![A-Za-z0-9])[SM]\d+(?!\d)")
CITE = re.compile(r"\[[^\]\n]*\]|\((?:\s*M\d+\s*,?)+\)")


def load(path, stock_code):
    """The member's file as shared-table rows; the four source columns are always set here, whatever it says."""
    rows = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if list(rows.columns) != COLUMNS:
        raise CollectError(f"{path}: 칸 이름과 순서는 공통 15칸과 같아야 해요. 지금: {list(rows.columns)}. "
                           "members/valuation/dummy_data.example.csv 머리줄을 그대로 쓰세요")
    if rows.empty:
        raise CollectError(f"{path}: 머리줄 아래에 줄이 하나도 없어요")
    wrong = sorted(set(rows["종목코드"]) - {stock_code})
    if wrong:
        raise CollectError(f"{path}: 종목코드가 실행한 종목({stock_code})과 달라요: {wrong}")
    values = pd.to_numeric(rows["값"].str.replace(",", ""), errors="coerce")
    if values.isna().any():
        raise CollectError(f"{path}: 값 칸이 숫자가 아닌 줄이 있어요: {rows.loc[values.isna(), '값'].tolist()}")
    rows = rows.assign(값=values, **FIXED, **{"출처 URL": path.as_posix()})
    if not check_records(rows, show=False):
        raise CollectError(f"{path}: 필수 칸이 비었거나 상태 칸이 '형식 통과'/'확인 필요'가 아니에요")
    return rows


def attach(bundle, part, path):
    """(bundle with the dummy rows, run status lines). A row whose item the engine already has a value for is
    dropped, so a dummy file left behind never overrides real data; a dummy close is dropped once real prices exist.
    For PRICE_READERS a dummy close becomes the price input of market cap, PER and PBR."""
    from pipeline import all_rows  # pipeline imports this module, so not at the top
    rows = load(path, bundle.stock_code)
    known = all_rows(bundle)
    real = set(known.loc[~known["값"].map(is_blank), "항목"]) | ({CLOSE} if not bundle.prices.empty else set())
    dropped = rows["항목"].isin(real)
    notes = [(STEP, "⚠", f"더미 무시: 진짜 값 있음 ({item})") for item in rows.loc[dropped, "항목"].unique()]
    rows = rows[~dropped]
    if rows.empty:
        return bundle, notes
    sid = f"S{len(bundle.sources) + 1}"
    new, tagged = build_sources(with_ids(rows))
    changes = {"sources": pd.concat([bundle.sources, new.assign(source_id=sid)], ignore_index=True),
               "dummy": tagged.assign(source_id=sid)}
    closes = changes["dummy"]["항목"] == CLOSE
    memo = f"{path.as_posix()} {len(rows)}줄을 [{sid}]로 {part} 질문에만 넣음. 엔진 요청 시험용이라 진짜 결과 아님"
    if part in PRICE_READERS and closes.any():
        prices = changes["dummy"][closes]
        stale = price_problem(prices, datetime.now(KST).date())
        changes.update(prices=prices, price_error="", price_stale=stale, dummy=changes["dummy"][~closes],
                       metrics=_recompute(bundle, prices, stale))
        memo += ". 더미 종가로 시가총액·PER·PBR 다시 계산"
    return replace(bundle, **changes), [*notes, (STEP, "⚠", memo)]


def _recompute(bundle, prices, stale):
    """The bundle's metrics with market cap, PER and PBR recomputed from the dummy close, keeping their M#."""
    metrics = bundle.metrics
    old = metrics["지표"].isin(PRICE_METRICS)
    if not old.any():
        return metrics
    first = int(metrics.loc[metrics["지표"] == VALUATION_NAMES[0], "metric_id"].iloc[-1][1:])
    # shortcut: build_bundle's owner_error note is not stored, so a PER blocked by a failed owner call loses that note.
    new = valuation_metrics(bundle.records, prices, bundle.shares, stale, bundle.year, first)
    new = new[new["지표"].isin(PRICE_METRICS)]
    assert list(new["metric_id"]) == list(metrics.loc[old, "metric_id"]), "dummy recompute would renumber M#"
    return (pd.concat([metrics[~old], new], ignore_index=True)
            .sort_values("metric_id", key=lambda ids: ids.str[1:].astype(int), ignore_index=True))


def source_id(bundle):
    hit = bundle.sources.loc[bundle.sources["출처"] == SOURCE, "source_id"]
    return hit.iloc[0] if len(hit) else None


def _metric_ids(bundle, sid):
    return set(bundle.metrics.loc[bundle.metrics["source_id"].map(lambda ids: sid in ids), "metric_id"])


def block(bundle):
    """The data block appended to the dummy part's question, or "" when no dummy row is in use."""
    from pipeline import _csv, all_rows
    sid = source_id(bundle)
    if sid is None:
        return ""
    rows = all_rows(bundle)
    rows = rows[rows["source_id"] == sid]
    metrics = bundle.metrics[bundle.metrics["metric_id"].isin(_metric_ids(bundle, sid))]
    parts = [f"## 더미 데이터 (엔진 요청 시험용, 진짜 값 아님. 출처 {sid}. 인용한 숫자는 리포트에 더미로 표시돼요)",
             _csv(rows[["rid", "항목", "기준일", "값", "단위", "source_id"]])]
    if len(metrics):
        parts += ["더미로 계산한 지표", _csv(metrics.assign(
            값=metrics["값"].map(lambda v: "" if is_blank(v) else f"{v:.2f}"))[
            ["metric_id", "지표", "기준일", "값", "단위", "계산식", "상태", "이유"]])]
    parts.append(f"source_id,출처,신뢰도\n{sid},{SOURCE},하")
    return "\n\n" + "\n\n".join(parts) + "\n"


def is_dummy(label, sid):
    """Whether a claim's 출처 번호 ([S1][S9]) includes the dummy source."""
    return sid is not None and sid in TOKEN.findall(str(label))


def verdict(row, bundle):
    sid = source_id(bundle) if bundle is not None else None
    return f"{row['판정']} {MARK}" if is_dummy(row["출처 번호"], sid) else row["판정"]


def checklist(checked, bundle):
    sid = source_id(bundle) if bundle is not None else None
    if sid is None:
        return []
    used = 0 if checked is None else int(checked["출처 번호"].map(lambda label: is_dummy(label, sid)).sum())
    return [f"- [ ] 더미 데이터 [{sid}]: 이 출처를 쓴 숫자 {used}개는 엔진 요청 시험용이라 진짜 결과가 아님"]


def mark_text(text, cites):
    """MARK before every citation that names a dummy S#, M# or rid, so it stays visible after the page hides citations."""
    if not text or not cites["tokens"] and not cites["rids"]:
        return text
    hit = lambda m: (set(TOKEN.findall(m[0])) & cites["tokens"]) or any(r in m[0] for r in cites["rids"])
    return CITE.sub(lambda m: f"{MARK} {m[0]}" if hit(m) else m[0], text)


def cites(bundle):
    from pipeline import all_rows
    sid = source_id(bundle)
    if sid is None:
        return {"tokens": set(), "rids": set()}
    rows = all_rows(bundle)
    return {"tokens": {sid} | _metric_ids(bundle, sid),
            "rids": {"|".join(r.split("|")[:4]) for r in rows.loc[rows["source_id"] == sid, "rid"]}}


def mark_inputs(bundle, pages, checked):
    """report_data inputs with dummy citations and claims marked; unchanged when no dummy is in use."""
    sid = source_id(bundle)
    if sid is None:
        return pages, checked
    found = cites(bundle)
    pages = {p: {s: mark_text(t, found) for s, t in subs.items()} for p, subs in pages.items()}
    if checked is not None:
        checked = checked.assign(문장=[f"[더미] {r['문장']}" if is_dummy(r["출처 번호"], sid) else r["문장"]
                                     for _, r in checked.iterrows()])
    return pages, checked


def mark_data(data, bundle):
    """The page JSON with dummy-based key metrics, table rows and current price labelled."""
    sid = source_id(bundle)
    if sid is None:
        return data
    ids = _metric_ids(bundle, sid)
    for item in data["key_metrics"]:
        if set(TOKEN.findall(item["label"])) & ids:
            item["label"] += f" {MARK}"
    for row in data["company"]["rows"]:
        if set(TOKEN.findall(row["item"])) & ids:
            row["item"] += f" {MARK}"
    summary = data["summary"]
    if summary["price_source"] == sid:
        summary["upside_note"] = " · ".join(filter(None, [summary["upside_note"], "더미 종가(진짜 아님)"]))
    return data
