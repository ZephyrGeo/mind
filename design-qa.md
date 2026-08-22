# Mind Canvas 2 Design QA

- Source visual truth: `docs/design/mind-chatgpt-inspired-canvas-2.png`
- Implementation screenshot: `docs/design/mind-canvas-2-implementation-before-sidebar-feedback.png`
- Combined comparison: `docs/design/mind-canvas-2-qa-comparison-before-sidebar-feedback.png`
- Intended viewport: desktop empty state; exact CSS viewport was not supplied with the screenshot
- Source pixels: 1487 × 1058
- Implementation pixels: 3290 × 1914
- Density normalization: both frames were proportionally reduced into one 2420 × 848 comparison canvas; exact device pixel ratio remains unknown
- State: light theme, empty new conversation, conversation history visible

**Findings**

- [P2] The desktop sidebar had no collapse/reopen control.
  Evidence: the rendered screenshot showed a permanently fixed sidebar, while the requested ChatGPT-like interaction requires reclaiming the canvas when history is not needed.
  Impact: the main workspace could not expand for long conversations or focused work.
  Fix applied: added an in-sidebar collapse control, a main-canvas reopen control, animated grid resizing, and mobile drawer-compatible behavior.
- [P2] Sidebar typography was materially smaller than the selected canvas and user preference.
  Evidence: navigation and conversation rows rendered around 11–13px and looked faint in the combined comparison.
  Impact: history scanning and navigation were harder than necessary on a large desktop viewport.
  Fix applied: after one additional user-directed increase, navigation and new-chat text now use 16px, search and conversation titles 15px, group/profile labels 14px, and supporting metadata 12px.
- Post-fix visual evidence is still missing.
  Impact: toggle placement, transition behavior, larger-text wrapping, and final fidelity cannot be passed from source code alone.
  Fix: provide a fresh screenshot showing the expanded sidebar and, ideally, the collapsed state.

**Required Fidelity Surfaces**

- Fonts and typography: first-pass mismatch found and fixed; post-fix capture pending.
- Spacing and layout rhythm: overall empty-state composition is close; collapsible-sidebar states remain unverified.
- Colors and visual tokens: warm ivory, orange accent, and subtle borders align with the selected canvas.
- Image quality and asset fidelity: rendered Phosphor icons are sharp in the supplied screenshot; the new sidebar toggle icon remains unverified.
- Copy and content: verified statically against the selected design and frontend contract tests.

**Full-view Comparison Evidence**

The combined canvas shows a faithful warm-light palette, centered hero/composer hierarchy, and matching lightweight sidebar structure. The implementation initially lacked sidebar toggling and used smaller sidebar type than the target.

**Focused Region Comparison Evidence**

The sidebar comparison was readable enough to identify the toggle and typography findings. No separate crop was needed because the supplied implementation screenshot had sufficient resolution.

**Primary Interactions and Console**

- Automated frontend and backend contracts pass.
- Sidebar toggle contract coverage was added and all automated tests pass.
- Browser interaction tests, responsive inspection, and console-error inspection remain blocked pending local browser access or post-fix screenshots.

**Comparison History**

- Initial implementation pass: canvas 2 structure, light palette, centralized composer, grouped history, responsive drawer, and icon system implemented.
- First visual comparison: found P2 missing toggle and P2 undersized sidebar type using the combined comparison image.
- Fixes made: desktop collapse/reopen state, mobile-safe toggle behavior, grid transition, and two rounds of increased sidebar typography.
- Post-fix comparison: blocked pending a fresh rendered screenshot.

**Implementation Checklist**

- Capture the expanded and collapsed desktop sidebar states after hot reload.
- Compare the new expanded state with the selected source in a combined visual input.
- Confirm the new typography does not wrap or truncate unexpectedly.
- Exercise history search, conversation opening, mode switching, and responsive navigation.
- Check browser console errors.

**Follow-up Polish**

None classified until the first rendered comparison is available.

Historical result: blocked

---

# Mind Memory Option 3 Design QA

- Source visual truth: `/Users/fuyimin/.codex/generated_images/019faeda-a892-7c62-acb7-a285e5e57826/exec-b45e069d-c083-4b11-aeff-af2904a4c38c.png`
- Implementation screenshot: unavailable because the saved in-app browser permission blocks `http://127.0.0.1:3000/`
- Intended viewport: 1440 × 1024 CSS px
- Source pixels: 1487 × 1058
- Implementation pixels: unavailable
- Density normalization: unavailable until the implementation can be captured
- State: Memory view with review items, saved memories, first review row expanded, light theme

**Findings**

- [P1] Browser-rendered comparison is unavailable.
  Evidence: the selected source image is available and inspected, but the in-app browser refuses local access before the implementation can be captured.
  Impact: typography, row density, wrapping, responsive behavior, interaction states, and console health cannot be approved from source code or build output alone.
  Fix: allow localhost access in the in-app browser, open the Memory view, and capture the 1440 × 1024 review state.

**Required Fidelity Surfaces**

- Fonts and typography: statically implemented with Inter followed by PingFang SC, Hiragino Sans GB, Microsoft YaHei, and system sans-serif fallbacks; visual comparison blocked.
- Spacing and layout rhythm: compact toolbar, inline add control, grouped single-column lists, expandable rows, and mobile reflow are implemented; visual comparison blocked.
- Colors and visual tokens: existing Mind cream, charcoal, stone, and orange tokens are reused; rendered contrast remains unverified.
- Image quality and asset fidelity: the selected Memory concept contains no raster content; UI symbols continue to use the existing Phosphor icon library.
- Copy and content: search, add, review, saved, history, source, expiry, confidence, version, and existing actions are present in the built frontend.

**Full-view Comparison Evidence**

Blocked: no browser-rendered implementation screenshot exists for a combined comparison with the selected source.

**Focused Region Comparison Evidence**

Blocked for the same reason. The expanded review row and Chinese typography require a focused rendered comparison.

**Primary Interactions and Console**

- Static frontend contracts cover the redesigned selectors and copy and currently pass.
- Search, inline creation, expand/collapse, confirm, enable/disable, pin, edit, expiry, delete, and history controls remain wired to the existing behavior.
- Browser interaction testing and console-error inspection are blocked by saved localhost permissions.

**Comparison History**

- Initial implementation: rebuilt Memory as the selected Option 3 single-column grouped list and applied the requested Chinese sans-serif stack.
- First browser capture: blocked before navigation by the saved localhost permission; no visual fixes can be responsibly inferred from code alone.

**Implementation Checklist**

- Allow localhost access and capture the Memory view at 1440 × 1024.
- Compare the source and implementation in one combined image.
- Verify Chinese wrapping, row alignment, expanded detail spacing, mobile reflow, and visible focus states.
- Exercise the primary Memory actions and check the browser console.

**Follow-up Polish**

None classified until the first rendered comparison is available.

final result: blocked

---

# Mind Insight Diff Chat-first UI Design QA — 2026-08-22

- Source visual truth: `/Users/fuyimin/.codex/generated_images/019faeda-a892-7c62-acb7-a285e5e57826/exec-24dd65da-877d-4bdc-b37e-a075367dd68a.png`
- Implementation screenshot: `/tmp/mind-insight-qa/implementation-desktop.png`
- Responsive screenshot: `/tmp/mind-insight-qa/implementation-mobile.png`
- Full comparison: `/tmp/mind-insight-qa/design-comparison.png`
- Focused comparison: `/tmp/mind-insight-qa/design-comparison-focused.png`
- Viewports: 1280 × 720 CSS px desktop; 390 × 844 CSS px responsive
- Source pixels: 1448 × 1086; implementation pixels: 1280 × 720 desktop and 390 × 844 responsive
- Density normalization: device scale factor 1. The 4:3 source was normalized to 960 × 720 beside the 1280 × 720 implementation for the full comparison. Focused report regions were cropped and normalized to 720 px height for the detailed comparison.
- State: completed comparison Research turn, Latest report selected, light theme; Baseline, stale-claim, source, progress, and responsive states also exercised.

**Findings**

- No actionable P0, P1, or P2 mismatch remains. The implementation preserves the selected Chat-first structure: a six-step progress header, complete latest report, immutable baseline/latest tabs, compact mutually exclusive change counts, claim-level status and confidence, two-sided evidence, separate stale claims, collapsed sources, and a persistent composer.
- The implementation intentionally retains the existing Mind shell, larger conversation typography, combined Chats and researches sidebar, and provider-neutral copy instead of reproducing the mock's removed sidebar timestamps or conversation header.

**Required Fidelity Surfaces**

- Fonts and typography: the existing sans-serif product stack is retained; headings, report body, compact metadata, and status labels preserve clear hierarchy without serif Chinese fallbacks or clipped text.
- Spacing and layout rhythm: progress, snapshot metadata, diff summary, report findings, stale claims, sources, and composer form one continuous assistant card. Desktop alignment and vertical rhythm match the selected direction; the 390 px layout reflows to two progress columns without horizontal overflow.
- Colors and visual tokens: neutral black/gray surfaces use a restrained blue Research accent. Changed, New, Contradicted, and Stale remain distinguishable through green, blue, orange, and gray semantic markers without warming the overall interface.
- Image quality and asset fidelity: no raster product imagery is required. Visible symbols use the project's existing icon library and the established ice-blue snowflake product mark.
- Copy and content: provider names are absent from progress and retry text; the complete report, snapshot preservation, comparison action, confidence labels, evidence links, stale claims, sources, and continued conversation composer are all present.

**Full-view Comparison Evidence**

- The combined comparison confirms the same primary hierarchy and interaction order as the source: completed progress, report controls, report tabs, snapshot relationship, change summary, full findings, collapsed evidence sections, and composer.
- Differences in sidebar density and report type scale are intentional continuations of previously approved Mind UI decisions rather than fidelity regressions.

**Focused Region Comparison Evidence**

- The focused comparison confirms the progress bar, six named steps, action placement, tabs, snapshot metadata, change counts, report heading, inline classification confidence, and previous/current evidence remain legible and aligned.
- The implementation places evidence immediately after the affected finding paragraph, keeping the report readable before showing the comparison detail.

**Primary Interactions and Console**

- Switched between Latest report and Baseline report and confirmed each immutable snapshot renders independently.
- Expanded stale claims and sources independently and confirmed their evidence links remain present.
- Confirmed the Research composer stays available below the report.
- Confirmed the 390 px viewport has `scrollWidth === clientWidth` and no horizontal overflow.
- Browser console: no warnings or errors.

**Comparison History**

- Initial implementation: progress and report were visually separated and change evidence appeared before the affected report paragraph.
- Fixes made: combined progress and report into one assistant card, aligned Research accents to the selected blue direction, rendered six numbered stages, and moved two-sided evidence directly after the matching finding paragraph.
- Post-fix evidence: `/tmp/mind-insight-qa/design-comparison.png` and `/tmp/mind-insight-qa/design-comparison-focused.png` show no remaining actionable P0/P1/P2 difference.

**Implementation Checklist**

- Six-stage progress and terminal states verified.
- Complete latest and baseline snapshots verified.
- Four mutually exclusive change categories and claim confidence verified.
- Stale claims and source disclosure verified.
- Desktop and responsive layout verified.
- Automated frontend, backend, type, and lint checks verified.

**Follow-up Polish**

- P3: production report language and source volume will create denser real-world content than the fixture; the current collapse and wrapping behavior is ready for that load, but a staging visual pass remains useful after deployment.

final result: passed

---

# Mind Cited Sources Disclosure — 2026-08-23

- Source visual truth: `/var/folders/h3/hrcbcfns6nv185w_syw_lbbh0000gn/T/codex-clipboard-163c2a53-b73b-4590-8fab-51de56b82038.png`
- Supporting problem screenshot: `/var/folders/h3/hrcbcfns6nv185w_syw_lbbh0000gn/T/codex-clipboard-828b8f7d-ea61-48b0-95a2-87e73abbfd41.png`
- Implementation screenshot: unavailable because the saved in-app browser permission blocks `http://127.0.0.1:3000/`
- Intended viewport: desktop Research report; exact CSS viewport was not supplied
- Source pixels: 319 × 96 focused target crop; 1672 × 1264 supporting screenshot
- Implementation pixels: unavailable
- Density normalization: unavailable until the implementation can be captured
- State: completed Research report with the Sources disclosure collapsed

**Findings**

- [P1] Browser-rendered comparison is unavailable.
  Evidence: both source screenshots were opened and inspected, but the in-app browser rejected local navigation before the updated disclosure could be captured.
  Impact: exact icon alignment, type scale, collapsed-row height, expanded list density, and console health cannot be visually approved.
  Fix: allow localhost access in the in-app browser and capture the collapsed and expanded Sources states.

**Required Fidelity Surfaces**

- Fonts and typography: the disclosure label now uses the existing sans-serif stack at 14px with semibold weight; visual comparison is blocked.
- Spacing and layout rhythm: one full-width disclosure row remains below the report, with the icon and label grouped left and caret right; visual comparison is blocked.
- Colors and visual tokens: the existing neutral report border and gray label color are retained; visual contrast is blocked.
- Image quality and asset fidelity: no raster asset is required; the existing Phosphor books and caret icons match the selected component language.
- Copy and content: the collapsed row contains only `Sources`; the old total-source badge and duplicate generated source section are removed.

**Full-view Comparison Evidence**

Blocked: no browser-rendered implementation screenshot is available for a combined comparison.

**Focused Region Comparison Evidence**

Blocked for the same reason. The selected target is already a focused Sources disclosure crop.

**Primary Interactions and Console**

- Automated frontend tests verify that only report-cited sources remain visible, duplicate canonical URLs share one display number, sparse source IDs are renumbered by first use, and generated trailing Sources sections are removed.
- Expanded/collapsed interaction and browser console inspection remain blocked by the saved localhost permission.

**Comparison History**

- Earlier state: the report showed a model-generated Sources list plus a second disclosure reporting all 58 pages seen during search.
- Fixes made: removed the generated source section at presentation time, limited the disclosure to actually cited sources, deduplicated URLs, assigned contiguous display IDs, and removed the all-source count and `View all` state.
- Post-fix visual comparison: blocked before local navigation by the saved permission.

**Implementation Checklist**

- Capture the collapsed Sources row.
- Expand Sources and verify cited titles, continuous IDs, wrapping, and link affordances.
- Confirm the report has no second Sources heading or all-source count.
- Check responsive layout and browser console errors.

**Follow-up Polish**

None classified until browser-rendered evidence is available.

final result: blocked

---

# Conversation Refresh Route Regression — 2026-08-22

- Opened an existing Research conversation and confirmed its conversation ID is encoded in the URL.
- During asynchronous restoration, the page shows a neutral `Opening conversation…` state instead of briefly rendering the new-conversation screen.
- Reloaded the page and confirmed the same conversation, report, and composer are restored instead of the new-conversation screen.
- Switched the same conversation to Chat mode, reloaded, and confirmed both the conversation and selected mode remain intact.
- Legacy `#/chat` and `#/research` routes continue to open a new conversation.
- Frontend contract tests cover conversation-aware route generation and restoration.

final result: passed

---

# Mind Sidebar Chat and Research Sections Design QA

- Source visual truth: `/var/folders/h3/hrcbcfns6nv185w_syw_lbbh0000gn/T/codex-clipboard-7a2e015c-5c35-4d0b-8c55-61acf767bb27.png`
- Implementation screenshot: unavailable because the saved in-app browser permission blocks `http://127.0.0.1:3000/`
- Intended viewport: desktop sidebar; exact CSS viewport was not supplied
- Source pixels: 560 × 740
- Implementation pixels: unavailable
- Density normalization: unavailable until the implementation can be captured
- State: expanded Chats and Research history sections, light theme

**Findings**

- [P1] Browser-rendered comparison is unavailable.
  Evidence: the source screenshot was opened and inspected, but the in-app browser rejected local access before an implementation screenshot could be captured.
  Impact: final spacing, label alignment, caret placement, transition behavior, and console health cannot be approved visually.
  Fix: allow localhost access in the in-app browser and capture the expanded and collapsed sidebar states.

**Required Fidelity Surfaces**

- Fonts and typography: existing sidebar sans-serif sizing is preserved; rendered fidelity is blocked.
- Spacing and layout rhythm: Chats and Research are separate stacked sections with compact title rows; rendered fidelity is blocked.
- Colors and visual tokens: existing neutral sidebar and hover tokens are reused; rendered contrast is blocked.
- Image quality and asset fidelity: no raster imagery is required; section and caret controls use the existing Phosphor icon library.
- Copy and content: both section names, independent empty states, and search-aware empty messages are present.

**Full-view Comparison Evidence**

Blocked: no browser-rendered implementation screenshot is available for a combined comparison with the source.

**Focused Region Comparison Evidence**

Blocked for the same reason. The source itself is already a focused sidebar crop.

**Primary Interactions and Console**

- Both sections remain visible even when empty.
- Each section has an independent accessible expand/collapse button.
- Automated frontend contracts pass.
- Browser interaction testing and console-error inspection are blocked by saved localhost permissions.

**Comparison History**

- Initial implementation: separated stored conversations by `mode` into Chats and Research.
- Current refinement: added persistent dual section headings, independent caret controls, collapsed states, and section-specific empty states.
- Post-fix visual comparison: blocked before local navigation by the saved permission.

**Implementation Checklist**

- Restart the local app so the backend returns conversation `mode` values.
- Capture expanded Chats and Research sections.
- Collapse and reopen each section and confirm the other section is unaffected.
- Check truncation, hover/active states, and browser console errors.

**Follow-up Polish**

None classified until the rendered comparison is available.

final result: blocked

---

# Current Design QA Status

The Insight Diff Chat-first UI audit dated 2026-08-22 is the current handoff result. Earlier blocked sections above are retained as historical records for unrelated Memory and sidebar work.

final result: passed

---

# Mind Research Running State Refinement — 2026-08-22

- Source visual truth: `/var/folders/h3/hrcbcfns6nv185w_syw_lbbh0000gn/T/codex-clipboard-4fa5a944-f8d0-4a24-b147-68c789d8678f.png`
- Implementation screenshot: `/tmp/mind-insight-qa/implementation-progress-final.png`
- Combined comparison: `/tmp/mind-insight-qa/progress-design-comparison.png`
- Viewports: 840 × 808 CSS px desktop verification; 390 × 844 requested responsive override, rendered content width 325 CSS px in the in-app surface
- Source pixels: 1868 × 1326; implementation pixels: 840 × 808; responsive capture rendered at 325 × 703 pixels
- Density normalization: source and implementation were normalized to 806 px height in the combined comparison.
- State: Research conversation with one compact user message and an active Clarify brief task; light theme; composer visible.

**Findings**

- No actionable P0, P1, or P2 issue remains. The user message now sizes to its text instead of stretching with the conversation grid.
- The running Research state no longer uses a progress bar, expanded card, or six-stage row. It exposes only the current task, step count, and any actionable recovery notice.
- The current task label uses a restrained blue shimmer while running; completed, failed, cancelled, and reduced-motion states remain static.

**Required Fidelity Surfaces**

- Fonts and typography: existing Mind sans-serif typography is preserved. The current-task label remains readable throughout the shimmer and uses static text for reduced-motion users.
- Spacing and layout rhythm: conversation rows now align to their content start; the user bubble measured 204 × 48 CSS px for the Chinese prompt and no longer creates a tall empty panel.
- Colors and visual tokens: the Research task uses the existing ice-blue and blue accent on a neutral white canvas without adding a card background or visible progress track.
- Image quality and asset fidelity: no raster imagery is required; the snowflake and spinner continue to use the existing product icon library.
- Copy and content: the active task and `N / 6 steps` remain visible; provider-neutral recovery messages are preserved.

**Full-view Comparison Evidence**

- `/tmp/mind-insight-qa/progress-design-comparison.png` directly contrasts the reported oversized user bubble and progress panel with the compact implementation in the same image.
- The implementation preserves the same message order and composer while removing the unwanted vertical expansion and progress chrome.

**Focused Region Comparison Evidence**

- A separate crop was unnecessary because the combined full-view comparison renders the affected user bubble and Research status line clearly at readable size.
- Runtime measurement confirmed the task shimmer changed from `-58.9952%` to `-108.167%` background position over 450 ms.

**Primary Interactions and Console**

- Opened an active Research conversation and confirmed the current task and stop action remain available.
- Opened a completed Research comparison and confirmed the compact completion line still leads into the complete report.
- Verified the responsive state has no horizontal overflow (`scrollWidth === clientWidth`).
- Browser console: no warnings or errors.

**Comparison History**

- Earlier state: grid rows stretched sparse messages to fill the viewport; Research progress rendered a large bordered panel, progress track, and six-stage list.
- Fixes made: added start alignment and content-sized user-message constraints; replaced the expanded progress UI with one semantic status row and animated current-task label.
- Post-fix evidence: user bubble, task line, composer, desktop layout, and responsive layout passed visual and interaction checks.

**Implementation Checklist**

- Compact user message height verified.
- Active-task shimmer verified over time.
- Progress track and six-stage list removed.
- Completed, error, retry, and reduced-motion fallbacks retained.
- Desktop, responsive, console, and automated frontend checks passed.

**Follow-up Polish**

- P3: a real staging Research run should be checked once to confirm the backend's live phase transitions feel well paced with the new compact animation.

final result: passed

---

# Current Design QA Status — 2026-08-23

The cited-only Sources implementation is functionally covered, but its selected
collapsed and expanded visual states cannot be captured because the saved in-app
browser permission blocks the local application. The latest handoff therefore
remains blocked on browser-rendered evidence.

final result: blocked
