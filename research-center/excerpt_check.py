"""KFA study team 1: an excerpt check placed beside the engine's number check, never replacing its verdict.

The engine can only check numbers that have a table row (rid) or metric (M#). Numbers quoted from the
annual report's text excerpts (E#) therefore stay REVIEW there; this module only says whether the number
is literally written in the excerpt the sentence cites.

[한국어 안내] 이 파일은 고치지 않고 실행만 해요.
    excerpt_check()  표 근거가 없는 숫자가, 문장이 인용한 발췌(E#) 글 안에 실제로 있는지 찾아요
                     결과: "발췌 일치 (E3)" / "발췌에 없음 (E3)" / "발췌 번호 없음" / 해당 없으면 빈칸
"""

import re

from collect import is_blank

_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3})")


def excerpt_check(sentence, evidence_id, number, excerpts, excerpt_sources=()):
    """For a number with no table evidence in a sentence citing E#, whether the cited excerpt text contains it.
    excerpts: {E#: text}; excerpt_sources: the S# the excerpts come from. A sentence citing one of those S#
    but no E# is "발췌 번호 없음": searching the whole source would match short numbers like "4개사" anywhere.
    Returns '' when the row has table evidence, no number, or cites neither."""
    value = re.sub(r"[^\d.\-]", "", str(number).replace(",", "")).strip(".")
    if evidence_id or is_blank(number) or not re.search(r"\d", value):
        return ""
    cited = [e for e in dict.fromkeys(re.findall(r"\bE\d+\b", str(sentence))) if e in excerpts]
    if not cited:
        return "발췌 번호 없음" if set(re.findall(r"\bS\d+\b", str(sentence))) & set(excerpt_sources) else ""
    pattern = re.compile(rf"(?<![\d.]){re.escape(value)}(?!\d|\.\d)")
    found = [e for e in cited if pattern.search(_THOUSANDS.sub("", excerpts[e]))]
    return f"발췌 일치 ({', '.join(found)})" if found else f"발췌에 없음 ({', '.join(cited)})"
