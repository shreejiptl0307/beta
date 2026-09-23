"""
Data layer for Indian stock multi-agent analysis.
Supports two modes:
1. 'demo': loads pre-built evidence bundles from demo_data/*.json
2. 'live': fetches live NSE data via yfinance using tickers from universe.json,
   analyzes all stocks concurrently or screens top movers, and builds normalized evidence bundles.
"""

import os
import json
import glob
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

POSITIVE_KEYWORDS = {
    "surge", "surges", "jump", "jumps", "gain", "gains", "rally", "rallies",
    "profit", "growth", "high", "record", "upgrade", "outperform", "beat",
    "expansion", "order", "orders", "contract", "bullish", "soar", "soars",
    "dividend", "acquisition", "strong", "positive", "breakout", "rebound"
}

NEGATIVE_KEYWORDS = {
    "fall", "falls", "drop", "drops", "slump", "slumps", "decline", "declines",
    "loss", "plunge", "plunges", "downgrade", "underperform", "miss", "weak",
    "crash", "cut", "cuts", "probe", "investigation", "penalty", "default",
    "bearish", "selloff", "headwind", "pressure", "warning", "concern"
}


def score_headline_sentiment(title: str) -> str:
    """Classifies headline string into 'positive', 'negative', or 'neutral'."""
    if not title:
        return "neutral"
    words = set(title.lower().replace("-", " ").replace(".", " ").replace(",", " ").split())
    pos_matches = len(words & POSITIVE_KEYWORDS)
    neg_matches = len(words & NEGATIVE_KEYWORDS)
    if pos_matches > neg_matches:
        return "positive"
    elif neg_matches > pos_matches:
        return "negative"
    return "neutral"


def load_universe(base_dir: str) -> Dict[str, List[Dict[str, str]]]:
    """Loads universe.json from base directory."""
    universe_path = os.path.join(base_dir, "universe.json")
    if os.path.exists(universe_path):
        with open(universe_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "large_cap": [{"symbol": "RELIANCE.NS", "name": "Reliance Industries", "sector": "Energy"}],
        "mid_cap": [{"symbol": "TRENT.NS", "name": "Trent Ltd", "sector": "Consumer Cyclical"}],
        "small_cap": [{"symbol": "SUZLON.NS", "name": "Suzlon Energy", "sector": "Industrials"}]
    }


def load_demo_evidence(base_dir: str) -> List[Dict[str, Any]]:
    """Loads all demo evidence bundles from demo_data/*.json."""
    demo_dir = os.path.join(base_dir, "demo_data")
    evidence_list = []
    if os.path.exists(demo_dir):
        files = sorted(glob.glob(os.path.join(demo_dir, "*.json")))
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    evidence_list.append(data)
            except Exception as e:
                logger.error(f"Failed to load demo file {file_path}: {e}")
    return evidence_list


def build_evidence_bundle(
    symbol: str,
    name: str,
    cap_segment: str,
    sector: str,
    hist_df: Any,
    info: Dict[str, Any],
    news_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Constructs a normalized evidence bundle from yfinance data.
    Ensures missing values are null and tracked in data_gaps.
    """
    data_gaps = []

    # 1. Price metrics
    price_live = None
    day_open = None
    day_high = None
    day_low = None
    prev_close = None
    day_change_pct = None
    volume = None

    if hist_df is not None and not hist_df.empty:
        latest = hist_df.iloc[-1]
        price_live = float(latest.get("Close", 0)) or info.get("currentPrice") or info.get("regularMarketPrice")
        day_open = float(latest.get("Open", 0)) or info.get("open") or info.get("regularMarketOpen")
        day_high = float(latest.get("High", 0)) or info.get("dayHigh") or info.get("regularMarketDayHigh")
        day_low = float(latest.get("Low", 0)) or info.get("dayLow") or info.get("regularMarketDayLow")
        volume = int(latest.get("Volume", 0)) or info.get("volume") or info.get("regularMarketVolume")

        if len(hist_df) > 1:
            prev_row = hist_df.iloc[-2]
            prev_close = float(prev_row.get("Close", 0)) or info.get("previousClose") or info.get("regularMarketPreviousClose")
        else:
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    else:
        price_live = info.get("currentPrice") or info.get("regularMarketPrice")
        day_open = info.get("open") or info.get("regularMarketOpen")
        day_high = info.get("dayHigh") or info.get("regularMarketDayHigh")
        day_low = info.get("dayLow") or info.get("regularMarketDayLow")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        volume = info.get("volume") or info.get("regularMarketVolume")

    if price_live is not None and prev_close is not None and prev_close > 0:
        day_change_pct = round(((price_live - prev_close) / prev_close) * 100.0, 2)
    elif info.get("regularMarketChangePercent") is not None:
        day_change_pct = round(float(info.get("regularMarketChangePercent")), 2)

    price_data = {
        "live": round(price_live, 2) if price_live is not None else None,
        "day_open": round(day_open, 2) if day_open is not None else None,
        "day_high": round(day_high, 2) if day_high is not None else None,
        "day_low": round(day_low, 2) if day_low is not None else None,
        "prev_close": round(prev_close, 2) if prev_close is not None else None,
        "day_change_pct": day_change_pct,
        "volume": volume
    }
    for k, v in price_data.items():
        if v is None:
            data_gaps.append(f"price.{k}")

    # 2. 52-Week Range
    high_52 = info.get("fiftyTwoWeekHigh")
    low_52 = info.get("fiftyTwoWeekLow")
    pct_from_high = None
    position_pct = None

    if high_52 is not None and price_live is not None and high_52 > 0:
        pct_from_high = round(((price_live - high_52) / high_52) * 100.0, 2)
    if high_52 is not None and low_52 is not None and price_live is not None and high_52 > low_52:
        position_pct = round(((price_live - low_52) / (high_52 - low_52)) * 100.0, 2)

    range_52w = {
        "high": round(high_52, 2) if high_52 is not None else None,
        "low": round(low_52, 2) if low_52 is not None else None,
        "pct_from_high": pct_from_high,
        "position_pct": position_pct
    }
    for k, v in range_52w.items():
        if v is None:
            data_gaps.append(f"range_52w.{k}")

    # 3. Technicals (RVOL, SMA, return, trend)
    rvol = None
    price_vs_sma_pct = None
    window_return_pct = None
    swing_high = None
    swing_low = None
    day_range_position_pct = None
    trend = "sideways"

    if hist_df is not None and len(hist_df) >= 5:
        closes = hist_df["Close"]
        volumes = hist_df["Volume"]
        highs = hist_df["High"]
        lows = hist_df["Low"]

        # RVOL: today's volume / avg prior daily volume (past 20 days or available)
        prior_vols = volumes.iloc[:-1]
        if len(prior_vols) > 0:
            avg_prior_vol = prior_vols.mean()
            current_vol = volumes.iloc[-1]
            if avg_prior_vol > 0:
                rvol = round(float(current_vol / avg_prior_vol), 2)

        # 20-day SMA
        sma_len = min(20, len(closes))
        sma_val = closes.iloc[-sma_len:].mean()
        if sma_val > 0 and price_live is not None:
            price_vs_sma_pct = round(((price_live - sma_val) / sma_val) * 100.0, 2)

        # Window return
        start_close = closes.iloc[0]
        if start_close > 0 and price_live is not None:
            window_return_pct = round(((price_live - start_close) / start_close) * 100.0, 2)

        swing_high = round(float(highs.max()), 2)
        swing_low = round(float(lows.min()), 2)

        # Trend detection
        if price_vs_sma_pct is not None:
            if price_vs_sma_pct > 2.0 and (window_return_pct is None or window_return_pct > 0):
                trend = "up"
            elif price_vs_sma_pct < -2.0 and (window_return_pct is None or window_return_pct < 0):
                trend = "down"
            else:
                trend = "sideways"

    if day_high is not None and day_low is not None and price_live is not None and day_high > day_low:
        day_range_position_pct = round(((price_live - day_low) / (day_high - day_low)) * 100.0, 2)

    technicals = {
        "rvol": rvol if rvol is not None else 1.0,
        "price_vs_sma_pct": price_vs_sma_pct,
        "window_return_pct": window_return_pct,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "day_range_position_pct": day_range_position_pct,
        "trend": trend
    }
    for k, v in technicals.items():
        if v is None:
            data_gaps.append(f"technicals.{k}")

    # 4. Analyst ratings & upside
    target_mean = info.get("targetMeanPrice")
    target_low = info.get("targetLowPrice")
    target_high = info.get("targetHighPrice")
    consensus = info.get("recommendationKey", "none").replace("_", " ").title()
    num_analysts = info.get("numberOfAnalystOpinions") or 0

    upside_pct = None
    if target_mean is not None and price_live is not None and price_live > 0:
        upside_pct = round(((target_mean - price_live) / price_live) * 100.0, 2)

    buy_pct = 50.0
    hold_pct = 30.0
    sell_pct = 20.0
    if "Strong Buy" in consensus or consensus.lower() == "strongbuy":
        buy_pct, hold_pct, sell_pct = 85.0, 10.0, 5.0
    elif "Buy" in consensus:
        buy_pct, hold_pct, sell_pct = 75.0, 18.0, 7.0
    elif "Hold" in consensus:
        buy_pct, hold_pct, sell_pct = 40.0, 45.0, 15.0
    elif "Sell" in consensus or "Underperform" in consensus:
        buy_pct, hold_pct, sell_pct = 15.0, 30.0, 55.0

    analyst = {
        "consensus": consensus,
        "num_analysts": num_analysts,
        "buy_pct": buy_pct,
        "hold_pct": hold_pct,
        "sell_pct": sell_pct,
        "target_mean": round(target_mean, 2) if target_mean is not None else None,
        "target_low": round(target_low, 2) if target_low is not None else None,
        "target_high": round(target_high, 2) if target_high is not None else None,
        "upside_pct": upside_pct
    }
    for k, v in analyst.items():
        if v is None:
            data_gaps.append(f"analyst.{k}")

    # 5. News sentiment
    recent_news = []
    pos_count = 0
    neg_count = 0
    neutral_count = 0

    if news_items:
        for item in news_items[:6]:
            title = item.get("title", "")
            publisher = item.get("publisher", "Financial Media")
            pub_time = item.get("providerPublishTime", "")
            sentiment = score_headline_sentiment(title)

            if sentiment == "positive":
                pos_count += 1
            elif sentiment == "negative":
                neg_count += 1
            else:
                neutral_count += 1

            recent_news.append({
                "title": title,
                "publisher": publisher,
                "date": str(pub_time),
                "sentiment": sentiment
            })

    news_data = {
        "total": len(recent_news),
        "positive": pos_count,
        "negative": neg_count,
        "neutral": neutral_count,
        "recent": recent_news
    }

    return {
        "symbol": symbol,
        "name": name or info.get("shortName") or symbol,
        "cap_segment": cap_segment,
        "sector": sector or info.get("sector") or "General",
        "price": price_data,
        "range_52w": range_52w,
        "technicals": technicals,
        "analyst": analyst,
        "news": news_data,
        "data_gaps": data_gaps
    }


def fetch_single_stock_safe(stock_info: Dict[str, str], cap_label: str) -> Optional[Dict[str, Any]]:
    """Worker function for concurrent thread execution."""
    sym = stock_info["symbol"]
    name = stock_info.get("name", sym)
    sector = stock_info.get("sector", "General")
    return fetch_live_stock_data(sym, name, cap_label, sector)


def fetch_live_stock_data(symbol: str, name: str, cap_segment: str, sector: str) -> Optional[Dict[str, Any]]:
    """Fetches yfinance data for a single ticker and builds the evidence bundle."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            info = {}
        news = []
        try:
            news = ticker.news or []
        except Exception:
            news = []

        return build_evidence_bundle(
            symbol=symbol,
            name=name,
            cap_segment=cap_segment,
            sector=sector,
            hist_df=hist,
            info=info,
            news_items=news
        )
    except Exception as e:
        logger.error(f"Error fetching live data for {symbol}: {e}")
        return None


def fetch_and_screen_live_universe(
    base_dir: str,
    shortlist_per_bucket: int = 0,
    progress_callback: Optional[Any] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Screens the live universe grouped by large/mid/small cap concurrently.
    If shortlist_per_bucket <= 0, ALL valid stocks in the universe are analyzed.
    Otherwise keeps top shortlist_per_bucket per category.
    Returns (shortlisted_evidence_bundles, total_scanned_count).
    """
    universe = load_universe(base_dir)
    all_evidence: List[Dict[str, Any]] = []
    
    stock_tasks = []
    bucket_names = [
        ("large_cap", "Large Cap"),
        ("mid_cap", "Mid Cap"),
        ("small_cap", "Small Cap")
    ]

    for key, cap_label in bucket_names:
        stocks = universe.get(key, [])
        for stock_info in stocks:
            stock_tasks.append((stock_info, cap_label, key))

    total_scanned = len(stock_tasks)
    bucket_results = {"large_cap": [], "mid_cap": [], "small_cap": []}

    # Parallel multi-threaded fetch using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_stock = {
            executor.submit(fetch_single_stock_safe, s_info, c_label): (s_info, b_key)
            for (s_info, c_label, b_key) in stock_tasks
        }

        completed_count = 0
        for future in as_completed(future_to_stock):
            completed_count += 1
            s_info, b_key = future_to_stock[future]
            try:
                bundle = future.result()
                if bundle:
                    bucket_results[b_key].append(bundle)
            except Exception as e:
                logger.error(f"Failed to fetch {s_info.get('symbol')}: {e}")

            if progress_callback:
                progress_callback("scout", f"Scanned {completed_count}/{total_scanned}", scanned=completed_count)

    # Sort each bucket by momentum / day change
    for key, cap_label in bucket_names:
        items = bucket_results.get(key, [])
        items.sort(
            key=lambda x: (x.get("price", {}).get("day_change_pct") or 0.0),
            reverse=True
        )
        if shortlist_per_bucket > 0:
            all_evidence.extend(items[:shortlist_per_bucket])
        else:
            all_evidence.extend(items)

    return all_evidence, total_scanned
