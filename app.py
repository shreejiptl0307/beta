"""
Flask Server, Agent State Machine Orchestrator, SQLite Audit, and Telegram Dispatcher
for Indian Stock Multi-Agent Analysis Dashboard.
"""

import os
import sys
import json
import time
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests
from flask import Flask, render_template, request, jsonify

from data_sources import (
    load_demo_evidence,
    fetch_and_screen_live_universe,
    load_universe
)
from scoring import evaluate_deterministic
from llm import evaluate_with_llm_or_fallback, detect_provider

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app")

# Basic lightweight .env loader
def load_env_file(filepath: str) -> None:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, ".env"))

# Application Configuration
BRAND = os.environ.get("BRAND", "Antigravity Alpha")
CONFIDENCE_THRESHOLD = int(os.environ.get("CONFIDENCE_THRESHOLD", "7"))
SHORTLIST_PER_BUCKET = int(os.environ.get("SHORTLIST_PER_BUCKET", "0"))
SEND_DAILY_SUMMARY = os.environ.get("SEND_DAILY_SUMMARY", "false").lower() == "true"
AGENT_DELAY = float(os.environ.get("AGENT_DELAY", "0.2"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
LLM_PROVIDER_CONF = os.environ.get("LLM_PROVIDER", "auto")
PORT = int(os.environ.get("PORT", "5050"))
HOST = os.environ.get("HOST", "127.0.0.1")

DB_PATH = os.path.join(BASE_DIR, "audit.db")

# Initialize SQLite
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            mode TEXT,
            engine TEXT,
            scanned_count INTEGER,
            shortlisted_count INTEGER,
            buys_count INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verdicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            symbol TEXT,
            name TEXT,
            cap_segment TEXT,
            verdict TEXT,
            confidence INTEGER,
            winner TEXT,
            live_price REAL,
            day_change_pct REAL,
            rationale TEXT,
            key_catalyst TEXT,
            telegram_sent INTEGER,
            created_at TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# Global In-Memory Dashboard State
dashboard_state = {
    "is_running": False,
    "active_step": None,
    "completed_at": None,
    "kpi": {
        "universe": 0,
        "in_debate": 0,
        "buy_signals": 0,
        "top_pick": "—",
        "top_pick_conf": 0
    },
    "agents": {
        "scout": {"status": "offline", "stat1": 0, "stat2": 0},
        "technician": {"status": "offline", "stat1": 0, "stat2": "0.0x"},
        "fundamentalist": {"status": "offline", "stat1": 0, "stat2": "0.0%"},
        "newsdesk": {"status": "offline", "stat1": 0, "stat2": "Neutral"},
        "bull": {"status": "offline", "stat1": 0, "stat2": 0},
        "bear": {"status": "offline", "stat1": 0, "stat2": 0},
        "judge": {"status": "offline", "stat1": 0, "stat2": 0},
        "messenger": {"status": "offline", "stat1": 0, "stat2": "Ready"}
    },
    "verdicts": [],
    "footer": {
        "stocks_count": 0,
        "timestamp": "—",
        "engine": "auto"
    }
}

state_lock = threading.Lock()


def scrub_token(text: str) -> str:
    """Scrubs Telegram bot token from any logs or messages."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN in text:
        return text.replace(TELEGRAM_BOT_TOKEN, "[SCRUBBED_BOT_TOKEN]")
    return text


def send_telegram_message(text: str) -> bool:
    """Dispatches message to Telegram Bot API with HTML formatting."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info(f"[Telegram Simulator - No Token Configured]\n{scrub_token(text)}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram message sent successfully.")
            return True
        else:
            logger.warning(f"Telegram API response: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False


def run_pipeline(mode: str = "demo"):
    """Background execution loop for multi-agent analysis."""
    global dashboard_state
    detected_engine = detect_provider(LLM_PROVIDER_CONF if LLM_PROVIDER_CONF != "auto" else None)

    with state_lock:
        dashboard_state["is_running"] = True
        dashboard_state["active_step"] = "scout"
        dashboard_state["verdicts"] = []
        dashboard_state["kpi"] = {
            "universe": 0,
            "in_debate": 0,
            "buy_signals": 0,
            "top_pick": "—",
            "top_pick_conf": 0
        }
        for ag in dashboard_state["agents"]:
            dashboard_state["agents"][ag]["status"] = "offline"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dashboard_state["footer"]["timestamp"] = now_str
        dashboard_state["footer"]["engine"] = detected_engine

    try:
        # Step 1: Scout Agent
        with state_lock:
            dashboard_state["active_step"] = "scout"
            dashboard_state["agents"]["scout"]["status"] = "working"

        evidence_bundles = []
        total_scanned = 0

        if mode == "live":
            evidence_bundles, total_scanned = fetch_and_screen_live_universe(
                BASE_DIR,
                shortlist_per_bucket=SHORTLIST_PER_BUCKET
            )
        else:
            time.sleep(AGENT_DELAY)
            evidence_bundles = load_demo_evidence(BASE_DIR)
            universe = load_universe(BASE_DIR)
            total_scanned = sum(len(stocks) for stocks in universe.values())

        with state_lock:
            dashboard_state["agents"]["scout"]["status"] = "done"
            dashboard_state["agents"]["scout"]["stat1"] = total_scanned
            dashboard_state["agents"]["scout"]["stat2"] = len(evidence_bundles)
            dashboard_state["kpi"]["universe"] = total_scanned
            dashboard_state["kpi"]["in_debate"] = len(evidence_bundles)
            dashboard_state["footer"]["stocks_count"] = total_scanned

        time.sleep(AGENT_DELAY)

        # Step 2: Technician
        with state_lock:
            dashboard_state["active_step"] = "technician"
            dashboard_state["agents"]["technician"]["status"] = "working"
        
        time.sleep(AGENT_DELAY)
        rvols = [b.get("technicals", {}).get("rvol") or 1.0 for b in evidence_bundles]
        avg_rvol = round(sum(rvols) / max(len(rvols), 1), 2)
        with state_lock:
            dashboard_state["agents"]["technician"]["status"] = "done"
            dashboard_state["agents"]["technician"]["stat1"] = len(evidence_bundles)
            dashboard_state["agents"]["technician"]["stat2"] = f"{avg_rvol}x"

        time.sleep(AGENT_DELAY)

        # Step 3: Fundamentalist
        with state_lock:
            dashboard_state["active_step"] = "fundamentalist"
            dashboard_state["agents"]["fundamentalist"]["status"] = "working"

        time.sleep(AGENT_DELAY)
        upsides = [b.get("analyst", {}).get("upside_pct") or 0.0 for b in evidence_bundles]
        avg_upside = round(sum(upsides) / max(len(upsides), 1), 1)
        with state_lock:
            dashboard_state["agents"]["fundamentalist"]["status"] = "done"
            dashboard_state["agents"]["fundamentalist"]["stat1"] = len(evidence_bundles)
            dashboard_state["agents"]["fundamentalist"]["stat2"] = f"{avg_upside:+0.1f}%"

        time.sleep(AGENT_DELAY)

        # Step 4: Newsdesk
        with state_lock:
            dashboard_state["active_step"] = "newsdesk"
            dashboard_state["agents"]["newsdesk"]["status"] = "working"

        time.sleep(AGENT_DELAY)
        total_headlines = sum(b.get("news", {}).get("total", 0) for b in evidence_bundles)
        net_pos = sum(b.get("news", {}).get("positive", 0) for b in evidence_bundles)
        net_neg = sum(b.get("news", {}).get("negative", 0) for b in evidence_bundles)
        net_tone = "Bullish" if net_pos > net_neg else ("Bearish" if net_neg > net_pos else "Neutral")

        with state_lock:
            dashboard_state["agents"]["newsdesk"]["status"] = "done"
            dashboard_state["agents"]["newsdesk"]["stat1"] = total_headlines
            dashboard_state["agents"]["newsdesk"]["stat2"] = net_tone

        time.sleep(AGENT_DELAY)

        # Step 5 & 6: Bull, Bear, and Judge Debate
        with state_lock:
            dashboard_state["active_step"] = "debate"
            dashboard_state["agents"]["bull"]["status"] = "working"
            dashboard_state["agents"]["bear"]["status"] = "working"
            dashboard_state["agents"]["judge"]["status"] = "working"

        evaluated_verdicts = []
        bull_scores = []
        bear_scores = []
        buy_count = 0
        top_pick_sym = "—"
        top_pick_conf = 0

        engine_used = detected_engine

        for evidence in evidence_bundles:
            sym = evidence.get("symbol", "UNKNOWN")
            eval_res, engine_name = evaluate_with_llm_or_fallback(evidence, forced_provider=LLM_PROVIDER_CONF if LLM_PROVIDER_CONF != "auto" else None)
            engine_used = engine_name

            v_info = eval_res.get("verdict", {})
            scores_info = eval_res.get("scores", {})

            b_score = scores_info.get("bull", {}).get("score", 50)
            be_score = scores_info.get("bear", {}).get("score", 50)
            bull_scores.append(b_score)
            bear_scores.append(be_score)

            verdict_str = v_info.get("verdict", "WATCH")
            conf_val = v_info.get("confidence", 5)
            if verdict_str == "BUY":
                buy_count += 1
                if conf_val > top_pick_conf:
                    top_pick_conf = conf_val
                    top_pick_sym = f"{sym.replace('.NS', '')} ({conf_val}/10)"

            row = {
                "symbol": sym,
                "name": evidence.get("name", sym),
                "cap_segment": evidence.get("cap_segment", ""),
                "verdict": verdict_str,
                "confidence": conf_val,
                "winner": v_info.get("winner", "Bull"),
                "rationale": v_info.get("rationale", ""),
                "key_catalyst": v_info.get("key_catalyst", ""),
                "live_price": evidence.get("price", {}).get("live"),
                "day_change_pct": evidence.get("price", {}).get("day_change_pct"),
                "bull_score": b_score,
                "bear_score": be_score
            }
            evaluated_verdicts.append(row)

            # Live update verdicts table incrementally
            with state_lock:
                dashboard_state["verdicts"] = list(evaluated_verdicts)
                dashboard_state["kpi"]["buy_signals"] = buy_count
                dashboard_state["kpi"]["top_pick"] = top_pick_sym
                dashboard_state["kpi"]["top_pick_conf"] = top_pick_conf
                dashboard_state["agents"]["judge"]["stat1"] = len(evaluated_verdicts)
                dashboard_state["agents"]["judge"]["stat2"] = buy_count

            time.sleep(0.05)

        avg_bull = round(sum(bull_scores) / max(len(bull_scores), 1), 1)
        avg_bear = round(sum(bear_scores) / max(len(bear_scores), 1), 1)

        with state_lock:
            dashboard_state["agents"]["bull"]["status"] = "done"
            dashboard_state["agents"]["bull"]["stat1"] = len(evaluated_verdicts)
            dashboard_state["agents"]["bull"]["stat2"] = avg_bull

            dashboard_state["agents"]["bear"]["status"] = "done"
            dashboard_state["agents"]["bear"]["stat1"] = len(evaluated_verdicts)
            dashboard_state["agents"]["bear"]["stat2"] = avg_bear

            dashboard_state["agents"]["judge"]["status"] = "done"
            dashboard_state["footer"]["engine"] = engine_used

        time.sleep(AGENT_DELAY)

        # Step 7: Messenger & Telegram Alerts (Only dispatch confirmed BUY signals)
        with state_lock:
            dashboard_state["active_step"] = "messenger"
            dashboard_state["agents"]["messenger"]["status"] = "working"

        fired_buys = []
        for v in evaluated_verdicts:
            if v["verdict"] == "BUY" and v["confidence"] >= CONFIDENCE_THRESHOLD:
                fired_buys.append(v)
                cap_clean = v["cap_segment"].replace(" Cap", "") if v["cap_segment"] else "Large"
                price_str = f"₹{v['live_price']:,.2f}" if v["live_price"] is not None else "₹—"
                change_str = f"{v['day_change_pct']:+0.2f}%" if v["day_change_pct"] is not None else "0.00%"

                msg = (
                    f"🟢 <b>BUY SIGNAL — {v['symbol']}</b> ({cap_clean} cap)\n\n"
                    f"<b>Verdict:</b> BUY | <b>Confidence:</b> {v['confidence']}/10\n"
                    f"<b>Winner:</b> {v['winner']}\n\n"
                    f"<b>Why:</b> {v['rationale']}\n\n"
                    f"<b>Key catalyst:</b> {v['key_catalyst']}\n\n"
                    f"<b>Live price:</b> {price_str} | <b>Day change:</b> {change_str}\n\n"
                    f"<i>— Analysis only. No trade was placed. Not investment advice.</i>"
                )
                send_telegram_message(msg)
                time.sleep(0.4)

        # Optional Daily Summary (only if SEND_DAILY_SUMMARY is true)
        if SEND_DAILY_SUMMARY:
            summary_lines = [
                f"📊 <b>DAILY ANALYSIS SUMMARY — {BRAND}</b>",
                f"<b>Engine:</b> {engine_used} | <b>Timestamp:</b> {now_str} IST",
                f"<b>Scanned:</b> {total_scanned} | <b>In Debate:</b> {len(evaluated_verdicts)} | <b>Buy Signals:</b> {len(fired_buys)}\n"
            ]
            if fired_buys:
                summary_lines.append("<b>Fired BUY Signals:</b>")
                for fb in fired_buys:
                    summary_lines.append(f"• <b>{fb['symbol']}</b> (Conf: {fb['confidence']}/10, Price: ₹{fb['live_price']})")
            else:
                summary_lines.append("<i>No BUY signals fired above confidence threshold.</i>")
            summary_lines.append("\n<i>— Analysis only. No trade was placed. Not investment advice.</i>")
            send_telegram_message("\n".join(summary_lines))

        with state_lock:
            dashboard_state["agents"]["messenger"]["status"] = "done"
            dashboard_state["agents"]["messenger"]["stat1"] = len(fired_buys)
            dashboard_state["agents"]["messenger"]["stat2"] = engine_used

        # Record to SQLite Audit
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO runs (timestamp, mode, engine, scanned_count, shortlisted_count, buys_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now_str, mode, engine_used, total_scanned, len(evaluated_verdicts), len(fired_buys)))
            run_id = cur.lastrowid

            for v in evaluated_verdicts:
                cur.execute("""
                    INSERT INTO verdicts (
                        run_id, symbol, name, cap_segment, verdict, confidence,
                        winner, live_price, day_change_pct, rationale, key_catalyst,
                        telegram_sent, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, v["symbol"], v["name"], v["cap_segment"], v["verdict"],
                    v["confidence"], v["winner"], v["live_price"], v["day_change_pct"],
                    v["rationale"], v["key_catalyst"],
                    1 if (v["verdict"] == "BUY" and v["confidence"] >= CONFIDENCE_THRESHOLD) else 0,
                    now_str
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"SQLite audit write failed: {e}")

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
    finally:
        with state_lock:
            dashboard_state["is_running"] = False
            dashboard_state["active_step"] = None
            dashboard_state["completed_at"] = datetime.now().strftime("%H:%M:%S")


@app.route("/")
def index():
    detected_engine = detect_provider(LLM_PROVIDER_CONF if LLM_PROVIDER_CONF != "auto" else None)
    return render_template(
        "dashboard.html",
        brand=BRAND,
        engine_badge=detected_engine
    )


@app.route("/start", methods=["POST"])
def start_cycle():
    global dashboard_state
    with state_lock:
        if dashboard_state["is_running"]:
            return jsonify({"error": "A cycle is already running"}), 400

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "demo")

    th = threading.Thread(target=run_pipeline, args=(mode,), daemon=True)
    th.start()
    return jsonify({"status": "started", "mode": mode})


@app.route("/status")
def status():
    with state_lock:
        return jsonify(dashboard_state)


@app.route("/config")
def config():
    detected_engine = detect_provider(LLM_PROVIDER_CONF if LLM_PROVIDER_CONF != "auto" else None)
    return jsonify({
        "brand": BRAND,
        "engine": detected_engine,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "shortlist_per_bucket": SHORTLIST_PER_BUCKET,
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    })


if __name__ == "__main__":
    logger.info(f"Starting {BRAND} dashboard on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
