---
title: "RDS Connection Pool Exhaustion from Lambda Without Connection Pooling"
resource_type: RDS
severity: critical
region: ap-northeast-1
root_cause: connection_pool_exhaustion
confidence: 0.93
date: 2026-01-28
tags: [rds, connection-pool, lambda, rds-proxy, database, scaling]
---

# RDS Connection Pool Exhaustion from Lambda Without Connection Pooling

## Symptoms
- Application returning `Too many connections` errors from RDS MySQL (`myapp-prod-mysql`)
- CloudWatch `DatabaseConnections` metric at max_connections limit (default: 150 for db.t3.medium)
- Lambda function `order-processor` error rate spiked to 40%+
- RDS CPU and memory utilization normal — the instance itself is healthy
- Errors correlate with Lambda concurrent execution count increases
- Manual `SHOW PROCESSLIST` on the database shows hundreds of connections in `Sleep` state

## Root Cause
The `order-processor` Lambda function was deployed **without a connection pooler**. Each Lambda invocation:

1. Opens a new MySQL connection in the handler function
2. Executes 1-3 queries
3. Does **not** explicitly close the connection (relies on garbage collection)
4. Lambda execution environment is frozen (not terminated), keeping the TCP connection alive in `Sleep` state
5. When the environment is reused, a **new** connection is opened instead of reusing the existing one

With ~200 concurrent Lambda invocations during peak, the connection count exceeded the RDS `max_connections` parameter (150). New connection attempts were rejected with `ERROR 1040 (HY000): Too many connections`.

The issue was compounded by:
- Lambda reserved concurrency set to 500 (far exceeding RDS connection limit)
- No connection timeout configured on the client side
- MySQL `wait_timeout` set to default 28800 seconds (8 hours), keeping idle connections alive

## Resolution Steps
1. **Immediate mitigation**: Increase RDS `max_connections` parameter temporarily:
   ```bash
   aws rds modify-db-parameter-group --db-parameter-group-name myapp-prod-params \
     --parameters "ParameterName=max_connections,ParameterValue=300,ApplyMethod=immediate"
   ```
2. **Deploy RDS Proxy** to manage connection pooling:
   ```bash
   aws rds create-db-proxy --db-proxy-name myapp-proxy \
     --engine-family MYSQL \
     --auth SecretArn=arn:aws:secretsmanager:ap-northeast-1:123456:secret:myapp-db-creds \
     --role-arn arn:aws:iam::123456:role/rds-proxy-role \
     --vpc-subnet-ids subnet-aaa subnet-bbb
   ```
3. Update Lambda function to connect via RDS Proxy endpoint instead of direct RDS endpoint
4. Configure RDS Proxy with:
   - `MaxConnectionsPercent`: 80 (use up to 80% of RDS max_connections)
   - `MaxIdleConnectionsPercent`: 30
   - `ConnectionBorrowTimeout`: 30 seconds
5. Set Lambda reserved concurrency to a reasonable limit (e.g., 100)
6. Add explicit connection close in Lambda handler:
   ```python
   def handler(event, context):
       conn = pymysql.connect(host=PROXY_ENDPOINT, ...)
       try:
           # ... query logic
       finally:
           conn.close()
   ```
7. Monitor `DatabaseConnections` metric and verify it stabilizes below 80% of max

## Prevention
- Always use RDS Proxy or an external connection pooler (PgBouncer, ProxySQL) for Lambda-to-RDS workloads
- Set Lambda reserved concurrency to a value that aligns with RDS connection capacity
- Explicitly close database connections in Lambda handlers using try/finally
- Reduce MySQL `wait_timeout` to 300 seconds for Lambda workloads to reclaim idle connections faster
- Implement CloudWatch alarm on `DatabaseConnections` > 80% of `max_connections`
- Use connection pooling libraries (e.g., `sqlalchemy` with pool_size) when running in persistent compute (ECS/EC2)

## Related
- Applies to any serverless-to-RDS architecture (Lambda, Fargate) without connection pooling
- PostgreSQL has the same issue; use RDS Proxy or PgBouncer
- Aurora Serverless v2 has higher default connection limits but is still subject to exhaustion without pooling
