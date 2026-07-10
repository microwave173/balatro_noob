import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v1_4 import loop
from v1_4.core.effort import (
    ante_review_outcome,
    build_ante_trajectory,
    normalize_effort_review,
    select_extreme_reviews,
)
from v1_4.core.runner import (
    HISTORY_COMPRESS_TRIGGER_RECORDS,
    HISTORY_KEEP_RECENT,
    HISTORY_MAX_CHARS,
    _history_chars,
    _history_record,
)
from v1_4.reflect import _apply_rule_operations, _trim_prompt


def _play_event(step: int, ante: int, round_num: int, chips: int, after_chips: int, hands: int, after_state: str) -> dict:
    after_ante = ante + 1 if round_num == ante * 3 and after_state == "ROUND_EVAL" else ante
    return {
        "step": step,
        "stage": "PLAY",
        "action": "play",
        "joker_signature": ["Joker A"],
        "decision": {"action": "play", "cards": [0, 1], "reason": "Concrete short reason."},
        "observation": {
            "state": {"blinds": {"boss": {"status": "CURRENT", "score": 600}}},
            "boss": {"name": "The Test", "effect": "test effect", "score": 600},
        },
        "before": {
            "state": "SELECTING_HAND", "ante": ante, "round": round_num, "chips": chips,
            "hands_left": hands, "discards_left": 3, "money": 4,
        },
        "after": {
            "state": after_state, "ante": after_ante, "round": round_num, "chips": after_chips,
            "hands_left": hands - 1, "discards_left": 3, "money": 4,
        },
    }


class EffortTests(unittest.TestCase):
    def test_boss_clear_and_loss_are_review_boundaries(self) -> None:
        clear = _play_event(1, 1, 3, 0, 700, 4, "ROUND_EVAL")
        self.assertEqual(ante_review_outcome(clear), (1, False))
        loss = _play_event(2, 2, 4, 100, 200, 1, "GAME_OVER")
        self.assertEqual(ante_review_outcome(loss), (2, True))

    def test_loss_score_is_forced_to_ten(self) -> None:
        loss = _play_event(1, 2, 4, 100, 200, 1, "GAME_OVER")
        trajectory = build_ante_trajectory(2, [loss], failed=True)
        review = normalize_effort_review({"effort_score": 2, "summary": "easy"}, trajectory)
        self.assertEqual(review["effort_score"], 10)
        self.assertTrue(review["forced_loss_score"])

    def test_shop_state_does_not_overwrite_blind_resource_margin(self) -> None:
        play = _play_event(1, 1, 1, 0, 400, 2, "ROUND_EVAL")
        shop = {
            "step": 2, "stage": "SHOP", "action": "buy", "decision": {"target": "card0"},
            "before": {"ante": 1, "round": 1, "hands_left": 4, "discards_left": 4, "money": 8},
            "after": {"ante": 1, "round": 1, "hands_left": 4, "discards_left": 4, "money": 4, "state": "SHOP"},
        }
        trajectory = build_ante_trajectory(1, [play, shop], failed=False)
        self.assertEqual(trajectory["rounds"][0]["hands_left"], 1)

    def test_extreme_selection_does_not_overlap(self) -> None:
        items = [
            {"created_at": str(i), "review": {"ante": i, "effort_score": i, "outcome": "CLEARED"}, "trajectory": {"totals": {"actions": i}}}
            for i in range(1, 8)
        ]
        hardest, easiest = select_extreme_reviews(items, 3)
        self.assertEqual([x["review"]["effort_score"] for x in hardest], [7, 6, 5])
        self.assertEqual([x["review"]["effort_score"] for x in easiest], [1, 2, 3])


class ReflectOperationTests(unittest.TestCase):
    def test_incremental_operations_are_bounded_and_validated(self) -> None:
        rules = ["one", "two", "three"]
        operations = [
            {"op": "update", "target_id": "R2", "rule": "two updated", "reason": "contrast"},
            {"op": "delete", "target_id": "R3", "rule": "", "reason": "contradicted"},
            {"op": "add", "target_id": "", "rule": "four", "reason": "new evidence"},
            {"op": "update", "target_id": "R2", "rule": "bad", "reason": "duplicate edit"},
        ]
        updated, applied, rejected = _apply_rule_operations(rules, operations, 6)
        self.assertEqual(updated, ["one", "two updated", "four"])
        self.assertEqual(len(applied), 3)
        self.assertEqual(rejected[0]["rejected"], "target already edited")

    def test_ante_prompt_trim_honors_character_limit(self) -> None:
        sample = {
            "review": {"ante": 1, "effort_score": 8, "evidence": ["x" * 2000]},
            "trajectory": {
                "events": [{"step": i, "reason": "x" * 1000, "before": {"chips": i}, "after": {"chips": i + 1}} for i in range(40)],
                "shop_actions": [{"action": "buy", "reason": "y" * 1000} for _ in range(20)],
            },
        }
        prompt = _trim_prompt({"hardest_antes": [sample], "easiest_antes": [sample]}, 8000)
        self.assertLessEqual(len(json.dumps(prompt, ensure_ascii=False)), 8000)


class CompactTests(unittest.TestCase):
    def test_recent_history_is_compact_and_threshold_is_not_five_actions(self) -> None:
        event = _play_event(1, 1, 1, 0, 100, 4, "SELECTING_HAND")
        event["decision"]["commentary"] = "x" * 1000
        record = _history_record(event)
        self.assertNotIn("commentary", record)
        self.assertLessEqual(len(record["why"]), 140)
        recent = [dict(record, step=i) for i in range(HISTORY_COMPRESS_TRIGGER_RECORDS)]
        self.assertGreater(HISTORY_KEEP_RECENT, 8)
        self.assertLessEqual(_history_chars("", recent), HISTORY_MAX_CHARS)


class LoopRestartTests(unittest.TestCase):
    @staticmethod
    def _args(out: Path, games: int) -> SimpleNamespace:
        return SimpleNamespace(
            games_per_iter=games, balatrobot_host="127.0.0.1", balatrobot_port=12346,
            auto_restart_game=True, out_dir=str(out), model="m", provider="qwen",
            decision_format="tool", think=False, reasoning_effort="low", thinking_budget=0,
            llm_log_io=False, balatrobot_serve_command="", balatrobot_health_timeout=1,
        )

    def test_win_then_health_loss_restarts_before_next_game(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            (out / "runs").mkdir(parents=True)
            args = self._args(out, 2)
            calls = {"health": 0, "restart": 0, "agent": 0}

            def health(*_args: object) -> bool:
                calls["health"] += 1
                return calls["health"] == 1

            def restart(*_args: object) -> tuple[None, str]:
                calls["restart"] += 1
                return None, ""

            def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
                calls["agent"] += 1
                path = out / "runs" / f"{calls['agent']}.json"
                path.write_text(json.dumps({"result": {"won": calls["agent"] == 1}}), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch.object(loop, "_balatrobot_healthy", side_effect=health), patch.object(
                loop, "_restart_balatrobot", side_effect=restart
            ), patch.object(loop.subprocess, "run", side_effect=run), patch.object(loop.time, "sleep"):
                completed, error, serve_process = loop._run_games_individually(args, root, root / "state.json", {})
            self.assertEqual((completed, error), (2, ""))
            self.assertIsNone(serve_process)
            self.assertEqual(calls["restart"], 1)

    def test_zero_exit_without_run_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            (out / "runs").mkdir(parents=True)
            args = self._args(out, 1)
            with patch.object(loop, "_balatrobot_healthy", return_value=True), patch.object(
                loop, "_restart_balatrobot", return_value=(None, "")
            ), patch.object(loop.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                completed, error, _ = loop._run_games_individually(args, root, root / "state.json", {})
            self.assertEqual(completed, 0)
            self.assertIn("produced no run record", error)

    def test_managed_serve_is_stopped_but_external_none_is_ignored(self) -> None:
        process = SimpleNamespace(poll=lambda: None, terminate=unittest.mock.Mock(), wait=unittest.mock.Mock())
        loop._stop_managed_serve(None)
        loop._stop_managed_serve(process)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
