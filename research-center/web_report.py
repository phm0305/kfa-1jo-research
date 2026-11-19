"""KFA study team 1: one run's result as a single HTML page in the team prototype design.

web/template.html draws the whole screen from one JSON block (<script id="report-data">); this module
only fills that block. It writes nothing the run did not produce: a missing value is None, which the
page shows as "확인 필요". pipeline.render_html reads a run folder and calls write_html.

[한국어 안내] 실행 결과 폴더를 1조 시제품 화면(report.html) 한 장으로 바꿔요. 마크다운 리포트·검증 기록지는 그대로 있고,
    이 화면은 보여주기용이에요. 결과에 없는 칸은 "확인 필요"로 보여요.
"""

import json
import re
from pathlib import Path

from collect import is_blank
from engine import FIX, PASS
from layout import PAGES
from market import current_price
from pipeline import _eok, all_rows

TEMPLATE = Path(__file__).resolve().parent / "web" / "template.html"
NEED = "확인 필요"
PANEL_PAGES = {"industry": 2, "company": 3, "valuation": 4}
SEVERITY = {"pass": 0, "hold": 1, "reject": 2}
DATA_BLOCK = re.compile(r'(<script type="application/json" id="report-data">)(.*?)(</script>)', re.S)
CITATION = re.compile(r"(?<![A-Za-z0-9])[ME]\d+(?!\d)|\d{6}\|[^|\]\n]+\|[^|\]\n]+\|\d{4}-\d{2}-\d{2}")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")
# shortcut: the industry chart line is fixed to Nongshim's main product (11/16 decision); other stocks show 확인 필요 until a rule is chosen.
SERIES_ITEM = "품목 매출(라면, 합계)"
SERIES_SOURCE = "DART 사업보고서 원문: II. 사업의 내용"
LOWER_IS_BETTER = {"부채비율"}
TRENDS = {"개선": "up", "악화": "down", "횡보": "flat"}
INDUSTRY_HEADER = ("업종", "추세", "한 줄 제목")


def _number(value, digits):
    return None if is_blank(value) else round(float(value), digits)


def _eok_number(row):
    text = _eok(row)
    return float(text) if text else None


def _text(page):
    return "\n\n".join(t for t in page.values() if t)


def _paragraphs(text):
    """Blank-line separated paragraphs; line breaks inside one (a point and its "- " lines) are kept for the page."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _why(metric_id, texts):
    """The first sentence of a part's text whose only M#, E# or rid citation is this metric, or ""."""
    for text in texts:
        for sentence in SENTENCE_END.split(text):
            if _citations(sentence) == {metric_id}:
                return sentence.strip()
    return ""


def _citations(text):
    return {c.rsplit("|", 1)[0] if c.count("|") == 4 else c for c in CITATION.findall(text)}


def _first_source(label):
    found = re.search(r"S\d+", str(label or ""))
    return found.group(0) if found else None


def _verification(checked):
    claims = {}
    for _, row in checked.iterrows():
        status = "pass" if row["판정"] == PASS else "reject" if row["판정"] == FIX else "hold"
        note = f"{row['근거 id'] or '근거 id 없음'} → {row['판정']}"
        if not is_blank(row["이유"]) and row["이유"]:
            note += f": {row['이유']}"
        if row["발췌 대조"]:
            note += f" / {row['발췌 대조']}"
        item = claims.setdefault(row["claim_id"], {"claim": row["문장"] or NEED, "part": row["파트"], "status": status,
                                                   "note": "", "source": _first_source(row["출처 번호"]), "returned_to": None})
        if SEVERITY[status] > SEVERITY[item["status"]]:
            item["status"] = status
        item["note"] = f"{item['note']} | {note}" if item["note"] else note
    return list(claims.values())


def report_data(bundle, pages, checked):
    """The template's JSON. pages: {page number: {subheading: text}} as the run left them; checked: the engine's
    claim check plus the columns 파트 (the writing part's name) and 발췌 대조 (excerpt_check result)."""
    year = bundle.year
    records, metrics = bundle.records, bundle.metrics
    rows_by_rid = all_rows(bundle)
    source_of = dict(zip(rows_by_rid["rid"], rows_by_rid["source_id"]))
    price = current_price(bundle.prices)
    part_texts = [_text(pages.get(p, {})) for p in PANEL_PAGES.values()]
    by_year = lambda table, y: table[table["기준일"].str[:4] == str(y)]

    key_metrics = [{"label": f"{m['지표']} ({m['metric_id']})", "value": _number(m["값"], 2), "unit": m["단위"], "star": False,
                    "why": _why(m["metric_id"], part_texts),
                    "source": source_of.get(m["입력 rid"][0]) if len(m["입력 rid"]) else None}
                   for _, m in by_year(metrics, year).iterrows()]

    rows = []
    for item in records["항목"].drop_duplicates():
        values = {y: by_year(records[records["항목"] == item], y) for y in (year - 1, year)}
        prev, curr = (_eok_number(v.iloc[0]) if len(v) else None for v in values.values())
        rows.append({"item": item, "prev": prev, "curr": curr, "kind": "amount"})
    for name in metrics["지표"].drop_duplicates():
        found = {y: by_year(metrics[metrics["지표"] == name], y) for y in (year - 1, year)}
        ids = ", ".join(f["metric_id"].iloc[0] for f in found.values() if len(f))
        prev, curr = (_number(f["값"].iloc[0], 2) if len(f) else None for f in found.values())
        rows.append({"item": f"{name} ({ids})", "prev": prev, "curr": curr, "kind": "ratio",
                     **({"lower_is_better": True} if name in LOWER_IS_BETTER else {})})

    segments = bundle.segments
    line = (segments[(segments["항목"] == SERIES_ITEM) & (segments["출처"] == SERIES_SOURCE)].sort_values("기준일")
            if not segments.empty else segments)
    series = [{"period": r["기준일"][:4], "value": _eok_number(r)} for _, r in line.iterrows()]
    series_label = (f"{SERIES_ITEM.removeprefix('품목 매출(').split(',')[0]} 매출 (II. 사업의 내용 품목 표 합계, 억원) "
                    f"[{line['source_id'].iloc[0]}]" if len(line) else NEED)

    body = lambda page: {s: t for s, t in pages.get(page, {}).items() if not (page == PANEL_PAGES["industry"] and s in INDUSTRY_HEADER)}
    notes = lambda page: [{"text": p, "source": None} for p in _paragraphs(_text(body(page)))] or [{"text": NEED, "source": None}]
    industry = pages.get(PANEL_PAGES["industry"], {})
    summary_text = _paragraphs(_text(pages.get(1, {})))
    points = []
    for sub in PAGES[5][1]:
        text = pages.get(5, {}).get(sub) or ""
        cited = _citations(text)
        refs = [panel for panel, page in PANEL_PAGES.items() if cited & _citations(_text(pages.get(page, {})))]
        points.append({"text": text or NEED, "refs": refs})

    return {
        "meta": {"is_example": False, "ticker": bundle.stock_code, "name": bundle.stock_name, "industry": industry.get("업종") or NEED,
                 "as_of": records["기준일"].max(), "currency": "KRW"},
        "summary": {"opinion": NEED, "one_line": summary_text[0] if summary_text else NEED,
                    "current_price": None if price is None else float(price["값"]),
                    "price_as_of": None if price is None else price["기준일"],
                    "price_source": None if price is None else price["source_id"],
                    "upside_note": "검증 실패" if bundle.price_stale else None},
        "key_metrics": key_metrics,
        "industry": {"trend": TRENDS.get((industry.get("추세") or "").strip()),
                     "headline": industry.get("한 줄 제목") or NEED, "series_label": series_label,
                     "series": series, "notes": notes(PANEL_PAGES["industry"])},
        "company": {"unit": "단위: 억원(공통 재무 표 값을 코드가 바꿈), 비율은 %(지표 표 M#)",
                    "periods": [str(year - 1), str(year)], "rows": rows, "drivers": notes(PANEL_PAGES["company"])},
        "valuation": {"method": NEED, "method_reason": "", "bps": None, "multiples": [],
                      "target_multiple": None, "conclusion": _text(pages.get(PANEL_PAGES["valuation"], {})) or NEED},
        "conclusion": {"points": points},
        "verification": {"claims": _verification(checked) if checked is not None else []},
        # The page hides citations in the text; this maps a rid (first four fields, as the engine reads a short rid)
        # or an M# (its first input row) to the S# its footnote points at.
        "cite_sources": [{"cite": "|".join(rid.split("|")[:4]), "source": s} for rid, s in source_of.items() if s]
                        + [{"cite": m["metric_id"], "source": source_of[m["입력 rid"][0]]} for _, m in metrics.iterrows()
                           if len(m["입력 rid"]) and source_of.get(m["입력 rid"][0])],
        "sources": [{"id": s["source_id"], "name": s["출처"], "as_of": s["기준일 범위"]} for _, s in bundle.sources.iterrows()]
                   + [{"id": e["id"], "name": f"발췌: {e['제목']} [{e['source_id']}]", "as_of": ""} for e in bundle.excerpts],
    }


def write_html(data, path):
    block = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).replace("</", "<\\/")
    html, n = DATA_BLOCK.subn(lambda m: f"{m[1]}\n{block}\n{m[3]}", TEMPLATE.read_text(encoding="utf-8"), count=1)
    if n != 1:
        raise ValueError(f"{TEMPLATE} has no <script id=\"report-data\"> block")
    path = Path(path)
    path.write_text(html, encoding="utf-8")
    return path
