"""
LLM Debate engine for Indian Stock Analysis.
Auto-detects provider in priority order:
1. claude_code CLI (via local subprocess - no API key needed, uses Claude subscription)
2. anthropic (via ANTHROPIC_API_KEY)
3. openai (via OPENAI_API_KEY)
4. deterministic (fallback when offline or no provider available)
"""

import os
import json
import shutil
import subprocess
import logging
from typing import Dict, Any, Optional, Tuple

import requests
from scoring import evaluate_deterministic, verify_grounding, clamp

logger = logging.getLogger(__name__)


def detect_provider(forced_provider: Optional[str] = None) -> str:
    """Detects available LLM provider based on configuration and environment."""
    if forced_provider and forced_provider.lower() in ("claude_code", "anthropic", "openai", "deterministic"):
        return forced_provider.lower()

    # 1. Check for claude CLI on PATH
    if shutil.which("claude"):
        return "claude_code"

    # 2. Check for Anthropic API Key
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    # 3. Check for OpenAI API Key
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    # 4. Fallback
    return "deterministic"


def build_debate_prompt(evidence: Dict[str, Any]) -> str:
    """Builds prompt for the 6-agent panel + Judge."""
    evidence_json = json.dumps(evidence, indent=2)
    return f"""You are an elite Indian equity investment panel analyzing a stock on the National Stock Exchange (NSE).
Evidence Bundle:
{evidence_json}

Your panel consists of:
1. Bull: argues why this stock should be bought now (catalysts, volume, breakouts).
2. Bear: argues the risks and reasons to avoid/wait (drawdowns, lack of volume, high valuation, risks).
3. Technician: reads price action, 52-week position, RVOL, and moving average trends.
4. Fundamentalist: weighs analyst consensus, target prices, and implied upside.
5. Newsdesk: weighs news headline sentiment and business developments.
6. Judge: weighs the arguments objectively.

Grounding Rule: Every number you cite MUST exist in the Evidence Bundle. Never invent numbers. If data is unavailable, state "data unavailable".

Decision Rules for Judge:
- BUY: favorable risk/reward confirmed with strong momentum or volume (confidence 7-10).
- WATCH: promising or consolidating setup, but unconfirmed (confidence 4-6).
- AVOID: downtrend, weak volume, negative risk/reward, or adverse news (confidence 1-6).

Respond ONLY with a valid JSON object strictly matching this schema:
{{
  "scores": {{
    "bull": {{
      "score": <number 0-100>,
      "reasons": ["<point 1, <=25 words>", "<point 2, <=25 words>"]
    }},
    "bear": {{
      "score": <number 0-100>,
      "reasons": ["<point 1, <=25 words>", "<point 2, <=25 words>"]
    }},
    "technician": {{
      "score": <number 0-100>,
      "reasons": ["<technical view, <=25 words>"]
    }},
    "fundamentalist": {{
      "score": <number 0-100>,
      "reasons": ["<fundamental view, <=25 words>"]
    }},
    "newsdesk": {{
      "score": <number 0-100>,
      "reasons": ["<news tone summary, <=25 words>"]
    }}
  }},
  "verdict": {{
    "winner": "Bull" | "Bear",
    "verdict": "BUY" | "WATCH" | "AVOID",
    "confidence": <integer 1-10>,
    "rationale": "<judge rationale, <=2 sentences>",
    "key_catalyst": "<single top driving reason>",
    "bull_score": <number 0-100>,
    "bear_score": <number 0-100>,
    "net": <number -100 to 100>
  }}
}}
"""


def extract_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extracts JSON object from a raw response string."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        # Try finding outermost { and }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                pass
    return None


def call_claude_code(prompt: str, model: str = "haiku") -> Dict[str, Any]:
    """Invokes local claude CLI in print mode with JSON output."""
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if model:
        cmd.extend(["--model", model])

    res = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60
    )

    if res.returncode != 0:
        raise RuntimeError(f"Claude CLI exited with code {res.returncode}: {res.stderr}")

    envelope = json.loads(res.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"Claude CLI error: {envelope.get('error') or envelope.get('result')}")

    result_text = envelope.get("result", "")
    parsed = extract_json(result_text)
    if not parsed:
        raise ValueError("Could not parse JSON from Claude CLI result envelope")
    return parsed


def call_anthropic(prompt: str, api_key: str) -> Dict[str, Any]:
    """Invokes Anthropic Messages API."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }
    resp = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=40)
    resp.raise_for_status()
    data = resp.json()
    text = data["content"][0]["text"]
    parsed = extract_json(text)
    if not parsed:
        raise ValueError("Could not parse JSON from Anthropic response")
    return parsed


def call_openai(prompt: str, api_key: str) -> Dict[str, Any]:
    """Invokes OpenAI Chat Completions API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=40)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    parsed = extract_json(text)
    if not parsed:
        raise ValueError("Could not parse JSON from OpenAI response")
    return parsed


def evaluate_with_llm_or_fallback(
    evidence: Dict[str, Any],
    forced_provider: Optional[str] = None
) -> Tuple[Dict[str, Any], str]:
    """
    Evaluates evidence bundle using detected LLM provider.
    Returns (evaluation_result, provider_name_used).
    Gracefully falls back to deterministic rule engine if LLM fails.
    """
    provider = detect_provider(forced_provider)
    prompt = build_debate_prompt(evidence)

    if provider == "claude_code":
        try:
            model = os.environ.get("CLAUDE_MODEL", "haiku")
            res = call_claude_code(prompt, model=model)
            # Verify and sanitize
            _sanitize_verdict(res)
            return res, "claude_code"
        except Exception as e:
            logger.warning(f"Claude CLI failed ({e}), falling back to deterministic.")

    elif provider == "anthropic":
        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            res = call_anthropic(prompt, api_key)
            _sanitize_verdict(res)
            return res, "anthropic"
        except Exception as e:
            logger.warning(f"Anthropic API failed ({e}), falling back to deterministic.")

    elif provider == "openai":
        try:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            res = call_openai(prompt, api_key)
            _sanitize_verdict(res)
            return res, "openai"
        except Exception as e:
            logger.warning(f"OpenAI API failed ({e}), falling back to deterministic.")

    # Deterministic Engine Fallback
    det_res = evaluate_deterministic(evidence)
    return det_res, "deterministic"


def _sanitize_verdict(data: Dict[str, Any]) -> None:
    """Validates and ensures fields adhere to bounds."""
    if "verdict" not in data or "scores" not in data:
        raise ValueError("Missing scores or verdict keys in LLM output")

    v = data["verdict"]
    v["verdict"] = v.get("verdict", "WATCH").upper()
    if v["verdict"] not in ("BUY", "WATCH", "AVOID"):
        v["verdict"] = "WATCH"

    v["confidence"] = int(clamp(v.get("confidence", 5), 1, 10))
    if v["verdict"] == "BUY" and v["confidence"] < 7:
        v["confidence"] = 7

    b_score = float(data.get("scores", {}).get("bull", {}).get("score", 50))
    be_score = float(data.get("scores", {}).get("bear", {}).get("score", 50))
    v["bull_score"] = round(b_score, 1)
    v["bear_score"] = round(be_score, 1)
    v["net"] = round(b_score - be_score, 1)
    if "winner" not in v or v["winner"] not in ("Bull", "Bear"):
        v["winner"] = "Bull" if v["net"] >= 0 else "Bear"
