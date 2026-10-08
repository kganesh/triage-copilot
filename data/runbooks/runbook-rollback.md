# Runbook: Deploy regression and rollback

## When to use
Latency or error rate changes sharply within 30 minutes after a deploy or release of the affected service. Startup log lines show the new version shortly before the symptoms begin. Errors point at code paths or client libraries touched by the change.

## Diagnosis
Compare the deploy timestamp with the first point where p99 latency or error rate leaves its baseline. Read the deploy summary for changes to client libraries, retry policies, timeouts, parsers or serialization. If a dependency's request rate rose sharply at the same time, suspect a retry storm caused by the new release.

## Steps
1. Announce the suspected bad deploy in the incident channel and freeze further deploys of the service.
2. Roll back to the previous known-good version using the deploy pipeline's rollback action.
3. Watch p99 latency and error rate for 10 minutes; they should return to baseline.
4. If the rollback does not help within 15 minutes, the deploy is not the cause: re-open triage.
5. Open a follow-up ticket to fix forward with a test that reproduces the regression.

## Retry policies
Retries without exponential backoff and jitter multiply load on a degraded dependency. Cap retries at 2 for synchronous user-facing calls and always enable jitter.
