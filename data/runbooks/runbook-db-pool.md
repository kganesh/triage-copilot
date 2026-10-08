# Runbook: Database connection pool exhaustion

## When to use
HikariCP or other pool errors such as "Connection is not available, request timed out". The db_connections_in_use metric sits at the pool maximum while CPU falls, because threads are blocked waiting for connections rather than doing work.

## Diagnosis
Look for slow query or lock wait warnings that started before the pool saturated. A single slow query holding connections for many seconds will exhaust a pool of 40 to 50 connections at modest traffic. Check whether request rate changed; if traffic is flat, the cause is query duration, not load. A deploy that only touched docs or dashboards cannot cause this.

## Steps
1. Identify the slowest queries from the slow query log and the database's active session view.
2. Kill long-running queries or sessions holding locks if they are safe to terminate.
3. Add the missing index or rewrite the query; avoid SELECT * on large tables.
4. Set a statement timeout shorter than the pool's connection timeout so one bad query cannot block the pool.
5. Do not simply raise the pool size: it moves the bottleneck to the database and can make it worse.
