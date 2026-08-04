# High CPU on API Pods

**Severity:** SEV-2
**Owner:** Platform / API team
**Related dashboards:** `api-latency`, `k8s-node-cpu`

## Symptoms

- p95 latency on the API gateway rises above 800ms.
- Kubernetes reports one or more `api-*` pods with CPU throttling.
- HPA (Horizontal Pod Autoscaler) is pinned at max replicas.

## Triage

1. Confirm the scope. Run `kubectl top pods -n api --sort-by=cpu` and note
   whether CPU is spread across pods or concentrated on one.
2. Check the deploy timeline. A regression usually correlates with the most
   recent rollout — inspect `kubectl rollout history deployment/api -n api`.
3. Look for a traffic spike in the `api-latency` dashboard. A genuine spike is
   handled differently from a code regression.

## Mitigation

- **Traffic spike:** raise the HPA ceiling temporarily with
  `kubectl scale deployment/api --replicas=<n> -n api`, then confirm CPU falls
  below 70%.
- **Code regression:** roll back the offending deploy (see the "Rolling Back a
  Bad Deploy" runbook). Do not raise replica count to mask a hot loop — it only
  spreads the cost.
- **Runaway request:** if a single tenant or endpoint dominates CPU, enable the
  per-route rate limit in the gateway config and reload.

## Verification

- p95 latency returns below 300ms for 10 consecutive minutes.
- No pod shows sustained CPU throttling in `k8s-node-cpu`.

## Escalation

If CPU remains saturated 20 minutes after mitigation, page the Platform on-call
lead and open a SEV-1 bridge.
