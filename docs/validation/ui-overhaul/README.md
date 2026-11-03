# UI overhaul browser evidence

The production Next.js build was exercised against the isolated real simulator
and backend using `BROWSER_SITE_LAYOUT=pharma`. No model API calls were made.
The stack uses throwaway databases and signed test learning fixtures; screenshots
are a simulation, not evidence of a physical deployment.

`browser-report.json` records nine passing workflow checks and no unexpected
page errors. It includes real mission creation, controller admission, obstacle
injection and environment revalidation, pause, busy-carrier handling, global
stop/release, mobile navigation, disconnected telemetry and forced WebGL failure.

Final validation on 2 November 2026:

- Backend regression suite: **449 passed** in 300.35 seconds.
- Production Next.js build: passed, including TypeScript validation.
- Browser workflow checks: **9 passed**.
- Isolated validation services: shut down after the checks.

- [Landing](landing-desktop.png)
- [Mission Control and the new 3D facility](mission-control-3d.png)
- [Recorded mission decisions](mission-evidence.png)
- [Operator access](operator-access.png)
- [Mobile workspace](mission-control-mobile.png)
- [Disconnected mobile workspace](disconnected-mobile.png)
- [WebGL fallback](webgl-fallback.png)

Reproduce with `scripts/browser_validation_stack.py` and
`node tests/mission-control.browser.cjs`; see [implementation notes](../../UI_UX_OVERHAUL.md).
