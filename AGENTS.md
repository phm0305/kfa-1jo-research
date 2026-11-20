# 1조 리서치 센터 작업 규칙

이 파일은 조원과 조원이 쓰는 AI(Claude Code, Codex)가 함께 읽어요. AI는 아래 규칙을 지켜 주세요.

## 1. 고쳐도 되는 곳은 내 폴더 하나

- 고쳐도 되는 곳: `members/<내 파트>/` 하나뿐이에요. 내 파트 이름은 industry(산업분석), company(기업·재무분석), valuation(기업가치 평가), center(리서치 센터장) 중 하나예요.
- 읽기만 하는 곳: `engine/`, `research-center/`, `prompts/`, 다른 조원의 `members/` 폴더, `verifier/`, `run.py`, `notebooks/`.
- 다른 조원의 지시서를 끼워 보고 싶으면 복사하지 말고 실행할 때 `--with <파트>`를 붙여요(아래 4번).

## 2. 데이터가 더 필요하면 엔진 요청서에

데이터 묶음에 없는 숫자나 자료가 필요하면 엔진 코드를 고치지 말고 `members/<내 파트>/engine_request.md`에 적어요. 필요한 데이터, 왜 필요한지, 리포트 어느 칸에 쓸지를 적으면 엔진 담당이 받아서 반영해요.

## 3. 올리기 전 확인

- 작업을 시작할 때 `git pull`로 최신 내용을 받아요.
- 커밋하기 전에 `git status`를 봐요. `members/<내 파트>/` 밖의 파일이 바뀌어 있으면 커밋하지 말고 되돌려요(`git restore <파일>`).
- 결과 폴더(`runs/`)에서는 `report.md`, `report.html`, `verification.md`만 올라가요. 나머지 파일은 자동으로 빠져요.
- Colab만 쓰는 경우: GitHub 웹에서 `members/<내 파트>/prompts/<내 파트>.md`를 열고 연필 아이콘으로 고친 뒤 "Commit changes"를 눌러요. 다른 파일은 열어 보기만 해요.

## 4. 실행 방법

내 PC (Windows PowerShell, 레포 폴더에서):

```
py -m pip install -r requirements.txt
py run.py --member industry --stock 004370 --year 2025
py run.py --member industry --stock 004370 --year 2025 --with company
```

- `industry` 자리에 내 파트 이름을 써요. 두 번째 줄은 company 조원의 지시서를 끼워서 돌려 보는 예예요.
- `python` 대신 `py`를 써요. `python`을 쳤을 때 Microsoft Store가 열리거나 아무 일도 안 일어나면, 그건 Windows의 가짜 `python`이에요. `py`로 실행하면 돼요.
- 결과는 `members/<내 파트>/runs/<종목코드>_<연도>_<월일_시분>/`에 생겨요. 실행 결과 맨 위 "지시서" 줄에서 지시서 6개가 각각 어느 파일에서 읽혔는지 보여요. 내 파트가 `members/<내 파트>/prompts/...`로 나오면 내 지시서가 쓰인 거예요.

Colab: `notebooks/research_center.ipynb`를 Colab에서 열고 첫 칸의 `MEMBER = "industry"`를 내 파트로 바꾼 뒤 모두 실행해요. Colab은 GitHub에 올라간 지시서를 읽으니, 고친 지시서는 먼저 GitHub에 올려요.

## 5. 키 준비

| 키 이름 | 필요한 사람 | 받는 곳 |
|---|---|---|
| `GEMINI_API_KEY` | 모두 필수 | 스터디 세팅 가이드(SETUP.md) 8번 |
| `DART_API_KEY` | 모두 필수 | 스터디 세팅 가이드(SETUP.md) 8번 |
| `DATA_GO_KR_KEY` | 주가 공식 API 연결 후 필요. 밸류에이션·센터장은 필수, 나머지는 선택 | 아래 순서 |

- 내 PC: 레포 맨 위 폴더에 `.env` 파일을 만들고 한 줄에 하나씩 `GEMINI_API_KEY=키값`처럼 적어요. `.env`는 GitHub에 올라가지 않아요.
- Colab: 왼쪽 🔑 Secrets에 같은 이름으로 등록하고 노트북 액세스를 켜요.
- `DATA_GO_KR_KEY` 받는 순서: 공공데이터포털(data.go.kr)에 가입하고 로그인 → "금융위원회_주식시세정보" 검색 → 오픈 API 활용신청 → 마이페이지의 개발계정에서 일반 인증키(Decoding)를 복사해요. 신청 직후에는 키가 바로 안 될 수 있어요.

## 6. 지시서 쓰는 규칙

- 맨 위 `---` 두 줄 사이의 머리말에는 `파트`, `리포트 칸`, `데이터` 세 가지만 써요.
- 본문에서 쓸 수 있는 빈칸은 `{종목명}`, `{종목코드}`, `{연도}` 세 개뿐이에요.

## 7. Gemini 무료 한도

- 한 번 실행에 Gemini를 고칠 것이 없으면 7번, 많으면 최대 28번 불러요(품질 점검 1바퀴 기준).
- 무료 한도는 키 하나, 모델 하나에 하루 20번이고 매일 17:00(한국 시각)에 다시 차요. 처음부터 새로 돌리면 한 번 실행으로 한도에 걸릴 수도 있어요. 걸리면 그 단계에서 멈추고 기록지만 만들어요.
- 같은 질문은 Gemini를 다시 부르지 않고 저장된 답을 써요(♻). 새로 실행하면 직전 결과 폴더의 첫 바퀴 답을 가져오므로, 내 지시서만 고쳤다면 내 파트와 그 뒤 단계(센터장, 숫자 대조, 품질 점검, 반대신문)만 새로 불러요.

## 8. 고도화 한 번이 끝나면 AI가 보고할 것

1. 지시서에서 바꾼 점
2. 리포트에서 달라진 점(직전 결과 폴더의 `report.md`와 비교)
3. 숫자 대조 FIX 개수 변화(직전 결과 폴더와 이번 결과 폴더의 `verification.md`에서 FIX 줄 수)
