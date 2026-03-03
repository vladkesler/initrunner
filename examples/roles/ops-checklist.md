# Ops Checklist

Companion file for `ops-heartbeat.yaml`. The heartbeat trigger reads this file
on each tick and sends its contents to the agent as a prompt.

## Infrastructure

- [ ] Check disk usage on /data (alert if > 80%)
- [ ] Verify DNS resolution for api.example.com
- [ ] Ping gateway 10.0.0.1 (alert if packet loss > 0%)
- [ ] Confirm NTP sync — `systemctl status chronyd`

## Services

- [ ] Curl health endpoint https://api.example.com/health (expect 200)
- [ ] Curl metrics endpoint https://api.example.com/metrics (expect 200)
- [ ] Check available memory (alert if free < 512 MB)
