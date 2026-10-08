# Runbook: CPU saturation and noisy neighbors

## When to use
CPU utilization near 100% or CPU throttling, rising executor queue depth, worker thread timeouts, and latency growth while request rate stays flat.

## Diagnosis
If traffic did not increase, the extra CPU demand comes from somewhere else. Check other workloads on the same node or host: batch jobs, reconcilers and cron jobs are common noisy neighbors. Look at their recent config changes, especially parallelism or concurrency settings.

## Steps
1. Confirm which workloads share the node and compare their CPU curves with the affected service.
2. Reduce the noisy neighbor's parallelism or pause the batch job.
3. Move batch workloads to a separate node pool with taints and tolerations.
4. Set CPU requests and limits so latency-sensitive services get guaranteed capacity.
5. Scale out the affected service only as a temporary mitigation.
