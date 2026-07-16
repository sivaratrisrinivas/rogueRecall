from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "roguerecall.cli", "dashboard", "--runs-root", ".qualification-runs", "--port", "0", "--no-open"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        line = process.stdout.readline().strip()
        url = line.removeprefix("Read-only dashboard: ")
        results = []
        with sync_playwright() as playwright:
            for engine_name in ("chromium", "firefox", "webkit"):
                browser = getattr(playwright, engine_name).launch()
                page = browser.new_page(viewport={"width": 320, "height": 720}, reduced_motion="reduce")
                page.goto(url)
                page.get_by_role("heading", name="RogueRecall Evaluation Run").wait_for()
                page.keyboard.press("Tab")
                focused = page.evaluate("document.activeElement !== document.body")
                no_horizontal_overflow = page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
                reduced = page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                results.append({"engine": engine_name, "heading": True, "keyboard_focus": focused, "narrow_screen": no_horizontal_overflow, "reduced_motion": reduced, "outcome": "passed" if focused and no_horizontal_overflow and reduced else "failed"})
                browser.close()
        output = Path("browser-qualification.json")
        output.write_text(json.dumps({"schema_version": "1.0.0", "results": results}, indent=2) + "\n")
        if any(result["outcome"] != "passed" for result in results):
            raise SystemExit(1)
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
