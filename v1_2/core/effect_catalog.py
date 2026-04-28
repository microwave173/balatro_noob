import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_OPENRPC_PATH = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Balatro"
    / "Mods"
    / "balatrobot"
    / "src"
    / "lua"
    / "utils"
    / "openrpc.json"
)


class EffectCatalog:
    def __init__(self, openrpc_path: str | None = None) -> None:
        self.openrpc_path = Path(openrpc_path) if openrpc_path else DEFAULT_OPENRPC_PATH
        self.effects = self._load_effects()

    def describe(self, key: str, fallback: str = "") -> str:
        text = self.effects.get(key) or fallback or ""
        return " ".join(str(text).split())

    def enrich_card(self, card: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(card)
        value = dict(out.get("value") or {})
        key = str(out.get("key") or "")
        api_effect = str(value.get("effect") or "")

        if out.get("set") == "DEFAULT":
            rank = value.get("rank")
            if rank:
                value["effect"] = f"+{_rank_chip_value(str(rank))} Chips"
        else:
            value["effect"] = self.describe(key, api_effect)

        out["value"] = value
        return out

    def _load_effects(self) -> Dict[str, str]:
        if not self.openrpc_path.exists():
            return {}
        try:
            data = json.loads(self.openrpc_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        effects: Dict[str, str] = {}

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                const = obj.get("const")
                desc = obj.get("description")
                if isinstance(const, str) and isinstance(desc, str):
                    effects[const] = desc
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        return effects


def _rank_chip_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in ("K", "Q", "J", "T"):
        return 10
    try:
        return int(rank)
    except Exception:
        return 0
