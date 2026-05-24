"""
ai_brain.py — OpenRouter Scare Hook Generator
──────────────────────────────────────────────────────────────────────────────
Tiered model routing:
  Recruit / Lieutenant  →  mistral/mistral-7b-instruct:free  (free tier)
                           fallback: google/gemini-flash-1.5  (free tier)
  Admiral               →  deepseek/deepseek-chat  (paid — high-value leads only)

Output per lead:
  {
    "vulnerability":  "Prompt Injection",
    "scare_hook":     "Two-sentence hook that makes a founder sweat.",
    "subject_line":   "Cold email subject line (≤9 words)"
  }
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from config import (
    OPENROUTER_API_KEY,
    RANK_ADMIRAL,
    RANK_LIEUTENANT,
    RANK_RECRUIT,
)

logger = logging.getLogger("war-machine.ai_brain")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Tiered model routing ──────────────────────────────────────────────────────
MODEL_FREE_PRIMARY  = "mistral/mistral-7b-instruct:free"
MODEL_FREE_FALLBACK = "google/gemini-flash-1.5"
MODEL_PREMIUM       = "deepseek/deepseek-chat"

RANK_MODEL_MAP: dict[str, list[str]] = {
    RANK_RECRUIT:    [MODEL_FREE_PRIMARY, MODEL_FREE_FALLBACK],
    RANK_LIEUTENANT: [MODEL_FREE_PRIMARY, MODEL_FREE_FALLBACK],
    RANK_ADMIRAL:    [MODEL_PREMIUM, MODEL_FREE_PRIMARY],
}

# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an elite red-team operator at a top-tier offensive security firm.
Your job: read a company's AI product description and instantly identify their most likely
critical vulnerability. Be blunt, specific, and technically credible.

Respond ONLY with valid JSON — no markdown, no explanation, no extra keys:
{
  "vulnerability":  "<one of: Prompt Injection | EDoS | Data Leakage | Agent Privilege Escalation | Supply Chain Poisoning | Insecure Output Handling | Model Inversion | Adversarial Input>",
  "scare_hook":     "<exactly 2 sentences: sentence 1 names the specific threat vector for their product, sentence 2 states the concrete business impact>",
  "subject_line":   "<cold email subject ≤9 words, no clickbait, technically credible>"
}"""

USER_TEMPLATE = """Company: {company_name}
Description: {description}

Identify the single most critical AI security vulnerability for this specific product."""


# ── Core generator ────────────────────────────────────────────────────────────

def generate_scare_hook(
    company_name: str,
    description:  str,
    rank:         str = RANK_RECRUIT,
    retries:      int = 3,
    backoff:      float = 2.0,
) -> dict[str, str]:
    """
    Call OpenRouter with the correct model tier for this lead's rank.
    Returns parsed JSON dict or a safe fallback on failure.
    """
    models = RANK_MODEL_MAP.get(rank, RANK_MODEL_MAP[RANK_RECRUIT])
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_TEMPLATE.format(
                company_name=company_name,
                description=description or "AI product company",
            )},
        ],
        "temperature": 0.7,
        "max_tokens":  400,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://war-machine.forgeguard.ai",
        "X-Title":       "ForgeGuard War Machine",
    }

    for model in models:
        for attempt in range(retries):
            try:
                payload["model"] = model
                logger.debug(f"  [{company_name}] Attempt {attempt+1} with {model}")

                with httpx.Client(timeout=30) as client:
                    resp = client.post(OPENROUTER_URL, json=payload, headers=headers)

                if resp.status_code == 429:
                    wait = backoff * (2 ** attempt)
                    logger.warning(f"  Rate limited on {model}. Waiting {wait:.0f}s…")
                    time.sleep(wait)
                    continue

                if resp.status_code == 402:
                    logger.warning(f"  {model} requires payment — trying next model")
                    break

                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                result = _parse_json_response(raw, company_name)
                logger.info(
                    f"  ✓ [{rank}] {company_name}: {result.get('vulnerability', '?')} "
                    f"(model: {model.split('/')[-1]})"
                )
                return result

            except (httpx.HTTPError, KeyError, IndexError) as exc:
                logger.warning(f"  [{company_name}] {model} attempt {attempt+1} failed: {exc}")
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))

        logger.warning(f"  [{company_name}] Model {model} exhausted, trying fallback")

    logger.error(f"  [{company_name}] All models failed — using fallback hook")
    return _fallback_hook(company_name)


def process_leads_batch(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich a list of leads with scare hooks in-place."""
    total = len(leads)
    for i, lead in enumerate(leads, 1):
        name = lead.get("company_name", "Unknown")
        desc = lead.get("description", "")
        rank = lead.get("rank", RANK_RECRUIT)

        logger.info(f"[{i}/{total}] Generating hook for {name} ({rank})…")
        hook_data = generate_scare_hook(name, desc, rank=rank)
        lead.update(hook_data)
        time.sleep(0.3)  # gentle pacing on free tier

    return leads


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_response(raw: str, company_name: str) -> dict[str, str]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        data = json.loads(cleaned)
        for key in ("vulnerability", "scare_hook", "subject_line"):
            if key not in data:
                raise ValueError(f"Missing key: {key}")
        return {
            "vulnerability": str(data["vulnerability"]),
            "scare_hook":    str(data["scare_hook"]),
            "subject_line":  str(data["subject_line"]),
        }
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"  JSON parse failed for {company_name}: {exc}")
        # Best-effort regex extraction
        scare = re.search(r'"scare_hook"\s*:\s*"([^"]+)"', cleaned)
        subj  = re.search(r'"subject_line"\s*:\s*"([^"]+)"', cleaned)
        vuln  = re.search(r'"vulnerability"\s*:\s*"([^"]+)"', cleaned)
        if scare and subj and vuln:
            return {
                "vulnerability": vuln.group(1),
                "scare_hook":    scare.group(1),
                "subject_line":  subj.group(1),
            }
        return _fallback_hook(company_name)


def _fallback_hook(company_name: str) -> dict[str, str]:
    return {
        "vulnerability": "Prompt Injection",
        "scare_hook": (
            f"Your AI model at {company_name} accepts untrusted input without "
            f"sanitization, creating a direct prompt injection surface. "
            f"An attacker could exfiltrate internal system prompts and user data "
            f"within minutes of deployment."
        ),
        "subject_line": f"Critical AI security gap at {company_name}",
    }


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    result = generate_scare_hook(
        company_name="Synthwave AI",
        description="We build an AI copilot for enterprise sales teams that reads emails, CRM data, and Slack to auto-generate deal summaries.",
        rank=RANK_ADMIRAL,
    )
    print(json.dumps(result, indent=2))
