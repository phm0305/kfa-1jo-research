"""Run an offline PER/PBR calculation using an isolated local input file."""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from statistics import median


def calculate(data):
    cutoff = data["valuation_date"]
    actual, forecast, peers = (data[key] for key in ("actual", "forecast", "peer_snapshot"))
    price = data.get("price")
    if any(date >= cutoff for date in (actual["filing_date"], forecast["published"], peers["published"])):
        raise ValueError("Date-only filings and estimates must predate the valuation date.")
    if price is not None and (price["date"] != cutoff or price["close"] <= 0):
        raise ValueError("The close must be positive and match the valuation date.")
    if forecast["year"] != peers["year"] or len({peer["name"] for peer in peers["peers"]}) < 2:
        raise ValueError("Expected at least two peers and a matching forecast year.")

    earnings = actual["net_income"]
    eps = earnings / actual["year_end_float"]
    bps = actual["equity"] / actual["year_end_float"]
    basic_eps = earnings / actual["weighted_average_shares"]
    if round(basic_eps) != actual["disclosed_eps"]:
        raise ValueError("Recalculated basic EPS does not match the disclosure.")

    assumptions = data["trial_assumptions"]
    multiples = {}
    for model in ("per", "pbr"):
        factor = assumptions[f"{model}_reference_factor"]
        values = [peer[model] for peer in peers["peers"]]
        if not 0.5 <= factor <= 2 or min(values) <= 0:
            raise ValueError(f"Invalid {model.upper()} inputs.")
        multiples[model] = median(values) * factor

    close = price["close"] if price is not None else None
    rows = []
    for scenario in assumptions["scenarios"]:
        per_value = forecast["eps"] * scenario["eps_factor"] * multiples["per"]
        pbr_value = forecast["bps"] * scenario["bps_factor"] * multiples["pbr"]
        rows.append({
            "name": scenario["name"],
            "per_value": per_value,
            "pbr_value": pbr_value,
            "per_gap_pct": (per_value / close - 1) * 100 if close else None,
            "pbr_gap_pct": (pbr_value / close - 1) * 100 if close else None,
        })

    if [row["name"] for row in rows] != ["Bear", "Base", "Bull"]:
        raise ValueError("Expected Bear, Base, Bull in order.")
    for model in multiples:
        values = [row[f"{model}_value"] for row in rows]
        if min(values) <= 0 or values != sorted(values):
            raise ValueError(f"{model.upper()} scenario values must be positive and ordered.")

    return {
        "valuation_date": cutoff,
        "close": close,
        "engine_eps": eps,
        "basic_eps_recalculated": basic_eps,
        "bps": bps,
        "market_cap": close * actual["issued_shares"] if close else None,
        "market_per_on_fy2025": close / eps if close else None,
        "market_pbr_on_fy2025": close / bps if close else None,
        "target_multiples": multiples,
        "scenarios": rows,
    }


def verify(data, result):
    no_price = calculate({**data, "price": None})
    for key in ("market_cap", "market_per_on_fy2025", "market_pbr_on_fy2025"):
        if no_price[key] is not None:
            raise ValueError("Market metrics must be unavailable without a close.")
    for with_price, without_price in zip(result["scenarios"], no_price["scenarios"], strict=True):
        for model in ("per", "pbr"):
            if with_price[f"{model}_value"] != without_price[f"{model}_value"]:
                raise ValueError("Scenario valuation unexpectedly depends on the close.")
            if without_price[f"{model}_gap_pct"] is not None:
                raise ValueError("Gaps must be unavailable without a close.")
    if Decimal(str(result["engine_eps"])).quantize(Decimal("0.01")) != Decimal("29161.38"):
        raise ValueError("Engine EPS does not match the stored run.")

    late_forecast = {**data["forecast"], "published": data["valuation_date"]}
    try:
        calculate({**data, "forecast": late_forecast})
    except ValueError as error:
        if "must predate" not in str(error):
            raise
    else:
        raise ValueError("Forecast without a verifiable intraday timestamp was accepted.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = calculate(data)
    verify(data, result)
    print(json.dumps({"checks": "pass", **result}, indent=2))


if __name__ == "__main__":
    main()
