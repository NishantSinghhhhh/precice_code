#!/usr/bin/env python3
"""
Jekyll to Hugo Migration Analyzer
===================================
Scans a Jekyll codebase and produces a detailed migration report
telling you exactly what changes are needed in each file.

Usage:
    python3 jekyll_to_hugo_analyzer.py /path/to/jekyll/site

Output:
    - migration_report.md   → Full detailed report
    - migration_summary.txt → Quick overview
"""

import os
import re
import sys
import json
from pathlib import Path
from collections import defaultdict

# ── ANSI colors for terminal output ──
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ══════════════════════════════════════════════════════════════════
# PATTERN DEFINITIONS
# Each entry: (regex_pattern, description, hugo_equivalent, severity)
# severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
# ══════════════════════════════════════════════════════════════════

LIQUID_PATTERNS = [
    # Variables
    (r'\{\{\s*site\.title\s*\}\}',         "Jekyll site.title",             "{{ .Site.Title }}",                          "HIGH"),
    (r'\{\{\s*site\.description\s*\}\}',   "Jekyll site.description",       "{{ .Site.Params.description }}",             "HIGH"),
    (r'\{\{\s*site\.url\s*\}\}',           "Jekyll site.url",               "{{ .Site.BaseURL }}",                        "HIGH"),
    (r'\{\{\s*site\.baseurl\s*\}\}',       "Jekyll site.baseurl",           "{{ .Site.BaseURL }}",                        "HIGH"),
    (r'\{\{\s*site\.data\.',               "Jekyll site.data access",       "{{ .Site.Data. }}",                          "HIGH"),
    (r'\{\{\s*site\.pages\s*\}\}',         "Jekyll site.pages",             "{{ .Site.Pages }}",                          "HIGH"),
    (r'\{\{\s*site\.posts\s*\}\}',         "Jekyll site.posts",             "{{ where .Site.RegularPages 'Type' 'posts' }}", "HIGH"),
    (r'\{\{\s*site\.categories\s*\}\}',    "Jekyll site.categories",        "{{ .Site.Taxonomies.categories }}",          "HIGH"),
    (r'\{\{\s*site\.tags\s*\}\}',          "Jekyll site.tags",              "{{ .Site.Taxonomies.tags }}",                "HIGH"),
    (r'\{\{\s*page\.title\s*\}\}',         "Jekyll page.title",             "{{ .Title }}",                               "HIGH"),
    (r'\{\{\s*page\.content\s*\}\}',       "Jekyll page.content",           "{{ .Content }}",                             "HIGH"),
    (r'\{\{\s*page\.url\s*\}\}',           "Jekyll page.url",               "{{ .RelPermalink }}",                        "HIGH"),
    (r'\{\{\s*page\.date\s*\}\}',          "Jekyll page.date",              "{{ .Date }}",                                "HIGH"),
    (r'\{\{\s*page\.excerpt\s*\}\}',       "Jekyll page.excerpt",           "{{ .Summary }}",                             "HIGH"),
    (r'\{\{\s*page\.categories\s*\}\}',    "Jekyll page.categories",        "{{ .Params.categories }}",                   "MEDIUM"),
    (r'\{\{\s*page\.tags\s*\}\}',          "Jekyll page.tags",              "{{ .Params.tags }}",                         "MEDIUM"),
    (r'\{\{\s*page\.next\s*\}\}',          "Jekyll page.next",              "{{ .Next }}",                                "MEDIUM"),
    (r'\{\{\s*page\.previous\s*\}\}',      "Jekyll page.previous",          "{{ .Prev }}",                                "MEDIUM"),
    (r'\{\{\s*page\.layout\s*\}\}',        "Jekyll page.layout",            "{{ .Layout }}",                              "LOW"),
    (r'\{\{\s*page\.path\s*\}\}',          "Jekyll page.path",              "{{ .File.Path }}",                           "LOW"),
    (r'\{\{\s*page\.dir\s*\}\}',           "Jekyll page.dir",               "{{ .File.Dir }}",                            "LOW"),

    # Includes → Partials
    (r'\{%[-\s]*include\s+(\S+)',          "Jekyll include tag",            "{{ partial 'FILENAME' . }}",                 "CRITICAL"),
    (r'\{%[-\s]*include_relative\s+(\S+)',"Jekyll include_relative tag",   "{{ partial 'FILENAME' . }}",                 "CRITICAL"),

    # Layouts
    (r'layout:\s*(\S+)',                   "Jekyll layout frontmatter",     "Hugo uses layouts/_default/ folder structure","HIGH"),

    # Control flow
    (r'\{%[-\s]*if\s+page\.',              "Jekyll if page. condition",     "{{ if .Params.FIELD }} or {{ if .FIELD }}",  "HIGH"),
    (r'\{%[-\s]*if\s+site\.',              "Jekyll if site. condition",     "{{ if .Site.Params.FIELD }}",                "HIGH"),
    (r'\{%[-\s]*unless\s+',               "Jekyll unless tag",             "{{ if not ... }}",                           "HIGH"),
    (r'\{%[-\s]*for\s+(\w+)\s+in\s+',    "Jekyll for loop",               "{{ range .COLLECTION }}...{{ end }}",        "HIGH"),
    (r'\{%[-\s]*assign\s+',               "Jekyll assign tag",             "{{ $var := value }}",                        "MEDIUM"),
    (r'\{%[-\s]*capture\s+',              "Jekyll capture tag",            "{{ $var := ... }} (use scratch or partial)", "MEDIUM"),
    (r'\{%[-\s]*comment\s*%\}',           "Jekyll comment block",          "{{/* comment */}}",                          "LOW"),

    # Filters
    (r'\|\s*date:\s*["\']',               "Jekyll date filter",            "{{ .Date.Format 'Jan 2, 2006' }}",           "MEDIUM"),
    (r'\|\s*markdownify',                 "Jekyll markdownify filter",     "{{ .Content }} or {{ markdownify .Param }}", "MEDIUM"),
    (r'\|\s*slugify',                     "Jekyll slugify filter",         "{{ urlize .Title }}",                        "LOW"),
    (r'\|\s*truncate',                    "Jekyll truncate filter",        "{{ .Summary }} or truncate func",            "LOW"),
    (r'\|\s*jsonify',                     "Jekyll jsonify filter",         "{{ jsonify .Data }}",                        "LOW"),
    (r'\|\s*relative_url',                "Jekyll relative_url filter",    "{{ relURL .URL }}",                          "HIGH"),
    (r'\|\s*absolute_url',                "Jekyll absolute_url filter",    "{{ absURL .URL }}",                          "HIGH"),
    (r'\|\s*where\s+',                    "Jekyll where filter",           "{{ where .Pages 'Param' 'value' }}",         "MEDIUM"),
    (r'\|\s*sort\s+',                     "Jekyll sort filter",            "{{ sort .Pages 'Param' }}",                  "LOW"),
    (r'\|\s*group_by\s+',                 "Jekyll group_by filter",        "{{ range .Pages.GroupBy 'Param' }}",         "MEDIUM"),

    # Highlight
    (r'\{%[-\s]*highlight\s+(\w+)',       "Jekyll highlight block",        "{{< highlight LANG >}}...{{< /highlight >}}","MEDIUM"),

    # Link tags
    (r'\{%[-\s]*link\s+',                 "Jekyll link tag",               "{{ relref . 'path/to/page' }}",              "HIGH"),
    (r'\{%[-\s]*post_url\s+',             "Jekyll post_url tag",           "{{ relref . 'posts/post-name' }}",           "HIGH"),
]

FRONTMATTER_PATTERNS = [
    (r'^layout:\s*',          "layout field",      "Hugo uses folder/file structure, not layout field in frontmatter", "HIGH"),
    (r'^permalink:\s*',       "permalink field",   "Use url: in Hugo frontmatter or configure permalinks in hugo.toml", "HIGH"),
    (r'^categories:\s*',      "categories field",  "Works in Hugo too — ensure taxonomy is configured in hugo.toml",   "LOW"),
    (r'^tags:\s*',            "tags field",        "Works in Hugo too — ensure taxonomy is configured in hugo.toml",   "LOW"),
    (r'^published:\s*false',  "published: false",  "Use draft: true in Hugo",                                          "MEDIUM"),
    (r'^excerpt:\s*',         "excerpt field",     "Hugo uses .Summary — set summary in frontmatter or use ","MEDIUM"),
    (r'^header:\s*',          "header field",      "Move to params section or use custom Params in Hugo",              "LOW"),
]

CONFIG_PATTERNS = {
    "_config.yml": [
        ("title:",           "site title",        "title = '' in hugo.toml",                          "HIGH"),
        ("description:",     "site description",  "[params]\n  description = ''",                     "HIGH"),
        ("baseurl:",         "base URL",          "baseURL = '' in hugo.toml",                        "CRITICAL"),
        ("url:",             "site URL",          "baseURL = '' in hugo.toml",                        "CRITICAL"),
        ("permalink:",       "permalink format",  "[permalinks] section in hugo.toml",                "HIGH"),
        ("collections:",     "collections",       "Hugo uses content types/sections in content/ dir", "HIGH"),
        ("defaults:",        "front matter defaults", "[frontmatter] or cascade in hugo.toml",        "HIGH"),
        ("plugins:",         "plugins list",      "Hugo uses modules, shortcodes, partials instead",  "CRITICAL"),
        ("gems:",            "gems list",         "Hugo has no gems — use Hugo modules",              "CRITICAL"),
        ("exclude:",         "exclude list",      "ignoreFiles in hugo.toml",                         "MEDIUM"),
        ("include:",         "include list",      "Not needed in Hugo — all content/ is included",    "LOW"),
        ("sass:",            "sass config",       "Hugo has built-in SCSS via Hugo Pipes",            "MEDIUM"),
        ("markdown:",        "markdown engine",   "Hugo uses goldmark by default — configure in [markup]", "MEDIUM"),
        ("highlighter:",     "code highlighter",  "Hugo uses Chroma — configure in [markup.highlight]", "MEDIUM"),
        ("paginate:",        "pagination",        "paginate = N in hugo.toml",                        "HIGH"),
        ("timezone:",        "timezone",          "timeZone = '' in hugo.toml",                       "LOW"),
        ("future:",          "future posts",      "buildFuture = true in hugo.toml",                  "LOW"),
    ]
}

FILE_MAPPING = {
    "_layouts/default.html":     "layouts/_default/baseof.html",
    "_layouts/page.html":        "layouts/_default/single.html",
    "_layouts/post.html":        "layouts/posts/single.html",
    "_layouts/home.html":        "layouts/index.html",
    "_includes/header.html":     "layouts/partials/header.html",
    "_includes/footer.html":     "layouts/partials/footer.html",
    "_includes/head.html":       "layouts/partials/head.html",
    "_includes/nav.html":        "layouts/partials/nav.html",
    "_posts/":                   "content/posts/",
    "_pages/":                   "content/",
    "_data/":                    "data/",
    "_sass/":                    "assets/scss/ or static/css/",
    "_site/":                    "public/ (auto-generated, do not migrate)",
    "assets/":                   "static/ or assets/ (Hugo Pipes)",
    "Gemfile":                   "go.mod (Hugo modules)",
    "_config.yml":               "hugo.toml or hugo.yaml",
}

# ══════════════════════════════════════════════════════════════════
# SCANNER CLASS
# ══════════════════════════════════════════════════════════════════

class JekyllMigrationAnalyzer:
    def __init__(self, jekyll_path: str):
        self.root = Path(jekyll_path).resolve()
        self.report = defaultdict(list)
        self.stats = defaultdict(int)
        self.all_issues = []

    def scan(self):
        print(f"\n{BOLD}{CYAN}🔍 Scanning Jekyll codebase: {self.root}{RESET}\n")

        if not self.root.exists():
            print(f"{RED}ERROR: Path does not exist: {self.root}{RESET}")
            sys.exit(1)

        # Scan all files
        for filepath in sorted(self.root.rglob("*")):
            if filepath.is_file():
                self._analyze_file(filepath)

        print(f"\n{GREEN}✅ Scan complete!{RESET}")
        print(f"   Files scanned:  {self.stats['files_scanned']}")
        print(f"   Issues found:   {self.stats['total_issues']}")
        print(f"   Critical:       {self.stats['CRITICAL']}")
        print(f"   High:           {self.stats['HIGH']}")
        print(f"   Medium:         {self.stats['MEDIUM']}")
        print(f"   Low:            {self.stats['LOW']}")

    def _should_skip(self, filepath: Path) -> bool:
        skip_dirs  = {'.git', '_site', 'node_modules', '.sass-cache', 'vendor'}
        skip_exts  = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
                      '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.zip'}
        if any(part in skip_dirs for part in filepath.parts):
            return True
        if filepath.suffix.lower() in skip_exts:
            return True
        return False

    def _analyze_file(self, filepath: Path):
        if self._should_skip(filepath):
            return

        self.stats['files_scanned'] += 1
        rel_path = str(filepath.relative_to(self.root))

        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return

        issues = []

        # ── Check config files ──
        if filepath.name in ('_config.yml', '_config.yaml'):
            issues += self._check_config(content, rel_path)

        # ── Check HTML/Liquid templates ──
        if filepath.suffix in ('.html', '.htm', '.liquid', '.xml'):
            issues += self._check_liquid(content, rel_path)

        # ── Check Markdown files ──
        if filepath.suffix in ('.md', '.markdown'):
            issues += self._check_markdown(content, rel_path)

        # ── Check SCSS/CSS ──
        if filepath.suffix in ('.scss', '.sass', '.css'):
            issues += self._check_scss(content, rel_path)

        # ── Check for Jekyll-specific files ──
        issues += self._check_filename(filepath, rel_path)

        if issues:
            self.report[rel_path] = issues
            self.stats['total_issues'] += len(issues)
            for issue in issues:
                self.stats[issue['severity']] += 1

    def _check_liquid(self, content: str, path: str) -> list:
        issues = []
        lines = content.split('\n')

        for pattern, description, hugo_equiv, severity in LIQUID_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    issues.append({
                        'type': 'LIQUID_TEMPLATE',
                        'severity': severity,
                        'line': i,
                        'found': line.strip()[:100],
                        'description': description,
                        'fix': hugo_equiv,
                        'path': path
                    })

        return issues

    def _check_markdown(self, content: str, path: str) -> list:
        issues = []
        lines = content.split('\n')

        # Check frontmatter
        in_frontmatter = False
        frontmatter_end = 0
        if content.startswith('---'):
            for i, line in enumerate(lines[1:], 2):
                if line.strip() == '---':
                    frontmatter_end = i
                    break
                in_frontmatter = True

        for i, line in enumerate(lines[:frontmatter_end], 1):
            for pattern, description, fix, severity in FRONTMATTER_PATTERNS:
                if re.search(pattern, line):
                    issues.append({
                        'type': 'FRONTMATTER',
                        'severity': severity,
                        'line': i,
                        'found': line.strip(),
                        'description': f"Frontmatter: {description}",
                        'fix': fix,
                        'path': path
                    })

        # Check for Liquid in markdown
        for i, line in enumerate(lines, 1):
            for pattern, description, hugo_equiv, severity in LIQUID_PATTERNS:
                if re.search(pattern, line):
                    issues.append({
                        'type': 'LIQUID_IN_MARKDOWN',
                        'severity': severity,
                        'line': i,
                        'found': line.strip()[:100],
                        'description': f"Liquid tag in markdown: {description}",
                        'fix': hugo_equiv,
                        'path': path
                    })

        # Check for Jekyll post naming
        filename = Path(path).name
        if re.match(r'^\d{4}-\d{2}-\d{2}-', filename):
            issues.append({
                'type': 'POST_NAMING',
                'severity': 'MEDIUM',
                'line': 0,
                'found': filename,
                'description': "Jekyll date-prefixed post filename",
                'fix': "Hugo supports this format but date should be in frontmatter. File can be renamed without date prefix.",
                'path': path
            })

        # Check for excerpt separator
        if '' in content:
            issues.append({
                'type': 'EXCERPT',
                'severity': 'LOW',
                'line': content[:content.index('')].count('\n') + 1,
                'found': '',
                'description': "Jekyll excerpt separator",
                'fix': "Hugo supports natively — no change needed! ✅",
                'path': path
            })

        return issues

    def _check_config(self, content: str, path: str) -> list:
        issues = []
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            for key, description, fix, severity in CONFIG_PATTERNS.get('_config.yml', []):
                if re.search(r'^\s*' + re.escape(key), line):
                    issues.append({
                        'type': 'CONFIG',
                        'severity': severity,
                        'line': i,
                        'found': line.strip(),
                        'description': f"_config.yml: {description}",
                        'fix': f"hugo.toml equivalent: {fix}",
                        'path': path
                    })

        return issues

    def _check_scss(self, content: str, path: str) -> list:
        issues = []
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # Jekyll @import with quotes
            if re.search(r'@import\s+["\']', line):
                issues.append({
                    'type': 'SCSS_IMPORT',
                    'severity': 'MEDIUM',
                    'line': i,
                    'found': line.strip(),
                    'description': "Jekyll SCSS @import",
                    'fix': "Works the same in Hugo. Move SCSS to assets/scss/ and use Hugo Pipes: {{ $style := resources.Get 'scss/main.scss' | toCSS }}",
                    'path': path
                })
                break  # only flag once per file

            # Jekyll front matter in SCSS (--- at top)
            if i <= 3 and line.strip() == '---':
                issues.append({
                    'type': 'SCSS_FRONTMATTER',
                    'severity': 'HIGH',
                    'line': i,
                    'found': '---',
                    'description': "Jekyll SCSS file has front matter (--- at top)",
                    'fix': "Remove the --- front matter. Hugo processes SCSS via Hugo Pipes without front matter.",
                    'path': path
                })
                break

        return issues

    def _check_filename(self, filepath: Path, rel_path: str) -> list:
        issues = []
        name = filepath.name
        parts = filepath.parts

        # Jekyll special directories
        jekyll_dirs = {
            '_layouts':  "Move to layouts/ — rename files per Hugo convention",
            '_includes': "Move to layouts/partials/",
            '_posts':    "Move to content/posts/ — remove date prefix from filename if desired",
            '_pages':    "Move to content/",
            '_data':     "Move to data/ — works same in Hugo",
            '_sass':     "Move to assets/scss/ and use Hugo Pipes",
            '_plugins':  "CANNOT MIGRATE DIRECTLY — rewrite as Hugo shortcodes or modules",
        }

        for jekyll_dir, fix in jekyll_dirs.items():
            if jekyll_dir in parts:
                severity = 'CRITICAL' if jekyll_dir == '_plugins' else 'HIGH'
                issues.append({
                    'type': 'DIRECTORY_STRUCTURE',
                    'severity': severity,
                    'line': 0,
                    'found': f"File in {jekyll_dir}/",
                    'description': f"Jekyll {jekyll_dir} directory",
                    'fix': fix,
                    'path': rel_path
                })
                break

        # Gemfile
        if name == 'Gemfile':
            issues.append({
                'type': 'GEMFILE',
                'severity': 'CRITICAL',
                'line': 0,
                'found': 'Gemfile',
                'description': "Jekyll Gemfile — Ruby dependencies",
                'fix': "Delete Gemfile. Hugo has no Ruby dependency. Use go.mod for Hugo modules if needed.",
                'path': rel_path
            })

        return issues

    # ══════════════════════════════════════════════════════════════
    # REPORT GENERATION
    # ══════════════════════════════════════════════════════════════

    def generate_report(self):
        report_path = self.root / "migration_report.md"
        summary_path = self.root / "migration_summary.txt"

        self._write_markdown_report(report_path)
        self._write_summary(summary_path)
        self._print_terminal_report()

        print(f"\n{BOLD}📄 Reports saved:{RESET}")
        print(f"   {GREEN}{report_path}{RESET}")
        print(f"   {GREEN}{summary_path}{RESET}")

    def _severity_emoji(self, severity):
        return {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(severity, '⚪')

    def _write_markdown_report(self, path: Path):
        lines = []
        lines.append("# Jekyll → Hugo Migration Report\n")
        lines.append(f"**Codebase scanned:** `{self.root}`\n")
        lines.append(f"**Files scanned:** {self.stats['files_scanned']}\n")
        lines.append(f"**Total issues:** {self.stats['total_issues']}\n")
        lines.append("")

        # Stats table
        lines.append("## Summary\n")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| 🔴 Critical | {self.stats['CRITICAL']} |")
        lines.append(f"| 🟠 High     | {self.stats['HIGH']} |")
        lines.append(f"| 🟡 Medium   | {self.stats['MEDIUM']} |")
        lines.append(f"| 🟢 Low      | {self.stats['LOW']} |")
        lines.append("")

        # File structure mapping
        lines.append("## Directory Structure Changes\n")
        lines.append("| Jekyll Path | Hugo Path |")
        lines.append("|-------------|-----------|")
        for jekyll, hugo in FILE_MAPPING.items():
            lines.append(f"| `{jekyll}` | `{hugo}` |")
        lines.append("")

        # hugo.toml template
        lines.append("## hugo.toml Template\n")
        lines.append("```toml")
        lines.append("baseURL = '[https://yoursite.com/](https://yoursite.com/)'")
        lines.append("languageCode = 'en-us'")
        lines.append("title = 'Your Site Title'")
        lines.append("theme = ''  # if using a theme")
        lines.append("")
        lines.append("[params]")
        lines.append("  description = 'Your site description'")
        lines.append("")
        lines.append("[markup]")
        lines.append("  [markup.goldmark]")
        lines.append("    [markup.goldmark.renderer]")
        lines.append("      unsafe = true  # allows raw HTML in markdown")
        lines.append("  [markup.highlight]")
        lines.append("    style = 'github'")
        lines.append("")
        lines.append("[taxonomies]")
        lines.append("  category = 'categories'")
        lines.append("  tag = 'tags'")
        lines.append("")
        lines.append("paginate = 10")
        lines.append("")
        lines.append("[[menus.main]]")
        lines.append("  name = 'Home'")
        lines.append("  url  = '/'")
        lines.append("  weight = 1")
        lines.append("```\n")

        # Per-file issues
        lines.append("## File-by-File Issues\n")

        # Sort by severity
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_files = sorted(
            self.report.items(),
            key=lambda x: min(severity_order.get(i['severity'], 4) for i in x[1])
        )

        for index, (filepath, issues) in enumerate(sorted_files):
            # Add a small gap between files to avoid page breaks in PDF conversion
            if index > 0:
                lines.append("<br>\n\n---\n\n<br>\n")

            # Switched to bold text to avoid Markdown-to-PDF converters forcing a new page
            lines.append(f"**📁 `{filepath}`**\n")

            # Group by severity
            for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
                sev_issues = [i for i in issues if i['severity'] == severity]
                if not sev_issues:
                    continue

                emoji = self._severity_emoji(severity)
                
                # Also swapped this heading for bold text
                lines.append(f"\n**{emoji} {severity} ({len(sev_issues)} issues)**\n")

                for issue in sev_issues:
                    lines.append(f"**Line {issue['line']}** — {issue['description']}")
                    lines.append(f"- **Found:** `{issue['found']}`")
                    lines.append(f"- **Hugo equivalent:** `{issue['fix']}`")
                    lines.append("")

        # Quick reference
        lines.append("## Quick Reference: Liquid → Hugo Template Syntax\n")
        lines.append("| Jekyll / Liquid | Hugo / Go Template |")
        lines.append("|-----------------|-------------------|")
        quick_ref = [
            ("{{ page.title }}", "{{ .Title }}"),
            ("{{ page.content }}", "{{ .Content }}"),
            ("{{ page.url }}", "{{ .RelPermalink }}"),
            ("{{ page.date | date: '%Y' }}", "{{ .Date.Format '2006' }}"),
            ("{{ page.excerpt }}", "{{ .Summary }}"),
            ("{{ site.title }}", "{{ .Site.Title }}"),
            ("{{ site.baseurl }}", "{{ .Site.BaseURL }}"),
            ("{{ site.posts }}", "{{ where .Site.RegularPages 'Type' 'posts' }}"),
            ("{% include file.html %}", "{{ partial 'file.html' . }}"),
            ("{% for post in site.posts %}", "{{ range where .Site.RegularPages 'Type' 'posts' }}"),
            ("{% if page.var %}", "{{ if .Params.var }}"),
            ("{% assign x = val %}", "{{ $x := val }}"),
            ("{% highlight python %}", "{{< highlight python >}}"),
            ("{{ 'text' | markdownify }}", "{{ markdownify 'text' }}"),
            ("{{ url | relative_url }}", "{{ relURL url }}"),
            ("{{ url | absolute_url }}", "{{ absURL url }}"),
            ("layout: default", "Use layouts/_default/baseof.html"),
            ("published: false", "draft: true"),
            ("excerpt: text", "summary: text or use "),
        ]
        for jekyll, hugo in quick_ref:
            lines.append(f"| `{jekyll}` | `{hugo}` |")
        lines.append("")

        path.write_text('\n'.join(lines), encoding='utf-8')

    def _write_summary(self, path: Path):
        lines = []
        lines.append("JEKYLL → HUGO MIGRATION SUMMARY")
        lines.append("=" * 50)
        lines.append(f"Codebase: {self.root}")
        lines.append(f"Files scanned: {self.stats['files_scanned']}")
        lines.append(f"Total issues: {self.stats['total_issues']}")
        lines.append(f"  CRITICAL: {self.stats['CRITICAL']}")
        lines.append(f"  HIGH:     {self.stats['HIGH']}")
        lines.append(f"  MEDIUM:   {self.stats['MEDIUM']}")
        lines.append(f"  LOW:      {self.stats['LOW']}")
        lines.append("")
        lines.append("FILES WITH CRITICAL ISSUES:")
        lines.append("-" * 40)
        for filepath, issues in self.report.items():
            critical = [i for i in issues if i['severity'] == 'CRITICAL']
            if critical:
                lines.append(f"  {filepath} ({len(critical)} critical)")
                for issue in critical[:3]:
                    lines.append(f"    → Line {issue['line']}: {issue['description']}")
        lines.append("")
        lines.append("ALL FILES WITH ISSUES:")
        lines.append("-" * 40)
        for filepath, issues in sorted(self.report.items()):
            lines.append(f"  {filepath}: {len(issues)} issues")

        path.write_text('\n'.join(lines), encoding='utf-8')

    def _print_terminal_report(self):
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  MIGRATION REPORT{RESET}")
        print(f"{BOLD}{'='*60}{RESET}\n")

        severity_color = {
            'CRITICAL': RED,
            'HIGH': YELLOW,
            'MEDIUM': CYAN,
            'LOW': GREEN
        }

        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_files = sorted(
            self.report.items(),
            key=lambda x: min(severity_order.get(i['severity'], 4) for i in x[1])
        )

        for filepath, issues in sorted_files:
            print(f"{BOLD}📁 {filepath}{RESET}  ({len(issues)} issues)")

            for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
                sev_issues = [i for i in issues if i['severity'] == severity]
                if not sev_issues:
                    continue
                color = severity_color[severity]
                emoji = self._severity_emoji(severity)
                for issue in sev_issues:
                    line_info = f"line {issue['line']}" if issue['line'] > 0 else "file-level"
                    print(f"  {emoji} {color}[{severity}]{RESET} {line_info} — {issue['description']}")
                    print(f"       Found:  {YELLOW}{issue['found'][:80]}{RESET}")
                    print(f"       Fix:    {GREEN}{issue['fix'][:80]}{RESET}")
            print()


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"\n{BOLD}Usage:{RESET} python3 jekyll_to_hugo_analyzer.py /path/to/jekyll/site\n")
        print(f"Example: python3 jekyll_to_hugo_analyzer.py ~/my-jekyll-blog\n")
        sys.exit(1)

    jekyll_path = sys.argv[1]
    analyzer = JekyllMigrationAnalyzer(jekyll_path)
    analyzer.scan()
    analyzer.generate_report()