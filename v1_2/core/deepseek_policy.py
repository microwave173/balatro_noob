import json
import re
import sys
from typing import Any, Dict, Optional

from openai import OpenAI

from .prompts import (
    BLIND_PLAN_SCHEMA,
    BLIND_SELECT_SCHEMA,
    COMPACT_FORMAT_GUIDE,
    GAME_PRIMER,
    MASTER_IDENTITY,
    PACK_DECISION_SCHEMA,
    PLAY_DECISION_SCHEMA,
    REFLECT_SCHEMA,
    SHOP_DECISION_SCHEMA,
    STRATEGY_TIPS,
)


class DeepSeekPolicy:
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        url: str = "https://api.deepseek.com",
        timeout: float = 45.0,
        log_io: bool = False,
        think: bool = False,
        reasoning_effort: str = "high",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = _normalize_base_url(url)
        self.timeout = timeout
        self.log_io = log_io
        self.think = think
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=timeout) if api_key else None
        self.base_system = MASTER_IDENTITY + "\n\n" + GAME_PRIMER + "\n\n" + STRATEGY_TIPS + "\n\n" + COMPACT_FORMAT_GUIDE

    def blind_select(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("BLIND_SELECT", "Choose whether to select or skip the blind.", observation, BLIND_SELECT_SCHEMA)
        return self._json_chat("BLIND_SELECT", prompt, BLIND_SELECT_SCHEMA, max_tokens=240, thinking=self.think, temperature=0.0)

    def blind_plan(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PLAY", "Make a short tactical plan for this blind before playing cards.", observation, BLIND_PLAN_SCHEMA)
        return self._json_chat("BLIND_PLAN", prompt, BLIND_PLAN_SCHEMA, max_tokens=360, thinking=self.think, temperature=0.0)

    def play_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PLAY", "Choose the best play, discard, or inspect_deck action.", observation, PLAY_DECISION_SCHEMA)
        return self._json_chat("PLAY_DECISION", prompt, PLAY_DECISION_SCHEMA, max_tokens=360, thinking=self.think, temperature=0.0)

    def shop_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("SHOP", "Choose the best shop action.", observation, SHOP_DECISION_SCHEMA)
        return self._json_chat("SHOP_DECISION", prompt, SHOP_DECISION_SCHEMA, max_tokens=520, thinking=self.think, temperature=0.0)

    def pack_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PACK", "Choose the best pack option.", observation, PACK_DECISION_SCHEMA)
        return self._json_chat("PACK_DECISION", prompt, PACK_DECISION_SCHEMA, max_tokens=240, thinking=self.think, temperature=0.0)

    def reflect(self, prompt: Dict[str, Any], *, thinking: bool = True, max_tokens: int = 1800) -> Dict[str, Any]:
        text = json.dumps(prompt, ensure_ascii=False)
        return self._json_chat("REFLECT", text, REFLECT_SCHEMA, max_tokens=max_tokens, thinking=thinking, temperature=0.25)

    def _json_chat(
        self,
        label: str,
        user_text: str,
        task_schema: str,
        *,
        max_tokens: int,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("missing DeepSeek API key")
        if not self.client:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

        if self.log_io:
            _safe_print("[v1_2-llm-input] " + json.dumps({"label": label, "user": user_text}, ensure_ascii=False))

        request: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.base_system},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}},
        }
        if thinking:
            request["reasoning_effort"] = self.reasoning_effort
        else:
            request["temperature"] = temperature

        response = self.client.chat.completions.create(**request)

        choices = response.choices or []
        raw = ""
        if choices:
            message = choices[0].message
            raw = (message.content or "").strip()
            reasoning = getattr(message, "reasoning_content", None)
            if not raw and reasoning:
                raw = str(reasoning or "").strip()

        if self.log_io:
            _safe_print("[v1_2-llm-output] " + json.dumps({"label": label, "raw": raw}, ensure_ascii=False))

        parsed = _extract_json(raw)
        if parsed:
            return parsed

        repaired = self._repair_json(label, user_text, task_schema, raw, max_tokens=max_tokens)
        return repaired or {}

    def _repair_json(
        self,
        label: str,
        user_text: str,
        task_schema: str,
        raw: str,
        *,
        max_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        repair_prompt = (
            "The previous response was invalid because it was not a JSON object.\n"
            "Return the decision again as exactly one valid JSON object matching the schema.\n"
            "No prose. No markdown. No chain-of-thought. Short reason only.\n\n"
            f"ORIGINAL_INPUT:\n{user_text}\n\n"
            f"INVALID_RESPONSE:\n{raw[:1200]}\n\n"
            f"{_strict_schema(task_schema)}"
        )
        if not self.client:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        if self.log_io:
            _safe_print("[v1_2-llm-input] " + json.dumps({"label": label + "_REPAIR", "user": repair_prompt}, ensure_ascii=False))

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.base_system},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0.0,
            max_tokens=min(max_tokens, 260),
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        choices = response.choices or []
        raw2 = ""
        if choices:
            message = choices[0].message
            raw2 = (message.content or "").strip()
            reasoning = getattr(message, "reasoning_content", None)
            if not raw2 and reasoning:
                raw2 = str(reasoning or "").strip()

        if self.log_io:
            _safe_print("[v1_2-llm-output] " + json.dumps({"label": label + "_REPAIR", "raw": raw2}, ensure_ascii=False))
        return _extract_json(raw2)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        try:
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    return None


def _normalize_base_url(url: str) -> str:
    out = str(url or "https://api.deepseek.com").rstrip("/")
    suffix = "/chat/completions"
    if out.endswith(suffix):
        out = out[: -len(suffix)]
    return out


def _strict_schema(task_schema: str) -> str:
    return (
        task_schema
        + "\n\nHard output rule: return exactly one JSON object. "
        + "Begin with { and end with }. Put any brief explanation only inside the JSON reason field."
    )


def _decision_user(stage: str, task: str, observation: str, schema: str) -> str:
    return (
        f"Current stage: {stage}\n\n"
        f"Task: {task}\n\n"
        "Information you can see:\n"
        f"{observation}\n\n"
        "Now use the game rules and strategy tips above to make the strongest decision.\n"
        "Return only one JSON object matching the schema. Do not write anything outside the JSON.\n"
        "The reason field may contain a few concise sentences explaining the decision.\n\n"
        f"{_strict_schema(schema)}"
    )


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace")
        print(encoded.decode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace"))
