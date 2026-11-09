"""Provider-agnostic JSON completion with exponential backoff.

All three providers are asked for a single JSON object; the parsing here is
deliberately forgiving because only OpenAI enforces a JSON response format.
On unrecoverable failure the caller receives a neutral Hold verdict rather than
an exception, so one bad API call cannot abort a 40-scenario run -- the same
behaviour as the original experiment scripts.
"""
import json
import math
import re
import time
from typing import Dict

from .config import require_key

FALLBACK = {"thought": "API failure", "verdict": "Hold", "message": "I abstain."}

_clients: Dict[str, object] = {}


def _openai():
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI(api_key=require_key("openai"), timeout=60.0)
    return _clients["openai"]


def _anthropic():
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic(
            api_key=require_key("anthropic"), timeout=60.0
        )
    return _clients["anthropic"]


def _google():
    if "google" not in _clients:
        from google import genai
        _clients["google"] = genai.Client(api_key=require_key("google"))
    return _clients["google"]


def parse_json(text: str) -> dict:
    """Recover a JSON object from a model response that may be fenced or padded."""
    if not text:
        return {}
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        braced = re.search(r"\{.*\}", text, re.DOTALL)
        if braced:
            text = braced.group(0)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def call_json(backend: dict, system_prompt: str, user_prompt: str,
              max_retries: int = 5) -> dict:
    """Return the model's JSON reply as a dict, retrying transient errors."""
    provider, model = backend["provider"], backend["model"]

    for attempt in range(max_retries):
        try:
            if provider == "openai":
                resp = _openai().chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": user_prompt}],
                    response_format={"type": "json_object"},
                )
                return parse_json(resp.choices[0].message.content)

            if provider == "anthropic":
                resp = _anthropic().messages.create(
                    model=model,
                    max_tokens=1024,          # required by the Anthropic API
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return parse_json("".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                ))

            if provider == "google":
                from google.genai import types
                resp = _google().models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                    ),
                )
                return parse_json(resp.text)

            raise ValueError(f"Unknown provider: {provider}")

        except Exception as exc:                      # noqa: BLE001 - provider SDKs
            if attempt == max_retries - 1:
                print(f"\n[llm] giving up on {provider}/{model}: {exc}")
                return dict(FALLBACK)
            wait = math.pow(2, attempt) * 2
            print(f"\n[llm] {provider}/{model} error ({exc}); retrying in {wait:.0f}s")
            time.sleep(wait)

    return dict(FALLBACK)
