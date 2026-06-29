/**
 * End-to-end demo for the Touchstone TypeScript SDK.
 *
 * Mirrors `scripts/demo.py`: signup -> API key -> workspace -> project ->
 * verifier -> submit -> wait -> print result. Run against a live stack:
 *
 *   npm run demo
 *
 * Configuration (env):
 *   TOUCHSTONE_BASE_URL   control-plane URL (default http://localhost:8000)
 *   TOUCHSTONE_RHD_URL    reward-hacking-detector URL (default = base URL)
 *   TOUCHSTONE_ARTIFACT   artifact ref to submit (default demo/run.json)
 *
 * If only the control-plane is running (no verification-engine), the run stays
 * PENDING; the demo reports that instead of hanging.
 */

import { PollTimeoutError, TouchstoneClient } from "../src/index.js";

const BASE_URL = process.env["TOUCHSTONE_BASE_URL"] ?? "http://localhost:8000";
const RHD_URL = process.env["TOUCHSTONE_RHD_URL"] ?? BASE_URL;
const ARTIFACT = process.env["TOUCHSTONE_ARTIFACT"] ?? "demo/run.json";

function step(n: number, msg: string): void {
  console.log(`\n[${n}] ${msg}`);
}

async function main(): Promise<void> {
  const client = new TouchstoneClient({ baseUrl: BASE_URL, rhdUrl: RHD_URL });
  // Unique suffix so the demo is re-runnable without slug/email collisions.
  const suffix = Date.now().toString(36);

  step(1, "Signing up a new organization");
  const token = await client.signup({
    email: `founder+${suffix}@acme.com`,
    password: "correct horse battery staple",
    orgName: "Acme",
    orgSlug: `acme-${suffix}`,
  });
  console.log(`    org=${token.org_slug} (JWT stored on client)`);

  step(2, "Creating an API key and switching to it");
  const key = await client.createApiKey("ci", { role: "member" });
  client.setApiKey(key.secret);
  console.log(`    key_id=${key.key_id} role=${key.role}`);

  step(3, "Creating a workspace and project");
  const ws = await client.createWorkspace("Research", `research-${suffix}`);
  const project = await client.createProject(ws.id, "Coding Agent", `coding-agent-${suffix}`);
  console.log(`    workspace=${ws.slug} project=${project.slug}`);

  step(4, "Registering a code verifier");
  const verifier = await client.registerVerifier(
    project.id,
    "Answer 42",
    `answer-42-${suffix}`,
    "code",
    {
      code:
        "def check(artifact):\n" +
        "    ok = artifact.get('answer') == 42\n" +
        "    return {'score': 1.0 if ok else 0.0}\n",
      threshold: 1.0,
    },
  );
  console.log(`    verifier=${verifier.slug} v${verifier.version} id=${verifier.id}`);

  step(5, `Submitting an artifact for verification (${ARTIFACT})`);
  const run = await client.submitVerification(verifier.id, ARTIFACT);
  console.log(`    run=${run.id} status=${run.status}`);

  step(6, "Waiting for the verification result");
  try {
    const result = await client.waitForVerification(run.id, { timeoutMs: 15_000, intervalMs: 500 });
    console.log(
      `    status=${result.status} score=${result.score} ` +
        `uncertainty=${result.uncertainty} passed=${result.passed} risk=${result.risk_score}`,
    );
  } catch (err) {
    if (err instanceof PollTimeoutError) {
      console.log(
        "    still PENDING — is the verification-engine running? " +
          "The control-plane accepted the run; grading happens in the engine.",
      );
    } else {
      throw err;
    }
  }

  console.log("\nDone.");
}

main().catch((err: unknown) => {
  console.error("\nDemo failed:", err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
