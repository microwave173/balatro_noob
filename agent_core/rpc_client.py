import json
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional


class JsonRpcClient:
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        on_result: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.url = f"http://{host}:{port}"
        self.timeout = timeout
        self.on_result = on_result

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, retries: int = 1) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": 1}
        if params is not None:
            payload["params"] = params
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_err: Optional[Exception] = None
        for _ in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
                if "error" in out:
                    err = out["error"]
                    name = err.get("data", {}).get("name", "RPC_ERROR")
                    raise RuntimeError(f"{name}: {err.get('message', 'unknown error')}")
                result = out["result"]
                if self.on_result and isinstance(result, dict):
                    try:
                        self.on_result(method, result)
                    except Exception:
                        pass
                return result
            except Exception as e:
                last_err = e
                time.sleep(0.08)
        raise last_err if last_err else RuntimeError("unknown rpc error")


def wait_for_state(
    rpc: JsonRpcClient,
    target_states: List[str],
    timeout_sec: float = 8.0,
    poll_sec: float = 0.08,
) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            state = rpc.call("gamestate", retries=0)
            if state.get("state") in target_states:
                return state
        except Exception:
            pass
        time.sleep(poll_sec)
    return None
