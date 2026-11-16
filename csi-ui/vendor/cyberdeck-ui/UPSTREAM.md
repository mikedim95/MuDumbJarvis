# Cyberdeck UI source

- Repository: https://github.com/riagoncalves/cyberdeck-ui
- Commit: `a4c84e6380a3c2918fb131a810b0da493b6b0877`
- Downloaded: 2026-11-16
- License: MIT, copyright 2026 riagoncalves; original LICENSE retained.

The selected component directories and shared tokens are copied unchanged from
the registry. Original HTML, CSS, React source and the modal's vanilla script
are retained for provenance. JARVIS imports the actual shared tokens, Profile
Card, HUD Card, Status Badge and Modal styles. Scoped application overrides
adapt their surfaces, spacing and behavior to the CSI workspace.

The original demo modal script is preserved as reference, not loaded globally:
React owns the live floating-window lifecycle. No upstream website, analytics,
CDN, extra application server or optional web-font requests are introduced.
