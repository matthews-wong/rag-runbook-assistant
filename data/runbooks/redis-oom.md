# Redis Out Of Memory (OOM)

**Severity:** SEV-2
**Owner:** Platform / Caching team
**Related dashboards:** `redis-memory`, `redis-evictions`

## Symptoms

- Writes fail with `OOM command not allowed when used memory > 'maxmemory'`.
- `redis-evictions` shows a sharp climb in evicted keys.
- Cache hit rate drops and downstream latency rises as traffic falls through to
  the database.

## Triage

1. Check memory pressure: `redis-cli INFO memory` and read `used_memory_human`
   against `maxmemory`.
2. Inspect the eviction policy: `redis-cli CONFIG GET maxmemory-policy`. For a
   cache it should be an `allkeys-*` policy; `noeviction` will hard-fail writes.
3. Find big keys with `redis-cli --bigkeys` to spot an unbounded collection or a
   missing TTL.

## Mitigation

- **Wrong policy:** if the policy is `noeviction` on a pure cache, switch it:
  `redis-cli CONFIG SET maxmemory-policy allkeys-lru` (and persist it in config).
- **Missing TTLs:** identify the key pattern without expiry and add a TTL in the
  writing service. As a stopgap, scan-and-expire the offending prefix.
- **Genuinely undersized:** scale the instance to a larger memory tier during a
  maintenance window; note that this requires a failover on most managed Redis.

## Verification

- `used_memory` stabilizes below 75% of `maxmemory`.
- Eviction rate returns to baseline and cache hit rate recovers.

## Escalation

If a single key or collection is growing without bound and cannot be expired
safely, involve the owning service team before flushing — a blind `FLUSHALL`
can cause a thundering-herd on the database.
