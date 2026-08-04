# Rolling Back a Bad Deploy

**Severity:** varies (match the severity of the regression)
**Owner:** Release / owning service team
**Related dashboards:** `deploy-timeline`, `error-rate`, `api-latency`

## Symptoms

- Error rate or latency rises sharply immediately after a rollout.
- The `deploy-timeline` annotation lines up with the start of the incident.
- New error signatures appear in logs that did not exist on the prior version.

## Decision: roll back or roll forward

Roll back first, ask questions later — restoring service beats diagnosing in
production. Roll forward only when the fix is trivial, already reviewed, and
faster to ship than a rollback.

## Triage

1. Confirm the deploy is the cause: correlate the incident start with
   `kubectl rollout history deployment/<svc> -n <ns>` and the `deploy-timeline`
   dashboard.
2. Identify the last known-good revision number from the rollout history.

## Mitigation (Kubernetes)

- **Roll back to the previous revision:**
  `kubectl rollout undo deployment/<svc> -n <ns>`.
- **Roll back to a specific revision:**
  `kubectl rollout undo deployment/<svc> --to-revision=<n> -n <ns>`.
- **Watch the rollout complete:**
  `kubectl rollout status deployment/<svc> -n <ns>`.

## Handling data / migration changes

If the bad deploy ran a database migration, a code rollback alone is not safe —
the schema may have moved forward. Prefer backward-compatible migrations so the
previous version still runs against the new schema. If it does not, involve the
Data on-call before rolling back and treat the migration reversal as a separate,
carefully reviewed step.

## Verification

- `error-rate` and `api-latency` return to their pre-deploy baseline.
- Rollout status reports the known-good revision as fully available.

## Follow-up

- Freeze further deploys of the service until a root cause is understood.
- Open a retro and add a regression test that would have caught the fault.
