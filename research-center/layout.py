"""KFA study team 1: the research report's table of contents, the only place it is defined.

Page titles follow research-center/README.md. Page 2's 업종, 추세 and 한 줄 제목 fill the industry panel's
header in report.html (web_report.py); 추세 must be one of 개선, 악화, 횡보. 본문 is a placeholder until
the team settles the subheadings (11/17 meeting).

[한국어 안내] 리포트 목차예요. 쪽 제목과 소제목은 여기 한 곳에만 적어요.
    지시서(prompts/*.md) 머리말에는 "리포트 칸: 3쪽"처럼 몇 쪽인지만 적고, 소제목은 여기서 가져가요.
"""

PAGES = {
    1: ("투자 요약", ("본문",)),
    2: ("산업분석", ("업종", "추세", "한 줄 제목", "본문")),
    3: ("기업·재무분석", ("본문",)),
    4: ("기업가치 평가", ("본문",)),
    5: ("투자포인트와 검증", ("C-1", "C-2", "C-3")),
}
