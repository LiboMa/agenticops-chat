# Common Error Patterns by Language

## Overview

This reference covers frequently encountered error patterns in production applications,
organized by language/runtime. For each pattern, the typical root cause and remediation
steps are provided.

## Java

### NullPointerException

**Pattern in logs**:
```
java.lang.NullPointerException
    at com.myapp.service.OrderService.processOrder(OrderService.java:142)
    at com.myapp.controller.OrderController.createOrder(OrderController.java:87)
```

**Typical root causes**:
- Uninitialized object reference — field not set before method call
- Database query returned null instead of expected entity
- External service returned unexpected null in response payload
- Race condition — object set to null by another thread between check and use

**Remediation**:
1. Check the exact line number in the stack trace
2. Add null checks or use `Optional<T>` for return values from DB/external calls
3. Use `Objects.requireNonNull()` at method boundaries to fail fast with clear message
4. Review thread safety if the object is shared state

### OutOfMemoryError

**Pattern in logs**:
```
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)
    at java.util.ArrayList.grow(ArrayList.java:265)
```
or:
```
java.lang.OutOfMemoryError: GC overhead limit exceeded
java.lang.OutOfMemoryError: Metaspace
```

**Typical root causes**:
- Heap space: loading too much data into memory (large query result set, file processing)
- Heap space: memory leak — objects retained by static collections, listeners, caches without eviction
- GC overhead: heap nearly full, spending >98% time in GC recovering <2% memory
- Metaspace: too many dynamically generated classes (reflection, proxies, classloader leak)

**Remediation**:
1. Heap space: enable heap dumps on OOM (`-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp`)
2. Analyze dump with Eclipse MAT or VisualVM — find dominator tree / retained size
3. For data loading: use streaming/pagination instead of loading all results
4. For leaks: check static maps, event listeners not deregistered, ThreadLocal not cleaned
5. Metaspace: check for classloader leaks (common in app servers with hot redeploy)
6. Short-term: increase `-Xmx` or container memory limit, but fix the root cause

### ClassNotFoundException / NoClassDefFoundError

**Pattern in logs**:
```
java.lang.ClassNotFoundException: com.example.SomeClass
    at java.net.URLClassLoader.findClass(URLClassLoader.java:382)
```
or:
```
java.lang.NoClassDefFoundError: com/example/SomeClass
Caused by: java.lang.ClassNotFoundException: com.example.SomeClass
```

**Typical root causes**:
- Missing dependency in classpath (JAR not included in deployment)
- Version conflict — class exists in a different version of the JAR
- Container classloader isolation (ECS/K8s: wrong base image, missing layer)
- NoClassDefFoundError: class was present at compile time but missing at runtime

**Remediation**:
1. Check `pom.xml` / `build.gradle` for the dependency scope (should not be `provided` unless supplied by runtime)
2. Run `mvn dependency:tree` or `gradle dependencies` to find version conflicts
3. For containers: verify the JAR is present in the image (`docker run --rm IMAGE ls -la /app/lib/`)
4. For NoClassDefFoundError: check if static initializer of the class threw an exception (look for earlier errors)

### Connection Pool Exhaustion

**Pattern in logs**:
```
org.apache.commons.dbcp2.PoolableConnectionFactory - Cannot create PoolableConnection
com.zaxxer.hikari.pool.HikariPool - Connection is not available, request timed out after 30000ms
java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available
```

**Typical root causes**:
- Slow queries holding connections too long
- Missing connection close in error paths (not using try-with-resources)
- Pool max size too small for workload
- Database at max connections (all pools combined exceed DB limit)

**Remediation**:
1. Check active connections: `SHOW PROCESSLIST` (MySQL) or `SELECT * FROM pg_stat_activity` (PostgreSQL)
2. Enable HikariCP leak detection: `hikari.leakDetectionThreshold=60000`
3. Ensure all connections are closed in finally blocks or use try-with-resources
4. Increase pool size cautiously (total across all app instances must be < DB max_connections)
5. Optimize slow queries that hold connections

## Python

### ImportError / ModuleNotFoundError

**Pattern in logs**:
```
ModuleNotFoundError: No module named 'boto3'
ImportError: cannot import name 'some_function' from 'mymodule'
```

**Typical root causes**:
- Package not installed in the runtime environment
- Virtual environment not activated / wrong Python interpreter
- Circular import between modules
- Name changed between library versions

**Remediation**:
1. Check installed packages: `pip list | grep PACKAGE` in the actual runtime environment
2. For Lambda: verify package is in the deployment package or layer
3. For containers: verify `pip install` ran correctly in Dockerfile (check build logs)
4. For circular imports: restructure to lazy import or move import inside function
5. Version mismatch: check `pip show PACKAGE` for version, compare against docs

### ConnectionError / ConnectionRefusedError

**Pattern in logs**:
```
requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionRefusedError(111, 'Connection refused'))
urllib3.exceptions.MaxRetryError: HTTPConnectionPool(host='api.example.com', port=443): Max retries exceeded
```

**Typical root causes**:
- Target service is down or not listening on expected port
- DNS resolution failure (wrong hostname, DNS cache stale)
- Security group / network ACL blocking the connection
- Connection pool exhausted (urllib3 default pool size: 10)

**Remediation**:
1. Verify target is reachable: `curl -v TARGET:PORT` from the same network
2. Check DNS: `nslookup HOSTNAME` or `dig HOSTNAME`
3. Check security groups allow outbound from source and inbound to target
4. For pool exhaustion: increase `pool_maxsize` in requests Session or use connection pooling
5. Add retry with exponential backoff: `urllib3.util.Retry(total=3, backoff_factor=1)`

### TimeoutError

**Pattern in logs**:
```
requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='api.example.com', port=443): Read timed out. (read timeout=30)
socket.timeout: timed out
botocore.exceptions.ReadTimeoutError: Read timeout on endpoint URL
```

**Typical root causes**:
- Target service responding slowly (overloaded, cold start, long query)
- Network latency (cross-region calls, VPN overhead)
- Timeout value too aggressive for the operation
- Lambda approaching execution timeout

**Remediation**:
1. Check target service latency independently
2. Increase timeout for known slow operations (batch, reports)
3. For AWS SDK: configure `botocore.config.Config(read_timeout=120, connect_timeout=10)`
4. Add circuit breaker pattern to avoid cascading failures
5. For Lambda: check remaining time with `context.get_remaining_time_in_millis()`

### MemoryError / Killed (OOM)

**Pattern in logs**:
```
MemoryError
# or in system logs:
kernel: [12345.678901] Out of memory: Killed process 1234 (python3) total-vm:2048000kB
```

**Typical root causes**:
- Loading entire large file into memory (CSV, JSON)
- Unbounded list/dict growth in a loop
- Pandas DataFrame too large for available memory
- Container memory limit too low

**Remediation**:
1. Use streaming/chunked processing: `pandas.read_csv(chunksize=10000)`
2. Use generators instead of lists for large sequences
3. For Lambda: increase memory configuration (also increases CPU proportionally)
4. For containers: increase memory limit or optimize memory usage
5. Profile with `tracemalloc` or `memory_profiler` to find allocations

## Node.js

### ECONNREFUSED

**Pattern in logs**:
```
Error: connect ECONNREFUSED 127.0.0.1:5432
    at TCPConnectWrap.afterConnect [as oncomplete] (net.js:1141:16)
```

**Typical root causes**:
- Target service not running on expected host/port
- Container networking: using localhost when service is in another container
- Database not started yet (race condition in container orchestration)

**Remediation**:
1. Verify target: `nc -zv HOST PORT` from the application's network context
2. In Docker/K8s: use service name not localhost (e.g., `db:5432` not `localhost:5432`)
3. Add connection retry logic with backoff on startup
4. Use health checks and dependency ordering in docker-compose / K8s init containers

### ENOMEM / Heap Out of Memory

**Pattern in logs**:
```
FATAL ERROR: CALL_AND_RETRY_LAST Allocation failed - JavaScript heap out of memory
FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory
```

**Typical root causes**:
- Default Node.js heap limit (~1.5GB) exceeded
- Loading large JSON files with `JSON.parse()` on huge strings
- Unbounded array/object growth (event listeners, caching without eviction)
- Memory leak from unclosed streams, database connections, or event emitters

**Remediation**:
1. Increase heap: `node --max-old-space-size=4096 app.js`
2. For large JSON: use streaming parser (`JSONStream`, `stream-json`)
3. Check for event listener leaks: `process.on('warning', ...)` to catch MaxListenersExceeded
4. Profile with `--inspect` and Chrome DevTools memory snapshot
5. Use `clinic.js` or `0x` for production-safe profiling

### UnhandledPromiseRejection / unhandledRejection

**Pattern in logs**:
```
UnhandledPromiseRejectionWarning: Error: something went wrong
(node:12345) UnhandledPromiseRejectionWarning: Unhandled promise rejection.
```

**Typical root causes**:
- Missing `.catch()` on a Promise chain
- Missing `try/catch` around `await` in an async function
- Error thrown inside a callback passed to a Promise constructor
- Event emitter error not handled

**Remediation**:
1. Add global handler: `process.on('unhandledRejection', (reason, promise) => { logger.error(reason); })`
2. Ensure all Promise chains have `.catch()` or are inside `try/catch` with `await`
3. Use ESLint rule `no-floating-promises` to catch at build time
4. For Express: use `express-async-errors` or wrap async handlers

### ETIMEDOUT / ESOCKETTIMEDOUT

**Pattern in logs**:
```
Error: connect ETIMEDOUT 10.0.1.50:3306
Error: ESOCKETTIMEDOUT
```

**Typical root causes**:
- Network connectivity issue (security group, NACL, route table)
- Target service overloaded and not accepting connections
- Connection pool exhausted on target side
- DNS resolution pointing to wrong/unreachable IP

**Remediation**:
1. Test connectivity: `nc -zv -w 5 HOST PORT`
2. Check security groups and NACLs for the target
3. Review connection pool settings on both client and server
4. Add timeout configuration: `{ timeout: 10000, connectionTimeout: 5000 }`

## Go

### panic: runtime error

**Pattern in logs**:
```
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x4a2b3c]

goroutine 1 [running]:
main.processRequest(0x0)
    /app/main.go:42 +0x1c
```

**Typical root causes**:
- Nil pointer dereference — calling method on nil interface or pointer
- Index out of range on slice or array
- Map access on nil map (writing to uninitialized map)
- Channel closed while being read/written

**Remediation**:
1. Check the goroutine stack trace for the exact line
2. Add nil checks before dereferencing pointers returned from functions
3. Initialize maps with `make(map[K]V)` before writing
4. Use `recover()` in deferred functions for graceful panic handling
5. Add bounds checking before slice/array access

### context deadline exceeded

**Pattern in logs**:
```
context deadline exceeded
rpc error: code = DeadlineExceeded desc = context deadline exceeded
```

**Typical root causes**:
- HTTP client timeout too short for the operation
- gRPC call exceeding context deadline
- Database query running longer than context timeout
- Cascading timeouts (caller timeout shorter than callee processing time)

**Remediation**:
1. Increase timeout: `ctx, cancel := context.WithTimeout(ctx, 30*time.Second)`
2. Check if the downstream service is healthy and responding within SLA
3. Add per-operation timeouts instead of a single global timeout
4. Implement circuit breaker to fail fast on known-degraded dependencies
5. Log remaining deadline at entry points: `deadline, ok := ctx.Deadline()`

### too many open files

**Pattern in logs**:
```
accept tcp [::]:8080: accept4: too many open files
open /tmp/data.json: too many open files
```

**Typical root causes**:
- File descriptors not being closed (HTTP response bodies, file handles)
- Connection pool leak — goroutines opening connections without closing
- System ulimit too low for the workload
- Goroutine leak creating unbounded connections

**Remediation**:
1. Check current limits: `ulimit -n` (default often 1024, production needs 65535+)
2. Ensure `resp.Body.Close()` is called for every HTTP response (even on error paths)
3. Use `defer file.Close()` immediately after opening files
4. Check for goroutine leaks: expose `/debug/pprof/goroutine` and check count over time
5. Increase limit: `ulimit -n 65535` or set in systemd unit file (`LimitNOFILE=65535`)

## General Patterns

### Connection Timeout vs Read Timeout

- **Connection timeout**: time to establish TCP connection (usually 5-10s is sufficient)
- **Read timeout**: time to receive response after connection is established (varies by operation)
- Always configure both separately
- Connection timeout should be short; read timeout depends on expected response time

### Retry Storm / Thundering Herd

**Pattern**: error rate spikes, then multiplies as retries pile up

**Indicators in logs**:
- Rapid succession of the same error from the same client
- Exponentially increasing request count during incidents
- "Circuit breaker open" messages (if implemented)

**Remediation**:
1. Use exponential backoff with jitter: `delay = min(base * 2^attempt + random_jitter, max_delay)`
2. Implement circuit breaker (open after N failures, half-open to test, close on success)
3. Set max retry count (typically 3 for idempotent, 0 for non-idempotent)
4. Use client-side request hedging cautiously (only for read-only, idempotent operations)

### Cascading Failure Pattern

**Pattern**: one service fails, causing dependent services to fail in sequence

**Indicators**:
- Timeout errors spreading across services over minutes
- Connection pool exhaustion in multiple services
- Error rate increasing service by service in dependency order

**Remediation**:
1. Implement circuit breakers between all service boundaries
2. Set aggressive timeouts on downstream calls (fail fast)
3. Use bulkheads (separate connection pools per dependency)
4. Add fallback responses for non-critical dependencies
5. Load shed at the edge (return 503 early rather than cascading)
