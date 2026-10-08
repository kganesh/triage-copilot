# Postmortem: Payments latency from a noisy batch neighbor (January 2026)

## Summary
A config change raised batch-reconciler parallelism. The batch job shared nodes with payments-svc and consumed nearly all CPU, throttling payments-svc. Payments latency rose 8x while its own traffic stayed flat.

## Detection
Latency alert on payments-svc. Payments had no deploys, which delayed diagnosis by 25 minutes because responders looked for a code change in the wrong service.

## Resolution
Reducing reconciler parallelism restored payments latency immediately. Batch jobs were moved to a dedicated node pool.

## Lessons
When a service's CPU rises without more traffic, check co-located workloads and their recent config changes.
