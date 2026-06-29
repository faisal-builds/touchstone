# Touchstone Dashboard

The operator console for the Touchstone verification layer — a Next.js (App
Router) application that lets a customer drive the whole platform from a browser:
register verifiers, watch runs and risk, read the tamper-evident audit chain, and
measure how robust each verifier is against manipulation.

## Design

Instrument-grade, graphite-on-paper. The product name is the thesis — a
*touchstone* reveals the purity of gold by the streak it leaves — so the single
signature accent is the **assay streak**, a bronze→gold gradient used only for the
active-nav marker and the arc of the **Robustness Gauge**. All data (scores,
hashes, ids, timestamps) is set in tabular monospace, the way a measurement
instrument would render it. Everything else stays quiet so the gauge is the one
memorable element.

## Architecture

The dashboard is a **backend-for-frontend (BFF)**. The browser only ever talks to
the Next.js server; that server holds the session and proxies to the backends:

```
browser ──▶ Next.js (this app)
                ├─ Server Components ─▶ control-plane / RHD   (read, token from cookie)
                ├─ /api/cp/[...]      ─▶ control-plane         (client mutations)
                ├─ /api/rhd/[...]     ─▶ reward-hacking-detector
                └─ /api/auth/*        ─▶ login / signup / logout (sets httpOnly cookie)
```

- **Auth/session** — login and signup call the control-plane, then store the
  issued JWT in an httpOnly cookie. Middleware guards every app route. The same
  JWT authenticates both the control-plane and the reward-hacking detector (the
  RHD accepts the control-plane's `org`-claim token in addition to API keys).
- **Type-safe client** — `src/lib/api` mirrors the backend response shapes; the
  `cp` / `rhd` helpers attach the token and map problem+json into a typed
  `ApiError`. Server Components fetch directly; client components POST through the
  proxy and `router.refresh()`.
- **Resilience** — every data surface handles loading (`loading.tsx`, skeletons),
  error (`error.tsx`, error states), and empty states. If a backend is briefly
  unavailable the page degrades rather than crashing.

## Pages

Overview · Verifiers (list + detail with the robustness gauge, trend, and
launch-evaluation) · Runs · Risk · Robustness (evaluations + version compare) ·
Evaluation report (with export) · Exploit corpus (searchable) · Audit trail ·
API keys (create, secret shown once) · Settings (workspaces & projects) · Login ·
Signup.

## Develop

```bash
npm install
cp .env.example .env        # point CONTROL_PLANE_URL / RHD_URL at your backends
npm run dev                 # http://localhost:3000
```

Other scripts: `npm run build`, `npm run start`, `npm run lint`,
`npm run typecheck`, `npm run test` (Vitest).

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `CONTROL_PLANE_URL` | control-plane base URL (server-side) | `http://localhost:8000` |
| `RHD_URL` | reward-hacking-detector base URL (server-side) | `http://localhost:8030` |
| `SESSION_COOKIE_NAME` | session cookie name | `ts_session` |

## Tests

`npm run test` runs the Vitest suite: the formatting/presentation helpers, the
problem+json error mapping, and component render tests for the Robustness Gauge
and the badge system. `npm run build` (a full production build) and
`npm run typecheck` are the broader correctness gates.
