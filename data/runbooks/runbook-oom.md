# Runbook: Memory exhaustion and OOMKilled containers

## When to use
Containers restart with OOMKilled status, or logs show java.lang.OutOfMemoryError: Java heap space. Restart counts climb and requests fail during restarts.

## Diagnosis
Find the allocation site in the OutOfMemoryError stack trace; caches and snapshot loaders that read whole datasets into memory are frequent causes. Compare the heap size (-Xmx) with the container memory limit: the heap must leave room for metaspace, threads and direct buffers. If metrics are unavailable, rely on container restart counts and OOM log lines.

## Steps
1. Capture a heap dump on the next OOM (-XX:+HeapDumpOnOutOfMemoryError) for analysis.
2. Raise the container memory limit temporarily to stop the restart loop.
3. Bound the offending cache: add a maximum size or eviction policy, or load data in pages.
4. Set -Xmx to about 75% of the container limit.
5. Add an alert on restart count so OOM loops are caught before user impact.
