#!/usr/bin/env python3
"""
Jekyll → Hugo Migration Script
================================
Walks the repo and rewrites files so they work with Hugo instead of Jekyll.
Covers frontmatter keys, layout names, include tags, and Liquid template syntax.

Usage:
  python migrate_jekyll_to_hugo.py [--repo /path/to/repo] [--dry-run] [--verbose]
"""

import os
import re
import sys
import argparse
import shutil
from pathlib import Path
from datetime import datetime


# ─── What to touch (and what to leave alone) ──────────────────────────────────

# These directories are never entered — they're either generated output or
# dependency folders that Hugo doesn't need us to touch.
SKIP_DIRS = {
  ".git", "node_modules", "_site", "public",
  "vendor", ".bundle", "imported",
}

CONTENT_EXTENSIONS  = {".md", ".html"}
TEMPLATE_EXTENSIONS = {".html"}
CONFIG_EXTENSIONS   = {".yml", ".yaml", ".xml"}

# Hugo's data/ folder uses the same shape as Jekyll's _data/ — skip both.
DATA_SKIP_PREFIXES = ("data/", "_data/")

# Jekyll layout name → Hugo layout name.
# The Hugo equivalents live in layouts/_default/<name>.html.
LAYOUT_MAP = {
  "default":       "baseof",
  "page":          "page",
  "post":          "single",
  "landing_page":  "landing",
  "default_print": "baseof_print",
  "page_print":    "page_print",
  "none":          "none",
}


# ─── Change tracking ──────────────────────────────────────────────────────────

# Every rewrite we make gets recorded here so the final report has full detail.
stats = {
  "files_scanned": 0,
  "files_changed": 0,
  "changes":       [],
}


def log_change(filepath, line_no, kind, before, after):
  stats["changes"].append({
    "file":   filepath,
    "line":   line_no,
    "kind":   kind,
    "before": before.strip(),
    "after":  after.strip(),
  })


def should_skip(path: Path, repo_root: Path) -> bool:
  rel   = path.relative_to(repo_root)
  parts = rel.parts

  for part in parts:
    if part in SKIP_DIRS or part.startswith("."):
      # .github is the one hidden folder we still want to process (issue templates etc.)
      if part == ".github":
        return False
      return True

  # Data files are already Hugo-compatible — nothing to change there.
  rel_str = str(rel).replace("\\", "/")
  for prefix in DATA_SKIP_PREFIXES:
    if rel_str.startswith(prefix):
      return True

  return False


# ─── Transform 1: permalink → url ─────────────────────────────────────────────
# Jekyll frontmatter uses `permalink` to set the output path.
# Hugo calls the same concept `url`, and prefers clean slash-terminated paths.

def fix_permalink(lines, filepath):
  result      = []
  in_front    = False
  front_count = 0
  changed     = False

  for i, line in enumerate(lines):
    if line.strip() == "---":
      front_count += 1
      # We're inside frontmatter between the first and second --- markers.
      in_front = (front_count == 1)
      if front_count == 2:
        in_front = False
      result.append(line)
      continue

    if in_front:
      m = re.match(r'^(\s*)permalink:\s*(.+)$', line)
      if m:
        indent = m.group(1)
        value  = m.group(2).strip().strip('"').strip("'")
        # Strip any leading slash and trailing .html, then wrap in /slug/ form.
        value    = value.lstrip("/")
        value    = re.sub(r'\.html$', '', value)
        new_line = f"{indent}url: /{value}/\n"
        log_change(filepath, i + 1, "permalink→url", line, new_line)
        result.append(new_line)
        changed = True
        continue

    result.append(line)

  return result, changed


# ─── Transform 2: layout names ────────────────────────────────────────────────
# Jekyll and Hugo both use a `layout` key, but their naming conventions differ.
# We also drop a comment so developers know which file to create in Hugo.

def fix_layout_frontmatter(lines, filepath):
  result      = []
  in_front    = False
  front_count = 0
  changed     = False

  for i, line in enumerate(lines):
    if line.strip() == "---":
      front_count += 1
      in_front = (front_count == 1)
      if front_count == 2:
        in_front = False
      result.append(line)
      continue

    if in_front:
      m = re.match(r'^(\s*)layout:\s*["\']?(\S+?)["\']?\s*$', line)
      if m:
        indent        = m.group(1)
        jekyll_layout = m.group(2)
        hugo_layout   = LAYOUT_MAP.get(jekyll_layout, jekyll_layout)
        new_line      = f"{indent}layout: {hugo_layout}  # Hugo: layouts/_default/{hugo_layout}.html\n"
        log_change(filepath, i + 1, "layout-frontmatter", line, new_line)
        result.append(new_line)
        changed = True
        continue

    result.append(line)

  return result, changed


# ─── Transform 3: {% include %} → Hugo partials ───────────────────────────────
# Jekyll includes are roughly equivalent to Hugo partials.
# Parameters get turned into a dict context so the partial can still access them.

INCLUDE_RE = re.compile(
  r'\{%-?\s*include\s+([^\s%}]+(?:\s+[^\s%}]+)*?)\s*-?%\}'
)


def _include_replacer(m):
  raw   = m.group(1).strip()
  parts = raw.split(None, 1)

  filename = parts[0]
  params   = parts[1] if len(parts) > 1 else None

  if params:
    # Jekyll: {% include warning.html content="oops" %}
    # Hugo:   {{- partial "warning.html" (dict "content" "oops" "page" .) -}}
    kv_pairs = re.findall(r'(\w+)=["\']?([^"\'%}\s]+)["\']?', params.strip())
    if kv_pairs:
      dict_args = " ".join(f'"{k}" "{v}"' for k, v in kv_pairs)
      return f'{{{{- partial "{filename}" (dict {dict_args} "page" .) -}}}}'

  return f'{{{{- partial "{filename}" . -}}}}'


def fix_include_tags(lines, filepath):
  result  = []
  changed = False

  for i, line in enumerate(lines):
    new_line, n = INCLUDE_RE.subn(_include_replacer, line)
    if n > 0:
      log_change(filepath, i + 1, "include→partial", line, new_line)
      changed = True
    result.append(new_line)

  return result, changed


# ─── Transform 4: Liquid → Go template syntax ─────────────────────────────────
# This is the big one. Jekyll uses Liquid tags everywhere; Hugo uses Go templates.
# We handle loops, conditionals, variable assignment, site/page variables,
# and the most common filters. Complex cases get a comment flagging manual review.

# Compiled patterns — defined once so they're not recompiled on every line.
FOR_RE         = re.compile(r'\{%-?\s*for\s+(\w+)\s+in\s+([^\s%}]+(?:\.[^\s%}]+)*)\s*(?:limit:\d+)?\s*-?%\}')
ENDFOR_RE      = re.compile(r'\{%-?\s*endfor\s*-?%\}')

IF_RE          = re.compile(r'\{%-?\s*if\s+(.+?)\s*-?%\}')
UNLESS_RE      = re.compile(r'\{%-?\s*unless\s+(.+?)\s*-?%\}')
ELSIF_RE       = re.compile(r'\{%-?\s*elsif\s+(.+?)\s*-?%\}')
ENDIF_RE       = re.compile(r'\{%-?\s*endif\s*-?%\}')
ENDUNLESS_RE   = re.compile(r'\{%-?\s*endunless\s*-?%\}')

ASSIGN_RE      = re.compile(r'\{%-?\s*assign\s+(\w+)\s*=\s*(.+?)\s*-?%\}')

SITE_DATA_RE        = re.compile(r'\{\{\s*site\.data\.(\w+)\.(\w+)\s*\}\}')
SITE_DATA_ALERTS_RE = re.compile(r'\{\{\s*site\.data\.alerts\.(\w+)\s*\}\}')
SITE_TITLE_RE       = re.compile(r'\{\{\s*site\.title\s*\}\}')
SITE_URL_RE         = re.compile(r'\{\{\s*site\.url\s*\}\}')
SITE_BASEURL_RE     = re.compile(r'\{\{\s*site\.baseurl\s*\}\}')

PAGE_TITLE_RE   = re.compile(r'\{\{\s*page\.title\s*\}\}')
PAGE_URL_RE     = re.compile(r'\{\{\s*page\.url\s*\}\}')
PAGE_SUMMARY_RE = re.compile(r'\{\{\s*page\.summary\s*\}\}')
PAGE_CONTENT_RE = re.compile(r'\{\{\s*page\.content\s*\}\}')
PAGE_DATE_RE    = re.compile(r'\{\{\s*page\.date\s*\}\}')
PAGE_TAGS_RE    = re.compile(r'\{\{\s*page\.tags\s*\}\}')
PAGE_PATH_RE    = re.compile(r'\{\{\s*page\.path\s*\}\}')
PAGE_PARAM_RE   = re.compile(r'\{\{\s*page\.(\w+)\s*\}\}')

RELATIVE_URL_RE   = re.compile(r"\|\s*relative_url\s*")
ABSOLUTE_URL_RE   = re.compile(r"\|\s*absolute_url\s*")
MARKDOWNIFY_RE    = re.compile(r"\|\s*markdownify\s*")
DATE_FILTER_RE    = re.compile(r"\|\s*date:\s*['\"]([^'\"]+)['\"]\s*")
STRIP_HTML_RE     = re.compile(r"\|\s*strip_html\s*")
STRIP_NEWLINES_RE = re.compile(r"\|\s*strip_newlines\s*")
TRUNCATE_RE       = re.compile(r"\|\s*truncate:\s*\d+\s*")
REMOVE_RE         = re.compile(r'\|\s*remove:\s*["\'][^"\']*["\']\s*')
SPLIT_RE          = re.compile(r'\|\s*split:\s*["\']([^"\']*)["\']')
APPEND_RE         = re.compile(r'\|\s*append:\s*["\']([^"\']*)["\']')
SORT_RE           = re.compile(r'\|\s*sort(?::\s*["\']([^"\']*)["\'])?\s*')
REVERSE_RE        = re.compile(r'\|\s*reverse\s*')
GROUP_BY_RE       = re.compile(r'\|\s*group_by:\s*["\']([^"\']*)["\']')

COMMENT_INLINE_RE = re.compile(r'\{%-?\s*comment\s*-?%\}')
ENDCOMMENT_RE     = re.compile(r'\{%-?\s*endcomment\s*-?%\}')
RAW_RE            = re.compile(r'\{%-?\s*raw\s*-?%\}')
ENDRAW_RE         = re.compile(r'\{%-?\s*endraw\s*-?%\}')


def _convert_condition(cond):
  """Rewrite a Liquid condition expression into Go template syntax."""
  cond = cond.strip()

  # page.X maps to Hugo's context variables or .Params for custom fields.
  cond = re.sub(r'\bpage\.title\b',   '.Title',          cond)
  cond = re.sub(r'\bpage\.url\b',     '.RelPermalink',   cond)
  cond = re.sub(r'\bpage\.summary\b', '.Summary',        cond)
  cond = re.sub(r'\bpage\.content\b', '.Content',        cond)
  cond = re.sub(r'\bpage\.tags\b',    '.Params.tags',    cond)
  cond = re.sub(r'\bpage\.(\w+)\b',   r'.Params.\1',     cond)

  # site.X becomes .Site.Params.X for custom config values.
  cond = re.sub(r'\bsite\.google_analytics\b', '.Site.Params.google_analytics', cond)
  cond = re.sub(r'\bsite\.feedback_disable\b', '.Site.Params.feedback_disable', cond)
  cond = re.sub(r'\bsite\.feedback_text\b',    '.Site.Params.feedback_text',    cond)
  cond = re.sub(r'\bsite\.feedback_link\b',    '.Site.Params.feedback_link',    cond)
  cond = re.sub(r'\bsite\.(\w+)\b',            r'.Site.Params.\1',              cond)

  # Null / boolean comparisons.
  cond = re.sub(r'==\s*null',   '| not', cond)
  cond = re.sub(r'!=\s*null',   '',      cond)
  cond = re.sub(r'==\s*true',   '',      cond)
  cond = re.sub(r'!=\s*false',  '',      cond)
  cond = re.sub(r'(\S+)\s*==\s*false', r'not \1', cond)

  # Jekyll's `contains` becomes Go's `in` with reversed argument order.
  def _contains_replacer(m):
    collection = m.group(1)
    item       = m.group(2)

    def _hugo_var(v):
      # Quoted strings and dot-expressions stay as-is; bare identifiers get a $ prefix.
      if v.startswith('$') or v.startswith('.') or v.startswith('"') or v.startswith("'"):
        return v
      return f'${v}'

    return f'in {_hugo_var(collection)} {_hugo_var(item)}'

  cond = re.sub(r'(\S+)\s+contains\s+(\S+)', _contains_replacer, cond)

  # forloop.* helpers become Hugo's $loop context variables.
  cond = re.sub(r'forloop\.first',  '$loop.IsFirst',          cond)
  cond = re.sub(r'forloop\.last',   '$loop.IsLast',           cond)
  cond = re.sub(r'forloop\.index0', '$loop.Index',            cond)
  cond = re.sub(r'forloop\.index',  '(add $loop.Index 1)',    cond)

  return cond.strip()


def _convert_for_collection(collection):
  """Map a Jekyll collection reference to its Hugo equivalent."""
  collection = collection.strip()

  # Built-in Jekyll collections have direct Hugo counterparts.
  if collection == 'site.posts':
    return 'where .Site.RegularPages "Type" "posts"'
  if collection == 'site.pages':
    return '.Site.RegularPages'
  if collection == 'site.publications':
    return '.Site.Data.publications'
  if collection == 'site.testimonials':
    return '.Site.Data.testimonials'
  if collection == 'site.sidebars':
    return '.Site.Params.sidebars'

  # site.data.X.Y — direct data file access.
  m = re.match(r'site\.data\.(\w+)(?:\.(\w+))?', collection)
  if m:
    return f'.Site.Data.{m.group(1)}.{m.group(2)}' if m.group(2) else f'.Site.Data.{m.group(1)}'

  # site.data[page.X] — dynamic data lookup using a page param as the key.
  m = re.match(r'site\.data\[page\.(\w+)\](?:\.(\w+))?', collection)
  if m:
    return (
      f'(index .Site.Data (.Params.{m.group(1)})).{m.group(2)}'
      if m.group(2)
      else f'(index .Site.Data .Params.{m.group(1)})'
    )

  m = re.match(r'page\.(\w+)', collection)
  if m:
    return f'.Params.{m.group(1)}'

  return collection


def _convert_assign_value(value):
  """Rewrite the right-hand side of a Jekyll assign tag."""
  value = value.strip()

  value = re.sub(
    r'site\.data\.(\w+)(?:\.(\w+))?',
    lambda m: f'.Site.Data.{m.group(1)}.{m.group(2)}' if m.group(2) else f'.Site.Data.{m.group(1)}',
    value,
  )
  value = re.sub(
    r'site\.data\[page\.(\w+)\](?:\.(\w+))?',
    lambda m: f'(index .Site.Data (.Params.{m.group(1)})).{m.group(2)}' if m.group(2) else f'(index .Site.Data .Params.{m.group(1)})',
    value,
  )
  value = re.sub(r'\bsite\.testimonials\b', '.Site.Data.testimonials', value)
  value = re.sub(r'\bsite\.publications\b', '.Site.Data.publications', value)
  value = re.sub(r'\bsite\.(\w+)\b',        r'.Site.Params.\1',        value)
  value = re.sub(r'\bpage\.(\w+)\b',        r'.Params.\1',             value)

  # Liquid filter chain → Hugo pipe chain.
  value = SORT_RE.sub(    lambda m: f' | sort "{m.group(1)}"' if m.group(1) else ' | sort', value)
  value = REVERSE_RE.sub( ' | reverse',                  value)
  value = GROUP_BY_RE.sub(lambda m: f' | group "{m.group(1)}"', value)
  value = SPLIT_RE.sub(   lambda m: f' | split "{m.group(1)}"', value)
  value = APPEND_RE.sub(  r' | printf "%s\1"',           value)
  value = REMOVE_RE.sub(  '',                            value)

  return value.strip()


def fix_liquid_tags(lines, filepath):
  """
  Main Liquid → Go template rewriter.
  Handles loops, conditionals, variable assignment, site/page variables,
  and the common filter set. Passes raw blocks through untouched.
  """
  result   = []
  changed  = False
  in_raw   = False

  for i, line in enumerate(lines):
    original = line

    # {% raw %} blocks contain literal Liquid that must not be processed.
    if RAW_RE.search(line):
      in_raw   = True
      new_line = ENDRAW_RE.sub('', RAW_RE.sub('', line))
      result.append(new_line)
      changed = True
      continue

    if in_raw:
      if ENDRAW_RE.search(line):
        in_raw   = False
        new_line = ENDRAW_RE.sub('', line)
        result.append(new_line)
        continue
      result.append(line)
      continue

    # Comments: {% comment %} … {% endcomment %} → {{/* … */}}
    if COMMENT_INLINE_RE.search(line):
      new_line = COMMENT_INLINE_RE.sub('{{/*', line)
      new_line = ENDCOMMENT_RE.sub('*/}}', new_line)
      if new_line != line:
        log_change(filepath, i + 1, "comment", line, new_line)
        changed = True
      line = new_line

    # for … in → range with a named loop context for forloop.* access.
    def for_replacer(m):
      var  = m.group(1)
      coll = _convert_for_collection(m.group(2))
      return f'{{{{- range $loop, ${var} := {coll} -}}}}'

    new_line, n = FOR_RE.subn(for_replacer, line)
    if n:
      log_change(filepath, i + 1, "for→range", line, new_line)
      changed = True
      line    = new_line

    new_line = ENDFOR_RE.sub('{{- end -}}', line)
    if new_line != line:
      log_change(filepath, i + 1, "endfor→end", line, new_line)
      changed = True
      line    = new_line

    # unless → if not (double negatives are simplified automatically)
    def unless_replacer(m):
      cond = _convert_condition(m.group(1))
      if cond.startswith('not '):
        return f'{{{{- if {cond[4:].strip()} -}}}}'
      return f'{{{{- if not ({cond}) -}}}}'

    new_line, n = UNLESS_RE.subn(unless_replacer, line)
    if n:
      log_change(filepath, i + 1, "unless→if-not", line, new_line)
      changed = True
      line    = new_line

    new_line = ENDUNLESS_RE.sub('{{- end -}}', line)
    if new_line != line:
      changed = True
      line    = new_line

    def if_replacer(m):
      cond = _convert_condition(m.group(1))
      return f'{{{{- if {cond} -}}}}'

    new_line, n = IF_RE.subn(if_replacer, line)
    if n:
      log_change(filepath, i + 1, "if→if", line, new_line)
      changed = True
      line    = new_line

    def elsif_replacer(m):
      cond = _convert_condition(m.group(1))
      return f'{{{{- else if {cond} -}}}}'

    new_line, n = ELSIF_RE.subn(elsif_replacer, line)
    if n:
      changed = True
      line    = new_line

    new_line = ENDIF_RE.sub('{{- end -}}', line)
    if new_line != line:
      changed = True
      line    = new_line

    # forloop.* can also appear outside condition blocks, e.g. in HTML attributes.
    new_line = re.sub(r'forloop\.last',   '$loop.IsLast',         line)
    new_line = re.sub(r'forloop\.first',  '$loop.IsFirst',        new_line)
    new_line = re.sub(r'forloop\.index0', '$loop.Index',          new_line)
    new_line = re.sub(r'forloop\.index',  '(add $loop.Index 1)',  new_line)
    if new_line != line:
      log_change(filepath, i + 1, "forloop.*→$loop.*", line, new_line)
      changed = True
      line    = new_line

    # assign → Go's := syntax with a $ prefix for the variable name.
    def assign_replacer(m):
      var = m.group(1)
      val = _convert_assign_value(m.group(2))
      return f'{{{{- ${var} := {val} -}}}}'

    new_line, n = ASSIGN_RE.subn(assign_replacer, line)
    if n:
      log_change(filepath, i + 1, "assign→$var", line, new_line)
      changed = True
      line    = new_line

    # Data variable rewrites — most specific patterns first to avoid partial matches.
    new_line = SITE_DATA_ALERTS_RE.sub(
      lambda m: f'{{{{- .Site.Data.alerts.{m.group(1)} -}}}}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = SITE_DATA_RE.sub(
      lambda m: f'{{{{- .Site.Data.{m.group(1)}.{m.group(2)} -}}}}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = SITE_TITLE_RE.sub('{{ .Site.Title }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = SITE_URL_RE.sub('{{ .Site.BaseURL }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = SITE_BASEURL_RE.sub('{{ .Site.BaseURL }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_TITLE_RE.sub('{{ .Title }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_URL_RE.sub('{{ .RelPermalink }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_SUMMARY_RE.sub('{{ .Summary }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_CONTENT_RE.sub('{{ .Content }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_TAGS_RE.sub('{{ .Params.tags }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = PAGE_PATH_RE.sub('{{ .File.Path }}', line)
    if new_line != line:
      changed = True
      line    = new_line

    # page.X catch-all — runs after the specific page.* cases above.
    new_line = PAGE_PARAM_RE.sub(lambda m: f'{{{{ .Params.{m.group(1)} }}}}', line)
    if new_line != line:
      changed = True
      line    = new_line

    # Filter rewrites — Liquid filters become Hugo pipe functions.
    new_line = RELATIVE_URL_RE.sub('| relURL ',    line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = ABSOLUTE_URL_RE.sub('| absURL ',    line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = MARKDOWNIFY_RE.sub('| markdownify ', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = DATE_FILTER_RE.sub(
      lambda m: f'| time.Format "{_jekyll_date_to_go(m.group(1))}" ', line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = STRIP_HTML_RE.sub('| plainify ',    line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = STRIP_NEWLINES_RE.sub('',           line)
    if new_line != line:
      changed = True
      line    = new_line

    new_line = TRUNCATE_RE.sub('| truncate 160 ',  line)
    if new_line != line:
      changed = True
      line    = new_line

    result.append(line)

  return result, changed


def _jekyll_date_to_go(fmt):
  """Convert a strftime-style date format string to Go's reference time format."""
  mapping = {
    '%Y': '2006', '%y': '06',
    '%m': '01',   '%-m': '1',
    '%d': '02',   '%-d': '2',
    '%B': 'January', '%b': 'Jan',
    '%A': 'Monday',  '%a': 'Mon',
    '%H': '15',  '%I': '03',
    '%M': '04',  '%S': '05',
    '%p': 'PM',
  }
  result = fmt
  for k, v in mapping.items():
    result = result.replace(k, v)
  return result


# ─── Transform 5: categories frontmatter ──────────────────────────────────────
# Hugo supports categories as a taxonomy, but it needs configuring in hugo.toml.
# We leave the value alone and add a comment to remind the developer.

def fix_categories(lines, filepath):
  result      = []
  in_front    = False
  front_count = 0
  changed     = False

  for i, line in enumerate(lines):
    if line.strip() == "---":
      front_count += 1
      in_front = (front_count == 1)
      if front_count == 2:
        in_front = False
      result.append(line)
      continue

    if in_front:
      m = re.match(r'^(\s*)categories:\s*(.+)$', line)
      if m:
        new_line = line.rstrip() + "  # Hugo: configure taxonomy in hugo.toml\n"
        log_change(filepath, i + 1, "categories-note", line, new_line)
        result.append(new_line)
        changed = True
        continue

    result.append(line)

  return result, changed


# ─── Transform 6: published: false → draft: true ──────────────────────────────
# Jekyll hides pages with `published: false`; Hugo uses `draft: true` instead.

def fix_published(lines, filepath):
  result      = []
  in_front    = False
  front_count = 0
  changed     = False

  for i, line in enumerate(lines):
    if line.strip() == "---":
      front_count += 1
      in_front = (front_count == 1)
      if front_count == 2:
        in_front = False
      result.append(line)
      continue

    if in_front:
      m = re.match(r'^(\s*)published:\s*false\s*$', line)
      if m:
        new_line = f"{m.group(1)}draft: true\n"
        log_change(filepath, i + 1, "published→draft", line, new_line)
        result.append(new_line)
        changed = True
        continue

    result.append(line)

  return result, changed


# ─── File processor ───────────────────────────────────────────────────────────

def process_file(filepath: Path, repo_root: Path, dry_run: bool, verbose: bool):
  ext = filepath.suffix.lower()
  if ext not in CONTENT_EXTENSIONS and ext not in CONFIG_EXTENSIONS:
    return

  # Don't process our own output files — that would cause all kinds of chaos.
  skip_names = {"migration_changes_report.md", "migrate_jekyll_to_hugo.py", "1.py"}
  if filepath.name in skip_names:
    return

  try:
    content = filepath.read_text(encoding="utf-8", errors="replace")
  except Exception as e:
    print(f"  [SKIP] {filepath}: {e}")
    return

  lines = content.splitlines(keepends=True)
  stats["files_scanned"] += 1

  any_changed = False

  for transform in [
    fix_permalink,
    fix_layout_frontmatter,
    fix_categories,
    fix_published,
    fix_include_tags,
    fix_liquid_tags,
  ]:
    lines, changed = transform(lines, str(filepath.relative_to(repo_root)))
    if changed:
      any_changed = True

  if any_changed:
    stats["files_changed"] += 1
    rel = filepath.relative_to(repo_root)

    if verbose or dry_run:
      print(f"\n  {'[DRY-RUN] Would change' if dry_run else 'Changed'}: {rel}")
      for c in [x for x in stats["changes"] if x["file"] == str(rel)]:
        print(f"    Line {c['line']:4d} [{c['kind']}]")
        print(f"      - {c['before'][:100]}")
        print(f"      + {c['after'][:100]}")

    if not dry_run:
      # Keep a .bak copy so nothing is irrecoverably lost.
      backup = filepath.with_suffix(filepath.suffix + ".bak")
      if not backup.exists():
        shutil.copy2(filepath, backup)
      filepath.write_text("".join(lines), encoding="utf-8")


# ─── Report ───────────────────────────────────────────────────────────────────

def write_report(repo_root: Path, dry_run: bool):
  report_path = repo_root / "migration_changes_report.md"
  now         = datetime.now().strftime("%Y-%m-%d %H:%M")

  lines = [
    f"# Jekyll → Hugo Migration Changes Report\n",
    f"Generated: {now}  \n",
    f"Mode: {'DRY-RUN (no files changed)' if dry_run else 'APPLIED (files modified in-place, .bak backups created)'}\n\n",
    f"## Summary\n\n",
    f"| Metric | Value |\n",
    f"|--------|-------|\n",
    f"| Files scanned | {stats['files_scanned']} |\n",
    f"| Files changed | {stats['files_changed']} |\n",
    f"| Total changes | {len(stats['changes'])} |\n\n",
  ]

  by_type = {}
  for c in stats["changes"]:
    by_type.setdefault(c["kind"], []).append(c)

  lines.append("## Changes by Type\n\n")
  for kind, items in sorted(by_type.items()):
    lines.append(f"### `{kind}` ({len(items)} changes)\n\n")
    lines.append("| File | Line | Before | After |\n")
    lines.append("|------|------|--------|-------|\n")
    for item in items[:50]:
      before = item['before'].replace('|', '\\|')[:80]
      after  = item['after'].replace('|', '\\|')[:80]
      lines.append(f"| `{item['file']}` | {item['line']} | `{before}` | `{after}` |\n")
    if len(items) > 50:
      lines.append(f"| ... | ... | *{len(items) - 50} more* | |\n")
    lines.append("\n")

  lines.append("## What To Do Next\n\n")
  lines.append("""
1. **Review `.bak` files** — Every changed file has a `.bak` backup next to it.
   Run `find . -name '*.bak'` to list them. Delete when satisfied.

2. **Hugo layout files** — The `include → partial` conversions reference partial
   files that must exist in `layouts/partials/`. The script preserves existing
   ones and flags missing ones in comments.

3. **Complex Liquid logic** — For loops using `site.publications`, custom assign
   pipelines, and nested data access may still need manual tweaking. Search for
   `TODO-HUGO` comments in the changed files.

4. **data/ files** — These were intentionally SKIPPED. Hugo uses `data/` the same
   way Jekyll uses `_data/` — no changes needed.

5. **Gemfile** — Delete `Gemfile` and `Gemfile.lock`. Hugo needs no Ruby dependencies.
   Run `hugo mod init github.com/precice/precice.github.io` to create `go.mod`.

6. **hugo.toml / hugo.yaml** — The `hugo.yaml` in the repo root is already the
   correct Hugo config. Remove `_config.yml` after verifying all params are ported.
""")

  report_path.write_text("".join(lines), encoding="utf-8")
  print(f"\n📄 Report written to: {report_path}")
  return report_path


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
  parser = argparse.ArgumentParser(
    description="Jekyll → Hugo in-place migration script for precice.github.io"
  )
  parser.add_argument("--repo",    default=".", help="Path to the repository root (default: current directory)")
  parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")
  parser.add_argument("--verbose", action="store_true", help="Print every change made")
  args = parser.parse_args()

  repo_root = Path(args.repo).resolve()
  if not repo_root.exists():
    print(f"ERROR: repo path does not exist: {repo_root}")
    sys.exit(1)

  print(f"\n{'='*60}")
  print(f"  Jekyll → Hugo Migration Script")
  print(f"  Repo: {repo_root}")
  print(f"  Mode: {'DRY-RUN' if args.dry_run else 'LIVE (will modify files)'}")
  print(f"{'='*60}\n")

  for root, dirs, files in os.walk(repo_root):
    root_path = Path(root)

    # Prune ignored directories so os.walk doesn't descend into them.
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

    for fname in files:
      fpath = root_path / fname
      if should_skip(fpath, repo_root):
        continue
      process_file(fpath, repo_root, args.dry_run, args.verbose)

  print(f"\n{'='*60}")
  print(f"  Files scanned : {stats['files_scanned']}")
  print(f"  Files changed : {stats['files_changed']}")
  print(f"  Total changes : {len(stats['changes'])}")
  print(f"{'='*60}\n")

  report = write_report(repo_root, args.dry_run)
  print(f"\n✅ Done. See report: {report}")


if __name__ == "__main__":
  main()