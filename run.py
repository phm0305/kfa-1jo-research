"""Run the team 1 research center with one member's prompts.

    py run.py --member industry --stock 004370 --year 2025
    py run.py --member industry --stock 004370 --year 2025 --with company
    py run.py --member industry --render-only

[한국어 안내] 내 지시서로 리포트를 만들어요. 고치지 않고 실행만 해요.
    --member       내 파트 (industry, company, valuation, center)
    --with         다른 조원의 지시서와 화면 조각을 끼워 보고 싶을 때 그 파트 이름 (읽기만 하고 복사하지 않아요)
    --render-only  내 직전 결과 폴더의 report.html만 지금 화면 조각으로 다시 그려요. Gemini·DART를 부르지 않아요.
    결과는 members/<내 파트>/runs/<종목코드>_<연도>_<월일_시분>/ 에 생겨요.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Messages carry emoji; a piped stdout on Windows defaults to cp949, which cannot encode them (an AI agent running this pipes it).
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(ROOT)
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "research-center")]

from collect import KST, get_key  # noqa: E402  (needs the sys.path above)
from pipeline import find_fragments, fragment_line, new_run_dir, run  # noqa: E402

MEMBERS = sorted(d.name for d in Path("members").iterdir() if d.is_dir())


def main():
    parser = argparse.ArgumentParser(description="1조 리서치 센터: 내 지시서로 리포트 만들기")
    parser.add_argument("--member", required=True, choices=MEMBERS, help="내 파트")
    parser.add_argument("--stock", help="종목코드 (예: 004370)")
    parser.add_argument("--year", type=int, help="사업보고서 연도 (예: 2025)")
    parser.add_argument("--with", dest="borrowed", action="append", default=[], choices=MEMBERS,
                        help="끼워 볼 다른 조원의 파트")
    parser.add_argument("--render-only", action="store_true", help="직전 결과의 report.html만 다시 그리기")
    args = parser.parse_args()
    prompts_dirs = [Path("members", m, "prompts") for m in args.borrowed] + [Path("members", args.member, "prompts"), Path("prompts")]
    runs = Path("members", args.member, "runs")
    if args.render_only:
        render_only(runs, find_fragments(prompts_dirs))
        return
    if not args.stock or not args.year:
        parser.error("--stock과 --year를 적어 주세요 (--render-only일 때만 빼도 돼요)")
    run_dir = new_run_dir(runs, args.stock, args.year, datetime.now(KST))
    dummy_csv = Path("members", args.member, "dummy_data.csv")
    result = run(args.stock, args.year, prompts_dirs, run_dir, get_key("GEMINI_API_KEY"), get_key("DART_API_KEY"),
                 quota_dirs=[runs], dummy_data=(args.member, dummy_csv) if dummy_csv.exists() else None)
    for step, mark, memo in result.status:
        print(mark, step, memo)
    print(f"결과 폴더: {run_dir.as_posix()}")


def render_only(runs, fragments):
    from web_report import redraw
    # Folder names end in MMDD_HHMM (new_run_dir); git pull resets folder times, so the name orders runs, not the clock.
    done = [d for d in runs.glob("*_*_*") if (d / "report.html").exists()]
    if not done:
        sys.exit(f"❌ {runs.as_posix()}에 report.html이 있는 결과 폴더가 없어요. 먼저 --stock, --year를 붙여 한 번 실행해 주세요")
    run_dir = max(done, key=lambda d: d.name[-9:])
    print("ℹ 화면 조각", fragment_line(fragments))
    print(f"✅ 다시 그림: {redraw(run_dir / 'report.html', fragments).as_posix()} (Gemini·DART 호출 0번)")


if __name__ == "__main__":
    main()
