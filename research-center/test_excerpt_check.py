"""Run from the repo root: py -B -m pytest research-center/test_excerpt_check.py -q"""

from excerpt_check import excerpt_check

EXCERPTS = {"E2": "라 면 | 2,990,975 | 85.1", "E3": "소맥분 1,144,063 백만원, 가동률 72.3%"}


def test_a_number_without_table_evidence_is_looked_up_only_in_the_excerpts_its_sentence_cites():
    assert excerpt_check("매입액 1144063백만원[S4, E3]", "", "1144063", EXCERPTS) == "발췌 일치 (E3)"
    assert excerpt_check("비중 85.1%[S4, E3]", "", "85.1", EXCERPTS) == "발췌에 없음 (E3)"
    assert excerpt_check("가동률 72%[S4, E3]", "", "72", EXCERPTS) == "발췌에 없음 (E3)"
    assert excerpt_check("매출 [S5, E2]", "004370|매출액(연간)|...", "2990975", EXCERPTS) == ""


def test_an_excerpt_source_cited_without_its_E_number_is_flagged_not_searched():
    assert excerpt_check("주요 4개사 [S4] 기준 56.0% [S4]", "", "4", EXCERPTS, {"S4"}) == "발췌 번호 없음"
    assert excerpt_check("영업이익률 5.2% [S3]", "", "5.2", EXCERPTS, {"S4"}) == ""
