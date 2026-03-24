"""
preCICE Documentation Typo Checker — Permalink-driven
======================================================
Reads a list of permalinks from a .txt file, constructs full URLs,
scrapes each page, checks for TYPOS using Gemini, and produces a report.

Usage:
    python 22.py --api-key YOUR_GEMINI_API_KEY

Options:
    --permalinks  Path to permalinks.txt              [default: /home/nishant/Desktop/1/permalinks.txt]
    --base-url    Base URL of the Jekyll site         [default: http://127.0.0.1:4000]
    --api-key     Gemini API key                      [required, or set GEMINI_API_KEY env var]
    --output      Output directory for results         [default: ./grammar-report]
    --delay       Delay between pages in seconds       [default: 1]
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from google import genai
from playwright.sync_api import sync_playwright


# ─── Config ───────────────────────────────────────────────────────────────────

MODEL_NAME = "gemini-2.5-pro"

TYPO_PROMPT = """You are a spell-checker for technical documentation. Your ONLY job is to find TYPOS — misspelled English words.

ONLY report:
- Clearly misspelled English words (e.g. "teh" instead of "the", "occured" instead of "occurred")
- Doubled words (e.g. "the the")

DO NOT report:
- Grammar issues, punctuation, style, or sentence structure
- Technical terms, library names, variable names, function names
- Command-line arguments, file paths, URLs, config keys
- Abbreviations, acronyms (e.g. API, CPU, preCICE, OpenFOAM)
- Code snippets or anything inside backticks
- Version numbers, package names
- Words that are valid in either American or British English

For each typo found, respond in this exact JSON format (array of objects):
[
  {
    "typo": "the misspelled word exactly as it appears",
    "correction": "the correctly spelled word",
    "original_text": "the surrounding sentence or phrase (up to 20 words of context)",
    "url": ""
  }
]

If there are NO typos, respond with exactly: []

TEXT TO CHECK:
"""


# ─── Permalink loader ─────────────────────────────────────────────────────────

def load_permalinks(txt_path: Path, base_url: str) -> list[tuple[str, str]]:
    """
    Reads permalinks.txt produced by extract_permalinks.py.
    Returns list of (permalink, full_url) tuples.

    Expected format (repeating):
        some-page.html
          source: docs/foo/some-page.md
        <blank line>
    """
    if not txt_path.exists():
        print(f"❌ Permalinks file not found: {txt_path}")
        sys.exit(1)

    base = base_url.rstrip("/")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    raw_lines = txt_path.read_text(encoding="utf-8").splitlines()

    print(f"📋 Reading permalinks from: {txt_path}")
    print(f"   Total lines in file: {len(raw_lines)}")

    for line in raw_lines:
        stripped = line.strip()

        # Skip blanks, header lines, source lines, and separator lines
        if not stripped:
            continue
        if stripped.startswith("source:"):
            continue
        if stripped.startswith("preCICE") or stripped.startswith("Generated") \
                or stripped.startswith("Total") or stripped.startswith("="):
            continue

        # What's left should be a permalink like "some-page.html" or "/some/path/"
        permalink = stripped.lstrip("/")

        if not permalink or permalink in seen:
            continue

        seen.add(permalink)
        full_url = f"{base}/{permalink}"
        entries.append((permalink, full_url))

    print(f"   Unique permalinks loaded: {len(entries)}")
    return entries


# ─── Screenshot helper ────────────────────────────────────────────────────────

def take_section_screenshot(page, output_path: Path, error_text: str) -> str | None:
    screenshot_file = str(output_path)
    print(f"  📸 Attempting screenshot for: \"{error_text[:40].strip()}...\"")
    try:
        search_text = error_text[:40].strip()
        locator = page.get_by_text(search_text, exact=False).first
        if locator.count() > 0:
            locator.scroll_into_view_if_needed()
            time.sleep(0.3)
            box = locator.bounding_box()
            if box:
                clip = {
                    "x": max(0, box["x"] - 20),
                    "y": max(0, box["y"] - 40),
                    "width": min(1280, box["width"] + 40),
                    "height": min(600, box["height"] + 80),
                }
                page.screenshot(path=screenshot_file, clip=clip)
                print(f"  📸 Section screenshot saved: {output_path.name}")
                return screenshot_file
        else:
            print(f"  📸 Text not found on page — falling back to viewport screenshot")
    except Exception as e:
        print(f"  ⚠  Screenshot locator failed: {e} — falling back to viewport screenshot")

    try:
        page.screenshot(path=screenshot_file, full_page=False)
        print(f"  📸 Fallback viewport screenshot saved: {output_path.name}")
        return screenshot_file
    except Exception as e:
        print(f"  ⚠  Screenshot failed entirely: {e}")
        return None


# ─── Gemini typo checker ──────────────────────────────────────────────────────

def check_typos(client, text: str) -> list[dict]:
    if not text or len(text.strip()) < 50:
        print(f"  ⏭  Text too short ({len(text.strip())} chars) — skipping Gemini call")
        return []

    MAX_CHARS = 8000
    chunks = [text[i:i + MAX_CHARS] for i in range(0, min(len(text), 24000), MAX_CHARS)]
    print(f"  🤖 Sending {len(chunks)} chunk(s) to Gemini ({len(text):,} chars total)...")

    all_typos = []
    for idx, chunk in enumerate(chunks, 1):
        print(f"  🤖 Chunk {idx}/{len(chunks)} ({len(chunk):,} chars)...", end=" ", flush=True)
        t0 = time.time()
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=TYPO_PROMPT + chunk,
            )
            elapsed = time.time() - t0
            raw = response.text.strip()
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            typos = json.loads(raw)
            if isinstance(typos, list):
                all_typos.extend(typos)
                print(f"done in {elapsed:.1f}s — {len(typos)} typo(s) found")
            else:
                print(f"done in {elapsed:.1f}s — unexpected response shape, skipping")
        except json.JSONDecodeError as e:
            print(f"⚠  JSON parse error: {e} | raw response: {raw[:80]!r}")
        except Exception as e:
            print(f"⚠  Gemini error: {e}")

    print(f"  🤖 Gemini check complete — {len(all_typos)} total typo(s) across all chunks")
    return all_typos


# ─── Page text extractor ──────────────────────────────────────────────────────

def extract_page_text(page) -> str:
    print(f"  📄 Extracting page text (stripping nav/code/footer)...")
    text = page.evaluate("""() => {
        const skip = ['nav', 'footer', 'header', 'script', 'style', 'code', 'pre',
                       '.topnav', '.sidebar', '#sidebar', '.breadcrumb', '.toc',
                       '[class*="highlight"]', '[class*="code"]'];
        const clone = document.body.cloneNode(true);
        skip.forEach(sel => {
            clone.querySelectorAll(sel).forEach(el => el.remove());
        });
        return clone.innerText || clone.textContent || '';
    }""")
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    print(f"  📄 Extracted {len(text):,} chars of content")
    return text


# ─── Main agent ───────────────────────────────────────────────────────────────

def run_agent(permalinks_file: str, base_url: str, api_key: str,
              output_dir: str, delay: float):

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    screenshots_dir = out / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    report_json = out / "report.json"

    # ── Load all permalinks up front ──────────────────────────────────────────
    entries = load_permalinks(Path(permalinks_file), base_url)
    total_pages = len(entries)

    print(f"\n{'='*60}")
    print(f"  preCICE Typo Checker — Permalink Mode")
    print(f"{'='*60}")
    print(f"  Model        : {MODEL_NAME}")
    print(f"  Base URL     : {base_url}")
    print(f"  Permalinks   : {permalinks_file}")
    print(f"  Pages queued : {total_pages}")
    print(f"  Output       : {out.resolve()}")
    print(f"  Delay        : {delay}s between pages")
    print(f"{'='*60}\n")

    if total_pages == 0:
        print("❌ No permalinks found — check your permalinks.txt format.")
        sys.exit(1)

    print(f"⚙  Initialising Gemini client...")
    client = genai.Client(api_key=api_key)
    print(f"⚙  Gemini client ready\n")

    all_results = []
    pages_checked = 0
    pages_skipped = 0
    total_typos = 0
    pages_with_typos = 0
    start_time = time.time()

    with sync_playwright() as pw:
        print(f"🌐 Launching headless Chromium browser...")
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        print(f"🌐 Browser ready\n")

        for idx, (permalink, url) in enumerate(entries, 1):
            elapsed_total = time.time() - start_time
            eta_per_page  = elapsed_total / idx if idx > 1 else 0
            eta_remaining = eta_per_page * (total_pages - idx)

            print(f"\n[{idx}/{total_pages}] ({elapsed_total:.0f}s elapsed"
                  f"{f', ~{eta_remaining:.0f}s remaining' if eta_remaining else ''}) → {url}")

            pages_checked += 1

            try:
                print(f"  🌐 Navigating to page...")
                t0 = time.time()
                response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                load_time = time.time() - t0

                if not response or response.status >= 400:
                    status = response.status if response else '?'
                    print(f"  ✗ HTTP {status} — skipping this page")
                    pages_skipped += 1
                    all_results.append({
                        "url": url,
                        "permalink": permalink,
                        "page_number": idx,
                        "skipped": True,
                        "skip_reason": f"HTTP {status}",
                        "typos": [],
                    })
                    continue

                print(f"  🌐 Page loaded in {load_time:.2f}s (HTTP {response.status})")

                text = extract_page_text(page)
                typos = check_typos(client, text)

                page_result = {
                    "url": url,
                    "permalink": permalink,
                    "page_number": idx,
                    "checked_at": datetime.now().isoformat(),
                    "typo_count": len(typos),
                    "typos": [],
                }

                if typos:
                    pages_with_typos += 1
                    print(f"  ✗ Found {len(typos)} typo(s) on this page:")
                    for i, typo in enumerate(typos):
                        total_typos += 1
                        typo_id = f"p{idx}_t{i + 1}"

                        print(f"    [{i + 1}/{len(typos)}] ✏  '{typo.get('typo', '?')}'"
                              f" → '{typo.get('correction', '?')}'")
                        print(f"         Context: \"{typo.get('original_text', '')[:70]}\"")

                        ss_filename = screenshots_dir / f"{typo_id}.png"
                        ss_path = take_section_screenshot(
                            page, ss_filename, typo.get("original_text", "")
                        )

                        typo["screenshot"] = str(ss_path) if ss_path else None
                        typo["typo_id"] = typo_id
                        typo["url"] = url
                        page_result["typos"].append(typo)
                else:
                    print(f"  ✓ No typos found on this page")

                all_results.append(page_result)

            except Exception as e:
                print(f"  ✗ Unhandled error: {type(e).__name__}: {e}")
                pages_skipped += 1
                all_results.append({
                    "url": url,
                    "permalink": permalink,
                    "page_number": idx,
                    "error": str(e),
                    "typos": [],
                })

            # ── Save report after every page ──────────────────────────────────
            print(f"  💾 Saving report.json ({idx}/{total_pages} pages, {total_typos} typo(s))...")
            with open(report_json, "w", encoding="utf-8") as f:
                json.dump({
                    "meta": {
                        "base_url": base_url,
                        "permalinks_file": str(permalinks_file),
                        "model": MODEL_NAME,
                        "check_type": "typos_only",
                        "generated_at": datetime.now().isoformat(),
                        "total_pages": total_pages,
                        "pages_checked": pages_checked,
                        "pages_skipped": pages_skipped,
                        "pages_with_typos": pages_with_typos,
                        "total_typos": total_typos,
                    },
                    "pages": all_results,
                }, f, indent=2, ensure_ascii=False)
            print(f"  💾 report.json saved")

            if delay > 0:
                print(f"  ⏳ Waiting {delay}s before next page...")
                time.sleep(delay)

        print(f"\n🌐 Closing browser...")
        browser.close()
        print(f"🌐 Browser closed")

    total_elapsed = time.time() - start_time
    avg_per_page  = total_elapsed / pages_checked if pages_checked else 0

    print(f"\n{'='*60}")
    print(f"  ✅ Agent finished!")
    print(f"{'='*60}")
    print(f"  Model              : {MODEL_NAME}")
    print(f"  Total pages        : {total_pages}")
    print(f"  Pages checked      : {pages_checked}")
    print(f"  Pages skipped      : {pages_skipped}")
    print(f"  Pages with typos   : {pages_with_typos}")
    print(f"  Pages clean        : {pages_checked - pages_with_typos - pages_skipped}")
    print(f"  Total typos found  : {total_typos}")
    print(f"  Total time elapsed : {total_elapsed:.1f}s")
    print(f"  Avg time per page  : {avg_per_page:.1f}s")
    print(f"  JSON report        : {report_json.resolve()}")
    print(f"  Screenshots        : {screenshots_dir.resolve()}/")
    print(f"{'='*60}")
    print(f"\n  Now run: python generate_report.py\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Permalink-driven typo checker for preCICE docs"
    )
    parser.add_argument("--permalinks", default="/home/nishant/Desktop/1/permalinks.txt")
    parser.add_argument("--base-url",   default="http://127.0.0.1:4000")
    parser.add_argument("--api-key",    default=os.getenv("GEMINI_API_KEY", ""))
    parser.add_argument("--output",     default="./grammar-report")
    parser.add_argument("--delay",      type=float, default=1.0)

    args = parser.parse_args()

    if not args.api_key:
        print("❌ ERROR: Gemini API key is required.")
        print("   Pass --api-key YOUR_KEY  or  export GEMINI_API_KEY=YOUR_KEY")
        sys.exit(1)

    run_agent(
        permalinks_file=args.permalinks,
        base_url=args.base_url,
        api_key=args.api_key,
        output_dir=args.output,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()