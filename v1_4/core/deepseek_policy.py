import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from openai import OpenAI

from .prompts import (
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
        decision_format: str = "auto",
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
        self.decision_format = str(decision_format or "auto").lower()
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
        return self._structured_chat("BLIND_SELECT", prompt, "blind_select_decision", BLIND_SELECT_PARAMS, max_tokens=240, thinking=self.think, temperature=0.0)

    def play_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PLAY", "Choose the best play, discard, or inspect_deck action.", observation, PLAY_DECISION_SCHEMA)
        return self._structured_chat("PLAY_DECISION", prompt, "play_decision", PLAY_PARAMS, max_tokens=360, thinking=self.think, temperature=0.0)

    def shop_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("SHOP", "Choose the best shop action.", observation, SHOP_DECISION_SCHEMA)
        return self._structured_chat("SHOP_DECISION", prompt, "shop_decision", SHOP_PARAMS, max_tokens=520, thinking=self.think, temperature=0.0)

    def pack_decision(self, observation: str) -> Dict[str, Any]:
        prompt = _decision_user("PACK", "Choose the best pack option.", observation, PACK_DECISION_SCHEMA)
        return self._structured_chat("PACK_DECISION", prompt, "pack_decision", PACK_PARAMS, max_tokens=520, thinking=self.think, temperature=0.0)

    def reflect(self, prompt: Dict[str, Any], *, thinking: bool = True, max_tokens: int = 1800) -> Dict[str, Any]:
        text = json.dumps(prompt, ensure_ascii=False)
        return self._structured_chat("REFLECT", text, "reflect_rulebook", REFLECT_PARAMS, max_tokens=max_tokens, thinking=thinking, temperature=0.25)

    def summarize_history(self, existing_summary: str, older_actions: list[Dict[str, Any]]) -> str:
        prompt = {
            "task": "Compress current-run Balatro operation history for future decision prompts.",
            "existing_summary": existing_summary or "",
            "older_actions": older_actions,
            "requirements": [
                "Write a compact factual summary of important decisions, outcomes, scoring strength, Joker changes, consumable use attempts, errors, and lessons that still matter in this same run.",
                "Use the latest commentary and reason fields to infer the next intended plan if one is visible, such as target hand type, whether to save or spend discards, shop upgrade priorities, boss preparation, or consumable timing.",
                "Include that inferred next plan explicitly as 'Next plan: ...' when there is enough evidence; otherwise omit it instead of inventing one.",
                "Prefer exact outcomes from the records over speculation.",
                "Do not include hidden reasoning. Keep it under 1400 characters.",
            ],
        }
        result = self._structured_chat(
            "HISTORY_SUMMARY",
            json.dumps(prompt, ensure_ascii=False),
            "summarize_history",
            HISTORY_SUMMARY_PARAMS,
            max_tokens=700,
            thinking=self.think,
            temperature=0.0,
        )
        return str(result.get("summary") or "").strip()[:1600]

    def _structured_chat(
        self,
        label: str,
        user_text: str,
        tool_name: str,
        params: Dict[str, Any],
        *,
        max_tokens: int,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        if self._effective_decision_format() == "json":
            return self._json_chat(label, user_text, tool_name, params, max_tokens=max_tokens, thinking=thinking, temperature=temperature)
        return self._tool_chat(label, user_text, _tool_spec(tool_name, params), max_tokens=max_tokens, thinking=thinking, temperature=temperature)

    def _effective_decision_format(self) -> str:
        if self.decision_format in ("json", "tool"):
            return self.decision_format
        return "json" if self.provider == "deepseek" else "tool"

    def _structured_max_tokens(self, requested: int, thinking: bool) -> int:
        if self.provider == "deepseek" and thinking and self._effective_decision_format() == "json":
            return max(int(requested or 0), 16384)
        return int(requested or 0)

    def _json_chat(
        self,
        label: str,
        user_text: str,
        tool_name: str,
        params: Dict[str, Any],
        *,
        max_tokens: int,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("missing DeepSeek API key")
        if not self.client:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

        system = _json_base_system(self.base_system) + "\n\n" + _json_output_system_rule(tool_name, params)
        prompt = _json_user(user_text, tool_name, params)
        max_tokens = self._structured_max_tokens(max_tokens, thinking)
        raw = ""
        parsed: Optional[Dict[str, Any]] = None
        for attempt in range(2):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt if attempt == 0 else _json_retry_user(prompt, raw, params)},
            ]
            request: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            self._add_thinking_request_options(request, thinking, force_tool_choice=None)
            parsed, raw = self._send_and_parse_json_request(request)
            if parsed:
                break

        if parsed:
            self._emit_commentary(label, parsed)
            parsed["_tool_name"] = tool_name
            parsed["_decision_format"] = "json"
            return parsed

        self._emit_parse_error(label, "llm_json_not_valid", raw)
        return {
            "_parse_error": "llm_json_not_valid",
            "_label": label,
            "_tool_name": tool_name,
            "_decision_format": "json",
            "_raw_decision": _salvage_decision_from_text(raw),
            "_raw_response": raw[:4000],
        }

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
        self._add_thinking_request_options(
            request,
            thinking,
            force_tool_choice=None if thinking else tool["function"]["name"],
        )

        parsed, raw, tool_name = self._send_and_parse_tool_request(request)
        if not parsed and thinking:
            retry_request = dict(request)
            retry_request["extra_body"] = _thinking_disabled_extra_body(self.provider)
            retry_request["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}
            retry_request.pop("reasoning_effort", None)
            parsed, raw, tool_name = self._send_and_parse_tool_request(retry_request)

        if parsed:
            self._emit_commentary(label, parsed)

        if parsed:
            parsed["_tool_name"] = tool_name
            parsed["_decision_format"] = "tool"
            return parsed

        return {
            "_parse_error": "llm_tool_call_not_valid",
            "_label": label,
            "_tool_name": tool_name,
            "_decision_format": "tool",
            "_raw_response": raw[:4000],
        }

    def _add_thinking_request_options(self, request: Dict[str, Any], thinking: bool, force_tool_choice: Optional[str]) -> None:
        if self.provider == "qwen":
            extra_body: Dict[str, Any] = {"enable_thinking": bool(thinking)}
            if thinking:
                budget = self.thinking_budget or _qwen_budget_for_effort(self.reasoning_effort)
                if budget > 0:
                    extra_body["thinking_budget"] = budget
            request["extra_body"] = extra_body
        else:
            request["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
            if thinking:
                request["reasoning_effort"] = _deepseek_reasoning_effort(self.reasoning_effort)
        if force_tool_choice:
            request["tool_choice"] = {"type": "function", "function": {"name": force_tool_choice}}

    def _emit_commentary(self, label: str, parsed: Dict[str, Any]) -> None:
        commentary = str(parsed.get("commentary") or "").strip()
        if commentary:
            if self.commentary_callback:
                try:
                    self.commentary_callback(label, commentary)
                except Exception:
                    pass
            if self.log_io:
                _safe_print("[v1_4-llm-commentary] " + json.dumps({"label": label, "commentary": commentary}, ensure_ascii=False))

    def _emit_parse_error(self, label: str, code: str, raw: str) -> None:
        excerpt = " ".join(str(raw or "").split())[:700]
        message = f"{code}: model did not return valid structured output. raw={excerpt}"
        if self.commentary_callback:
            try:
                self.commentary_callback(label, message)
            except Exception:
                pass
        if self.log_io:
            _safe_print("[v1_4-llm-parse-error] " + json.dumps({"label": label, "error": code, "raw": excerpt}, ensure_ascii=False))

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

    def _send_and_parse_json_request(self, request: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], str]:
        response = self.client.chat.completions.create(**request)
        raw = ""
        choices = response.choices or []
        if choices:
            message = choices[0].message
            raw = (message.content or "").strip()
            if not raw:
                reasoning = getattr(message, "reasoning_content", None)
                if reasoning:
                    raw = str(reasoning or "").strip()
        return _extract_json(raw), raw


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


def _salvage_decision_from_text(text: str) -> Dict[str, Any]:
    lowered = str(text or "").lower()
    action = ""
    for candidate in ("inspect_deck", "discard", "play", "reroll", "next_round", "buy", "sell", "use", "skip", "select"):
        if re.search(rf"\b{re.escape(candidate)}\b", lowered):
            action = candidate
            break
    cards: list[int] = []
    m = re.search(r"(?:cards?|indexes?|indices)\D{0,20}\[([0-9,\s]+)\]", lowered)
    if not m:
        m = re.search(r"\[([0-9,\s]+)\]", lowered)
    if m:
        for part in m.group(1).split(","):
            try:
                cards.append(int(part.strip()))
            except Exception:
                pass
    out: Dict[str, Any] = {}
    if action:
        out["action"] = action
    if cards:
        out["cards"] = cards
    if text:
        out["reason"] = "Structured output failed; salvaged from raw model text."
        out["commentary"] = "The model did not return valid JSON, so Python salvaged a conservative action from its text."
    return out


def _json_base_system(text: str) -> str:
    replacements = {
        "Use the required tool call for decisions.": "Return the required JSON object for decisions.",
        "Output rule:\n- Use the required tool call exactly once.": "Output rule:\n- Return exactly one JSON object.",
        "- Do not write prose outside the tool call. Do not use markdown.": "- Do not write prose outside JSON. Do not use markdown.",
        "- The reason field may contain a few concise sentences, but keep it decision-focused.": "- The JSON reason field may contain a few concise sentences, but keep it decision-focused.",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


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


def _deepseek_reasoning_effort(reasoning_effort: str) -> str:
    effort = str(reasoning_effort or "high").lower()
    if effort in ("max", "xhigh"):
        return "max"
    return "high"


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


def _json_output_system_rule(name: str, parameters: Dict[str, Any]) -> str:
    required = parameters.get("required") or []
    properties = parameters.get("properties") or {}
    return (
        "Structured JSON output mode:\n"
        f"- Return exactly one JSON object for `{name}` in the final answer content.\n"
        "- Do not use markdown, code fences, XML, comments, or prose outside JSON.\n"
        "- The JSON object must satisfy this schema summary:\n"
        f"{json.dumps({'required': required, 'properties': properties}, ensure_ascii=False)}\n"
        "- Include all required keys even when their value is empty or null-like.\n"
        "- Use zero-based card indexes exactly as shown by the observation.\n"
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


def _json_user(user_text: str, name: str, parameters: Dict[str, Any]) -> str:
    required = parameters.get("required") or []
    text = (
        user_text.replace("Call the required tool exactly once. Do not write prose outside the tool call.", "Return the required JSON object exactly once. Do not write prose outside JSON.")
        .replace("Hard output rule: call the required tool exactly once.", "Hard output rule: return exactly one JSON object.")
        .replace("Tool arguments:", "JSON object fields:")
        .replace("Put any brief explanation only inside the tool's reason field.", "Put any brief explanation only inside the JSON reason field.")
    )
    return (
        text
        + "\n\nJSON output contract:\n"
        + f"Return a JSON object for {name}. The word json is intentionally present for JSON mode.\n"
        + f"Required keys: {required}.\n"
        + "Do not call tools. Do not write prose outside the JSON object.\n"
    )


def _json_retry_user(original: str, raw: str, parameters: Dict[str, Any]) -> str:
    required = parameters.get("required") or []
    return (
        "The previous final answer was not valid JSON or missed the schema.\n"
        "Convert the decision into one valid json object now. Do not explain.\n"
        f"Required keys: {required}.\n"
        f"Schema properties: {json.dumps(parameters.get('properties') or {}, ensure_ascii=False)}\n"
        f"Previous raw answer excerpt: {str(raw or '')[:1200]}\n"
        "Return JSON only."
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

HISTORY_SUMMARY_PARAMS = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Compact current-run factual memory to keep in future decision prompts."},
        "commentary": {"type": "string", "description": "One short sentence for the human operator about history compression."},
    },
    "required": ["summary", "commentary"],
}


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace")
        print(encoded.decode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace"))

