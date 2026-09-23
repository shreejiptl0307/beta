"""
Deterministic scoring engine & Grounding Verifier for Indian stock analysis.
Implements rule-based evaluation for Bull, Bear, Technicals, Fundamentals, Newsdesk, and Judge.
Includes Grounding Verifier ensuring all cited numbers trace back to the evidence bundle.
"""

import re
from typing import Dict, Any, List, Tuple


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(val, high))


def verify_grounding(text: str, evidence: Dict[str, Any]) -> List[str]:
    """
    Extracts numbers from generated text and verifies they trace back
    to numbers present in the evidence bundle. Returns list of untraceable numbers.
    """
    if not text:
        return []

    # Find all float/integer numbers in text
    extracted_nums = re.findall(r"[-+]?\d*\.?\d+", text)
    
    # Collect all numeric values present in the evidence dictionary
    evidence_nums = set()

    def collect_nums(obj):
        if isinstance(obj, (int, float)):
            evidence_nums.add(round(float(obj), 2))
            evidence_nums.add(round(float(obj), 1))
            evidence_nums.add(int(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                collect_nums(v)
        elif isinstance(obj, list):
            for item in obj:
                collect_nums(item)

    collect_nums(evidence)

    untraceable = []
    for num_str in extracted_nums:
        # Ignore trivial integers like 1, 2, 10 (ratings/scale denominators)
        try:
            val = float(num_str)
            if val in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 100.0, 0.0):
                continue
            # Check rounded match
            r2 = round(val, 2)
            r1 = round(val, 1)
            rint = int(val)
            if r2 not in evidence_nums and r1 not in evidence_nums and rint not in evidence_nums:
                untraceable.append(num_str)
        except ValueError:
            continue

    return untraceable


def evaluate_deterministic(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates an evidence bundle deterministically based on market indicators.
    Returns agent scores, rationale points, and Judge verdict.
    """
    price = evidence.get("price", {})
    range_52 = evidence.get("range_52w", {})
    tech = evidence.get("technicals", {})
    analyst = evidence.get("analyst", {})
    news = evidence.get("news", {})

    live_price = price.get("live") or 0.0
    day_change = price.get("day_change_pct") or 0.0
    rvol = tech.get("rvol") or 1.0
    pos_52 = range_52.get("position_pct") or 50.0
    pct_from_high = range_52.get("pct_from_high") or -10.0
    trend = tech.get("trend") or "sideways"
    price_vs_sma = tech.get("price_vs_sma_pct") or 0.0
    day_close_pos = tech.get("day_range_position_pct") or 50.0
    window_return = tech.get("window_return_pct") or 0.0
    upside_pct = analyst.get("upside_pct") if analyst.get("upside_pct") is not None else 0.0
    buy_pct = analyst.get("buy_pct") or 50.0
    sell_pct = analyst.get("sell_pct") or 10.0
    news_pos = news.get("positive", 0)
    news_neg = news.get("negative", 0)

    # --- 1. Bull Scoring ---
    bull_score = 30.0  # base
    bull_reasons = []

    if rvol >= 3.0:
        bull_score += 15.0
        bull_reasons.append(f"Exceptional volume surge ({rvol}x RVOL)")
    elif rvol >= 1.8:
        bull_score += 10.0
        bull_reasons.append(f"Healthy volume expansion ({rvol}x RVOL)")

    if pos_52 >= 85.0:
        bull_score += 15.0
        bull_reasons.append(f"Near 52-week high breakout zone ({pos_52}%)")
    elif pos_52 >= 70.0:
        bull_score += 10.0
        bull_reasons.append(f"Upper quartile of 52w range ({pos_52}%)")

    if trend == "up" and price_vs_sma > 0:
        bull_score += 15.0
        bull_reasons.append(f"Strong uptrend above SMA (+{price_vs_sma}%)")

    if day_close_pos >= 75.0:
        bull_score += 10.0
        bull_reasons.append(f"Strong session closing near highs ({day_close_pos}%)")

    if upside_pct >= 10.0:
        bull_score += 15.0
        bull_reasons.append(f"High analyst target upside (+{upside_pct}%)")
    elif upside_pct >= 5.0:
        bull_score += 8.0
        bull_reasons.append(f"Positive analyst upside (+{upside_pct}%)")

    if buy_pct >= 80.0:
        bull_score += 10.0
        bull_reasons.append(f"Consensus supermajority ({buy_pct}% Buy ratings)")

    if news_pos > news_neg:
        bull_score += 10.0
        bull_reasons.append(f"Positive newsflow catalysts ({news_pos} headlines)")

    if window_return > 5.0:
        bull_score += 10.0
        bull_reasons.append(f"Solid monthly momentum (+{window_return}%)")

    bull_score = clamp(bull_score, 5.0, 98.0)
    if not bull_reasons:
        bull_reasons.append("Holding key support levels with steady volume.")

    # --- 2. Bear Scoring ---
    bear_score = 30.0  # base
    bear_reasons = []

    if rvol < 1.0:
        bear_score += 10.0
        bear_reasons.append(f"Subdued trading volume ({rvol}x RVOL)")

    if pos_52 < 30.0:
        bear_score += 20.0
        bear_reasons.append(f"Languishing near 52-week lows ({pos_52}%)")
    elif pos_52 < 50.0:
        bear_score += 10.0
        bear_reasons.append(f"Below mid-point of 52-week channel ({pos_52}%)")

    if trend == "down" or price_vs_sma < -2.0:
        bear_score += 20.0
        bear_reasons.append(f"Bearish trend below SMA ({price_vs_sma}%)")

    if upside_pct <= 0.0:
        bear_score += 15.0
        bear_reasons.append(f"No analyst price headroom ({upside_pct}% upside)")

    if buy_pct < 55.0:
        bear_score += 10.0
        bear_reasons.append(f"Low institutional buy conviction ({buy_pct}%)")

    if pct_from_high <= -20.0:
        bear_score += 15.0
        bear_reasons.append(f"Steep drawdown from 52w peak ({pct_from_high}%)")

    if sell_pct >= 15.0:
        bear_score += 10.0
        bear_reasons.append(f"Elevated sell/underperform ratings ({sell_pct}%)")

    if news_neg > 0:
        bear_score += 12.0
        bear_reasons.append(f"Negative news headlines detected ({news_neg} items)")

    if day_close_pos < 30.0:
        bear_score += 10.0
        bear_reasons.append(f"Weak intraday finish near session lows ({day_close_pos}%)")

    bear_score = clamp(bear_score, 5.0, 98.0)
    if not bear_reasons:
        bear_reasons.append("Minimal immediate downside triggers identified.")

    # --- 3. Technician, Fundamentalist, Newsdesk Individual Scores ---
    tech_score = clamp(50.0 + (price_vs_sma * 2.5) + ((rvol - 1.0) * 15.0) + ((pos_52 - 50) * 0.4), 10.0, 95.0)
    fund_score = clamp(40.0 + (upside_pct * 1.8) + ((buy_pct - 50.0) * 0.6), 10.0, 95.0)
    news_score = 50.0
    if news_pos > 0 or news_neg > 0:
        news_score = clamp(50.0 + ((news_pos - news_neg) * 18.0), 15.0, 95.0)

    # --- 4. Judge Verdict Logic ---
    net = round(bull_score - bear_score, 1)
    has_leadership = (pos_52 >= 60.0) or (rvol >= 3.0)

    if net >= 25.0 and has_leadership:
        verdict = "BUY"
        winner = "Bull"
    elif net <= -15.0:
        verdict = "AVOID"
        winner = "Bear"
    else:
        verdict = "WATCH"
        winner = "Bull" if net >= 0 else "Bear"

    # Confidence calculation: clamp(round(4 + net/15), 1, 10), forced >= 7 for BUY and <= 6 otherwise
    raw_confidence = int(clamp(round(4.0 + (net / 15.0)), 1, 10))
    if verdict == "BUY":
        confidence = max(7, min(raw_confidence, 10))
    else:
        confidence = min(6, max(raw_confidence, 1))

    # Construct concise rationale and catalyst
    if verdict == "BUY":
        key_catalyst = bull_reasons[0] if bull_reasons else "Strong breakout momentum and institutional upside"
        rationale = f"Strong bull leadership (Net +{net}). Supported by {bull_reasons[0].lower()}."
    elif verdict == "AVOID":
        key_catalyst = bear_reasons[0] if bear_reasons else "Persistent downtrend with negative risk-reward"
        rationale = f"Bear dominance (Net {net}). Weak momentum and {bear_reasons[0].lower()}."
    else:
        key_catalyst = bull_reasons[0] if bull_reasons else "Consolidation within channel"
        rationale = f"Balanced setup (Net {net:+0.1f}). Awaiting confirmation on volume and key technical levels."

    return {
        "scores": {
            "bull": {
                "score": round(bull_score, 1),
                "reasons": bull_reasons[:3]
            },
            "bear": {
                "score": round(bear_score, 1),
                "reasons": bear_reasons[:3]
            },
            "technician": {
                "score": round(tech_score, 1),
                "reasons": [f"RVOL at {rvol}x, price {price_vs_sma:+0.1f}% vs SMA ({trend} trend)"]
            },
            "fundamentalist": {
                "score": round(fund_score, 1),
                "reasons": [f"Analyst upside {upside_pct:+0.1f}%, consensus {analyst.get('consensus', 'Hold')} ({buy_pct}% buy)"]
            },
            "newsdesk": {
                "score": round(news_score, 1),
                "reasons": [f"{news_pos} positive vs {news_neg} negative headlines"]
            }
        },
        "verdict": {
            "winner": winner,
            "verdict": verdict,
            "confidence": confidence,
            "rationale": rationale,
            "key_catalyst": key_catalyst,
            "bull_score": round(bull_score, 1),
            "bear_score": round(bear_score, 1),
            "net": net
        }
    }
