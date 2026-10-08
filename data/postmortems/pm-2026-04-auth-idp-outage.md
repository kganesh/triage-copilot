# Postmortem: Login failures during identity provider outage (April 2026)

## Summary
The external identity provider returned 503 errors for 70 minutes. auth-svc token exchange failed for about a third of requests, and the circuit breaker opened as designed.

## Detection
Error rate alert on auth-svc. Latency stayed normal because the circuit breaker failed fast.

## Resolution
No action on our side fixed the root cause; the provider recovered. Enabling cached-token fallback reduced user-facing failures for returning users.

## Lessons
Status page checks belong in the first five minutes of triage. A flat latency curve with high errors points at fast failures from a dependency.
