# 더미 데이터 기능 지우기

조원이 엔진 요청서에 적은 데이터를 엔진 반영 전에 시험해 보도록 임시로 넣은 기능이에요. 요청한 데이터를 엔진이 직접 받게 되면(특히 공식 주가 API) 아래를 모두 지워요. 진짜 값이 있는 항목의 더미는 이미 무시되므로, 지우기 전까지 남아 있어도 진짜 결과를 덮지는 않아요.

## 지울 파일

- `research-center/dummy.py`
- `research-center/test_dummy.py`
- `members/valuation/dummy_data.example.csv`
- 이 파일 `docs/plans/remove-dummy.md`

## 지울 연결 줄

`research-center/pipeline.py`:

- 맨 위 `import dummy`
- `Bundle`의 `dummy: pd.DataFrame = ...` 칸, `all_rows()`의 `bundle.dummy`와 독스트링의 "a member's dummy rows"
- `run()`의 `dummy_data=None` 인자와 독스트링 끝 문장
- `run()`에서 `plain = bundle = build_bundle(...)`을 `bundle = build_bundle(...)`로 되돌리고, 그 아래 `mine = ...`, `if dummy_data:` 세 줄 삭제
- `base = {...}`를 `base = {n: part_question(n, specs[n], bundle) for n in PART_NAMES}`로 되돌리고 바로 위 주석 삭제
- 센터장 질문 끝의 `+ (dummy.block(bundle) if mine == "center" else "")`
- `render_verification()`의 `dummy.verdict(r, bundle)`를 `r['판정']`으로 되돌리고, `lines += dummy.checklist(checked, bundle)` 삭제
- `render_html()`의 `dummy.mark_inputs(...)` 줄 삭제, `dummy.mark_data(..., bundle)`를 벗겨 `report_data(bundle, pages, checked)`만 남김

`run.py`:

- `dummy_csv = ...` 줄과 `run()` 호출의 `dummy_data=...` 인자

## 지울 설정과 안내

- `.gitignore`의 `members/*/dummy_data.csv`
- `AGENTS.md` 2번 절의 "반영 전에 더미로 시험해 보고 싶으면:"부터 아래 목록 세 줄

## 지운 뒤 확인

- `git grep -n -i dummy`와 `git grep -n 더미`가 아무것도 찾지 않아야 해요(실행 결과 폴더 제외).
- `py -B -m pytest research-center -q`가 통과해야 해요.
- 조원 폴더에 남은 `members/*/dummy_data.csv`는 GitHub에 없으니 각자 지워요.
