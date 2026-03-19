---
name: latency-analysis
description: >
  Analyze endpoint latency trends using historical check data from
  memory. Detects slow degradation, spikes vs sustained issues, and
  calculates baseline deviations.
---

Latency trend analysis skill using episodic memory.

## When to activate

Use this skill when comparing current latency against historical data,
or when the user asks about performance trends for an endpoint.

## Methodology

### 1. Gather history

Recall the last 10 episodic memories for the endpoint:
```
recall("<endpoint-host-and-path> check")
```
Extract latency values from each recalled episode.

### 2. Calculate baseline

Compute the rolling baseline as the median latency from recalled
episodes. If fewer than 3 data points exist, note "insufficient data
for baseline" and skip trend analysis.

### 3. Measure deviation

```
deviation = (current - baseline) / baseline * 100
```

Classification:
- **<25% deviation**: Normal fluctuation -- no action
- **25-100% deviation**: Elevated -- note but do not alert unless
  sustained
- **>100% deviation**: Degraded -- check if sustained
- **Timeout**: Down -- immediate alert

### 4. Determine trend direction

Compare the last 3 readings against the previous 3:
- All decreasing or stable: **improving**
- Mixed or flat: **stable**
- All increasing: **degrading**

### 5. Alert criteria

All three conditions must hold for a degradation alert:
1. Current latency > baseline * 1.5
2. At least 3 consecutive elevated readings (not a single spike)
3. Trend direction is "degrading" or "stable at elevated"

## MUST

- Use actual data from memory -- never estimate without checking
- State the baseline and current values in any alert
- Include the number of consecutive elevated readings

## MUST NOT

- Alert on a single spike (wait for 3 consecutive readings)
- Assume a baseline without checking memory
- Use absolute thresholds without comparing to this endpoint's own
  history (200ms might be normal for one endpoint, degraded for another)
