# Postmortem: Checkout retry storm against pricing (March 2025)

## Summary
A checkout-svc release changed the pricing client's retry policy to five immediate retries with no backoff. When pricing-svc slowed slightly under normal load, every checkout request multiplied into up to six pricing calls, tripling pricing traffic and pushing checkout p99 latency above two seconds for 40 minutes.

## Detection
Alert on checkout p99 latency. Pricing request rate rose 3x at the same minute as the checkout deploy.

## Resolution
Rolling back checkout-svc to the previous version restored latency within eight minutes.

## Lessons
Retry policy changes are risky changes and need a canary. Retries without jitter and backoff turn a small slowdown into an outage.
