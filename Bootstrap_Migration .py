#!/usr/bin/env python3
"""
Bootstrap 3 → 5 Migration Audit — PDF Report Generator (Compact)
Usage: python3 generate_pdf_report.py bootstrap_migration_summary.csv [output.pdf]
"""

import sys, re, csv, os
from collections import defaultdict
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG        = HexColor("#0f172a")
C_ACCENT    = HexColor("#6366f1")
C_CRITICAL  = HexColor("#ef4444")
C_WARNING   = HexColor("#f59e0b")
C_INFO      = HexColor("#3b82f6")
C_TEXT      = HexColor("#1e293b")
C_SUBTEXT   = HexColor("#64748b")
C_BORDER    = HexColor("#e2e8f0")
C_ROW_ALT   = HexColor("#f8fafc")
C_HEADER_BG = HexColor("#1e293b")
C_CRIT_BG   = HexColor("#fef2f2")
C_WARN_BG   = HexColor("#fffbeb")
C_INFO_BG   = HexColor("#eff6ff")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

SEV_COLOR = {"CRITICAL": C_CRITICAL, "WARNING": C_WARNING, "INFO": C_INFO}
SEV_BG    = {"CRITICAL": C_CRIT_BG,  "WARNING": C_WARN_BG,  "INFO": C_INFO_BG}
SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def clean_text(s):
    if not s:
        return s
    s = s.replace('|', ' / ')
    out = []
    i = 0
    while i < len(s):
        if s[i] == chr(92):
            i += 2
        else:
            out.append(s[i])
            i += 1
    s = ''.join(out)
    for ch in ['^', '$', '*', '+', '?', '(', ')', '{', '}', '[', ']']:
        s = s.replace(ch, '')
    while '  ' in s:
        s = s.replace('  ', ' ')
    return s.strip(' /') or 'N/A'


def build_styles():
    return {
        "section_heading": ParagraphStyle(
            "section_heading", fontName="Helvetica-Bold", fontSize=13,
            textColor=C_TEXT, leading=18, spaceBefore=10, spaceAfter=4,
        ),
        "file_heading": ParagraphStyle(
            "file_heading", fontName="Helvetica-Bold", fontSize=9,
            textColor=colors.white, leading=12,
        ),
        "issue_desc": ParagraphStyle(
            "issue_desc", fontName="Helvetica-Bold", fontSize=8,
            textColor=C_TEXT, leading=11,
        ),
        "fix_text": ParagraphStyle(
            "fix_text", fontName="Helvetica", fontSize=8,
            textColor=HexColor("#166534"), leading=11,
        ),
        "normal": ParagraphStyle(
            "normal", fontName="Helvetica", fontSize=9,
            textColor=C_TEXT, leading=13,
        ),
        "small": ParagraphStyle(
            "small", fontName="Helvetica", fontSize=7.5,
            textColor=C_SUBTEXT, leading=10,
        ),
    }


# ── Cover ─────────────────────────────────────────────────────────────────────
def draw_cover(canvas, doc, repo_path, stats):
    c = canvas
    W, H = PAGE_W, PAGE_H

    c.setFillColor(C_BG)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(HexColor("#1e1b4b"))
    c.circle(W - 30*mm, H - 20*mm, 55*mm, fill=1, stroke=0)
    c.circle(-10*mm, 30*mm, 50*mm, fill=1, stroke=0)

    c.setStrokeColor(C_ACCENT)
    c.setLineWidth(1.5)
    c.line(MARGIN, H - 22*mm, W - MARGIN, H - 22*mm)
    c.setFont("Helvetica", 8)
    c.setFillColor(C_ACCENT)
    c.drawString(MARGIN, H - 18*mm, "BOOTSTRAP MIGRATION AUDIT REPORT")
    c.setFillColor(HexColor("#475569"))
    c.drawRightString(W - MARGIN, H - 18*mm, datetime.now().strftime("%d %B %Y"))

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN, H - 62*mm, "Bootstrap 3")
    c.setFillColor(C_ACCENT)
    c.drawString(MARGIN + 116*mm, H - 62*mm, "\u2192 5")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(MARGIN, H - 76*mm, "Migration Audit Report")
    c.setStrokeColor(C_ACCENT)
    c.setLineWidth(3)
    c.line(MARGIN, H - 80*mm, MARGIN + 80*mm, H - 80*mm)

    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#94a3b8"))
    c.drawString(MARGIN, H - 92*mm, "REPOSITORY")
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.white)
    c.drawString(MARGIN, H - 101*mm, repo_path)
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#64748b"))
    c.drawString(MARGIN, H - 111*mm,
                 f"Generated  {datetime.now().strftime('%d %B %Y, %H:%M')}   \u2022   GSoC Proposal Review")

    c.setStrokeColor(HexColor("#1e293b"))
    c.setLineWidth(1)
    c.line(MARGIN, H - 119*mm, W - MARGIN, H - 119*mm)

    s = stats
    cards = [
        (str(s["total_files"]),   "Files Scanned",    C_ACCENT),
        (str(s["files_changed"]), "Files w/ Issues",  C_ACCENT),
        (str(s["critical"]),      "Critical",         C_CRITICAL),
        (str(s["warning"]),       "Warnings",         C_WARNING),
        (str(s["info"]),          "Info",             C_INFO),
    ]
    card_w = (W - 2*MARGIN - 4*4*mm) / 5
    cx, cy = MARGIN, H - 157*mm
    for val, label, col in cards:
        c.setFillColor(HexColor("#0f1f3d"))
        c.roundRect(cx, cy, card_w, 28*mm, 6, fill=1, stroke=0)
        c.setFillColor(col)
        c.roundRect(cx, cy + 26*mm, card_w, 2*mm, 2, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(col)
        c.drawCentredString(cx + card_w/2, cy + 14*mm, val)
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#94a3b8"))
        c.drawCentredString(cx + card_w/2, cy + 7*mm, label)
        cx += card_w + 4*mm

    c.setStrokeColor(HexColor("#1e293b"))
    c.setLineWidth(1)
    c.line(MARGIN, H - 167*mm, W - MARGIN, H - 167*mm)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.white)
    c.drawString(MARGIN, H - 179*mm, "What this report covers")
    items = [
        "\u2022  Every file with Bootstrap 3 patterns that must change",
        "\u2022  Exact line numbers for each deprecated class or attribute",
        "\u2022  Severity: Critical / Warning / Info",
        "\u2022  Bootstrap 5 replacement for every issue found",
    ]
    c.setFont("Helvetica", 9.5)
    c.setFillColor(HexColor("#94a3b8"))
    iy = H - 191*mm
    for item in items:
        c.drawString(MARGIN + 2*mm, iy, item)
        iy -= 10*mm

    c.setFillColor(HexColor("#0f1f3d"))
    c.roundRect(MARGIN, H - 250*mm, W - 2*MARGIN, 20*mm, 6, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(HexColor("#94a3b8"))
    c.drawString(MARGIN + 6*mm, H - 241*mm, "Prepared for")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.white)
    c.drawString(MARGIN + 6*mm, H - 248*mm, "GSoC Proposal Review  \u2022  Bootstrap 3 \u2192 5 Upgrade Project")

    c.setFillColor(HexColor("#0a0f1e"))
    c.rect(0, 0, W, 16*mm, fill=1, stroke=0)
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#475569"))
    c.drawCentredString(W/2, 6*mm, "GSoC Proposal Review  \u2022  Bootstrap Migration Audit Tool")


# ── Page header/footer ────────────────────────────────────────────────────────
def make_page_template(canvas, doc):
    if doc.page == 1:
        return
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(C_ACCENT)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN, h - 12*mm, w - MARGIN, h - 12*mm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(C_ACCENT)
    canvas.drawString(MARGIN, h - 9.5*mm, "Bootstrap 3 \u2192 5 Migration Audit")
    canvas.setFillColor(C_SUBTEXT)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - MARGIN, h - 9.5*mm, f"Page {doc.page}")
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 11*mm, w - MARGIN, 11*mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(C_SUBTEXT)
    canvas.drawCentredString(w/2, 7*mm, "GSoC Proposal Review  \u2022  Bootstrap Migration Audit Tool")
    canvas.restoreState()


# ── Compact issue row (single table row, not a card) ─────────────────────────
def build_issue_row(iss, usable_w):
    sev  = iss["severity"]
    line = iss["line"]
    desc = clean_text(iss["description"])
    fix  = clean_text(iss["fix"])
    pat  = clean_text(iss["pattern"])
    lc   = SEV_COLOR.get(sev, C_SUBTEXT)
    bg   = SEV_BG.get(sev, C_ROW_ALT)

    sev_para = Paragraph(
        f"<b>{sev}</b>",
        ParagraphStyle("s", fontName="Helvetica-Bold", fontSize=7,
                       textColor=lc, leading=10)
    )
    line_para = Paragraph(
        f"L{line}",
        ParagraphStyle("l", fontName="Helvetica", fontSize=7,
                       textColor=C_SUBTEXT, leading=10)
    )
    desc_para = Paragraph(
        f"<b>{desc}</b><br/>"
        f"<font color='#6366f1' size='7'>Pattern: {pat[:80]}</font>",
        ParagraphStyle("d", fontName="Helvetica", fontSize=8,
                       textColor=C_TEXT, leading=11)
    )
    fix_para = Paragraph(
        f"\u2705 {fix}",
        ParagraphStyle("f", fontName="Helvetica", fontSize=7.5,
                       textColor=HexColor("#166534"), leading=11)
    )

    col_widths = [22*mm, 10*mm, 75*mm, usable_w - 22*mm - 10*mm - 75*mm]
    t = Table(
        [[sev_para, line_para, desc_para, fix_para]],
        colWidths=col_widths,
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.3, C_BORDER),
        ("BACKGROUND",    (0, 0), (0, 0), HexColor("#fafafa")),
    ]))
    return t


# ── File block (header + compact rows) ───────────────────────────────────────
def file_block(styles, filename, issues, usable_w):
    issues = sorted(issues, key=lambda x: (SEV_ORDER.get(x["severity"], 9),
                                            int(x["line"] or 0)))
    counts = defaultdict(int)
    for iss in issues:
        counts[iss["severity"]] += 1

    badges = []
    for sev in ("CRITICAL", "WARNING", "INFO"):
        if counts[sev]:
            col = SEV_COLOR[sev].hexval()
            badges.append(f'<font color="{col}"><b>{counts[sev]} {sev}</b></font>')
    badge_str = "  \u00b7  ".join(badges)

    header = Table(
        [[
            Paragraph(f"\U0001f4c4 {filename}", styles["file_heading"]),
            Paragraph(badge_str, ParagraphStyle(
                "bx", fontName="Helvetica", fontSize=7.5,
                textColor=colors.white, alignment=TA_RIGHT)),
        ]],
        colWidths=[usable_w - 70*mm, 70*mm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_HEADER_BG),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements = [header]
    for iss in issues:
        elements.append(build_issue_row(iss, usable_w))
    elements.append(Spacer(1, 5))
    return elements


# ── Load CSV ──────────────────────────────────────────────────────────────────
def load_csv(path):
    files = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fname = row.get("file", "").strip().strip('"')
            parts = fname.replace("\\", "/").replace("\\\\", "/").split("/")
            short = "/".join(parts[-3:]) if len(parts) > 3 else fname
            sev = row.get("severity", "INFO").strip()
            if sev not in ("CRITICAL", "WARNING", "INFO"):
                sev = "INFO"
            files[short].append({
                "line":        row.get("line", "?").strip(),
                "severity":    sev,
                "pattern":     clean_text(row.get("pattern", "").strip().strip('"')),
                "description": clean_text(row.get("description", "").strip().strip('"')),
                "fix":         clean_text(row.get("fix", "").strip().strip('"')),
            })
    return files



# ── Main ──────────────────────────────────────────────────────────────────────
def generate(csv_path, out_path):
    print(f"  Loading: {csv_path}")
    file_data = load_csv(csv_path)

    total_files  = len(file_data)
    total_issues = sum(len(v) for v in file_data.values())
    sev_counts   = defaultdict(int)
    for issues in file_data.values():
        for iss in issues:
            sev_counts[iss["severity"]] += 1

    stats = {
        "total_files":   total_files,
        "files_changed": total_files,
        "critical":      sev_counts["CRITICAL"],
        "warning":       sev_counts["WARNING"],
        "info":          sev_counts["INFO"],
        "total":         total_issues,
    }

    styles = build_styles()
    usable_w = PAGE_W - 2 * MARGIN

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=18*mm, bottomMargin=16*mm,
        title="Bootstrap 3\u21925 Migration Audit",
        author="Migration Audit Tool",
    )

    story = []

    # Cover
    repo_label = os.path.basename(os.path.dirname(os.path.abspath(csv_path))) or "precice.github.io"
    story.append(Spacer(1, 1))
    story.append(PageBreak())

    # ── Executive Summary ─────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", styles["section_heading"]))
    story.append(Paragraph(
        f"Bootstrap 3 \u2192 5 migration audit for <b>{repo_label}</b>. "
        f"Found <b>{total_files} files</b> with <b>{total_issues} issues</b>: "
        f"<font color='#ef4444'><b>{sev_counts['CRITICAL']} Critical</b></font>, "
        f"<font color='#f59e0b'><b>{sev_counts['WARNING']} Warnings</b></font>, "
        f"<font color='#3b82f6'><b>{sev_counts['INFO']} Info</b></font>.",
        styles["normal"]
    ))
    story.append(Spacer(1, 4*mm))

    # Severity bar
    total_bar = sum(sev_counts.values()) or 1
    bar_w = usable_w - 28*mm
    for sev in ("CRITICAL", "WARNING", "INFO"):
        count = sev_counts.get(sev, 0)
        filled = max(bar_w * count / total_bar, 2)
        row = Table([[
            Paragraph(f"<b>{sev}</b>", ParagraphStyle("x", fontName="Helvetica-Bold",
                      fontSize=8, textColor=SEV_COLOR[sev])),
            Paragraph(f"{count}", ParagraphStyle("x", fontName="Helvetica-Bold",
                      fontSize=8, textColor=SEV_COLOR[sev])),
        ]], colWidths=[24*mm, 8*mm])
        row.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
        story.append(row)
        bt = Table([["",""]], colWidths=[filled, bar_w-filled], rowHeights=[7])
        bt.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(0,0),SEV_COLOR[sev]),
            ("BACKGROUND",(1,0),(1,0),C_BORDER),
        ]))
        story.append(bt)
        story.append(Spacer(1, 2))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 3*mm))

    # ── Severity legend (compact) ─────────────────────────────────────────────
    story.append(Paragraph("Severity Guide", styles["section_heading"]))
    cs = ParagraphStyle("lc", fontName="Helvetica", fontSize=8, leading=11, textColor=C_TEXT)
    hs = ParagraphStyle("lh", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=colors.white)
    legend_data = [
        [Paragraph("Level",hs), Paragraph("Meaning",hs), Paragraph("Action",hs)],
        [Paragraph("<font color='#ef4444'><b>CRITICAL</b></font>",cs),
         Paragraph("Removed/renamed — breaks layout in BS5",cs),
         Paragraph("Must fix",cs)],
        [Paragraph("<font color='#f59e0b'><b>WARNING</b></font>",cs),
         Paragraph("Behaviour changed — may produce incorrect output",cs),
         Paragraph("Fix recommended",cs)],
        [Paragraph("<font color='#3b82f6'><b>INFO</b></font>",cs),
         Paragraph("Minor change — verify manually",cs),
         Paragraph("Review &amp; verify",cs)],
    ]
    lt = Table(legend_data, colWidths=[28*mm, usable_w-28*mm-38*mm, 38*mm])
    lt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_HEADER_BG),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,C_ROW_ALT]),
        ("GRID",(0,0),(-1,-1),0.4,C_BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),6),
        ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(lt)
    story.append(PageBreak())

    # ── Files index (compact) ─────────────────────────────────────────────────
    story.append(Paragraph("Files Requiring Changes", styles["section_heading"]))
    sorted_files = sorted(
        file_data.items(),
        key=lambda kv: (-sum(1 for i in kv[1] if i["severity"]=="CRITICAL"), -len(kv[1]))
    )
    idx_data = [["#","File","Crit","Warn","Info","Total"]]
    for idx, (fname, issues) in enumerate(sorted_files, 1):
        fc = sum(1 for i in issues if i["severity"]=="CRITICAL")
        fw = sum(1 for i in issues if i["severity"]=="WARNING")
        fi = sum(1 for i in issues if i["severity"]=="INFO")
        idx_data.append([str(idx), fname,
                         str(fc) if fc else "—", str(fw) if fw else "—",
                         str(fi) if fi else "—", str(len(issues))])
    cw = [8*mm, 100*mm, 15*mm, 15*mm, 12*mm, 12*mm]
    it = Table(idx_data, colWidths=cw, repeatRows=1)
    it.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_HEADER_BG),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ALIGN",(0,0),(0,-1),"CENTER"),
        ("ALIGN",(2,0),(-1,-1),"CENTER"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,C_ROW_ALT]),
        ("GRID",(0,0),(-1,-1),0.4,C_BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("TEXTCOLOR",(2,1),(2,-1),C_CRITICAL),
        ("FONTNAME",(2,1),(2,-1),"Helvetica-Bold"),
    ]))
    story.append(it)
    story.append(PageBreak())

    # ── Detailed report — multiple files per page ─────────────────────────────
    story.append(Paragraph("Detailed Issue Report", styles["section_heading"]))
    story.append(Paragraph(
        "Files sorted by severity. Each row shows: severity · line · issue description · Bootstrap 5 fix.",
        styles["small"]
    ))
    story.append(Spacer(1, 3*mm))

    for fname, issues in sorted_files:
        elements = file_block(styles, fname, issues, usable_w)
        # Keep file header + first issue row together; rest flows naturally
        story.append(KeepTogether(elements[:3]))
        for el in elements[3:]:
            story.append(el)

    # ── Build ─────────────────────────────────────────────────────────────────
    def first_page(canvas, doc):
        draw_cover(canvas, doc, repo_label, stats)

    doc.build(story, onFirstPage=first_page, onLaterPages=make_page_template)
    print(f"  \u2705 PDF saved \u2192 {out_path}")


if __name__ == "__main__":
    csv_in  = sys.argv[1] if len(sys.argv) > 1 else "bootstrap_migration_summary.csv"
    pdf_out = sys.argv[2] if len(sys.argv) > 2 else "bootstrap_migration_report.pdf"
    if not os.path.exists(csv_in):
        print(f"Error: CSV not found: {csv_in}")
        sys.exit(1)
    generate(csv_in, pdf_out)