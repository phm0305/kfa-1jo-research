"""KFA study team 1: the research report's table of contents and default subheadings.

Page titles follow research-center/README.md. A prompt's 소제목 front matter replaces a page's default
subheadings for the run; pipeline.load_prompt is the only place that merges the two. Page 2's 업종, 추세 and
한 줄 제목 fill the industry panel's header in report.html (web_report.py); 추세 must be one of 개선, 악화, 횡보.

[한국어 안내] 리포트 목차와 기본 소제목이에요.
    지시서 머리말에 "소제목: {5쪽: [C-1, C-2, C-3, C-4]}"처럼 적으면 그 쪽은 그 소제목을 써요. 안 적으면 여기 값을 써요.
"""

PAGES = {
    1: ("투자 요약", ("본문",)),
    2: ("산업분석", ("업종", "추세", "한 줄 제목", "본문")),
    3: ("기업·재무분석", ("본문",)),
    4: ("기업가치 평가", ("본문",)),
    5: ("투자포인트와 검증", ("C-1", "C-2", "C-3")),
}
# Pages whose writer may fill only the first k subheadings (k >= 1); a gap would make the page's point numbers
# disagree with the verification record's.
PREFIX_PAGES = {5}
