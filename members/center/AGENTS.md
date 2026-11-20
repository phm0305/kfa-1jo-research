# 리서치 센터장 파트 (center)

레포 맨 위 `AGENTS.md`의 규칙을 먼저 따르고, 이 파일은 이 파트에만 해당하는 내용이에요.

- 맡은 곳: 리포트 1쪽 투자 요약과 5쪽 투자포인트와 검증
- 고칠 파일: `members/center/prompts/center.md` 하나. 데이터 요청은 `members/center/engine_request.md`에 적어요.
- 이번 주 목표: 농심(004370), 2025 사업보고서 기준으로 11/23(월)까지 지시서 고도화
- 실행: `py run.py --member center --stock 004370 --year 2025`
- 결과 확인: `members/center/runs/` 안의 가장 최근 폴더에서 `report.html`(리포트 화면)과 `verification.md`(숫자 대조와 검증 기록)를 봐요.
