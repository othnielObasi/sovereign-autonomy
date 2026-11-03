# Public pages validation — 3 November 2026

The production build passed using `.next-landing-validation`. Both `/` and
`/how-it-works` were then served by that Next.js build at port 19300, with the
isolated simulator and backend available for existing workspace links.

Run `node tests/public-pages.browser.cjs` from the repository root to reproduce
the read-only checks. See `browser-report.json` for the final results and the
desktop/mobile PNG files for visual evidence. No missions or robot commands are
issued by this test. External model services and physical hardware are outside
this change's validation scope.

The 489 backend tests and 15 operational browser checks displayed on the landing
are historical results from the separate operator-controls validation, dated
explicitly on the page and linked through `/landing/validation.json`. They are
not results of the public-pages browser suite.
