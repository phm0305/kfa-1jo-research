"""Offline end-to-end test for pipeline.run with a fake bundle and fake Gemini answers.

Run from the repo root: py -B -m pytest research-center/test_pipeline.py -q
(conftest.py at the repo root puts engine/ and research-center/ on sys.path)
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

import collect as c
import engine as e
import pipeline as p

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260311000001"
TEMPLATE = Path(__file__).resolve().parent / "web" / "template.html"


def page_data(html):
    return json.loads(re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)[1])


def fits(got, want):
    """got has the nested keys the page script reads in the template's example data; a list of records may be empty."""
    if isinstance(want, dict):
        return isinstance(got, dict) and set(got) == set(want) and all(fits(got[k], want[k]) for k in want)
    if isinstance(want, list) and want and isinstance(want[0], dict):
        keys = set(want[0]) - {"lower_is_better"}
        return isinstance(got, list) and all(set(g) - {"lower_is_better"} == keys for g in got)
    return True


def fake_bundle(stock_code, year, n_years, api_key):
    rows = pd.DataFrame([{"항목": "매출액(연간)", "값": v, "기준일": f"{y}-12-31"}
                         for y, v in ((2024, 100 * p.EOK), (2025, 110 * p.EOK))])
    records = c.finalize(rows, level=1, source="DART API", source_url=URL, reliability="상", basis="연결",
                         unit="원", disclosed="20260311", stock_code="004370", stock_name="농심")
    sources, records = e.build_sources(e.with_ids(records))
    metrics = e.compute_metrics(records, e.METRIC_SPECS[:1], "004370", "2025-12-31")
    return p.Bundle("004370", "농심", 2025, records, metrics, sources)


def fake_gemini(prompt, api_key, model, fallback_model, stubborn=False, company_numbers=False):
    """Industry first uses a page title as its key (code re-asks it once), then writes a wrong growth rate
    (the number check FIXes it and only industry is re-asked). stubborn: valuation never uses the right key."""
    if prompt.startswith(e.CLAIM_RULES):
        rates = re.findall(r"매출 성장률은 ([\d.]+)%", prompt.split("[글]")[1])
        answer = [{"claim_id": f"C-{i}", "문장": f"매출 성장률은 {r}%다 [S1] M1.", "근거": [["M1", r, "%"]]}
                  for i, r in enumerate(rates, 1)]
    elif "[리포트 초안]" in prompt:
        answer = []
    elif "[최종 리포트]" in prompt:
        answer = [{"대상": "2쪽 본문", "의견": "성장률 하나로 산업을 판단하기 어렵다"}]
    elif "[파트 글:" in prompt:
        answer = {"본문": "요약", "C-1": "주장 하나", "C-2": "주장 둘", "C-3": "주장 셋"}
    elif "2쪽 산업분석" in prompt and "[형식 오류]" not in prompt and "[고칠 점]" not in prompt:
        answer = {"2쪽 산업분석": "매출 성장률은 9.9%다 [S1] M1."}
    elif "2쪽 산업분석" in prompt:
        answer = {"업종": "라면", "추세": "개선", "한 줄 제목": "수출이 끈다",
                  "본문": f"매출 성장률은 {'10.0' if '[고칠 점]' in prompt else '9.9'}%다 [S1] M1."}
    elif stubborn and "4쪽 기업가치 평가" in prompt:
        answer = {"4쪽 기업가치 평가": "숫자 없는 글"}
    elif company_numbers and "3쪽 기업·재무분석" in prompt:
        answer = {"본문": "공장 가동률은 72.3%다 [S1]."}
    else:
        answer = {"본문": "숫자 없는 글"}
    return json.dumps(answer, ensure_ascii=False), model, []


def test_run_goes_through_fixes_only_the_flagged_part_and_reuses_everything_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)

    first = p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    # parts 3 + industry format retry + center + claims + qa, then industry + center + claims again, then cross-exam
    assert (first.calls, first.reused) == (11, 2)
    assert "industry_fmt_r0" in [s[0] for s in first.status]
    assert not [s for s in first.status if s[1] == "❌"]
    report = first.report.read_text(encoding="utf-8")
    assert "매출 성장률은 10.0%다" in report and "### C-3\n\n주장 셋" in report
    verification = first.verification.read_text(encoding="utf-8")
    assert "| C-1 매출 성장률은 10.0%다 [S1] M1. | industry | 10.0 % | M1 | PASS |" in verification
    assert "성장률 하나로 산업을 판단하기 어렵다" in verification

    page = page_data((tmp_path / "run" / "report.html").read_text(encoding="utf-8"))
    assert fits(page, page_data(TEMPLATE.read_text(encoding="utf-8")))
    assert page["industry"]["notes"] == [{"text": "매출 성장률은 10.0%다 [S1] M1.", "source": None}]
    assert (page["meta"]["industry"], page["industry"]["trend"], page["industry"]["headline"]) == ("라면", "up", "수출이 끈다")
    assert page["key_metrics"][0]["why"] == "매출 성장률은 10.0%다 [S1] M1."
    assert [(c["claim"], c["status"]) for c in page["verification"]["claims"]] == [("매출 성장률은 10.0%다 [S1] M1.", "pass")]

    industry_question = json.loads((tmp_path / "run" / "industry_r0_기록.json").read_text(encoding="utf-8"))["질문"]
    assert "개선, 악화, 횡보 중 한 단어만" in industry_question

    second =p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])
    assert (second.calls, second.reused) == (0, 13)


def test_a_part_that_keeps_the_wrong_key_is_marked_for_review_without_the_quality_check(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", lambda *args: fake_gemini(*args, stubborn=True))
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)

    result = p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    assert [s[0] for s in result.status].count("valuation_fmt_r0") == 1
    assert "## 4쪽 기업가치 평가\n\n### 본문\n\n(확인 필요" in result.report.read_text(encoding="utf-8")
    assert "- [ ] 형식 확인 필요 (valuation)" in result.verification.read_text(encoding="utf-8")


def test_a_text_with_numbers_but_no_claims_is_extracted_alone_once_then_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", lambda *args: fake_gemini(*args, company_numbers=True))
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)

    result = p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    # the fake extractor never finds the company sentence; round 1 asks the same question again, so it is reused
    assert [s[0] for s in result.status].count("claims_company_r0") == 1
    assert (result.calls, result.reused) == (12, 3)
    assert "- [ ] 숫자 뽑기 확인 필요 (company): 숫자 1개가" in result.verification.read_text(encoding="utf-8")


def test_a_typo_in_a_prompt_blank_stops_with_the_file_name(tmp_path):
    prompts = tmp_path / "prompts"
    shutil.copytree(PROMPTS, prompts)
    path = prompts / "company.md"
    path.write_text(path.read_text(encoding="utf-8") + "{종목이름}의 매출을 분석해 줘\n", encoding="utf-8")

    result = p.run("004370", 2025, [prompts], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    assert result.status[-1][1] == "❌" and "company.md" in result.status[-1][2] and "종목이름" in result.status[-1][2]


def test_a_run_that_cannot_finish_on_todays_main_model_quota_never_starts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(e, "_call_gemini", lambda *args: calls.append(args))
    quota = tmp_path / "quota"
    quota.mkdir()
    for n in range(p.DAILY_LIMIT - p.min_calls(1) + 1):
        (quota / f"x{n}_기록.json").write_text(json.dumps({"질문": f"q{n}", "모델": p.GEMINI_MODEL, "호출 시각": c.now_kst()}), encoding="utf-8")

    result = p.run("004370", 2025, [PROMPTS], tmp_path / "run", "key", "dart", quota_dirs=[quota])

    assert calls == [] and result.status[-1][0] == "호출 예산" and result.status[-1][1] == "❌"


def test_a_recorded_daily_limit_error_counts_as_no_calls_left_whatever_the_count(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(e, "_call_gemini", lambda *args: calls.append(args))
    quota = tmp_path / "quota"
    quota.mkdir()
    (quota / "x_기록.json").write_text(json.dumps({
        "모델": p.GEMINI_FALLBACK_MODEL, "호출 시각": c.now_kst(),
        "오류": [f"{p.GEMINI_MODEL} 429: GenerateRequestsPerDayPerProjectPerModel-FreeTier"]}), encoding="utf-8")

    result = p.run("004370", 2025, [PROMPTS], tmp_path / "run", "key", "dart", quota_dirs=[quota])

    assert calls == [] and result.status[-1][0] == "호출 예산"


def test_hitting_the_daily_limit_mid_run_stops_after_that_stage_and_still_writes_the_record(tmp_path, monkeypatch):
    def limited(prompt, api_key, model, fallback_model):
        answer, used, errors = fake_gemini(prompt, api_key, model, fallback_model)
        if "[파트 글:" in prompt:
            return answer, fallback_model, [f"{model} 429: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier"]
        return answer, used, errors

    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", limited)

    result = p.run("004370", 2025, [PROMPTS], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    assert result.status[-1][1] == "❌" and "하루 한도" in result.status[-1][2] and "center_r0.json" in result.status[-1][2]
    assert not (tmp_path / "run" / "claims_r0.json").exists()
    assert "하루 한도" in result.verification.read_text(encoding="utf-8")


def test_a_metric_why_is_only_a_sentence_citing_that_metric_alone():
    import web_report as w
    assert w._why("M1", ["둘 다 늘었다 [S1] M1, M2. 성장했다 [S1] M1."]) == "성장했다 [S1] M1."
    assert w._why("M1", ["둘 다 늘었다 [S1, E2] M1."]) == ""


def test_page_paragraphs_split_only_on_blank_lines_and_keep_the_point_with_its_list():
    import web_report as w
    assert w._paragraphs("요점 [S1]\n- 근거 하나 [S1]\n- 근거 둘 [S2]\n\n다음 문단") == [
        "요점 [S1]\n- 근거 하나 [S1]\n- 근거 둘 [S2]", "다음 문단"]


def test_each_prompt_comes_from_the_first_folder_that_has_it_and_the_first_status_line_says_which(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    mine, borrowed = tmp_path / "members/industry/prompts", tmp_path / "members/company/prompts"
    for folder, name in ((mine, "industry"), (borrowed, "company")):
        folder.mkdir(parents=True)
        shutil.copy(PROMPTS / f"{name}.md", folder)

    result = p.run("004370", 2025, [borrowed, mine, PROMPTS], tmp_path / "run", "key", "dart", quota_dirs=[tmp_path / "quota"])

    assert result.status[0][:2] == ("지시서", "ℹ")
    shown = dict(part.split(": ") for part in result.status[0][2].split(", "))
    assert shown["industry"] == (mine / "industry.md").as_posix()
    assert shown["company"] == (borrowed / "company.md").as_posix()
    assert shown["center"] == (PROMPTS / "center.md").as_posix()


def test_a_new_run_folder_reuses_the_last_runs_first_round_so_only_the_edited_part_is_asked_again(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "build_bundle", fake_bundle)
    monkeypatch.setattr(e, "_call_gemini", fake_gemini)
    prompts, runs = tmp_path / "prompts", tmp_path / "runs"
    shutil.copytree(PROMPTS, prompts)
    first_dir = p.new_run_dir(runs, "004370", 2025, datetime(2026, 11, 20, 10, 0))
    p.run("004370", 2025, [prompts], first_dir, "key", "dart", quota_dirs=[runs])
    counted = p.calls_since([runs], datetime(2000, 1, 1, tzinfo=c.KST))
    industry = prompts / "industry.md"
    industry.write_text(industry.read_text(encoding="utf-8") + "\n한 문장 더.\n", encoding="utf-8")

    second_dir = p.new_run_dir(runs, "004370", 2025, datetime(2026, 11, 20, 11, 0))

    assert not list(second_dir.glob("*_r1*")) and list(second_dir.glob("company_r0*"))
    assert p.calls_since([runs], datetime(2000, 1, 1, tzinfo=c.KST)) == counted
    second = p.run("004370", 2025, [prompts], second_dir, "key", "dart", quota_dirs=[runs])
    marks = {s[0]: s[1] for s in second.status}
    assert (marks["industry_r0"], marks["company_r0"], marks["valuation_r0"]) == ("✅", "♻", "♻")
