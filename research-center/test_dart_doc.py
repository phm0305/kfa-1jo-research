"""Offline tests for dart_doc.py on a small hand-made filing.

Run from the repo root: py -B -m pytest research-center/test_dart_doc.py -q
(engine/ or the deployment repo's tools/ must be on PYTHONPATH)
"""

import pandas as pd

import collect as c
from dart_doc import excerpts, load_document, segment_sales

URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260311000001"

FILING = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<SECTION-2><TITLE AASSOCNOTE="L-0-2-1-L1">1. 사업의 개요</TITLE><P>글로벌R&D부문 <당기> 설명</P></SECTION-2>
<SECTION-2><TITLE AASSOCNOTE="L-0-2-4-L1">4. 매출 및 수주상황</TITLE>
<TABLE><TR><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE>
<TR><TH>품목</TH><TH>유형</TH><TH>제2기</TH><TH>제1기</TH></TR>
<TR><TD ROWSPAN="3">라면</TD><TD>내수</TD><TD>80</TD><TD>70</TD></TR>
<TR><TD>수출</TD><TD>20</TD><TD>10</TD></TR>
<TR><TD>합계</TD><TD>100</TD><TD>80</TD></TR>
<TR><TD ROWSPAN="3">매출총계</TD><TD>내수</TD><TD>80</TD><TD>70</TD></TR>
<TR><TD>수출</TD><TD>20</TD><TD>10</TD></TR>
<TR><TD>합계</TD><TD>100</TD><TD>80</TD></TR>
</TABLE></SECTION-2>
<TABLE-GROUP ACLASS="{XBRL}NT_C_D871100"><TITLE>03. 영업부문 (연결)</TITLE>
<TABLE><TR><TD>당기</TD><TD>(단위 : 천원)</TD></TR></TABLE>
<TABLE>
<TR><TD></TD><TD COLSPAN="2">지역</TD><TD ROWSPAN="2">지역 합계</TD></TR>
<TR><TD></TD><TD>한국</TD><TD>미국</TD></TR>
<TR><TD>외부고객으로부터의 수익</TD><TD>60,000</TD><TD>40,000</TD><TD>100,000</TD></TR>
<TR><TD>부문영업손익</TD><TD>7,000</TD><TD>(2,000)</TD><TD>6,000</TD></TR>
</TABLE>
</TABLE-GROUP>
</DOCUMENT>
"""


def api_rows():
    rows = pd.DataFrame([
        {"항목": "매출액(연간)", "값": 100_000_400, "기준일": "2025-12-31"},
        {"항목": "영업이익(연간)", "값": 5_000_000, "기준일": "2025-12-31"},
        {"항목": "매출액(연간)", "값": 80_000_000, "기준일": "2024-12-31"},
    ])
    return c.finalize(rows, level=1, source="DART API", source_url=URL, reliability="상", basis="연결",
                      unit="원", disclosed="20260311", stock_code="004370", stock_name="농심")


def test_filing_is_read_and_a_table_failing_its_checks_is_flagged_with_an_excerpt(tmp_path):
    path = tmp_path / "doc.xml"
    path.write_text(FILING, encoding="utf-8")
    root = load_document(path)

    segments, problems, failed = segment_sales(root, 2025, api_rows())

    region = segments[segments["항목"].str.startswith("지역")]
    assert set(region["상태"]) == {c.REVIEW}
    assert region.set_index("항목").loc["지역 외부매출(미국)", "값"] == 40000
    assert any("칸 합 5,000 ≠ 합계 6,000" in p for p in problems)
    assert any("부문영업손익: 표 합계와 API 값 차이 1,000,000원" in p for p in problems)
    assert [f["제목"] for f in failed] == ["연결 주석 영업부문 표 (당기, 지역)"]

    sales = segments[segments["항목"].str.startswith("품목")].set_index(["항목", "기준일"])
    assert set(sales["상태"]) == {c.PASSED}
    assert sales.loc[("품목 매출(라면, 수출)", "2024-12-31"), "값"] == 10

    [overview] = excerpts(root, (1,), max_chars=10, url=URL)
    body = "글로벌R&D부문 <당기> 설명"
    assert (overview["글"], overview["잘린 글자 수"]) == (body[:10], len(body) - 10)
