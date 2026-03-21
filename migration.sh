#!/usr/bin/env bash

REPO_DIR="${1:-.}"
REPORT_FILE="bootstrap_migration_report.txt"
SUMMARY_FILE="bootstrap_migration_summary.csv"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

total_files=0
files_needing_change=0
total_issues=0

EXTENSIONS=("html" "htm" "twig" "liquid" "erb" "php" "jsx" "tsx" "vue" "js" "ts" "css" "scss" "sass" "less" "md" "yml" "yaml" "json" "xml" "njk" "jinja" "j2")

build_find_cmd() {
    local dir="$1"
    local cmd="find \"$dir\" -type f \( "
    local first=true
    for ext in "${EXTENSIONS[@]}"; do
        if $first; then
            cmd+="-iname \"*.$ext\""
            first=false
        else
            cmd+=" -o -iname \"*.$ext\""
        fi
    done
    cmd+=" \) \
        ! -path \"*/node_modules/*\" \
        ! -path \"*/.git/*\" \
        ! -path \"*/vendor/*\" \
        ! -path \"*/dist/*\" \
        ! -path \"*/.cache/*\" \
        ! -path \"*/_site/*\" \
        ! -path \"*/public/*\" \
        ! -path \"*/resources/*\" \
        ! -iname \"*.svg\""
    echo "$cmd"
}

declare -a PATTERNS=(

    "bootstrap@3\|bootstrap\.3\|bootstrap-3\|3\.[0-9]\.[0-9].*bootstrap\|bootstrap.*3\.[0-9]\.[0-9]|CRITICAL|Bootstrap 3 version reference found|Update to bootstrap@5.x CDN or package reference"
    "bootstrap\.min\.css\|bootstrap\.css\|bootstrap\.bundle\|bootstrap\.min\.js|WARNING|Generic Bootstrap file reference (verify version)|Make sure these point to Bootstrap 5 files"

    "col-xs-|CRITICAL|col-xs-* removed in BS5|Replace with col- (xs is now the default breakpoint)"
    "\bhidden-xs\b|\bvisible-xs\b|\bhidden-sm\b|\bvisible-sm\b|\bvisible-md\b|\bhidden-md\b|\bvisible-lg\b|\bhidden-lg\b|CRITICAL|BS3 responsive visibility helpers removed|Use d-none/d-sm-block/d-md-block etc."
    "\bcontainer-fluid\b.*\brow\b|\brow\b.*\bcontainer-fluid\b|INFO|Review container-fluid/row nesting|BS5 gutter system changed; check padding and margin"

    "\btext-left\b|WARNING|text-left changed in BS5|Use text-start"
    "\btext-right\b|WARNING|text-right changed in BS5|Use text-end"
    "\bfloat-left\b|WARNING|float-left changed in BS5|Use float-start"
    "\bfloat-right\b|WARNING|float-right changed in BS5|Use float-end"
    "\bml-[0-9]\b|\bmr-[0-9]\b|\bpl-[0-9]\b|\bpr-[0-9]\b|WARNING|ml-/mr-/pl-/pr-* renamed in BS5|Use ms-/me-/ps-/pe-* (logical properties)"
    "\btext-muted\b|INFO|text-muted deprecated in BS5.3|Use text-body-secondary"

    "\bnavbar-default\b|CRITICAL|navbar-default removed|Use navbar-light or navbar-dark with bg-* utility"
    "\bnavbar-toggle\b|CRITICAL|navbar-toggle renamed|Use navbar-toggler"
    "\bsr-only\b|CRITICAL|sr-only renamed in BS5|Use visually-hidden"
    "\bcollapse navbar-collapse\b|INFO|Review navbar-collapse markup|Structure slightly changed in BS5"
    "\bnav navbar-nav\b|WARNING|navbar-nav pattern changed|Drop the extra nav class prefix"

    "\bbtn-default\b|CRITICAL|btn-default removed|Use btn-secondary or btn-outline-secondary"
    "\bbtn-xs\b|CRITICAL|btn-xs removed|Use btn-sm"
    "\bdata-toggle=|CRITICAL|data-toggle attribute removed|Replace with data-bs-toggle"
    "\bdata-dismiss=|CRITICAL|data-dismiss attribute removed|Replace with data-bs-dismiss"
    "\bdata-target=|WARNING|data-target replaced in BS5|Replace with data-bs-target"
    "\bdata-spy=|CRITICAL|data-spy removed|Use Bootstrap 5 ScrollSpy JS API"
    "\bdata-ride=|CRITICAL|data-ride removed|Use data-bs-ride"
    "\bdata-slide=|CRITICAL|data-slide removed|Use data-bs-slide"
    "\bdata-interval=|WARNING|data-interval changed|Use data-bs-interval"
    "\bdata-parent=|CRITICAL|data-parent removed|Use data-bs-parent"
    "\bdata-offset=|WARNING|data-offset changed|Use data-bs-offset"

    "\bform-group\b|WARNING|form-group removed in BS5|Use mb-3 or a spacing utility"
    "\bform-control-feedback\b|CRITICAL|form-control-feedback removed|Use BS5 validation classes"
    "\bhas-error\b|\bhas-success\b|\bhas-warning\b|CRITICAL|Form validation state classes removed|Use was-validated or is-invalid/is-valid on inputs"
    "\bform-horizontal\b|CRITICAL|form-horizontal removed|Use grid classes directly on the form"
    "\bform-inline\b|CRITICAL|form-inline removed|Use d-flex/align-items-center or row/col grid"
    "\binput-group-addon\b|CRITICAL|input-group-addon removed|Use input-group-text"
    "\bcontrol-label\b|WARNING|control-label removed|Use form-label"
    "\bform-check\b|INFO|Verify checkbox markup|BS5 uses form-check with form-check-input and form-check-label"
    "\bradio\b.*class=|INFO|Verify radio button markup|BS5 uses form-check for radios too"

    "\bmodal-backdrop fade in\b|WARNING|Old modal backdrop class pattern|BS5 uses modal-backdrop show"
    "\bmodal-dialog-centered\b|INFO|modal-dialog-centered present|Verify it is the BS5 version"

    "\bpanel\b|\bpanel-default\b|\bpanel-heading\b|\bpanel-body\b|\bpanel-footer\b|\bpanel-title\b|CRITICAL|Panel component removed|Migrate to card/card-header/card-body/card-footer"
    "\bpanel-primary\b|\bpanel-success\b|\bpanel-info\b|\bpanel-warning\b|\bpanel-danger\b|CRITICAL|Contextual panel classes removed|Use card with border-* or text-bg-* utilities"

    "\bthumbnail\b|CRITICAL|thumbnail component removed|Use card with card-img"
    "\bwell\b|CRITICAL|Well component removed|Use card or bg-light with p-3 and rounded"

    "glyphicon|CRITICAL|Glyphicons removed in BS4/5|Use Bootstrap Icons, Font Awesome, or another icon library"
    "\bjumbotron\b|CRITICAL|Jumbotron removed in BS5|Use a div with py-5/bg-light or build a hero section with utilities"

    "\bbadge-\b|\blabel label-\b|WARNING|BS3 label/badge patterns changed|Use badge bg-* e.g. badge bg-primary"
    "\blabel-default\b|\blabel-primary\b|\blabel-success\b|\blabel-info\b|\blabel-warning\b|\blabel-danger\b|CRITICAL|BS3 label classes removed|Use badge text-bg-* classes"

    "\balert-dismissable\b|CRITICAL|alert-dismissable renamed|Use alert-dismissible"

    "role=\"progressbar\".*class=\"progress-bar\"|INFO|Verify progress bar markup|BS5 uses updated ARIA attributes"

    "\bdropdown-menu\b.*\bright\b|\bpull-right\b|WARNING|pull-right and dropdown-menu-right changed|Use dropdown-menu-end"
    "\bpull-left\b|WARNING|pull-left removed|Use float-start or ms-auto"
    "\bopen\b.*dropdown|WARNING|BS3 open class on dropdown parent|BS5 uses the show class"

    "\btable-condensed\b|CRITICAL|table-condensed renamed|Use table-sm"
    "\bsuccess\b.*\btable\b|\bdanger\b.*\btable\b|\bwarning\b.*\btable\b|WARNING|BS3 contextual table row classes changed|Use table-success/table-danger/table-warning"

    "\btab-content\b|\btab-pane\b|\bnav-tabs\b|INFO|Verify tab implementation|data-toggle=tab becomes data-bs-toggle=tab in BS5"

    "\baffix\b|\bdata-spy=\"affix\"\b|CRITICAL|Affix plugin removed in BS4/5|Use CSS position:sticky or a JS alternative"
    "\bdata-spy=\"scroll\"\b|CRITICAL|data-spy='scroll' removed|Use Bootstrap 5 ScrollSpy via JS: new bootstrap.ScrollSpy(...)"

    "\bcarousel-inner\b.*\bitem\b|\bclass=\"item\"\b|CRITICAL|Carousel item class renamed|Use carousel-item instead of item"
    "\bdata-slide-to=|WARNING|data-slide-to changed|Use data-bs-slide-to"
    "\bdata-ride=\"carousel\"\b|CRITICAL|data-ride='carousel' removed|Use data-bs-ride='carousel'"

    "\\\$.*tooltip\(\)|\\\$.*popover\(\)|WARNING|jQuery-based tooltip/popover init|BS5 requires explicit init: bootstrap.Tooltip / bootstrap.Popover"
    "jquery\|jQuery|\\\$\(document\)\.ready\|\\\$(function|\\\$\.fn\.|jquery\.min|WARNING|jQuery detected|BS5 dropped jQuery; audit all JS interactions"

    "-webkit-|INFO|Vendor-prefixed CSS found|Verify still needed; BS5 drops many old prefixes"

    "site\.baseurl\|site\.url\|page\.url\|page\.title\|page\.content\|\{\%.*\%\}|\{\{.*site\.\|include.*\.html|CRITICAL|Jekyll template syntax detected in content or layout|Convert to Hugo syntax: site.x -> .Site.Params.x, page.x -> .Params.x"
    "layout:.*baseof\|layout:.*default\|layout:.*page|WARNING|Frontmatter layout value may be Jekyll-style|Hugo ignores layout: in frontmatter for most cases; use cascade in hugo.yaml"
    "\burl:\s*/[a-z]|WARNING|Explicit url: frontmatter found|Remove url: frontmatter — let hugo.yaml uglyURLs handle routing"
    "permalink:|WARNING|Jekyll permalink frontmatter found|Convert to url: or slug: for Hugo"
    "\{\{.*\.Site\.Data\.[a-z].*\}\}|INFO|Hugo data access found|Verify variable scoping — use dollar sign prefix inside range loops"
    "README\.md|INFO|README.md referenced|Hugo does not treat README.md as index — rename to index.md or _index.md"
    "\bnavgoco\b|CRITICAL|navgoco jQuery plugin found|Not compatible with BS5; replace with BS5 accordion or collapse component"
    "jquery\.navgoco|CRITICAL|navgoco jQuery plugin referenced|Replace with native BS5 collapse for sidebar navigation"
)

print_header() {
    echo -e "${BOLD}${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║        Bootstrap 3 → 5  Migration Audit Script                  ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${RESET}"
    echo -e "  Scanning: ${BOLD}$REPO_DIR${RESET}"
    echo -e "  Report:   ${BOLD}$REPORT_FILE${RESET}"
    echo -e "  CSV:      ${BOLD}$SUMMARY_FILE${RESET}"
    echo ""
}

severity_color() {
    case "$1" in
        CRITICAL) echo -e "${RED}" ;;
        WARNING)  echo -e "${YELLOW}" ;;
        INFO)     echo -e "${CYAN}" ;;
        *)        echo -e "${RESET}" ;;
    esac
}

main() {
    print_header

    {
        echo "Bootstrap 3 → 5 Migration Audit Report"
        echo "Generated: $(date)"
        echo "Repository: $REPO_DIR"
        echo "========================================"
        echo ""
    } > "$REPORT_FILE"

    echo "file,line,severity,pattern,description,fix" > "$SUMMARY_FILE"

    mapfile -t FILES < <(eval "$(build_find_cmd "$REPO_DIR")" 2>/dev/null | sort)

    total_files=${#FILES[@]}
    echo -e "Found ${BOLD}$total_files${RESET} files to scan...\n"

    declare -A file_issues
    declare -A file_counts

    current_file=0

    for filepath in "${FILES[@]}"; do
        ((current_file++))
        rel_path="${filepath#$REPO_DIR/}"

        printf "\r\033[K  ${CYAN}[%4d/%4d]${RESET} Scanning: ${BOLD}%-80s${RESET}" \
            "$current_file" "$total_files" "${rel_path:0:80}" >&2

        local_issues=()

        for pattern_entry in "${PATTERNS[@]}"; do
            IFS='|' read -r pattern severity description fix <<< "$pattern_entry"

            while IFS=: read -r lineno matchline; do
                issue_str="${lineno}|${severity}|${pattern}|${description}|${fix}|${matchline}"
                local_issues+=("$issue_str")
                ((total_issues++))

                safe_file="${filepath//,/;}"
                safe_desc="${description//,/;}"
                safe_fix="${fix//,/;}"
                safe_match="${matchline//,/;}"
                echo "\"$safe_file\",$lineno,$severity,\"$pattern\",\"$safe_desc\",\"$safe_fix\"" >> "$SUMMARY_FILE"
            done < <(grep -inE "$pattern" "$filepath" 2>/dev/null | head -20)
        done

        if [ ${#local_issues[@]} -gt 0 ]; then
            ((files_needing_change++))
            file_issues["$filepath"]=$(printf '%s\n' "${local_issues[@]}")
            file_counts["$filepath"]=${#local_issues[@]}

            printf "\r\033[K" >&2
            echo -e "  ${RED}✗${RESET} [${current_file}/${total_files}] ${BOLD}${rel_path}${RESET}  → ${RED}${#local_issues[@]} issue(s)${RESET}"
        else
            printf "\r\033[K" >&2
            echo -e "  ${GREEN}✓${RESET} [${current_file}/${total_files}] ${rel_path}"
        fi
    done

    printf "\r\033[K" >&2
    echo -e "\n${GREEN}Scan complete.${RESET} Building full report...\n"

    echo -e "${BOLD}━━━  FILE-BY-FILE RESULTS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

    for filepath in "${!file_issues[@]}"; do
        rel_path="${filepath#$REPO_DIR/}"
        count="${file_counts[$filepath]}"
        echo -e "${BOLD}📄 $rel_path${RESET}  (${RED}$count issue(s)${RESET})"
        echo "──────────────────────────────────────────────────"

        while IFS='|' read -r lineno severity pattern description fix matchline; do
            color=$(severity_color "$severity")
            echo -e "  ${color}[$severity]${RESET} Line ${BOLD}$lineno${RESET}"
            echo -e "    Pattern   : $pattern"
            echo -e "    Issue     : $description"
            echo -e "    Fix       : ${GREEN}$fix${RESET}"
            echo -e "    Context   : ${YELLOW}$(echo "$matchline" | sed 's/^[[:space:]]*//' | cut -c1-120)${RESET}"
            echo ""
        done <<< "${file_issues[$filepath]}"

        {
            echo ""
            echo "FILE: $rel_path  [$count issues]"
            echo "--------------------------------------"
            while IFS='|' read -r lineno severity pattern description fix matchline; do
                echo "  [$severity] Line $lineno"
                echo "    Pattern : $pattern"
                echo "    Issue   : $description"
                echo "    Fix     : $fix"
                echo "    Context : $(echo "$matchline" | sed 's/^[[:space:]]*//' | cut -c1-120)"
                echo ""
            done <<< "${file_issues[$filepath]}"
        } >> "$REPORT_FILE"
    done

    echo -e "${BOLD}━━━  CLEAN FILES  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
    for filepath in "${FILES[@]}"; do
        if [ -z "${file_issues[$filepath]+_}" ]; then
            rel_path="${filepath#$REPO_DIR/}"
            echo -e "  ${GREEN}✓${RESET} $rel_path"
        fi
    done
    echo ""

    clean_files=$((total_files - files_needing_change))
    echo -e "${BOLD}${CYAN}━━━  SUMMARY  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "  Total files scanned     : ${BOLD}$total_files${RESET}"
    echo -e "  Files needing changes   : ${BOLD}${RED}$files_needing_change${RESET}"
    echo -e "  Clean files             : ${BOLD}${GREEN}$clean_files${RESET}"
    echo -e "  Total issues found      : ${BOLD}${RED}$total_issues${RESET}"
    echo -e ""
    echo -e "  📄 Full report  → ${BOLD}$REPORT_FILE${RESET}"
    echo -e "  📊 CSV summary  → ${BOLD}$SUMMARY_FILE${RESET}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

    {
        echo ""
        echo "========================================"
        echo "SUMMARY"
        echo "========================================"
        echo "Total files scanned   : $total_files"
        echo "Files needing changes : $files_needing_change"
        echo "Clean files           : $clean_files"
        echo "Total issues found    : $total_issues"
    } >> "$REPORT_FILE"
}

if [ ! -d "$REPO_DIR" ]; then
    echo -e "${RED}Error: Directory '$REPO_DIR' not found.${RESET}"
    echo "Usage: bash bootstrap_migration_audit.sh /path/to/repo"
    exit 1
fi

main