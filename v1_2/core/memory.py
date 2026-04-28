import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


SEVERITY_SCORE = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.9,
    "critical": 1.0,
}


class SkillMemory:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.play_path = self.data_dir / "play_skills.json"
        self.shop_path = self.data_dir / "shop_skills.json"
        self.mistakes_path = self.data_dir / "mistakes.jsonl"
        self.rulebook_path = self.data_dir.parent / "rulebook.md"
        self.play_skills = self._load_json_list(self.play_path)
        self.shop_skills = self._load_json_list(self.shop_path)

    def retrieve(self, phase: str, state: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
        skills = self.play_skills if phase == "PLAY" else self.shop_skills if phase == "SHOP" else []
        scored = []
        for skill in skills:
            trigger_match = _trigger_match(skill.get("trigger") or {}, state, phase)
            if trigger_match <= 0:
                continue
            confidence = float(skill.get("confidence", 0.5) or 0.5)
            recency = _recency_score(skill.get("updated_at") or skill.get("created_at"))
            severity = SEVERITY_SCORE.get(str(skill.get("severity", "medium")).lower(), 0.6)
            samples = ((skill.get("stats") or {}).get("samples") or skill.get("samples") or 1)
            sample_support = min(1.0, float(samples) / 20.0)
            priority = (
                0.45 * trigger_match
                + 0.25 * confidence
                + 0.15 * recency
                + 0.10 * severity
                + 0.05 * sample_support
            )
            item = dict(skill)
            item["runtime_priority"] = priority
            scored.append(item)
        scored.sort(key=lambda s: s.get("runtime_priority", 0), reverse=True)
        return scored[:limit]

    def save_skills(self, play_skills: List[Dict[str, Any]], shop_skills: List[Dict[str, Any]]) -> None:
        self.play_skills = _merge_skill_lists(self.play_skills, play_skills)
        self.shop_skills = _merge_skill_lists(self.shop_skills, shop_skills)
        self._write_json(self.play_path, self.play_skills)
        self._write_json(self.shop_path, self.shop_skills)

    def append_mistakes(self, mistakes: List[Dict[str, Any]]) -> None:
        if not mistakes:
            return
        self.mistakes_path.parent.mkdir(parents=True, exist_ok=True)
        with self.mistakes_path.open("a", encoding="utf-8") as f:
            for m in mistakes:
                out = dict(m)
                out.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

    def long_term_context(self, *, rule_limit: int = 40, mistake_limit: int = 20) -> Dict[str, List[str]]:
        return {
            "rules": self.read_rulebook_rules(limit=rule_limit),
            "mistakes": self.read_mistakes(limit=mistake_limit),
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

    def read_mistakes(self, limit: int = 12) -> List[str]:
        items = read_jsonl(self.mistakes_path)
        if not items:
            return []
        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        indexed = list(enumerate(items))
        indexed.sort(
            key=lambda pair: (
                severity_rank.get(str(pair[1].get("severity", "medium")).lower(), 2),
                str(pair[1].get("created_at", "")),
                pair[0],
            ),
            reverse=True,
        )
        out = []
        for _, item in indexed[:limit]:
            kind = str(item.get("kind") or "mistake")
            severity = str(item.get("severity") or "medium")
            pattern = str(item.get("pattern") or "").strip()
            better = str(item.get("better_action") or "").strip()
            if pattern or better:
                out.append(f"{kind},severity={severity},mistake={pattern},better={better}")
        return out

    @staticmethod
    def _load_json_list(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _merge_skill_lists(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now().isoformat(timespec="seconds")
    by_id: Dict[str, Dict[str, Any]] = {
        str(s.get("id")): dict(s)
        for s in existing
        if isinstance(s, dict) and s.get("id")
    }
    for skill in new:
        if not isinstance(skill, dict):
            continue
        sid = str(skill.get("id") or "").strip()
        if not sid:
            continue
        incoming = dict(skill)
        incoming.setdefault("created_at", now)
        incoming["updated_at"] = now
        old = by_id.get(sid)
        if old:
            stats = dict(old.get("stats") or {})
            stats["samples"] = int(stats.get("samples", 0) or 0) + 1
            incoming["stats"] = stats
            old_conf = float(old.get("confidence", 0.5) or 0.5)
            new_conf = float(incoming.get("confidence", old_conf) or old_conf)
            incoming["confidence"] = round(0.65 * old_conf + 0.35 * new_conf, 3)
            incoming.setdefault("created_at", old.get("created_at", now))
        else:
            incoming.setdefault("stats", {"samples": 1})
        by_id[sid] = incoming
    merged = list(by_id.values())
    merged.sort(key=lambda s: (float(s.get("confidence", 0.5) or 0.5), str(s.get("updated_at", ""))), reverse=True)
    return merged[:80]


def _trigger_match(trigger: Dict[str, Any], state: Dict[str, Any], phase: str) -> float:
    if trigger.get("phase") and str(trigger.get("phase")).upper() != phase.upper():
        return 0.0
    score = 0.35
    max_score = 0.35

    current_jokers = {
        str(c.get("label") or c.get("key") or "").lower()
        for c in (((state.get("jokers") or {}).get("cards")) or [])
    }
    jokers_any = [str(x).lower() for x in (trigger.get("jokers_any") or [])]
    if jokers_any:
        max_score += 0.4
        if any(j in current_jokers for j in jokers_any):
            score += 0.4

    boss_effect = str((((state.get("blinds") or {}).get("boss") or {}).get("effect") or "")).lower()
    boss_contains = str(trigger.get("boss_effect_contains") or trigger.get("next_boss_effect_contains") or "").lower()
    if boss_contains:
        max_score += 0.25
        if boss_contains in boss_effect:
            score += 0.25

    return min(1.0, score / max_score if max_score else 0.0)


def _recency_score(timestamp: Any) -> float:
    if not timestamp:
        return 0.5
    try:
        dt = datetime.fromisoformat(str(timestamp))
        days = max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
        return math.exp(-days / 7.0)
    except Exception:
        return 0.5
