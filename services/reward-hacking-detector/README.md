# Reward-Hacking Detector

> Measures how robust an AI **verifier** is against manipulation.

This is the differentiated core of Touchstone. A verifier grades artifacts; this
service attacks the verifier — generating diverse adversarial artifacts that do
**not deserve to pass**, running them through the verifier, and measuring how
often the verifier is fooled. The output is a **Verifier Robustness Score** with
a confidence interval, a deduplicated corpus of discovered exploits, and the
comparison/regression primitives a CI gate needs.

## The core idea

A **reward hack** is an artifact that does not deserve to pass yet the verifier
passes it — a false positive in the dangerous direction. Reward hacking is
specifically the verifier being *too lenient*: handing out reward for low-quality
work. Every attack this service generates is crafted to be undeserving
(`expected_pass = False`); if the verifier passes it, that is an exploit.

```
robustness = 1 - (exploits / executed_attacks)
```

A verifier that only checks "is there an answer field?" is fooled by almost every
corruption → low robustness. A verifier that checks the answer's actual value
rejects them → high robustness. The detector discriminates the two (proven by the
integration tests).

## Pipeline

```
seed cases ─▶ AttackGenerator ─▶ AttackExecutor ─▶ ExploitDetector ─▶ RobustnessScorer
            (reproducible        (parallel, via      (classify +        (score + Wilson
             variants)            engine sandbox)     dedup signature)    confidence interval)
```

The executor **reuses the verification-engine**: verifiers are built by the
engine's `VerifierFactory` and run through its hardened sandbox. The detector
never re-implements execution or sandboxing.

### 1. Adversarial test generation (`attacks/`)

Six strategies, each single-purpose and seeded for reproducibility:

| Strategy            | Category             | What it does |
|---------------------|----------------------|--------------|
| `content_mutation`  | `content_corruption` | breaks a passing artifact's correctness (corrupt value, drop/null a field, truncate) |
| `prompt_injection`  | `judge_manipulation` | embeds instructions/authority/flattery telling an LLM judge to score high |
| `length_padding`    | `length_bias`        | pads weak content with filler to exploit length-biased judges |
| `formatting_facade` | `formatting_exploit` | wraps empty content in elaborate structure to look thorough |
| `edge_cases`        | `edge_case`          | degenerate inputs: empty, null, extreme, control chars, homoglyphs |
| `model_adversary`   | `model_generated`    | an LLM crafts artifacts that are wrong but engineered to pass |

### 2. Attack execution (`execution/`)

Bounded-parallel (`asyncio` semaphore), per-attack timeout, every verifier
error/crash caught and recorded as an *errored* outcome (never an exploit).
Outcomes are returned ordered by variant ordinal, so a replay with the same seed
yields an identical outcome list — **deterministic replay**.

### 3. Exploit detection (`detection/`)

Decides which outcomes are reward hacks, categorizes them, and computes a stable
**dedup signature** (a digest of the exploit *class* — category + strategy +
normalized artifact shape) so near-duplicates collapse. Severity scales with how
confidently the verifier was fooled. Each exploit also records a **failure
reason** — a human-readable explanation grounded in the verifier's own score and
breakdown at the moment it was fooled (why it failed, not just what the attack
did).

### 4. Robustness score (`scoring/`)

Two complementary views of the same evaluation:

  * **Robustness** = `1 - exploit_rate`, reported with a **Wilson score
    confidence interval** (correct near 0/1 where the normal approximation fails).
  * **Severity-weighted robustness** — each exploit subtracts its severity weight
    (critical 1.0 … low 0.2) instead of a flat 1.0, so the score reflects *how
    badly* the verifier was fooled, not only how often.

Plus version comparison, **regression detection** (a statistically meaningful
drop, not noise), and trend direction.

### 5. Knowledge base (`knowledge/`)

Every exploit is persisted; re-discovering one (same verifier + signature)
increments its occurrence count rather than duplicating it, so the corpus grows
in *distinct* failure modes. Each exploit is **linked to the verifier version**
it was found against. The corpus is **searchable** by verifier, version,
category, severity, strategy, minimum score, and free text (over description /
failure reason / strategy / category / artifact), with pagination. The headline
robustness score is written back onto the verifier row. Adversarial artifacts are
stored as ASCII-escaped JSON so hostile inputs (null bytes, control chars)
round-trip safely.

### 6. API (`api/`)

All endpoints are scoped to the caller's organization (API-key auth against the
shared key store; tenant-isolated).

| Method & path | Purpose |
|---|---|
| `POST /v1/robustness/evaluations` | launch an evaluation (202 + id) |
| `GET /v1/robustness/evaluations/{id}` | query status + result |
| `GET /v1/robustness/evaluations/{id}/report` | reproducible report (seed, config, exploits) |
| `GET /v1/robustness/verifiers/{vid}/evaluations` | list a verifier's evaluations |
| `GET /v1/robustness/verifiers/{vid}/exploits` | the exploit corpus |
| `GET /v1/robustness/exploits/search` | search the corpus (category / severity / strategy / version / min-score / free text) |
| `GET /v1/robustness/verifiers/{vid}/trend` | robustness trend over time |
| `POST /v1/robustness/compare` | compare two evaluations (delta, regression) |

### 7. Worker (`worker.py`)

`EvaluationJobRunner` owns the persisted job lifecycle (pending → running →
completed/failed) with **retry + backoff**, **failure recovery** that scans the
store for evaluations stranded in pending/running by a crashed worker and re-runs
them faithfully (the seed and seed cases are persisted at launch, so recovery is
deterministic), and **event integration**: it consumes `control_plane.action`
(auto-evaluating a verifier when it is registered) and publishes
`reward_hacking.robustness_evaluated` on completion (with a regression flag
computed against the previous version).

## Running

```bash
# API
TOUCHSTONE_RHD_DATABASE_URL=postgresql+asyncpg://touchstone:touchstone@localhost:5432/touchstone \
  python -m touchstone_rhd.main          # serves on :8030

# Auto-evaluation worker
python -m touchstone_rhd.worker_main
```

Schema is owned by the control-plane (`robustness_evaluations`, `exploits`);
run its migrations first.

## Tests

```bash
PYTHONPATH=src pytest tests/ -q
```

25 unit tests (attacks/determinism, detection/dedup + failure reason,
scoring/Wilson/regression + severity weighting) and 12 integration tests against a
real sandbox + Postgres (weak-vs-strong discrimination, reproducibility,
persistence + dedup + writeback, weighted-score + version linkage, corpus search,
failure recovery, retry-to-failed, and the full authenticated API flow with
tenant isolation) — 42 in total.
