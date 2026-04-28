import argparse
import json
import os
import queue
import threading
import time
import ctypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI
import tkinter as tk


@dataclass
class CommentaryItem:
    key: str
    label: str
    updated_at: str
    original: str
    text: str
    translated: bool = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Topmost Balatro LLM commentary overlay")
    p.add_argument("--state-file", default="state.json")
    p.add_argument("--poll-ms", type=int, default=500)
    p.add_argument("--max-items", type=int, default=4)
    p.add_argument("--width", type=int, default=430)
    p.add_argument("--x-margin", type=int, default=0)
    p.add_argument("--y-margin", type=int, default=0)
    p.add_argument("--font-size", type=int, default=13)
    p.add_argument("--text-color", default="#fff3a3")
    p.add_argument("--meta-color", default="#b7f7ff")
    p.add_argument("--transparent-color", default="#010203")
    p.add_argument("--qwen-model", default=os.getenv("QWEN_TRANSLATE_MODEL", "qwen3.5-flash"))
    p.add_argument("--qwen-url", default=os.getenv("QWEN_BASE_URL", os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")))
    p.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")))
    p.add_argument("--no-translate", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--test-translate", action="store_true", help="Test Qwen translation once and exit")
    return p.parse_args()


class CommentaryOverlay:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.state_path = Path(args.state_file)
        if not self.state_path.is_absolute():
            self.state_path = (Path.cwd() / self.state_path).resolve()
        self.items: List[CommentaryItem] = []
        self.seen: set[str] = set()
        self.ui_queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="commentary_translate")
        self.client: Optional[OpenAI] = None
        if args.qwen_api_key and not args.no_translate:
            self.client = OpenAI(api_key=args.qwen_api_key, base_url=args.qwen_url, timeout=45)
        if args.debug:
            print(f"[overlay] state_file={self.state_path}")
            print(f"[overlay] qwen_model={args.qwen_model} translate={bool(self.client)}")

        self.root = tk.Tk()
        self.root.title("Balatro Commentary")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.configure(bg=args.transparent_color)
        self.root.wm_attributes("-transparentcolor", args.transparent_color)

        self.frame = tk.Frame(self.root, bg=args.transparent_color, padx=0, pady=0)
        self.frame.pack(fill="both", expand=True)
        self.status = tk.Label(
            self.frame,
            text=self._status_text(),
            bg=args.transparent_color,
            fg=args.meta_color,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
        )
        self.body = tk.Frame(self.frame, bg=args.transparent_color)
        self.body.pack(fill="both", expand=True)

        self._place_window()
        self._bind_drag()
        self.root.after(100, self._poll_ui_queue)
        self.root.after(100, self._render)
        self.root.after(500, self._keep_topmost)

        self.reader = threading.Thread(target=self._reader_loop, name="commentary_state_reader", daemon=True)
        self.reader.start()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.stop_event.set()
            self.executor.shutdown(wait=False, cancel_futures=True)

    def _status_text(self) -> str:
        if self.args.no_translate:
            mode = "translation off"
        elif self.client:
            mode = f"translating via {self.args.qwen_model}"
        else:
            mode = "QWEN_API_KEY missing"
        return f"Balatro commentary | {mode} | Esc closes"

    def _place_window(self) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = int(self.args.width)
        x = max(0, screen_w - width - int(self.args.x_margin))
        height = 260
        y = max(0, (screen_h - height) // 2 + int(self.args.y_margin))
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _keep_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", False)
            self.root.attributes("-topmost", True)
            self.root.lift()
            hwnd = self.root.winfo_id()
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception:
            pass
        self.root.after(1000, self._keep_topmost)

    def _bind_drag(self) -> None:
        self._drag_start: tuple[int, int] | None = None

        def start(event: Any) -> None:
            self._drag_start = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

        def move(event: Any) -> None:
            if not self._drag_start:
                return
            dx, dy = self._drag_start
            self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

        self.root.bind("<ButtonPress-1>", start)
        self.root.bind("<B1-Motion>", move)
        self.root.bind("<Escape>", lambda _event: self.root.destroy())

    def _reader_loop(self) -> None:
        last_mtime = 0.0
        while not self.stop_event.is_set():
            try:
                mtime = self.state_path.stat().st_mtime
            except FileNotFoundError:
                time.sleep(self.args.poll_ms / 1000)
                continue
            if mtime != last_mtime:
                last_mtime = mtime
                item = self._read_latest_commentary()
                if item and item.key not in self.seen:
                    self.seen.add(item.key)
                    self.ui_queue.put(("add", item.key, json.dumps(item.__dict__, ensure_ascii=False)))
                    if self.args.debug:
                        print(f"[overlay] new commentary {item.label}: {item.original[:120]}")
                    if self.client and not self.args.no_translate:
                        self.executor.submit(self._translate_and_queue, item)
            time.sleep(self.args.poll_ms / 1000)

    def _read_latest_commentary(self) -> Optional[CommentaryItem]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None
        live = data.get("live") if isinstance(data.get("live"), dict) else {}
        commentary = str(live.get("commentary") or "").strip()
        if not commentary:
            return None
        label = str(live.get("commentary_label") or "LLM")
        updated_at = str(live.get("commentary_updated_at") or live.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        key = f"{updated_at}|{label}|{commentary}"
        return CommentaryItem(key=key, label=label, updated_at=updated_at, original=commentary, text=commentary)

    def _translate_and_queue(self, item: CommentaryItem) -> None:
        translated = self._translate(item.original)
        if translated:
            if self.args.debug:
                print(f"[overlay] translated {item.label}: {translated[:120]}")
            self.ui_queue.put(("translate", item.key, translated))

    def _translate(self, text: str) -> str:
        if not self.client:
            return ""
        prompt = (
            "Translate this Balatro game commentary into concise natural Chinese. "
            "Keep card/Joker names readable; preserve numbers, money, hand names, and short strategic meaning. "
            "Return only the Chinese commentary, no quotes or markdown.\n\n"
            f"{text}"
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.args.qwen_model,
                messages=[
                    {"role": "system", "content": "You are a concise English-to-Chinese game commentary translator."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=500,
                extra_body={"enable_thinking": False},
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            if self.args.debug:
                print(f"[overlay] translation failed: {e}")
            return f"[translation failed] {e}"

    def _poll_ui_queue(self) -> None:
        changed = False
        while True:
            try:
                action, key, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if action == "add":
                data = json.loads(payload)
                self.items.append(CommentaryItem(**data))
                self.items = self.items[-int(self.args.max_items) :]
                changed = True
            elif action == "translate":
                for item in self.items:
                    if item.key == key:
                        item.text = payload
                        item.translated = True
                        changed = True
                        break
        if changed:
            self._render()
        self.root.after(100, self._poll_ui_queue)

    def _render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        if not self.items:
            tk.Label(
                self.body,
                text="Waiting for commentary...",
                bg=self.args.transparent_color,
                fg=self.args.text_color,
                anchor="w",
                justify="left",
                wraplength=max(250, int(self.args.width) - 30),
                font=("Microsoft YaHei UI", int(self.args.font_size)),
            ).pack(fill="x")
        else:
            for item in self.items[-int(self.args.max_items) :]:
                self._render_item(item)

        self.root.update_idletasks()
        width = int(self.args.width)
        height = max(70, self.frame.winfo_reqheight())
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        if self.args.x_margin == 0:
            screen_w = self.root.winfo_screenwidth()
            x = max(0, screen_w - width)
        if self.args.y_margin == 0:
            screen_h = self.root.winfo_screenheight()
            y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _render_item(self, item: CommentaryItem) -> None:
        box = tk.Frame(self.body, bg=self.args.transparent_color, padx=0, pady=0)
        box.pack(fill="x", pady=(0, 10))
        meta = f"{item.updated_at}  {item.label}"
        if item.translated:
            meta += "  CN"
        else:
            meta += "  EN"
        tk.Label(
            box,
            text=meta,
            bg=self.args.transparent_color,
            fg=self.args.meta_color,
            anchor="w",
            font=("Microsoft YaHei UI", max(8, int(self.args.font_size) - 4)),
        ).pack(fill="x")
        tk.Label(
            box,
            text=item.text,
            bg=self.args.transparent_color,
            fg=self.args.text_color,
            anchor="w",
            justify="left",
            wraplength=max(250, int(self.args.width) - 40),
            font=("Microsoft YaHei UI", int(self.args.font_size), "bold"),
        ).pack(fill="x", pady=(3, 0))


def main() -> None:
    args = parse_args()
    if args.test_translate:
        if not args.qwen_api_key:
            print("[overlay] QWEN_API_KEY is empty")
            return
        client = OpenAI(api_key=args.qwen_api_key, base_url=args.qwen_url, timeout=45)
        resp = client.chat.completions.create(
            model=args.qwen_model,
            messages=[
                {"role": "system", "content": "You translate English to Chinese. Return only Chinese."},
                {"role": "user", "content": "Taking Venus to boost Three of a Kind level."},
            ],
            temperature=0.2,
            max_tokens=200,
            extra_body={"enable_thinking": False},
        )
        print((resp.choices[0].message.content or "").strip())
        return
    CommentaryOverlay(args).run()


if __name__ == "__main__":
    main()
