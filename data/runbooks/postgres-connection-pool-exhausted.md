# Postgres Connection Pool Exhausted

**Severity:** SEV-1
**Owner:** Data / Backend team
**Related dashboards:** `pg-connections`, `pgbouncer-pools`

## Symptoms

- Application logs show `FATAL: sorry, too many clients already` or
  `remaining connection slots are reserved`.
- Requests time out waiting to check out a connection from the pool.
- `pg_stat_activity` count approaches `max_connections`.

## Triage

1. Measure current usage: `SELECT count(*) FROM pg_stat_activity;` and compare
   against `SHOW max_connections;`.
2. Identify the leak source. Group by application:
   `SELECT application_name, state, count(*) FROM pg_stat_activity
    GROUP BY 1, 2 ORDER BY 3 DESC;`
3. Look for connections stuck in `idle in transaction` — these are the usual
   culprit and indicate a code path that opens a transaction and never commits.

## Mitigation

- **Terminate leaked connections** that are idle in transaction for longer than
  5 minutes:
  `SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE state = 'idle in transaction' AND state_change < now() - interval '5 min';`
- **Front the database with PgBouncer** in transaction pooling mode if it is not
  already; this is the durable fix for connection storms.
- **Cap the application pool.** Ensure the per-instance pool size times the
  instance count stays well under `max_connections`.

## Verification

- `pg_stat_activity` count drops and holds below 80% of `max_connections`.
- No new `too many clients` errors in application logs for 15 minutes.

## Escalation

If terminating connections does not relieve pressure, or if the primary is
unresponsive, page the Data on-call and consider a controlled failover to the
replica.
