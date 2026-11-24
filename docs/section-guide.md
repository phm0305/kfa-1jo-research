# 리포트 화면 내 마음대로 바꾸기

`report.html`에서 내 파트가 맡은 패널은 내가 직접 그릴 수 있어요. 내 폴더에 `section.html` 파일 하나만 두면 돼요. 파일이 없으면 지금 화면(기본 화면)이 그대로 나와요.

| 내 파트 | 내가 그리는 패널 |
|---|---|
| industry | 산업 분석 (2쪽) |
| company | 기업·재무 분석 (3쪽) |
| valuation | 밸류에이션 (4쪽) |
| center | 한눈에 보기 (1쪽), 결론과 투자 포인트 (5쪽) |

출처 패널과 검증 기록지 탭은 엔진이 그려요. 조각으로 바꿀 수 없어요.

## 1. 소제목 정하기

소제목은 화면이 아니라 지시서에서 정해요. 지시서 맨 위 머리말에 `소제목`을 적으면 AI가 그 이름을 JSON 키로 써서 답해요. 형식 검사, `report.md` 순서, 검증 기록지도 이 목록을 따라요.

```
---
파트: 산업분석
리포트 칸: 2쪽
소제목:
  2쪽: [업종, 추세, 한 줄 제목, 본문]
데이터:
  ...
---
```

- 안 적으면 기본 소제목(`research-center/layout.py`)을 써요.
- 2쪽의 `업종`, `추세`, `한 줄 제목`은 화면 위쪽(업종 이름, 추세 표시, 제목)에 들어가요. 이 셋을 빼면 그 자리에 "확인 필요"가 나와요.
- 5쪽(센터장)은 목록 앞에서부터 쓴 만큼만 써도 돼요. `[C-1, C-2, C-3, C-4]`로 적고 C-1, C-2만 쓰면 통과예요. C-1, C-3처럼 중간을 건너뛰면 형식 오류로 한 번 다시 물어요.

## 2. section.html 시작하기

1. `docs/section-examples/<내 파트>.html`을 `members/<내 파트>/section.html`로 복사해요. 예시는 지금 기본 화면을 그대로 옮긴 거라서, 복사만 하고 돌리면 화면이 똑같이 나와요.
   - 소제목마다 제목을 달아 나눠 보여 주고 싶으면 `docs/section-examples/industry-by-subheading.html`을 보세요. `data.pages["2"]`를 돌면서 소제목을 제목으로, 글을 카드로 그려요. 다른 파트도 쪽 번호만 바꿔서 같은 방법으로 쓸 수 있어요.
2. 복사한 파일을 고쳐요. 파일 모양은 이래요.

```html
<div data-panel="industry">
  <div class="panel-head"><h2>산업 분석</h2></div>
  <h3 id="my-headline"></h3>
  <script>
    root.querySelector("#my-headline").textContent = data.industry.headline;
  </script>
</div>
```

- `data-panel` 블록 하나가 패널 하나예요. 이름은 industry, company, valuation, summary, conclusion 중 내 파트 것만 써요. 센터장은 summary와 conclusion 두 블록을 한 파일에 써요. 한 블록만 바꾸고 싶으면 다른 블록은 지워요(지운 패널은 기본 화면).
- 블록 안의 HTML이 패널 안의 내용이 돼요. `<script>`는 그 HTML을 채워요. `<script>` 안에서는 아래 세 이름을 쓸 수 있어요.
  - `data`: 이번 결과의 JSON 전체(3번 표)
  - `root`: 내 블록. 칸을 찾을 때 `document` 대신 `root.querySelector(...)`를 써요.
  - `ui`: 화면 도구(4번 표)
- `id`를 새로 만들 때는 다른 패널과 겹치지 않는 이름으로 지어요(예: `my-` 붙이기).

## 3. JSON 칸 목록

`report.html` 맨 아래 "출처" 패널의 "이 화면을 그린 데이터(JSON) 보기"를 누르면 실제 값을 볼 수 있어요. 값이 없으면 `null`이고, 기본 화면은 이걸 "확인 필요"로 보여요.

| 칸 | 뜻 |
|---|---|
| `meta.ticker`, `meta.name` | 종목코드, 종목명 |
| `meta.industry` | 2쪽 `업종` 칸의 글 |
| `meta.as_of` | 재무 자료의 가장 최근 기준일 |
| `meta.is_example`, `meta.currency` | 예시 데이터인지(실제 실행은 false), 통화(KRW) |
| `summary.opinion` | 투자의견. 지금은 늘 "확인 필요" |
| `summary.one_line` | 1쪽 본문의 첫 문단 |
| `summary.current_price`, `summary.price_as_of`, `summary.price_source` | 현재가(원), 그 기준일, 출처 번호(S#) |
| `summary.upside_note` | 주가 검증에 실패하면 "검증 실패", 아니면 null |
| `key_metrics[]` | 지표 카드 목록. 하나마다 `label`(이름과 M#), `value`, `unit`, `star`(판단 핵심인지), `why`(그 지표만 인용한 첫 문장), `source`(S#) |
| `industry.trend` | 2쪽 `추세` 칸. 개선 → "up", 악화 → "down", 횡보 → "flat", 그 밖에는 null |
| `industry.headline` | 2쪽 `한 줄 제목` 칸 |
| `industry.series_label`, `industry.series[]` | 차트 제목, 차트 점 목록(`period` 연도, `value` 억원) |
| `industry.notes[]` | 2쪽에서 업종·추세·한 줄 제목을 뺀 나머지 소제목 글을 문단으로 나눈 것. 하나마다 `text`, `source` |
| `company.unit`, `company.periods` | 표 단위 설명, 비교하는 두 해(예: ["2024", "2025"]) |
| `company.rows[]` | 재무 표 줄. `item`, `prev`(앞 해), `curr`(이번 해), `kind`("amount" 억원 / "ratio" %). 낮을수록 좋은 비율에는 `lower_is_better`가 붙어요 |
| `company.drivers[]` | 3쪽 글을 문단으로 나눈 것. `text`, `source` |
| `valuation.method`, `valuation.method_reason` | 적용 방식과 이유. 지금은 "확인 필요"와 빈칸 |
| `valuation.bps`, `valuation.multiples[]`, `valuation.target_multiple` | BPS(원), 민감도 표의 배수 목록, 목표 배수 |
| `valuation.conclusion` | 4쪽 글 전체 |
| `conclusion.points[]` | 5쪽 투자포인트. 하나마다 `text`, `refs`(근거가 된 패널 이름 목록). 빈 칸과 "해당 없음" 칸은 이미 빠져 있어요 |
| `pages["2"]` (1~5쪽 모두) | 그 쪽의 `{소제목: 글}`. 지시서 머리말의 소제목 순서 그대로예요. 비어 있거나 "해당 없음"으로 시작하는 칸도 소제목은 남고 글만 `""`이라서, 숨길지 보여 줄지 조각이 정해요. 쪽 번호는 `"2"`처럼 따옴표 안에 써요 |
| `verification`, `cite_sources`, `sources` | 검증 기록지와 출처. 엔진 몫이라 읽기만 해요 |

글 칸에는 `[S1]`, `M3` 같은 근거 표시가 그대로 들어 있어요. 화면에 글을 넣을 때는 `ui.card`를 쓰면 근거 표시를 숨기고 출처 각주를 달아 줘요.

예전 결과(이 기능이 생기기 전)의 JSON에는 나중에 생긴 칸이 없을 수 있어요. 없는 칸을 읽으면 그 패널은 기본 화면으로 돌아가요. 있을 때만 쓰고 싶은 칸은 `"lower_is_better" in r`처럼 먼저 확인해요.

## 4. ui 도구

| 도구 | 하는 일 |
|---|---|
| `ui.card(글, 자리)` | 글의 근거 표시를 숨기고 문단·목록으로 나눈 HTML을 돌려줘요. 끝에 출처 각주 번호(①②)를 달아요. `자리`는 출처 탭의 "쓴 곳"에 보일 이름이에요(예: "2쪽 산업"). |
| `ui.esc(글)` | 글을 HTML에 그대로 넣어도 안전하게 바꿔요. JSON 글을 HTML 문자열에 넣을 때는 꼭 거쳐요. |
| `ui.fmt(숫자, 자릿수)` | "1,234.5"처럼 쉼표와 소수점을 붙여요. 자릿수를 안 주면 1이에요. 값이 없으면 "확인 필요". |
| `ui.won(숫자)` | "12,345원"처럼 원 단위로 써요. 값이 없으면 "확인 필요". |
| `ui.srcTag(S번호)` | 누르면 출처 패널로 가는 `S1` 단추 HTML을 돌려줘요. 번호가 없으면 빈 글. |
| `ui.drawLine(svg, 점 목록)` | `<svg viewBox="0 0 560 220">` 안에 선 차트를 그려요. 점 목록은 `[{period, value}]`이고, 점이 두 개보다 적으면 "확인 필요"를 써요. |

이 도구들은 조원들의 조각이 함께 쓰는 약속이에요. 앞으로 도구를 바꿔야 하면 지금 것의 이름이나 인자를 고치지 않고 새 도구를 추가해요.

## 5. --render-only로 확인하기

조각을 고칠 때마다 리포트를 새로 만들 필요는 없어요. 한 번 실행한 결과가 있으면 화면만 다시 그릴 수 있어요.

```
py run.py --member industry --render-only
```

- 내 `runs/`에서 가장 최근 결과 폴더의 리포트를 지금 조각으로 다시 그려서, 같은 폴더에 `preview.html`로 써요. `report.html`은 바뀌지 않아요. Gemini와 DART를 한 번도 부르지 않고, 숫자도 그 실행 때 그대로예요. `preview.html`은 GitHub에 올라가지 않아요.
- 다른 조원의 조각을 같이 보려면 `--with company`처럼 붙여요.
- 결과 맞는지 보는 곳:
  - 출력 첫 줄 "화면 조각"에서 내 파트가 `members/<내 파트>/section.html`로 나오면 내 조각을 읽은 거예요.
  - 출력 둘째 줄 "미리보기"에 적힌 `preview.html`을 열어서 확인해요. 조각이 있는 패널 맨 아래에 "화면: ..." 줄이 있어요. 파일 이름이 나오면 내 조각으로 그린 거예요. "기본 (... 오류: ...)"이 나오면 조각에 문제가 있어서 기본 화면으로 그린 거예요. 괄호 안 오류 글을 보고 고쳐요.

## 6. 지킬 것

- 숫자는 JSON에서만 가져와요. HTML이나 `<script>`에 숫자를 직접 적지 않아요. 직접 적은 숫자는 숫자 대조를 거치지 않아서 검증 기록지와 화면이 달라져요.
- 모양은 공통 CSS 클래스로 내요. 쓸 수 있는 클래스: `panel-head`, `two-col`, `pill`(+`up`/`down`/`hold`), `tile`, `price-tiles`, `key-grid`, `key`, `notes`, `table-wrap`, `num`, `small`, `muted`, `method`, `sens-row`, `cell`, `points`, `refs`, `link-btn`, `chart`, `status`. `<style>`로 새 색이나 글꼴을 만들지 않아요. 다섯 패널이 한 리포트처럼 보이게 하려는 규칙이에요.
- 출처 탭은 건드리지 않아요. 출처 패널, 검증 기록지, 각주 번호는 엔진이 매겨요. 글은 `ui.card`로, 출처 단추는 `ui.srcTag`로만 넣어요.
