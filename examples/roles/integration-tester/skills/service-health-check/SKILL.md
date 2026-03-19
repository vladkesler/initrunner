---
name: service-health-check
description: >
  Health endpoint verification and dependency status checks. Probes
  standard health paths, validates dependency connectivity, and reports
  overall service readiness.
requires:
  bins: [curl]
---

Service health check skill using curl and standard system tools.

## When to activate

Use this skill when tests fail and the underlying service might be down,
when running pre-test health validation to confirm infrastructure is ready,
when a deployment just completed and needs smoke-test verification, or when
intermittent failures suggest an unstable dependency.

## Health endpoints

Probe these common health paths in order until one responds:

1. `/health`
2. `/healthz`
3. `/readiness`
4. `/api/health`
5. `/status`
6. `/ping`
7. `/` (root, as a last resort)

For each endpoint:

```
curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://host:port/health
```

A 200 response means healthy. A non-200 or timeout means the service or
that specific check is failing.

If the health endpoint returns a JSON body, parse it to extract per-dependency
status:

```
curl -s --max-time 5 http://host:port/health | python -c "
import sys, json
data = json.load(sys.stdin)
for dep, status in data.get('dependencies', {}).items():
    mark = 'OK' if status.get('healthy') else 'FAIL'
    print(f'  {dep}: {mark}')
"
```

## Dependency checks

For each service, verify that its dependencies are reachable:

- **Database** -- use the database-verification skill's connectivity checks
- **Cache (Redis/Memcached)** -- `redis-cli -h host ping` or equivalent
- **Message queue (RabbitMQ/Kafka)** -- check management API or port
  availability
- **External APIs** -- curl the external service's health endpoint or a
  known stable URL with a short timeout

Build a dependency map from the service's configuration (docker-compose.yaml,
environment variables, config files) and check each dependency individually.

## Docker service health

When services run in Docker:

```
docker-compose ps                     # all services and their status
docker logs --tail 30 <service>       # recent log output for errors
docker inspect --format='{{.State.Health.Status}}' <container>
```

Check for:
- Services in "Exit" or "Restarting" state
- Health checks reporting "unhealthy"
- OOM kills in docker events or logs
- Port mapping correctness (host port mapped to expected container port)

## Process checks

When services run directly on the host:

```
pgrep -f <process-name>              # check if process is running
ss -tlnp | grep :<port>             # check if port is listening
```

If a process is not running, check recent system logs for crash information.

## Port checks

Verify expected ports are listening and responsive:

```
curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://host:port/
```

For non-HTTP services, check port availability:

```
timeout 3 bash -c '</dev/tcp/host/port' && echo "open" || echo "closed"
```

Report which ports responded and which timed out.

## MUST

- Check all services before declaring a single service at fault -- a
  downstream dependency failure often looks like the upstream service is
  broken
- Report which specific dependency is down, not just "service unhealthy"
- Include timestamps in health reports so results can be compared over time
- Use timeouts on all network calls (--max-time for curl, timeout for
  other commands) to avoid hanging
- Report the full dependency chain when a failure is detected (e.g.,
  "service-a is failing because database-b is unreachable")

## MUST NOT

- Restart services without explicit user confirmation -- health checks are
  diagnostic only
- Assume localhost for all services -- read host/port from configuration
  or environment variables
- Ignore partial failures -- if 3 of 4 dependencies are healthy but 1 is
  down, report the mixed state clearly
- Cache health results across separate invocations -- always probe live
  status
- Treat a slow response as a healthy response -- enforce timeout thresholds
