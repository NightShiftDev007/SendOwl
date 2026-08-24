# Vertical Slice Smoke Runbook

This runbook verifies the bounded SandOwl chain without changing its architecture:

```text
AgendaScope evidence
  -> sealed WorldSnapshot
  -> sealed Scenario
  -> sealed Persona Cohort
  -> Semantic Experiment
  -> persisted Observation
  -> sealed DecisionReport V1/V2
```

It is an integration smoke, not a forecast, benchmark, or product recommendation.

## Cost and mutation boundary

The operator must explicitly confirm the billable boundary before creating a Semantic Experiment:

- worker startup probes call the configured LLM provider;
- each Semantic trial calls the configured provider and can incur cost;
- `POST /api/v2/semantic-experiments` creates durable trials and starts that billable work;
- WorldModel, Scenario, Cohort and DecisionReport POSTs mutate the local SandOwl database but do not themselves run the Semantic model;
- readiness, evidence detail, experiment detail, events, comparison and report GETs are read-only.

Never print or persist `LLM_API_KEY`. Record only `LLM_MODEL_NAME`, the non-secret configuration digest returned by readiness, and the prompt schema version.

## Preconditions

1. Create a recoverable PostgreSQL backup before migrations or fixture changes.
2. Confirm `alembic current` is the expected workspace head.
3. Confirm the three worker domains have recent heartbeats:
   - semantic: `semantic_runtime_ready=true`;
   - evaluation: capability-specific readiness only when those paths are in scope;
   - report: report/evidence tasks do not affect Semantic readiness.
4. Confirm `GET /api/v2/simulations/oasis/semantic-readiness` returns:
   - `worker_online=true`;
   - `semantic_runtime_ready=true`;
   - one unambiguous model/configuration;
   - the intended model name.
5. Choose 1–8 existing sealed Personas. Do not generate replacement Personas merely to make the smoke pass.

## Evidence preflight

For each selected AgendaScope article:

1. Read `/api/v2/media/articles/{article_id}` immediately before WorldModel creation.
2. Record the current `evidence_revision_sha256` as the selection-time concurrency guard.
3. Stop if an expected revision changed; review and intentionally accept the new source copy instead of silently substituting it.
4. Create the WorldModel with `verification=human_confirmed`.
5. Read the created snapshot and record its ID, version, frozen `captured_text_sha256` values and `snapshot_sha256`.

The selection-time revision and frozen content hash are different identities. Do not write live AgendaScope fields into an already sealed snapshot.

## Scenario and Cohort preflight

- Bind the Scenario to the exact sealed WorldSnapshot ID.
- Include one baseline and one or two alternatives.
- Mark every hypothetical intervention with the literal label `synthetic demo data`.
- Keep the baseline free of interventions.
- Record intervention offsets before running; for timing tests, ensure offsets enter the intended round.
- Create or select a sealed Cohort from an existing dataset and record member order, dataset hash and cohort hash.

The checked-in example designs are:

- first slice: `DEMO_CASE_DESIGN.md`;
- second slice: `SECOND_VERTICAL_SLICE_DESIGN.md`.

## Billable execution

After explicit cost confirmation, create exactly one bounded experiment request with:

- the sealed Scenario and Cohort IDs;
- the selected alternative IDs in stable order;
- one seed for the first smoke;
- one to two rounds;
- 15–240 minutes per round.

Poll `GET /api/v2/semantic-experiments/{experiment_id}` until every trial is terminal. Do not automatically enqueue a replacement when a trial fails; preserve the failure and diagnose its explicit error first.

## Observation verification

For every trial, read `/api/v2/semantic-trials/{trial_id}/events` and verify:

- event sequences are contiguous;
- scenario intervention events use `actor_kind=scenario` and the registered round;
- Persona events retain `persona_id`, phase and action type;
- scenario initial posts and Persona-authored content are counted separately;
- the result counts match the persisted event rows;
- `observed_at_raw` and SandOwl `recorded_at` remain distinct clock semantics.

Read `/api/v2/semantic-experiments/{experiment_id}/comparison` and confirm paired deltas use only successful baseline/alternative trials with the same seed.

## Report verification

Generate both immutable versions:

- V1: `POST /api/v2/decision-reports/from-experiment/{experiment_id}`;
- V2: `POST /api/v2/decision-reports/v2/from-experiment/{experiment_id}`.

Verify repeated POSTs return the same version-specific report ID and hash. V2 must contain exactly:

1. Evidence
2. Assumptions
3. Experiment
4. Observation
5. Comparison
6. Analysis
7. Limitations

Check the V2 directory, detail and Markdown routes through the frontend reverse proxy. Analysis may explain recorded differences but must not predict the future, claim causality, estimate a population, or select a best option.

## Completion record

Record timestamps and IDs for WorldModel, WorldSnapshot, Scenario, Cohort, Experiment, each Trial, V1 and V2. Also record:

- snapshot/scenario/cohort/experiment/report hashes;
- model/config/prompt/runtime versions;
- trial status and event counts;
- worker domain readiness;
- every manual step, failure and retry decision;
- the explicit limitations and synthetic-data boundary.

The smoke passes only when all resources remain queryable and sealed, persisted events reconcile with results, V1/V2 are independently verifiable, and no output is presented as a real-world prediction or recommendation.
