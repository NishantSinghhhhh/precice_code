
import json
import argparse
from pathlib import Path


# ─── Helpers ──────────────────────────────────────────────────────────────────

def permalink_to_md(permalink: str, docs_root: Path) -> Path | None:
    """
    Convert a permalink like 'adapter-calculix-config.html'
    to a .md source file path under docs_root.

    Tries common Jekyll/Docusaurus layouts:
        docs_root/<name>.md
        docs_root/docs/<name>.md
        docs_root/pages/<name>.md
    """
    stem = Path(permalink).stem  # e.g. 'adapter-calculix-config'

    candidates = [
        docs_root / f"{stem}.md",
        docs_root / "docs" / f"{stem}.md",
        docs_root / "pages" / f"{stem}.md",
        docs_root / "_docs" / f"{stem}.md",
        docs_root / "website" / "docs" / f"{stem}.md",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def fix_typo_in_text(content: str, original_text: str, typo: str, correction: str) -> tuple[str, bool]:
    """
    Find the original_text snippet in content and replace the typo word with correction.
    Returns (updated_content, was_changed).
    """
    if original_text not in content:
        return content, False

    fixed_snippet = original_text.replace(typo, correction, 1)
    updated = content.replace(original_text, fixed_snippet, 1)
    return updated, updated != content


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-fix typos in docs using report.json")
    parser.add_argument("--json",    default="grammar-report/report.json", help="Path to report JSON")
    parser.add_argument("--docs",    default=".",                           help="Root of docs source files")
    parser.add_argument("--dry-run", action="store_true",                   help="Preview changes without writing")
    args = parser.parse_args()

    json_path  = Path(args.json)
    docs_root  = Path(args.docs)

    if not json_path.exists():
        print(f"❌  JSON not found: {json_path}")
        return

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", [])

    total_fixed   = 0
    total_skipped = 0
    not_found     = 0

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Starting typo fixes...\n")

    for page in pages:
        typos = page.get("typos", [])
        if not typos:
            continue

        permalink = page.get("permalink", "")
        md_file   = permalink_to_md(permalink, docs_root)

        if not md_file:
            print(f"  ⚠️  Source file not found for: {permalink}")
            not_found += len(typos)
            continue

        content = md_file.read_text(encoding="utf-8")
        modified = False

        for typo_entry in typos:
            typo_word    = typo_entry.get("typo", "")
            correction   = typo_entry.get("correction", "")
            original_text = typo_entry.get("original_text", "")
            typo_id      = typo_entry.get("typo_id", "?")

            content, changed = fix_typo_in_text(content, original_text, typo_word, correction)

            if changed:
                print(f"  ✅  [{typo_id}] '{typo_word}' → '{correction}'  ({md_file.name})")
                total_fixed += 1
                modified = True
            else:
                print(f"  ⚠️  [{typo_id}] context not matched in file: '{original_text[:60]}...'")
                total_skipped += 1

        if modified and not args.dry_run:
            md_file.write_text(content, encoding="utf-8")

    # ── Summary ──
    print(f"\n{'─'*50}")
    print(f"  Fixed   : {total_fixed}")
    print(f"  Skipped : {total_skipped}  (context not found in file)")
    print(f"  Missing : {not_found}  (source .md file not found)")
    if args.dry_run:
        print(f"\n  Dry run — no files were written.")
    else:
        print(f"\n  Done. Files updated in: {docs_root.resolve()}")


if __name__ == "__main__":
    main()