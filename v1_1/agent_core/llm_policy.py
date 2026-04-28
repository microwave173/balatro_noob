import json
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


BASE_SYSTEM_PROMPT = (
    "You are a Balatro agent policy helper.\n"
    "Goal: survive and maximize win probability.\n"
    "Basic strategy:\n"
    "1) Prefer stable hands over greedy high variance lines.\n"
    "2) In shop, prioritize value Jokers, then Planet/Tarot/Spectral, avoid random reroll spam.\n"
    "3) Keep economy healthy; avoid buying weak cards if money is low.\n"
    "4) If a blind is already beatable, do not overcomplicate.\n"
    "5) Output STRICT JSON only.\n"
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    # Fast path
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Markdown code block path
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # Greedy object scan path
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None


class LLMPolicy:
    def __init__(
        self,
        enabled: bool,
        provider: str,
        model: str,
        timeout: float,
        log_io: bool,
        *,
        ollama_url: str = "http://127.0.0.1:11434/api/chat",
        deepseek_url: str = "https://api.deepseek.com/chat/completions",
        deepseek_api_key: str = "",
        think: bool = False,
        reference_text: str = "",
        skill_text: str = "",
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.log_io = log_io
        self.ollama_url = ollama_url
        self.deepseek_url = deepseek_url
        self.deepseek_api_key = deepseek_api_key
        self.think = think
        self.reference_text = (reference_text or "").strip()
        self.skill_text = (skill_text or "").strip()
        sections: List[str] = [BASE_SYSTEM_PROMPT]
        if self.reference_text:
            sections.append(
                "Stable Reference Strategy (long-term baseline, do not ignore unless a candidate is clearly better in current state):\n"
                + self.reference_text
            )
        if self.skill_text:
            sections.append(
                "Adaptive Rulebook (learned from recent runs; prefer these for short-term tuning when conflicts are minor):\n"
                + self.skill_text
            )
        self.system_prompt = "\n\n".join(sections)

    def choose(
        self,
        stage: str,
        summary: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        if not self.enabled:
            return None

        user_obj = {
            "task": "choose one action candidate index to execute",
            "stage": stage,
            "state_summary": summary,
            "candidates": candidates,
            "output_schema": {"candidate_index": "int", "reason": "string"},
        }
        if self.log_io:
            print("[llm-input]", json.dumps({"provider": self.provider, "stage": stage, "request": user_obj}, ensure_ascii=False))

        try:
            if self.provider == "ollama":
                text = self._chat_ollama(user_obj)
            elif self.provider == "deepseek":
                text = self._chat_deepseek(user_obj)
            else:
                raise RuntimeError(f"unsupported provider: {self.provider}")

            if self.log_io:
                print("[llm-output]", json.dumps({"provider": self.provider, "stage": stage, "raw": text}, ensure_ascii=False))

            parsed = _extract_json(text)
            if not parsed:
                return None
            idx = int(parsed.get("candidate_index", -1))
            if idx < 0 or idx >= len(candidates):
                return None
            reason = str(parsed.get("reason", "")).strip()
            return candidates[idx], reason
        except Exception as e:
            if self.log_io:
                print("[llm-output]", json.dumps({"provider": self.provider, "stage": stage, "error": str(e)}, ensure_ascii=False))
            return None

    def _chat_ollama(self, user_obj: Dict[str, Any]) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
            ],
            "options": {
                "num_ctx": 2048,
                "num_thread": 8,
                "num_gpu": 999,
            },
        }
        if self.think:
            payload["think"] = True

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.ollama_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        return ((out.get("message") or {}).get("content") or "").strip()

    def _chat_deepseek(self, user_obj: Dict[str, Any]) -> str:
        if not self.deepseek_api_key:
            raise RuntimeError("missing deepseek api key")

        # DeepSeek OpenAI-compatible chat completions.
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "max_tokens": 220,
            "response_format": {"type": "json_object"},
        }
        if self.think:
            payload["reasoning"] = {"enabled": True}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.deepseek_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.deepseek_api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        choices = out.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()
