# Public landing and capability guide

Implemented 3 November 2026 from the two HTML references in `sample_design`.

## Public experience

- `/` preserves the original cinematic hero, headline, environment selector and
  visual identity. Five capability groups introduce all 22 audited areas.
  Additional sections explain independent execution authority, show a recorded
  cleanroom simulator view, describe governed learning and link to evidence.
- `/how-it-works` contains a nine-stage interactive mission lifecycle, five
  illustrative scenarios, and 22 searchable capability cards grouped into five
  families. Cards have implementation/configuration labels, relevant scope
  notes and links to the existing operational workspaces.
- Mobile navigation, visible keyboard focus, skip links, retained focus after
  selector updates, and reduced-motion support apply to both public pages.

The scenario diagrams are explanatory and never dispatch commands. The facility
image is a recorded simulator screenshot, explicitly labelled as such. Application
links open existing pages; mission execution and other operational capabilities
are unchanged.

## Sources and maintenance

- `frontend/public/landing/index.html`: landing content, styles and interactions.
- `frontend/public/how-it-works/index.html`: detailed guide and its structured
  `CAPABILITIES`, `FAMILIES`, `STEPS`, `BOUNDARIES` and `WORKSPACES` data.
- `frontend/next.config.js`: public rewrites, outside the operational AppShell.
- `frontend/public/landing/facility-preview.png`: existing simulator validation
  image from `docs/validation/2026-11-03-facility-realism/facility-close-up.png`.
- `frontend/public/landing/validation.json`: dated copy of the previously recorded
  oversight validation. Landing counts describe that historical run, not a live
  test counter. Update both numbers and report together after fresh validation.
- `docs/CAPABILITY_AUDIT.md`: implementation and configuration scope reference.

Model integrations require configuration. The guide distinguishes these from
the simulator implementation. Mixed-fleet support covers navigation, STOP and
WAIT; physical manipulation, balance, cross-platform skill transfer and multi-site
failover are outside current scope. There is no hardware certification claim.

The sample's obsolete simulation link, old test counts, incomplete-oversight
description, embedded image payloads and unused demo scripts were not imported.
Its lifecycle, capability grouping, authority and learning layouts were adapted.
The original redundant three-card summary was replaced by the five-family overview.

## Verification

Production build: `NEXT_DIST_DIR=.next-landing-validation BACKEND_URL=http://127.0.0.1:18080 npm --prefix frontend run build`.

Read-only browser checks: `node tests/public-pages.browser.cjs` against port 19300.
Override the origin with `PUBLIC_BASE_URL` when needed. The validation stack
accepts `BROWSER_NEXT_DIST_DIR` to serve an isolated build without replacing other
build directories.

Checks cover original hero retention, actual screenshot loading, all 22 cards,
deep links, pointer/keyboard interaction, search/no-results/family/status filters,
scenario route changes, duplicate IDs, mobile navigation, widths 390/768/1024/1440,
reduced motion and JavaScript errors. Screenshots and the report are saved in
`docs/validation/2026-11-03-public-pages/`.

Backend tests were not rerun for this public HTML/CSS/JavaScript change. The
previous 489 backend results are labelled as recorded evidence on the landing.

## Clarity pass

Both public pages use simpler wording and larger body text. Every capability
card includes a plain-language purpose and a practical example before its steps.
Search includes those explanations and examples. Scenario sequences use numbered
steps, and the status legend explains simulator availability versus required
external-service setup. Technical names remain for discoverability, with their
meaning explained in the adjacent description. No operational behavior changed.

## Navigation and density optimization

The landing now has seven sections: original hero, working simulator, capability
families, movement authority, application environments, recorded evidence and
final application links. The repeated platform introduction, learning section
and model section were removed from this page; the detailed capability guide
retains coverage of those areas. The original hero remains, its image is
preloaded, and the actual simulator preview appears directly beneath it.

Each capability keeps its purpose, status and workspace link visible. Native
`details` / `summary` controls reveal examples, steps, outcomes and limits.
Search includes this content and automatically opens matching details. Lifecycle
shortcuts select the appropriate capability family. Counts and Reset filters
make the active selection visible and reversible.

Before/after snapshots in the validation folder use the same local browser and
900px viewport height. At width 390, the landing scroll height fell from 13,403px
to 9,315px (30.5%); the guide fell from 23,037px to 14,733px (36.0%). These measure
initial page length, not loading speed. Collapsing details does not remove their
HTML or claim a network-payload saving. Twelve read-only browser checks passed.

Reference reviewed: https://thehumanoid.ai/ on 3 November 2026. Its clear product
introduction, repeated primary action and evidence through case studies and
specifications informed the hierarchy: earlier simulator preview, persistent
Mission Control links and dated evidence. Its imagery, partner logos, hardware
specifications and deployment claims were not imported. Media did not fully load
in the headless reference screenshot, so no video-performance conclusions were
drawn from it.

### Local font loading

DM Sans and Manrope Latin variable WOFF2 files are served from
`frontend/public/landing/fonts/`, with both SIL Open Font License files retained.
The files came from Google Fonts CSS and fonts.gstatic.com; license texts came
from the google/fonts repository. Both pages preload these fonts, use
`font-display: swap`, and no longer import remote stylesheets.

A fresh local-browser sample before this fix recorded a 10.3-second landing load
while external fonts were requested. After self-hosting, a separate unthrottled
sample recorded approximately 95ms and 98ms load times for the landing and guide,
with CLS 0 on both. These are single localhost samples with uncontrolled external
network conditions in the earlier run, not field performance claims. See
`local-load-sample.json` and `local-load-after-fonts.json` in the validation folder.
The final browser suite also checks local font availability and that no public
page issues third-party requests.

## Recorded mission highlights

The working-system section now leads with one archived mission's five recorded
moments, a facility reference image and a floor plan using actual recorded poses.
See [RECORDED_MISSION_STORY.md](RECORDED_MISSION_STORY.md) for provenance,
verification, export instructions and the disclosed historical audit-linkage
limitation. The current public-page browser suite passes 13 checks.
