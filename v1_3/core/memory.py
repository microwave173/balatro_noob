import json
from pathlib import Path
from typing import Any, Dict, List


class SkillMemory:
    """Rulebook-only memory facade kept for runner compatibility."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.rulebook_path = self.data_dir.parent / "rulebook.md"

    def long_term_context(self, *, rule_limit: int = 80) -> dict[str, List[str]]:
        return {
            "rules": self.read_rulebook_rules(limit=rule_limit),
        }

    def read_rulebook_rules(self, limit: int = 20) -> List[str]:
        if not self.rulebook_path.exists():
            return []
        rules: List[str] = []
        in_summary = False
        for raw in self.rulebook_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("## "):
                in_summary = line == "## Summary Rules"
                continue
            if not in_summary:
                continue
            if not line.startswith("- "):
                continue
            text = line[2:].strip()
            if text:
                rules.append(text)
        return rules[-limit:] if limit else rules


def append_jsonl(path: str | Path, item: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path, limit: int | None = None) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out[-limit:] if limit else out
