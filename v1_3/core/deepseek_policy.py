import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

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
        model: str = "deepseek-v4-pro",
        url: str = "https://api.deepseek.com",
        timeout: float = 45.0,
        log_io: bool = False,
        think: bool = True,
        reasoning_effort: str = "high",
        thinking_budget: int = 0,
        provider: str = "deepseek",
        commentary_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = _normalize_base_url(url)
        self.timeout = timeout
        self.log_io = log_io
        self.think = think
        self.reasoning_effort = reasoning_effort
        self.thinking_budget = int(thinking_budget or 0)
        self.provider = str(provider or "deepseek").lower()
        self.commentary_callback = commentary_callback
        self.client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=timeout) if api_key else None
        self.base_system = (
            MASTER_IDENTITY
            + "\n\n"
            + GAME_PRIMER
            + "\n\n"
            + STRATEGY_TIPS
            + "\n\n"
            + _load_reference_guide()
            + "\n\n"
            + COMPACT_FORMAT_GUIDE
        )

    def blind_select(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("BLIND_SELECT", "Choose whether to select or skip the blind.", observation, BLIND_SELECT_SCHEMA)
        return self._tool_chat("BLIND_SELECT", prompt, _tool_spec("blind_select_decision", BLIND_SELECT_PARAMS), max_tokens=240, thinking=self.think, temperature=0.0)

    def blind_plan(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PLAY", "Make a short tactical plan for this blind before playing cards.", observation, BLIND_PLAN_SCHEMA)
        return self._tool_chat("BLIND_PLAN", prompt, _tool_spec("blind_plan_decision", BLIND_PLAN_PARAMS), max_tokens=360, thinking=self.think, temperature=0.0)

    def play_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PLAY", "Choose the best play, discard, or inspect_deck action.", observation, PLAY_DECISION_SCHEMA)
        return self._tool_chat("PLAY_DECISION", prompt, _tool_spec("play_decision", PLAY_PARAMS), max_tokens=360, thinking=self.think, temperature=0.0)

    def shop_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("SHOP", "Choose the best shop action.", observation, SHOP_DECISION_SCHEMA)
        return self._tool_chat("SHOP_DECISION", prompt, _tool_spec("shop_decision", SHOP_PARAMS), max_tokens=520, thinking=self.think, temperature=0.0)

    def pack_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PACK", "Choose the best pack option.", observation, PACK_DECISION_SCHEMA)
        return self._tool_chat("PACK_DECISION", prompt, _tool_spec("pack_decision", PACK_PARAMS), max_tokens=520, thinking=self.think, temperature=0.0)

    def reflect(self, prompt: Dict[str, Any], *, thinking: bool = True, max_tokens: int = 1800) -> Dict[str, Any]:
        text = json.dumps(prompt, ensure_ascii=False)
        return self._tool_chat("REFLECT", text, _tool_spec("reflect_rulebook", REFLECT_PARAMS), max_tokens=max_tokens, thinking=thinking, temperature=0.25)

    def _tool_chat(
        self,
        label: str,
        user_text: str,
        tool: Dict[str, Any],
        *,
        max_tokens: int,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("missing DeepSeek API key")
        if not self.client:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

        messages = [
            {"role": "system", "content": self.base_system},
            {"role": "user", "content": user_text},
        ]
        request: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "tools": [tool],
            "temperature": temperature,
        }
        if self.provider == "qwen":
            extra_body: Dict[str, Any] = {"enable_thinking": bool(thinking)}
            if thinking:
                budget = self.thinking_budget or _qwen_budget_for_effort(self.reasoning_effort)
                if budget > 0:
                    extra_body["thinking_budget"] = budget
            request["extra_body"] = extra_body
            if not thinking:
                request["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}
        else:
            request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
            if thinking:
                request["reasoning_effort"] = self.reasoning_effort
            else:
                request["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}

        parsed, raw, tool_name = self._send_and_parse_tool_request(request)
        if not parsed and thinking:
            retry_request = dict(request)
            retry_request["extra_body"] = _thinking_disabled_extra_body(self.provider)
            retry_request["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}
            retry_request.pop("reasoning_effort", None)
            parsed, raw, tool_name = self._send_and_parse_tool_request(retry_request)

        if parsed:
            commentary = str(parsed.get("commentary") or "").strip()
            if commentary:
                if self.commentary_callback:
                    try:
                        self.commentary_callback(label, commentary)
                    except Exception:
                        pass
                if self.log_io:
                    _safe_print("[v1_3-llm-commentary] " + json.dumps({"label": label, "commentary": commentary}, ensure_ascii=False))

        if parsed:
            parsed["_tool_name"] = tool_name
            return parsed

        return {
            "_parse_error": "llm_tool_call_not_valid",
            "_label": label,
            "_tool_name": tool_name,
            "_raw_response": raw[:4000],
        }

    def _send_and_parse_tool_request(self, request: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], str, str]:
        response = self.client.chat.completions.create(**request)
        parsed: Optional[Dict[str, Any]] = None
        raw = ""
        tool_name = ""
        choices = response.choices or []
        if choices:
            message = choices[0].message
            raw = (message.content or "").strip()
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                call = tool_calls[0]
                fn = getattr(call, "function", None)
                tool_name = str(getattr(fn, "name", "") or "")
                raw = str(getattr(fn, "arguments", "") or "")
                parsed = _extract_json(raw)
            else:
                reasoning = getattr(message, "reasoning_content", None)
                if not raw and reasoning:
                    raw = str(reasoning or "").strip()
        return parsed, raw, tool_name


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


def _qwen_budget_for_effort(reasoning_effort: str) -> int:
    effort = str(reasoning_effort or "high").lower()
    return {
        "low": 1024,
        "medium": 4096,
        "high": 8192,
    }.get(effort, 8192)


def _thinking_disabled_extra_body(provider: str) -> Dict[str, Any]:
    if str(provider or "").lower() == "qwen":
        return {"enable_thinking": False}
    return {"thinking": {"type": "disabled"}}


def _load_reference_guide() -> str:
    path = Path(__file__).resolve().parents[1] / "data" / "reference_guide.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return text[:6000]


def _strict_schema(task_schema: str) -> str:
    return (
        task_schema
        + "\n\nHard output rule: call the required tool exactly once. "
        + "Put any brief explanation only inside the tool's reason field."
    )


def _decision_user(stage: str, task: str, observation: str, schema: str) -> str:
    return (
        f"Current stage: {stage}\n\n"
        f"Task: {task}\n\n"
        "Information you can see:\n"
        f"{observation}\n\n"
        "Now use the game rules and strategy tips above to make the strongest decision.\n"
        "Call the required tool exactly once. Do not write prose outside the tool call.\n"
        "The reason field may contain a few concise sentences explaining the decision.\n\n"
        f"{_strict_schema(schema)}"
    )


def _tool_spec(name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Submit the structured Balatro agent decision.",
            "parameters": parameters,
        },
    }


STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
INT_ARRAY = {"type": "array", "items": {"type": "integer"}}

BLIND_SELECT_PARAMS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["select", "skip"]},
        "reason": {"type": "string"},
        "commentary": {"type": "string", "description": "2-4 short sentences explaining this decision for the human operator."},
    },
    "required": ["action", "reason", "commentary"],
}

BLIND_PLAN_PARAMS = {
    "type": "object",
    "properties": {
        "blind_plan": {"type": "string"},
        "preferred_hands": STRING_ARRAY,
        "discard_policy": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string"},
        "commentary": {"type": "string", "description": "2-4 short sentences explaining this plan for the human operator."},
    },
    "required": ["blind_plan", "preferred_hands", "discard_policy", "risk_level", "reason", "commentary"],
}

PLAY_PARAMS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["play", "discard", "use", "inspect_deck"]},
        "target": {"type": "string"},
        "cards": INT_ARRAY,
        "phase_plan": {"type": "string"},
        "reason": {"type": "string"},
        "commentary": {"type": "string", "description": "2-4 short sentences explaining this play/discard/use decision for the human operator."},
    },
    "required": ["action", "cards", "reason", "commentary"],
}

SHOP_PARAMS = {
    "type": "object",
    "properties": {
        "shop_plan": {"type": "string"},
        "action": {"type": "string", "enum": ["buy", "use", "sell", "reroll", "next_round"]},
        "target": {"type": "string"},
        "cards": INT_ARRAY,
        "reason": {"type": "string"},
        "commentary": {"type": "string", "description": "2-4 short sentences explaining this shop decision for the human operator."},
    },
    "required": ["shop_plan", "action", "target", "reason", "commentary"],
}

PACK_PARAMS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["pack"]},
        "target": {"type": "string"},
        "targets": INT_ARRAY,
        "reason": {"type": "string"},
        "commentary": {"type": "string", "description": "2-4 short sentences explaining this pack choice for the human operator."},
    },
    "required": ["action", "target", "reason", "commentary"],
}

REFLECT_PARAMS = {
    "type": "object",
    "properties": {
        "rules": STRING_ARRAY,
        "commentary": {"type": "string", "description": "2-4 short sentences summarizing what changed in the rulebook."},
    },
    "required": ["rules", "commentary"],
}


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace")
        print(encoded.decode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace"))
