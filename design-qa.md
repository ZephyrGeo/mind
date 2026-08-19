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
