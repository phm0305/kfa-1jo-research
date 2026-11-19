"""KFA study team 1 research center: the fixed-order pipeline on top of the shared engine.

Code collects, computes and checks numbers; Gemini parts only write. Expects engine/ and
research-center/ on sys.path. Member-facing messages are Korean on purpose.

[한국어 안내] 이 파일은 고치지 않고 실행만 해요.
    build_bundle()  DART에서 재무와 사업보고서 원문을 받아 공통 표·출처 목록·지표·사업부문·발췌를 만들어요 (파트에 넘기는 데이터 묶음)
    bundle_text()   데이터 묶음을 AI에게 넘길 글자로 바꿔요
    run()           지시서 6개로 파트 → 센터장 → 숫자 대조 → 품질 점검 → 반대신문을 끝까지 돌려 리포트와 검증 기록지를 만들어요
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from collect import KST, QUARTER_END, CollectError, SkipStep, collect_dart, is_blank, now_kst
from dart_doc import COMPANY_SOURCE, excerpts, fetch_document, industry_code, load_document, report_rcept_no, segment_sales
from excerpt_check import excerpt_check
from engine import (FIX, METRIC_SPECS, UNITS, ask_claims, build_sources, check_claims, claims_prompt,
                    compute_metrics, load_claims, render_check, with_ids)
from layout import PAGES

EOK = 10 ** 8
DOC_DIR = Path("data/dart_doc")
EXCERPT_SECTIONS = (1, 2, 3, 7)
# shortcut: temporary cap (11/15 decision); Nongshim's section 7 is 18,504 chars, revisit once part prompts exist.
EXCERPT_MAX_CHARS = 6000
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"
# Free tier, per key and model, from the 429 text of 11/16 (GenerateRequestsPerDayPerProjectPerModel-FreeTier).
DAILY_LIMIT = 20
# shortcut: the quota day starts at midnight US Pacific = 17:00 KST in winter; it is 16:00 KST from March to early November.
QUOTA_DAY_START_HOUR = 17
PART_NAMES = ("industry", "company", "valuation")
PROMPT_NAMES = (*PART_NAMES, "center", "qa", "cross_exam")
PROMPT_KEYS = {"파트", "리포트 칸", "데이터"}
DATA_KEYS = {"재무", "지표", "사업부문", "사업 설명"}
BLANKS = ("종목명", "종목코드", "연도")
WRITING_RULES = """규칙
- 출력은 JSON 객체 하나만: {"소제목": "본문", ...}. 소제목은 아래 [쓸 칸]의 소제목을 글자 그대로 쓰고, 다른 소제목을 만들지 마
- 숫자를 쓸 때마다 바로 뒤에 근거를 적어: 출처 번호 [S#]와 지표 번호(M#) 또는 줄 번호(rid)
- 재무 표·사업부문별 매출의 표 줄 값과 같은 숫자만 그 표 줄(rid)을 인용해. 발췌에만 있는 숫자(시장점유율 등)는 [S#, E#]로 인용해
- 발췌문에서 가져온 숫자는 [S#]와 함께 발췌 번호(E#)를 꼭 달아 (예: [S4, E3])
- M#를 인용할 때는 그 지표의 값과 단위도 함께 적어 (예: 매출 성장률 2.2% (M4)). M#만 적고 값을 빼지 마
- 새 숫자를 계산하지 마. 비중·비율이 필요하면 지표 표의 M#를 인용하고, 표에 없으면 숫자 대신 "계산 필요"라고 적어
- 받은 자료에 없는 숫자는 짐작하지 말고 "확인 필요"라고 적어
- 소제목마다 첫 줄에 요점 한 문장을 쓰고, 그 아래 줄마다 "- "로 시작하는 근거를 2~4개 써. 근거 하나는 1~2문장이고 숫자와 출처 번호를 담아. 근거 사이에 다른 문단을 섞지 마
- 위 지시서의 5번(출력)의 분량과 다룰 내용은 따르고, 글 모양(요점 한 줄 + 근거 목록)은 이 규칙을 따라. 차트·표·배치 요청은 본문에 "표 필요: (무엇)"으로 적어"""
# Fixed by the team lead, not the member's prompt body, so a member's industry prompt cannot drop it; web_report maps 추세.
PART_RULES = {"industry": """
- 업종 칸에는 회사의 주력 업종을 짧은 명사구로, 한 줄 제목 칸에는 산업 판단을 한 문장으로 써
- 업종코드는 식별용이다. 업종 이름은 발췌의 사업의 개요에 적힌 표현을 쓰고, 코드에서 이름을 추측하지 마
- 추세 칸에는 개선, 악화, 횡보 중 한 단어만 써. 최근 3년 주력 품목 매출과 영업이익률이 함께 늘면 개선, 함께 줄면 악화, 엇갈리거나 변화가 작으면 횡보로 판단해"""}
DELTA_UNITS = ("%p", "%포인트", "포인트")
CENTER_RULES = WRITING_RULES + """
- 숫자는 [파트 글]에 이미 나온 것만 근거와 함께 옮겨 써. 새 숫자를 만들지 마
- M# 번호는 지표 표의 정의를 따라. 같은 지표도 연도마다 번호가 달라서 지시서에 적힌 M1·M2·M3 이름과 다를 수 있으니, 파트 글에 값과 함께 적힌 M#를 그대로 옮겨
- 이 단계에는 숫자 대조 결과(PASS·FIX·REVIEW)가 아직 없어. 대조는 네 글을 받은 뒤 코드가 해
- 출력 칸은 1쪽과 5쪽이야. 다른 쪽은 쓰지 마"""
QA_RULES = """규칙
- 출력은 JSON 배열 하나만: [{"파트": "...", "지적": "..."}]. 고칠 점이 없으면 []
- 파트는 industry, company, valuation, center 중 하나를 글자 그대로
- 지적은 그 파트가 무엇을 고치면 되는지 한 문장으로"""
CROSS_RULES = """규칙
- 출력은 JSON 배열 하나만: [{"대상": "몇 쪽 소제목", "의견": "..."}]
- 리포트의 판단에 반대하는 근거를 [엔진 숫자]에서 찾아 적어. 리포트를 고쳐 쓰지는 마
- 숫자는 [엔진 숫자]에 있는 것만 근거(M# 또는 rid)와 함께 써"""


@dataclass(frozen=True)
class Bundle:
    stock_code: str
    stock_name: str
    year: int
    records: pd.DataFrame
    metrics: pd.DataFrame
    sources: pd.DataFrame
    segments: pd.DataFrame = field(default_factory=pd.DataFrame)
    excerpts: tuple = ()
    segment_problems: tuple = ()
    industry_code: str = ""
    industry_problem: str = ""


@dataclass(frozen=True)
class Scope:
    years: int
    metrics: bool
    segments: bool
    sections: tuple


@dataclass(frozen=True)
class PromptSpec:
    name: str
    part: str
    pages: tuple
    scope: Scope | None
    body: str


@dataclass(frozen=True)
class RunResult:
    status: tuple
    calls: int
    reused: int
    report: Path | None
    verification: Path | None


def build_bundle(stock_code, year, n_years, api_key):
    """Consolidated annual DART rows for the last n_years, tagged; metrics for every year that has
    a previous year; segment rows and excerpts from the year's annual report text.
    Metrics are numbered M1.. in (year, spec) order, so the same input keeps every M#.
    API and segment rows are tagged together so rid and S# are unique across both."""
    years = list(range(year - n_years + 1, year + 1))
    api_rows = pd.concat([collect_dart(stock_code, y, 4, "CFS", api_key) for y in years], ignore_index=True)
    rcept_no = report_rcept_no(api_rows, year)
    root = load_document(fetch_document(rcept_no, api_key, DOC_DIR))
    segment_rows, problems, failed = segment_sales(root, year, api_rows)
    sources, tagged = build_sources(with_ids(pd.concat([api_rows, segment_rows], ignore_index=True)))
    records, segments = tagged.iloc[:len(api_rows)], tagged.iloc[len(api_rows):].reset_index(drop=True)
    metrics = pd.concat([compute_metrics(records, METRIC_SPECS, stock_code, f"{y}-{QUARTER_END[4]}")
                         for y in years[1:]], ignore_index=True)
    metrics["metric_id"] = [f"M{n}" for n in range(1, len(metrics) + 1)]
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    source_ids = {(row["출처"], row["출처 URL"]): row["source_id"] for _, row in sources.iterrows()}
    # shortcut: an excerpt whose source has no rows (II-4 table not found) shows no S#; give it a source row if that happens.
    found = [{**e, "id": f"E{n}", "source_id": source_ids.get((e["출처"], e["출처 URL"]), "")}
             for n, e in enumerate([*excerpts(root, EXCERPT_SECTIONS, EXCERPT_MAX_CHARS, url), *failed], 1)]
    # A failed overview call must not stop the run: the industry part's prompt says what to do without a code.
    try:
        code, code_problem = industry_code(stock_code, api_key), ""
    except CollectError as err:
        code, code_problem = "", str(err)
    if code:
        # Appended after the engine's numbering so every existing S# keeps its number.
        sources = pd.concat([sources, pd.DataFrame([{
            "source_id": f"S{len(sources) + 1}", "출처": COMPANY_SOURCE, "출처 URL": "https://opendart.fss.or.kr",
            "줄 수": 1, "수집 방법": "1 공식 API", "신뢰도": "상", "기준일 범위": now_kst()[:10]}])], ignore_index=True)
    return Bundle(stock_code, records["종목명"].iloc[0], year, records, metrics, sources,
                  segments, tuple(found), tuple(problems), code, code_problem)


def _company_source(bundle):
    return bundle.sources.loc[bundle.sources["출처"] == COMPANY_SOURCE, "source_id"].iloc[0]


def _csv(table):
    return table.to_csv(index=False, lineterminator="\n").rstrip("\n")


def _eok(row):
    base, scale = UNITS.get(row["단위"], (None, None))
    if base != "원" or is_blank(row["값"]):
        return ""
    return f"{row['값'] * float(scale) / EOK:.1f}"


def _record_rows(records):
    rows = records.assign(연도=records["기준일"].str[:4], **{"값(억원)": records.apply(_eok, axis=1)})
    return _csv(rows[["rid", "항목", "연도", "기준", "값", "단위", "값(억원)", "상태", "source_id"]])


def _recent(table, scope, year):
    return table if scope is None else table[table["기준일"].str[:4].astype(int) > year - scope.years]


def bundle_text(bundle, scope=None):
    """The data block placed in a part's prompt; scope None means everything. Shown values are rounded
    so that copying them always stays within the engine's tolerance (half the last written digit)."""
    left_out = "(지시서 데이터 범위에서 뺌)"
    records = _recent(bundle.records, scope, bundle.year)
    metrics = _recent(bundle.metrics, scope, bundle.year)
    metrics = metrics.assign(
        값=metrics["값"].map(lambda v: "" if is_blank(v) else f"{v:.2f}"),
        **{"입력 rid": metrics["입력 rid"].map(" ; ".join)})
    with_segments = scope is None or scope.segments
    shown = [e for e in bundle.excerpts
             if (e["절"] is None and with_segments) or (e["절"] is not None and (scope is None or e["절"] in scope.sections))]
    excerpt_text = "\n\n".join(f"[{e['id']}] {e['제목']} [{e['source_id']}]\n{e['글']}"
                               + (f"\n(이하 {e['잘린 글자 수']:,}자 생략)" if e["잘린 글자 수"] else "")
                               for e in shown)
    checks = "\n".join(f"- {p}" for p in bundle.segment_problems) or "- 모든 표 통과 (칸 합 = 합계, 합계 = API 값)"
    segments = _record_rows(bundle.segments) if not bundle.segments.empty else "(없음)"
    parts = [
        f"# 데이터 묶음: {bundle.stock_name}({bundle.stock_code}) {bundle.year} 사업보고서 기준",
        "## 회사 정보",
        (f"항목,값,source_id\n업종코드(KSIC),{bundle.industry_code},{_company_source(bundle)}\n(업종명은 DART가 주지 않아 코드만)"
         if bundle.industry_code else f"(업종코드 없음{': ' + bundle.industry_problem if bundle.industry_problem else ''})"),
        "## 재무 표 (값은 원 단위 원본, 값(억원)은 코드가 바꾼 읽기용)",
        _record_rows(records) if len(records) else left_out,
        "## 지표 표",
        _csv(metrics[["metric_id", "지표", "기준일", "값", "단위", "계산식", "입력 rid", "상태", "이유"]])
        if scope is None or scope.metrics else left_out,
        "## 사업부문별 매출",
        segments if with_segments else left_out,
        *([f"자동 점검:\n{checks}"] if with_segments else []),
        "## 사업 설명 발췌",
        excerpt_text or ("(없음)" if scope is None or scope.sections else left_out),
        "## 출처",
        _csv(bundle.sources[["source_id", "출처", "출처 URL", "기준일 범위", "신뢰도"]]),
    ]
    return "\n\n".join(parts) + "\n"


def _stop(name, reason):
    raise CollectError(f"지시서 {name}.md: {reason}")


def _scope(name, data):
    if not isinstance(data, dict) or set(data) - DATA_KEYS:
        _stop(name, f"데이터 아래에는 {sorted(DATA_KEYS)}만 쓸 수 있어요. 지금: {data}")
    finance = data.get("재무") or {}
    if not isinstance(finance, dict) or set(finance) - {"연도 수", "기준"}:
        _stop(name, f"재무는 {{연도 수: 3, 기준: 연결}} 모양이어야 해요. 지금: {finance}")
    years = finance.get("연도 수", 0)
    if not isinstance(years, int) or years < 0:
        _stop(name, f"재무 연도 수는 0 이상의 정수여야 해요. 지금: {years}")
    if finance.get("기준", "연결") != "연결":
        _stop(name, "재무 기준은 지금 '연결'만 돼요")
    metrics, segments = data.get("지표", "없음"), data.get("사업부문", "아니오")
    if metrics not in ("전부", "없음") or segments not in ("예", "아니오"):
        _stop(name, f"지표는 전부/없음, 사업부문은 예/아니오 중 하나예요. 지금: {metrics}, {segments}")
    sections = tuple(data.get("사업 설명") or ())
    if not set(sections) <= set(EXCERPT_SECTIONS):
        _stop(name, f"사업 설명에는 절 번호 {list(EXCERPT_SECTIONS)} 중에서만 고를 수 있어요. 지금: {list(sections)}")
    return Scope(years, metrics == "전부", segments == "예", sections)


def load_prompt(path):
    """Read one prompt file: YAML front matter between --- lines, then the member's body."""
    path = Path(path)
    name = path.stem
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.fullmatch(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not match:
        _stop(name, "맨 위에 --- 두 줄로 감싼 머리말이 없어요")
    try:
        head = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as err:
        _stop(name, f"머리말을 읽지 못했어요 ({err})")
    if not isinstance(head, dict) or set(head) - PROMPT_KEYS:
        _stop(name, f"머리말에는 {sorted(PROMPT_KEYS)}만 쓸 수 있어요. 지금: {list(head) if isinstance(head, dict) else head}")
    if is_blank(head.get("파트")):
        _stop(name, "머리말의 '파트'가 비어 있어요")
    body = match.group(2).strip()
    unknown = set(re.findall(r"\{([^{}]*)\}", body)) - set(BLANKS)
    if unknown:
        _stop(name, f"모르는 빈칸 {sorted(unknown)}. 빈칸은 {{종목명}} {{종목코드}} {{연도}}만 돼요")
    pages = tuple(int(n) for n in re.findall(r"\d+", str(head.get("리포트 칸") or "")))
    if set(pages) - set(PAGES):
        _stop(name, f"리포트 칸은 {list(PAGES)}쪽 중에서만 돼요. 지금: {head.get('리포트 칸')}")
    scope = _scope(name, head["데이터"]) if "데이터" in head else None
    return PromptSpec(name, head["파트"], pages, scope, body)


def _fill(body, bundle):
    for blank, value in zip(BLANKS, (bundle.stock_name, bundle.stock_code, str(bundle.year))):
        body = body.replace(f"{{{blank}}}", value)
    return body


def _slots(pages):
    """Pages to fill plus the exact JSON keys; the 11/16 run used page titles as keys when both shared one line."""
    keys = ", ".join(f'"{s}"' for p in pages for s in PAGES[p][1])
    return "\n".join(f"- {p}쪽 {PAGES[p][0]}" for p in pages) + f"\nJSON 키(소제목)는 이것만 글자 그대로: {keys}"


def _read_json(path):
    """Saved answer as JSON, or None when the model did not return valid JSON."""
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", Path(path).read_text(encoding="utf-8"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _sections(path):
    answer = _read_json(path)
    if isinstance(answer, dict) and all(isinstance(v, str) for v in answer.values()):
        return answer
    return {"(형식 오류: JSON 객체가 아님)": Path(path).read_text(encoding="utf-8")}


def _plain(sections):
    return "\n".join(f"[{title}] {text}" for title, text in sections.items())


def _norm(text):
    return re.sub(r"\s", "", text)


class _Caller:
    """ask_claims plus bookkeeping: counts real Gemini calls, and in a later QA round reuses the
    previous round's file when the question is unchanged, so an untouched part is never asked twice."""

    def __init__(self, run_dir, api_key):
        self.run_dir, self.api_key = run_dir, api_key
        self.calls = self.reused = 0
        self.last = {}
        self.status = []

    def ask(self, stage, rnd, prompt):
        if stage in self.last and self.last[stage][0] == prompt:
            self.reused += 1
            self.status.append((f"{stage}_r{rnd}", "♻", "앞 바퀴와 같은 질문이라 그대로 씀"))
            return self.last[stage][1]
        path = self.run_dir / f"{stage}_r{rnd}.json"
        record = path.with_name(f"{path.stem}_기록.json")
        before = record.stat().st_mtime_ns if record.exists() else None
        ask_claims(prompt, self.api_key, path, GEMINI_MODEL, GEMINI_FALLBACK_MODEL)
        called = before != record.stat().st_mtime_ns
        self.calls += called
        self.reused += not called
        self.status.append((path.stem, "✅" if called else "♻", "Gemini 호출" if called else "저장된 답 재사용"))
        self.last[stage] = (prompt, path)
        if called:
            saved = json.loads(record.read_text(encoding="utf-8"))
            if saved["모델"] != GEMINI_MODEL and _limit_hit(saved):
                raise CollectError(f"기본 모델이 하루 한도에 걸려 여기서 멈춰요. {path.name}은 예비 모델 답으로 저장됐어요 "
                                   "(다음 실행에서 이 답을 다시 쓰지 않으려면 그 파일을 지우세요)")
        return path


def _write(caller, spec, rnd, prompt, bad):
    """Ask a writer and check its JSON keys against the layout in code, so the quality check never spends
    a call on format. One retry on a separate file (keeps the first answer reusable); still wrong -> bad."""
    expected = [s for p in spec.pages for s in PAGES[p][1]]
    sections = _sections(caller.ask(spec.name, rnd, prompt))
    if set(sections) != set(expected):
        retry = (f"{prompt}\n\n[형식 오류]\n앞 답의 JSON 키가 {list(sections)}였어. "
                 f"키는 {expected}만 글자 그대로 써. 내용은 그대로 둬도 돼.")
        sections = _sections(caller.ask(f"{spec.name}_fmt", rnd, retry))
    if set(sections) == set(expected):
        bad.discard(spec.name)
    else:
        bad.add(spec.name)
    return sections


def _owner(claim_text, texts):
    sentence = _norm(claim_text)
    return next((name for name, text in texts.items() if sentence and sentence in _norm(text)), "알 수 없음")


def _count_numbers(text):
    """Numbers a reader would check: citations ([S3, rid: ...], M5, E2) and bare years (2025년) are not counted."""
    text = re.sub(r"\[[^\]]*\]|\b[MSE]\d+\b|\b\d{4}년", " ", text)
    return len(re.findall(r"\d[\d,.]*", text))


def max_calls(qa_rounds):
    """Upper bound of real Gemini calls: per round 3 parts + 3 format retries + center + its retry + extraction
    + 4 separate extractions = 13, a quality check after every round but the last, and one cross-examination."""
    return 13 * (qa_rounds + 1) + qa_rounds + 1


def min_calls(qa_rounds):
    """Calls of a fresh run where nothing needs fixing: 3 parts, center, extraction, cross-examination,
    plus the quality check when there is a round for it."""
    return 6 + (qa_rounds > 0)


def quota_day_start(now):
    start = now.replace(hour=QUOTA_DAY_START_HOUR, minute=0, second=0, microsecond=0)
    return start if now >= start else start - timedelta(days=1)


def _limit_hit(record):
    return any(GEMINI_MODEL in e and "PerDay" in e for e in record.get("오류") or [])


def calls_since(dirs, since):
    """Answered Gemini calls per model in the record files (*_기록.json) under dirs since `since`, and whether
    any of them saw the main model's daily-limit error. The count undercounts: a record is overwritten when
    its question changes, and calls made elsewhere leave none; the limit error does not."""
    counts, hit = Counter(), False
    for folder in dirs:
        for path in Path(folder).rglob("*_기록.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                called = datetime.strptime(record["호출 시각"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
            if called >= since:
                counts[record.get("모델")] += 1
                hit = hit or _limit_hit(record)
    return counts, hit


def _check_budget(quota_dirs, qa_rounds):
    """Print what the record files say about today's quota; stop before any call when even a run
    with nothing to fix cannot finish on the main model."""
    start = quota_day_start(datetime.now(KST))
    used, hit = calls_since(quota_dirs, start)
    left = 0 if hit else DAILY_LIMIT - used[GEMINI_MODEL]
    print(f"📊 오늘 한도 구간({start:%m/%d %H:%M}~) 기록 파일 기준 호출: "
          + (", ".join(f"{m} {n}번" for m, n in used.items()) or "없음"))
    if hit:
        print(f"   기본 모델은 이번 구간에 이미 하루 한도 오류(429)가 기록돼 있어요. 남은 횟수 0번으로 봐요")
    else:
        print(f"   기본 모델 남은 횟수: 많아야 {left}번 / 하루 {DAILY_LIMIT}번 "
              "(기록을 덮어썼거나 다른 곳에서 부른 호출은 못 세서 실제로는 더 적을 수 있어요)")
    print(f"📞 이번 실행의 Gemini 호출: 문제가 없으면 {min_calls(qa_rounds)}번, 최대 {max_calls(qa_rounds)}번 "
          f"(품질 점검 {qa_rounds}바퀴 기준, 저장된 답을 다시 쓰면 그만큼 줄어요)")
    if left < min_calls(qa_rounds):
        raise CollectError(f"기본 모델 남은 횟수({left}번)가 이번 실행의 최소 호출 수({min_calls(qa_rounds)}번)보다 적어서 "
                           f"시작하지 않았어요. {QUOTA_DAY_START_HOUR}:00 KST 뒤에 다시 실행해 주세요")
    if left < max_calls(qa_rounds):
        print(f"⚠ 고칠 것이 많으면 중간에 한도에 걸릴 수 있어요. 걸리면 그 단계에서 멈추고 기록지만 만들어요")


def _extract_claims(caller, rnd, texts, records, metrics):
    """One extraction over all texts; a text that has numbers but got no claim is extracted alone once more
    (code decides, not the AI). Returns (claims, owner by claim_id, {text name: numbers} still without claims)."""
    claims = load_claims(caller.ask("claims", rnd, claims_prompt(records, metrics, "\n\n".join(texts.values()))))
    owners = {c["claim_id"]: _owner(c["문장"], texts) for c in claims}
    missed = {}
    for name, text in texts.items():
        numbers = _count_numbers(text)
        if not numbers or name in owners.values():
            continue
        alone = _tag_alone(name, load_claims(caller.ask(f"claims_{name}", rnd, claims_prompt(records, metrics, text))), owners)
        if not alone:
            missed[name] = numbers
        claims += alone
    return claims, owners, missed


def _tag_alone(name, claims, owners):
    """Claims from extracting one text alone: drop empty ones, prefix the id with the text's name, record the owner."""
    kept = [c for c in claims if c["문장"] or c["근거"]]
    for c in kept:
        c["claim_id"] = f"{name}:{c['claim_id']}"
        owners[c["claim_id"]] = name
    return kept


def run(stock_code, year, prompts_dir, run_dir, api_key, dart_key, max_qa_rounds=1, quota_dirs=("data",)):
    """Parts -> center -> one number check over all their text -> quality check -> (fix flagged parts,
    center again, number check again) -> cross-examination -> report.md and verification.md.
    A failed stage, or the main model hitting its daily limit, stops the stages after it;
    rerunning reuses every answer whose question is unchanged. quota_dirs: where record files of
    calls made with the same key live, for the budget printed before the run."""
    run_dir = Path(run_dir)
    bundle = None
    caller = _Caller(run_dir, api_key)
    state = {"qa": [], "cross": None, "checked": None, "owners": {}, "answers": {}, "bad_format": set(), "missed": {},
             "excerpts": {}, "excerpt_sources": set()}
    stage = "호출 예산"
    try:
        _check_budget(quota_dirs, max_qa_rounds)
        stage = "지시서 읽기"
        specs = {n: load_prompt(Path(prompts_dir) / f"{n}.md") for n in PROMPT_NAMES}
        stage = "데이터 묶음"
        n_years = max([2, *(specs[n].scope.years for n in PART_NAMES if specs[n].scope)])
        bundle = build_bundle(stock_code, year, n_years, dart_key)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "bundle.txt").write_text(bundle_text(bundle), encoding="utf-8")
        state["excerpts"] = {e["id"]: e["글"] for e in bundle.excerpts}
        state["excerpt_sources"] = {e["source_id"] for e in bundle.excerpts if e["source_id"]}
        caller.status.append(("데이터 묶음", "✅", f"재무 {len(bundle.records)}줄, 사업부문 {len(bundle.segments)}줄, "
                                                  f"발췌 {len(bundle.excerpts)}개, 지표 {len(bundle.metrics)}개, "
                                                  f"업종코드 {bundle.industry_code or '없음'}"))
        all_records = pd.concat([bundle.records, bundle.segments], ignore_index=True)
        base = {n: (f"{_fill(specs[n].body, bundle)}\n\n{WRITING_RULES}{PART_RULES.get(n, '')}\n\n[쓸 칸]\n{_slots(specs[n].pages)}\n\n"
                    f"{bundle_text(bundle, specs[n].scope)}") for n in PART_NAMES}
        notes = {}
        for rnd in range(max_qa_rounds + 1):
            stage = f"파트 (바퀴 {rnd})"
            for n in PART_NAMES:
                prompt = base[n]
                if notes.get(n):
                    prompt += f"\n\n[이전 답]\n{_plain(state['answers'][n])}\n\n[고칠 점]\n" + "\n".join(f"- {x}" for x in notes[n])
                state["answers"][n] = _write(caller, specs[n], rnd, prompt, state["bad_format"])
            stage = f"센터장 (바퀴 {rnd})"
            parts_text = "\n\n".join(f"[파트 글: {specs[n].part}]\n{_plain(state['answers'][n])}" for n in PART_NAMES)
            prompt = (f"{_fill(specs['center'].body, bundle)}\n\n{CENTER_RULES}\n\n[쓸 칸]\n{_slots(specs['center'].pages)}"
                      f"\n\n{parts_text}")
            if notes.get("center"):
                prompt += f"\n\n[이전 답]\n{_plain(state['answers']['center'])}\n\n[고칠 점]\n" + "\n".join(f"- {x}" for x in notes["center"])
            state["answers"]["center"] = _write(caller, specs["center"], rnd, prompt, state["bad_format"])
            stage = f"숫자 대조 (바퀴 {rnd})"
            texts = {n: _plain(state["answers"][n]) for n in (*PART_NAMES, "center")}
            claims, state["owners"], state["missed"] = _extract_claims(caller, rnd, texts, all_records, bundle.metrics)
            state["checked"] = check_claims(claims, bundle.metrics, all_records)
            render_check(state["checked"], bundle.metrics, bundle.sources, run_dir / f"check_r{rnd}.md")
            if rnd == max_qa_rounds:
                break
            stage = f"품질 점검 (바퀴 {rnd})"
            draft = render_report(specs, state["answers"], bundle, run_dir / f"report_r{rnd}.md",
                                  state["bad_format"]).read_text(encoding="utf-8")
            check_md = (run_dir / f"check_r{rnd}.md").read_text(encoding="utf-8")
            prompt = f"{_fill(specs['qa'].body, bundle)}\n\n{QA_RULES}\n\n[리포트 초안]\n{draft}\n\n[숫자 대조]\n{check_md}"
            state["qa"] = _qa_notes(caller.ask("qa", rnd, prompt))
            notes = {}
            for item in state["qa"]:
                notes.setdefault(item["파트"], []).append(item["지적"])
            for _, row in state["checked"][state["checked"]["판정"] == FIX].iterrows():
                notes.setdefault(state["owners"].get(row["claim_id"]), []).append(
                    f"숫자 대조 FIX: '{row['문장']}'의 {row['적은 숫자']} {row['적은 단위']} → {row['이유']}")
            notes.pop("알 수 없음", None)
            if not notes:
                break
        stage = "반대신문"
        report = render_report(specs, state["answers"], bundle, run_dir / "report.md", state["bad_format"])
        engine_numbers = (f"[지표 표]\n{_csv(bundle.metrics[['metric_id', '지표', '기준일', '값', '단위']])}\n\n"
                          f"[공통 표]\n{_csv(all_records[['rid', '항목', '값', '단위', '기준일', '상태']])}")
        prompt = (f"{_fill(specs['cross_exam'].body, bundle)}\n\n{CROSS_RULES}\n\n[최종 리포트]\n"
                  f"{report.read_text(encoding='utf-8')}\n\n[엔진 숫자]\n{engine_numbers}")
        state["cross"] = _read_json(caller.ask("cross_exam", 0, prompt))
    except (CollectError, SkipStep) as err:
        caller.status.append((stage, "❌", str(err)))
        verification = render_verification(caller, state, bundle, run_dir / "verification.md") if run_dir.exists() else None
        if bundle is not None:
            render_html(run_dir, bundle, specs)
        return RunResult(tuple(caller.status), caller.calls, caller.reused, None, verification)
    verification = render_verification(caller, state, bundle, run_dir / "verification.md")
    render_html(run_dir, bundle, specs)
    return RunResult(tuple(caller.status), caller.calls, caller.reused, report, verification)


def _qa_notes(path):
    answer = _read_json(path)
    valid = {*PART_NAMES, "center"}
    if not isinstance(answer, list):
        return [{"파트": "알 수 없음", "지적": f"품질 점검 답이 JSON 배열이 아님: {Path(path).read_text(encoding='utf-8')[:200]}"}]
    return [{"파트": item.get("파트") if item.get("파트") in valid else "알 수 없음", "지적": str(item.get("지적", ""))}
            for item in answer if isinstance(item, dict)]


def render_report(specs, answers, bundle, path, bad_format=()):
    """Report pages in layout order; each page's text comes from the prompt whose 리포트 칸 lists it."""
    owners = {p: n for n in (*PART_NAMES, "center") for p in specs[n].pages}
    lines = [f"# {bundle.stock_name}({bundle.stock_code}) {bundle.year} 리서치 리포트", ""]
    for page, (title, subtitles) in PAGES.items():
        lines += [f"## {page}쪽 {title}", ""]
        owner = owners.get(page)
        sections = answers.get(owner, {})
        missing = "(확인 필요: 다시 불러도 소제목이 목차와 다름)" if owner in bad_format else "(비어 있음)"
        for sub in subtitles:
            lines += [f"### {sub}", "", sections.get(sub) or missing, ""]
    shown = {s for _, subs in PAGES.values() for s in subs}
    extra = [(n, t, x) for n, sec in answers.items() for t, x in sec.items() if t not in shown]
    if extra:
        lines += ["## 목차에 없는 소제목 (AI가 만든 것)", ""]
        lines += [f"- {n} / {t}: {x}" for n, t, x in extra]
    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _latest(run_dir, name):
    """The answer file a run ended with for one stage: highest round, and that round's format retry if any."""
    found = [(int(m[2]), bool(m[1]), p) for p in run_dir.glob(f"{name}*_r*.json")
             if (m := re.fullmatch(rf"{re.escape(name)}(_fmt)?_r(\d+)\.json", p.name))]
    return max(found)[2] if found else None


def render_html(run_dir, bundle, specs):
    """report.html from the files a run left in run_dir (no Gemini call), so an old run folder converts too.
    Claims are checked again with the engine copy in use, so an old folder shows today's verdicts."""
    from web_report import report_data, write_html  # web_report imports this module, so not at the top
    # shortcut: a folder rerun with fewer QA rounds keeps stale higher-round files and they win; use a fresh folder per run.
    run_dir = Path(run_dir)
    answers = {n: _sections(p) for n in (*PART_NAMES, "center") if (p := _latest(run_dir, n))}
    texts = {n: _plain(a) for n, a in answers.items()}
    checked = None
    main = _latest(run_dir, "claims")
    if main:
        rnd = main.stem.rsplit("_r", 1)[1]
        claims = load_claims(main)
        owners = {c["claim_id"]: _owner(c["문장"], texts) for c in claims}
        for name in texts:
            alone = run_dir / f"claims_{name}_r{rnd}.json"
            if alone.exists():
                claims += _tag_alone(name, load_claims(alone), owners)
        records = pd.concat([bundle.records, bundle.segments], ignore_index=True)
        checked = check_claims(claims, bundle.metrics, records)
        excerpt_texts = {e["id"]: e["글"] for e in bundle.excerpts}
        excerpt_sources = {e["source_id"] for e in bundle.excerpts if e["source_id"]}
        checked["파트"] = [specs[o].part if o in specs else "알 수 없음" for o in checked["claim_id"].map(owners)]
        checked["발췌 대조"] = [excerpt_check(r["문장"], r["근거 id"], r["적은 숫자"], excerpt_texts, excerpt_sources)
                            for _, r in checked.iterrows()]
    page_owner = {p: n for n in (*PART_NAMES, "center") for p in specs[n].pages}
    pages = {p: {s: answers.get(page_owner.get(p), {}).get(s) for s in subs} for p, (_, subs) in PAGES.items()}
    return write_html(report_data(bundle, pages, checked), run_dir / "report.html")


def render_verification(caller, state, bundle, path):
    """① number check ② cross-examination ③ checklist for a person ④ blank for the member's change of view."""
    lines = ["# 검증 기록지", "", "## 실행 상태", "", "| 단계 | 상태 | 메모 |", "|---|---|---|"]
    lines += [f"| {s} | {mark} | {memo} |" for s, mark, memo in caller.status]
    lines += ["", f"Gemini 실제 호출 {caller.calls}번, 재사용 {caller.reused}번", "", "## ① 숫자 대조", ""]
    checked = state["checked"]
    if checked is None:
        lines.append("(실행 안 됨)")
    else:
        lines += ["판정은 엔진 그대로예요. 발췌 대조 칸은 표 근거가 없는 숫자가 문장이 인용한 발췌(E#) 글에 있는지 코드가 찾은 결과예요.", "",
                  "| 주장 | 파트 | 적은 숫자 | 근거 id | 판정 | 이유 | 발췌 대조 |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['claim_id']} {r['문장']} | {state['owners'].get(r['claim_id'], '')} | "
                  f"{'' if is_blank(r['적은 숫자']) else r['적은 숫자']} {r['적은 단위']} | {r['근거 id']} | {r['판정']} | {r['이유']} | "
                  f"{excerpt_check(r['문장'], r['근거 id'], r['적은 숫자'], state['excerpts'], state['excerpt_sources'])} |"
                  .replace("\n", " ") for _, r in checked.iterrows()]
    lines += ["", "## ② 반대신문", ""]
    cross = state["cross"]
    if isinstance(cross, list):
        lines += [f"- {c.get('대상', '')}: {c.get('의견', '')}" if isinstance(c, dict) else f"- {c}" for c in cross] or ["(의견 없음)"]
    else:
        lines.append("(실행 안 됨)" if cross is None else f"(형식 오류) {cross}")
    lines += ["", "## ③ 사람 체크리스트", ""]
    lines += [f"- [ ] 형식 확인 필요 ({n}): 다시 불러도 JSON 키가 목차 소제목과 다름" for n in sorted(state["bad_format"])]
    lines += [f"- [ ] 품질 점검 지적 ({q['파트']}): {q['지적']}" for q in state["qa"]]
    lines += [f"- [ ] 숫자 뽑기 확인 필요 ({n}): 숫자 {k}개가 있는데 그 글만 따로 뽑아도 주장 0개"
              for n, k in state["missed"].items()]
    if checked is not None:
        left = checked[checked["판정"] != "PASS"]
        lines += [f"- [ ] 숫자 대조 {r['판정']} ({state['owners'].get(r['claim_id'], '')}): {r['문장']} / {r['이유']}"
                  + (" (변화량: 엔진 표에 변화량 줄이 없어 대조 못 하는 알려진 한계)"
                     if _norm(str(r["적은 단위"])) in DELTA_UNITS else "")
                  for _, r in left.iterrows()]
    if bundle is not None:
        lines += [f"- [ ] 사업부문 표 자동 점검: {p}" for p in bundle.segment_problems]
        lines += [f"- [ ] 발췌 {e['id']} {e['제목']}: {e['잘린 글자 수']:,}자 잘림" for e in bundle.excerpts if e["잘린 글자 수"]]
    lines += ["- [ ] 투자의견: 목표 배수와 BUY/HOLD 기준이 지시서에 들어오기 전까지 확인 필요",
              "", "## ④ 판단 변화", "", "(조원이 씀)", ""]
    path = Path(path)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
