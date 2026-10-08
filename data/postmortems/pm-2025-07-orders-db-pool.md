# Postmortem: Orders connection pool exhaustion (July 2025)

## Summary
An order history query without an index on customer_ref took over ten seconds per call. Each call held a database connection for its full duration, and the 50-connection Hikari pool was exhausted within 15 minutes even though traffic was flat.

## Detection
Error rate alert on orders-svc; logs showed "Connection is not available" timeouts and slow query warnings beginning earlier.

## Resolution
Killing the long-running sessions bought time; adding an index on order_items(customer_ref, created_at) fixed it. Raising the pool size was tried first and made the database slower.

## Lessons
Add statement timeouts shorter than the pool timeout. Slow query warnings are a leading indicator of pool exhaustion.
