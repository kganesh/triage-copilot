# Runbook: Upstream dependency failure

## When to use
Error rate rises while latency and CPU stay flat or fall. Logs show 5xx responses from an upstream service or third-party provider, or circuit breakers opening.

## Diagnosis
Identify the failing upstream from error logs and circuit breaker state changes. Check the provider's status page and whether other consumers of the same dependency are affected. If the service has had no recent deploy, a dependency failure is the most likely cause.

## Steps
1. Confirm the upstream outage via its status page or owning team; open a ticket with the provider if external.
2. Keep the circuit breaker open so the service fails fast instead of piling up requests.
3. Enable the fallback path if one exists (cached tokens, degraded mode, queued retries).
4. Communicate customer impact; the fix is outside our control until the upstream recovers.
5. After recovery, verify the circuit breaker closes and error rate returns to baseline.
