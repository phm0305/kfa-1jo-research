"""KFA study team 1: segment tables and business-description excerpts from the annual report's
original text (DART document API), turned into shared-engine records.

The standard section numbers used here (L-0-2-n-L1, NT_C_D871100) were confirmed on one company
(Nongshim, 2025). When one is missing, nothing is guessed: the caller gets 확인 필요 and an excerpt.
Expects engine/ on sys.path. Member-facing messages are Korean on purpose.

[한국어 안내] 이 파일은 고치지 않고 실행만 해요.
    fetch_document()  사업보고서 원문을 받아 data/dart_doc/<접수번호>/ 에 저장해요 (있으면 다시 안 받아요)
    segment_sales()   영업부문 표(연결 주석)와 매출실적 표(II-4)를 공통 표 줄로 바꾸고 합계를 점검해요
    excerpts()        "II. 사업의 내용" 중 지정한 절의 글을 글자 수 상한까지 잘라 와요
    industry_code()   DART 기업개황에서 업종코드(KSIC)를 받아요 (업종명은 DART가 주지 않아요)
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

from collect import DART_URL, REVIEW, CollectError, _dart_status, collect_table, dart_corp, http_get, to_number

COMPANY_SOURCE = "DART 기업개황 API"
DOC_SOURCE_NOTE = "DART 사업보고서 원문: 연결재무제표 주석 영업부문"
DOC_SOURCE_BUSINESS = "DART 사업보고서 원문: II. 사업의 내용"
BUSINESS_NOTE = "L-0-2-{}-L1"
SEGMENT_GROUP = "{XBRL}NT_C_D871100"
CELL_TAGS = {"TD", "TH", "TE", "TU"}
# The filings write a literal '<' (e.g. <당기>) and a bare '&' (e.g. R&D) inside text.
_STRAY_LT = re.compile(r"<(?![A-Za-z/?!])")
_STRAY_AMP = re.compile(r"&(?![A-Za-z]+;|#\d+;|#x[0-9A-Fa-f]+;)")
_UNIT = re.compile(r"단위\s*:\s*([^)\s]+)")
_RCPNO = re.compile(r"rcpNo=(\d{14})")
UNIT_SCALE = {"원": 1, "천원": 10 ** 3, "백만원": 10 ** 6}


def industry_code(stock_code, api_key):
    """KSIC code as DART writes it, kept as text so a leading zero survives; '' when DART has none."""
    data = http_get(f"{DART_URL}/company.json", {"crtfc_key": api_key, "corp_code": dart_corp(stock_code, api_key)[0]}).json()
    _dart_status(data)
    return (data.get("induty_code") or "").strip()


def report_rcept_no(records, year):
    """The filing number of the annual report for `year`, read from the engine's DART rows."""
    rows = records[records["기준일"].astype(str).str.startswith(str(year))]
    found = rows["출처 URL"].astype(str).str.extract(_RCPNO)[0].dropna().unique().tolist()
    if len(found) != 1:
        raise CollectError(f"{year}년 사업보고서 접수번호를 하나로 못 골랐어요: {found}")
    return found[0]


def fetch_document(rcept_no, api_key, cache_dir):
    """Main XML of the filing. A filing never changes, so an existing folder is reused as is."""
    folder = Path(cache_dir) / rcept_no
    main = folder / f"{rcept_no}.xml"
    if main.exists():
        return main
    resp = http_get(f"{DART_URL}/document.xml", {"crtfc_key": api_key, "rcept_no": rcept_no}, timeout=120)
    try:
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        raise CollectError(f"원문 대신 다른 응답이 왔어요: {resp.text[:200]}") from None
    folder.mkdir(parents=True, exist_ok=True)
    with archive:
        for info in archive.infolist():
            target = (folder / Path(info.filename).name).resolve()
            if target.parent != folder.resolve():
                raise CollectError(f"원문 zip 안의 파일 이름이 이상해요: {info.filename}")
            target.write_bytes(archive.read(info))
    if not main.exists():
        raise CollectError(f"원문 zip에 본문 {main.name}이 없어요")
    return main


def load_document(path):
    raw = Path(path).read_text(encoding="utf-8")
    raw = _STRAY_LT.sub("&lt;", _STRAY_AMP.sub("&amp;", raw))
    try:
        return ET.fromstring(raw.encode("utf-8"))
    except ET.ParseError as err:
        raise CollectError(f"원문 XML을 읽지 못했어요 ({err}). 확인 필요") from None


def _text(el):
    return " ".join("".join(el.itertext()).split())


def _key(text):
    return re.sub(r"\s", "", text)


def _grid(table):
    """Rows of cell texts with ROWSPAN/COLSPAN expanded, so column i means the same in every row."""
    rows, pending = [], {}
    for tr in table.iter("TR"):
        cells, row = [c for c in tr if c.tag in CELL_TAGS], []
        while cells or len(row) in pending:
            col = len(row)
            if col in pending:
                text, left = pending.pop(col)
                if left > 1:
                    pending[col] = (text, left - 1)
                row.append(text)
                continue
            cell = cells.pop(0)
            text, down = _text(cell), int(cell.get("ROWSPAN") or 1)
            for _ in range(int(cell.get("COLSPAN") or 1)):
                if down > 1:
                    pending[len(row)] = (text, down - 1)
                row.append(text)
        rows.append(row)
    return rows


def _number(text):
    value, problem = to_number(text)
    return None if problem else value


def _split(grid):
    """(header rows, data rows, index of the first number column) or None for a table without numbers."""
    data_start = next((i for i, row in enumerate(grid) if any(_number(c) is not None for c in row[1:])), None)
    if data_start is None:
        return None
    data = [row for row in grid[data_start:] if row]
    first_num = min(next(j for j, c in enumerate(r) if j and _number(c) is not None) for r in data
                    if any(_number(c) is not None for c in r[1:]))
    return grid[:data_start], data, first_num


def _table_text(grid):
    return "\n".join(" | ".join(row) for row in grid if any(row))


def _section(root, note):
    return next((s for s in root.iter() if s.tag.startswith("SECTION")
                 and (t := s.find("TITLE")) is not None and t.get("AASSOCNOTE") == note), None)


def _api_value(records, item, year):
    rows = records[(records["항목"] == item) & (records["기준일"] == f"{year}-12-31") & (records["기준"] == "연결")]
    return rows["값"].iloc[0] if len(rows) == 1 else None


def _check_total(total, unit, api, label):
    """Problem text, or None when the table total is within one table unit of the API value."""
    if api is None:
        return f"{label}: 대조할 API 값이 없음"
    diff = abs(total * UNIT_SCALE[unit] - api)
    return None if diff <= UNIT_SCALE[unit] else f"{label}: 표 합계와 API 값 차이 {diff:,.0f}원"


def _sum_problem(parts, total, label):
    return None if sum(parts) == total else f"{label}: 칸 합 {sum(parts):,} ≠ 합계 {total:,}"


def _note_tables(group):
    """(period word, unit, grid) for every number table in the segment note, in order."""
    period = unit = None
    for table in group.iter("TABLE"):
        grid = _grid(table)
        for row in grid:
            if row and _key(row[0]) in ("당기", "전기"):
                period = _key(row[0])
            for cell in row:
                if m := _UNIT.search(cell):
                    unit = m.group(1)
        if _split(grid):
            yield period, unit, grid


def _region_rows(grid, unit, year, records):
    header, data, first = _split(grid)
    names = [_key(c) for c in header[-1][first:]]
    wanted = {"외부고객으로부터의수익": ("지역 외부매출", "매출액(연간)"), "부문영업손익": ("지역 부문영업손익", "영업이익(연간)")}
    rows, problems = [], []
    for row in data:
        if _key(row[0]) not in wanted:
            continue
        item, api_item = wanted[_key(row[0])]
        values = [_number(c) for c in row[first:]]
        rows += [{"항목": f"{item}({n})", "값": raw, "단위": unit, "기준일": f"{year}-12-31"}
                 for n, raw in zip(names, row[first:])]
        problems += [_sum_problem(values[:-1], values[-1], f"{year} {item}"),
                     _check_total(values[-1], unit, _api_value(records, api_item, year), f"{year} {item}")]
    if len(rows) != 2 * len(names):
        problems.append(f"{year} 지역 표에서 외부매출·부문영업손익 줄을 못 찾음")
    return rows, problems


def _product_rows(grid, unit, year, records):
    header, data, first = _split(grid)
    names = [_key(c) for c in header[-1][first:]]
    rows = [{"항목": f"품목 매출({_key(r[first - 1])}, {n})", "값": raw, "단위": unit, "기준일": f"{year}-12-31"}
            for r in data for n, raw in zip(names, r[first:])]
    values = [[_number(c) for c in r[first:]] for r in data]
    problems = [_sum_problem([v[j] for v in values[:-1]], values[-1][j], f"{year} 품목 {n}") for j, n in enumerate(names)]
    problems.append(_check_total(values[-1][-1], unit, _api_value(records, "매출액(연간)", year), f"{year} 품목 매출액"))
    return rows, problems


def _business_sales_rows(grid, unit, year, records):
    """II-4 sales table: columns are fiscal periods newest first, so column i is `year - i`."""
    header, data, first = _split(grid)
    rows, problems = [], []
    for i in range(len(data[0]) - first):
        y = year - i
        cells = {(_key(r[first - 2]), _key(r[first - 1])): r[first + i] for r in data}
        rows += [{"항목": f"품목 매출({p}, {kind})", "값": raw, "단위": unit, "기준일": f"{y}-12-31"}
                 for (p, kind), raw in cells.items()]
        nums = {k: _number(v) for k, v in cells.items()}
        totals = {kind: v for (p, kind), v in nums.items() if "총계" in p}
        parts = [v for (p, kind), v in nums.items() if "총계" not in p and kind in ("합계", "소계")]
        if "합계" not in totals:
            problems.append(f"{y} II-4 매출 총계 줄을 못 찾음")
            continue
        problems += [_sum_problem(parts, totals["합계"], f"{y} II-4 품목"),
                     _sum_problem([v for k, v in totals.items() if k != "합계"], totals["합계"], f"{y} II-4 내수·수출"),
                     _check_total(totals["합계"], unit, _api_value(records, "매출액(연간)", y), f"{y} II-4 매출 총계")]
    return rows, problems


def _to_records(rows, problems, *, source, reliability, url, rcept_no, records):
    """Shared-engine rows; when any check failed every row of that table is 확인 필요 with the reasons."""
    out = collect_table(pd.DataFrame(rows), level=1, source=source, source_url=url, reliability=reliability,
                        basis="연결", disclosed=rcept_no[:8], stock_code=records["종목코드"].iloc[0],
                        stock_name=records["종목명"].iloc[0])
    problems = [p for p in problems if p]
    if problems:
        out["상태"] = REVIEW
        out["비고"] = [("; ".join(filter(None, [n, *(f"⚠ 자동 점검: {p}" for p in problems)])))
                      for n in out["비고"].fillna("")]
    return out, problems


def segment_sales(root, year, records):
    """(segment records, problems, failed-table excerpts). records = the engine's consolidated DART rows,
    which give the filing URL and the API totals each table must match within one table unit."""
    rcept_no = report_rcept_no(records, year)
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    meta = {"url": url, "rcept_no": rcept_no, "records": records}
    parts, problems, failed = [], [], []

    group = next((g for g in root.iter("TABLE-GROUP") if g.get("ACLASS") == SEGMENT_GROUP), None)
    if group is None:
        problems.append(f"연결 주석 영업부문 표({SEGMENT_GROUP})를 못 찾음")
    for period, unit, grid in (_note_tables(group) if group is not None else ()):
        y = year if period == "당기" else year - 1
        is_region = any(_key(r[0]) == "외부고객으로부터의수익" for r in grid if r)
        reader = _region_rows if is_region else _product_rows
        if unit not in UNIT_SCALE or period is None:
            problems.append(f"영업부문 표의 단위나 당기·전기를 모름 ({unit}, {period})")
            failed.append(("연결 주석 영업부문 표", _table_text(grid)))
            continue
        out, bad = _to_records(*reader(grid, unit, y, records), source=DOC_SOURCE_NOTE, reliability="상", **meta)
        parts.append(out)
        problems += bad
        if bad:
            failed.append((f"연결 주석 영업부문 표 ({period}, {'지역' if is_region else '품목'})", _table_text(grid)))

    section = _section(root, BUSINESS_NOTE.format(4))
    tables = [] if section is None else [_grid(t) for t in section.iter("TABLE")]
    sales = next((i for i, g in enumerate(tables) if _split(g)), None)
    unit = next((m.group(1) for g in tables[:sales] for row in g for c in row if (m := _UNIT.search(c))), None) \
        if sales is not None else None
    if sales is None or unit not in UNIT_SCALE:
        problems.append(f"II-4 매출실적 표({BUSINESS_NOTE.format(4)})를 못 찾았거나 단위를 모름")
    else:
        out, bad = _to_records(*_business_sales_rows(tables[sales], unit, year, records),
                               source=DOC_SOURCE_BUSINESS, reliability="중", **meta)
        parts.append(out)
        problems += bad
        if bad:
            failed.append(("II-4 매출실적 표", _table_text(tables[sales])))

    segments = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return segments, problems, [{"절": None, "제목": t, "글": g, "출처": DOC_SOURCE_BUSINESS, "출처 URL": url,
                                 "잘린 글자 수": 0} for t, g in failed]


def _blocks(el):
    for child in el:
        if child.tag == "TABLE":
            yield _table_text(_grid(child))
        elif child.tag in ("P", "TITLE"):
            if text := _text(child):
                yield text
        else:
            yield from _blocks(child)


def excerpts(root, numbers, max_chars, url):
    """One excerpt per business subsection n (L-0-2-n-L1): paragraphs and tables as text, cut at max_chars.
    Failed-table excerpts from segment_sales carry 절 None, so a part's scope keeps them with the segment rows."""
    out = []
    for n in numbers:
        section = _section(root, BUSINESS_NOTE.format(n))
        if section is None:
            out.append({"절": n, "제목": f"II-{n} (확인 필요: {BUSINESS_NOTE.format(n)} 절을 못 찾음)", "글": "",
                        "출처": DOC_SOURCE_BUSINESS, "출처 URL": url, "잘린 글자 수": 0})
            continue
        title = _text(section.find("TITLE"))
        body = "\n".join(b for b in _blocks(section) if b != title)
        out.append({"절": n, "제목": title, "글": body[:max_chars], "출처": DOC_SOURCE_BUSINESS, "출처 URL": url,
                    "잘린 글자 수": max(0, len(body) - max_chars)})
    return out
