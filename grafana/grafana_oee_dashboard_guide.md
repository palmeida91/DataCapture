# Grafana OEE Dashboard - Setup Guide

## Dashboard: Sequence OEE Comparison

All OEE calculations use **MEDIAN** (via `percentile_cont`) instead of AVG to handle outliers from skip cycles and PLC glitches. The heavy calculations live in database views — Grafana queries are simple SELECTs.

### Prerequisites

Run these SQL files in order on the laptop:

```bash
cd ~/DataCollection/DataCapture
psql -U collector -d production -h localhost -f database/create_database.sql
psql -U collector -d production -h localhost -f database/seed_breaks.sql
psql -U collector -d production -h localhost -f database/create_views.sql
```

### Database Views Reference

| View | Contains | Keyed by |
|------|----------|----------|
| `v_sequence_availability` | Median TA% | bucket, sequence_id |
| `v_sequence_performance` | Median performance%, cycle times | bucket, sequence_id |
| `v_sequence_cycle_times` | Median cycle time, deviation | bucket, sequence_id |
| `v_sequence_downtime` | Median fault/blocked/starved | bucket, sequence_id |
| `v_line_quality` | Quality% from part counters | time, shift, hour |
| `v_break_compliance` | Break start/end compliance | break_start |

All time-bucketed views use 1-minute buckets (`date_trunc('minute', ...)`).

---

## Variable Setup

Go to **Dashboard Settings → Variables → New variable**

### Variable: `sequence`

| Setting | Value |
|---------|-------|
| Name | `sequence` |
| Type | Query |
| Data source | Your PostgreSQL source |
| Multi-value | ✅ Enabled |
| Include All option | ✅ Enabled |
| Default | All |

**Query:**

```sql
SELECT DISTINCT sequence_id::text
FROM cycle_times
WHERE $__timeFilter(time)
ORDER BY sequence_id
```

This auto-discovers sequences from whatever data exists in the selected time range.

---

## Row 1: Line-Level Summary (Stat Panels)

Single-value stat panels showing overall line performance.

---

### Panel 1A: Line OEE %

- **Visualization:** Stat
- **Panel title:** Line OEE %

```sql
WITH avail AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY availability_pct) AS a
    FROM v_sequence_availability
    WHERE $__timeFilter(bucket)
      AND sequence_id IN ($sequence)
),
perf AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY performance_pct) AS p
    FROM v_sequence_performance
    WHERE $__timeFilter(bucket)
      AND sequence_id IN ($sequence)
),
qual AS (
    SELECT
      CASE
        WHEN SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts) > 0 THEN
          SUM(good_parts)::numeric /
          (SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts)) * 100
        ELSE 100
      END AS q
    FROM quality_counters
    WHERE $__timeFilter(time)
)
SELECT
    ROUND(((avail.a / 100) * (perf.p / 100) * (qual.q / 100) * 100)::numeric, 1) AS "OEE %"
FROM avail, perf, qual
```

**Panel options:**
- Unit: Percent (0-100)
- Color mode: Background gradient
- Thresholds: 0 = Red, 60 = Yellow, 85 = Green

---

### Panel 1B: Quality %

- **Visualization:** Stat
- **Panel title:** Quality %

```sql
SELECT
    CASE
        WHEN SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts) > 0 THEN
            ROUND(
                (SUM(good_parts)::numeric /
                (SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts)) * 100), 1
            )
        ELSE 100
    END AS "Quality %"
FROM quality_counters
WHERE $__timeFilter(time)
```

**Panel options:**
- Unit: Percent (0-100)
- Color mode: Background gradient
- Thresholds: 0 = Red, 90 = Yellow, 95 = Green

---

### Panel 1C: Part Counts

- **Visualization:** Stat (or Bar gauge)
- **Panel title:** Part Counts

```sql
SELECT
    SUM(good_parts) AS "Good",
    SUM(reject_parts) AS "Reject",
    SUM(rework_parts) AS "Rework"
FROM quality_counters
WHERE $__timeFilter(time)
```

---

## Row 2: Per-Sequence Comparison

---

### Panel 2A: Availability % per Sequence (Bar Chart)

- **Visualization:** Bar chart
- **Panel title:** Availability by Sequence

```sql
SELECT
    sequence_id::text AS "Sequence",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY availability_pct)::numeric, 1) AS "Availability %"
FROM v_sequence_availability
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY sequence_id
ORDER BY sequence_id
```

**Panel options:**
- X axis: Sequence
- Orientation: Vertical
- Color scheme: Green-Yellow-Red (by value)
- Thresholds: 0 = Red, 85 = Yellow, 95 = Green

---

### Panel 2B: Performance % per Sequence (Bar Chart)

- **Visualization:** Bar chart
- **Panel title:** Performance by Sequence

```sql
SELECT
    sequence_id::text AS "Sequence",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY performance_pct)::numeric, 1) AS "Performance %"
FROM v_sequence_performance
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY sequence_id
ORDER BY sequence_id
```

**Panel options:** Same as 2A

---

### Panel 2C: Sequence Detail Table

- **Visualization:** Table
- **Panel title:** Sequence Summary

Uses two queries merged with a Grafana transform.

**Query A** (name it `perf`):

```sql
SELECT
    sequence_id AS "Seq",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY performance_pct)::numeric, 1) AS "Perf %",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_cycle_time_sec)::numeric, 2) AS "Cycle (s)",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_desired_cycle_sec)::numeric, 2) AS "Target (s)"
FROM v_sequence_performance
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY sequence_id
ORDER BY sequence_id
```

**Query B** (name it `avail`):

```sql
SELECT
    a.sequence_id AS "Seq",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY a.availability_pct)::numeric, 1) AS "Avail %",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.median_fault_sec)::numeric, 0) AS "Fault (s)",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.median_blocked_sec)::numeric, 0) AS "Blocked (s)",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.median_starved_sec)::numeric, 0) AS "Starved (s)"
FROM v_sequence_availability a
JOIN v_sequence_downtime d
  ON a.sequence_id = d.sequence_id AND a.bucket = d.bucket
WHERE $__timeFilter(a.bucket)
  AND a.sequence_id IN ($sequence)
GROUP BY a.sequence_id
ORDER BY a.sequence_id
```

**Transform:** Merge (joins both queries on the `Seq` field)

---

## Row 3: Trends Over Time

All trend panels use `$__timeGroup()` for automatic bucket sizing.

---

### Panel 3A: Availability Trend

- **Visualization:** Time series
- **Panel title:** Availability Trend

```sql
SELECT
    $__timeGroup(bucket, $__interval) AS time,
    sequence_id::text AS metric,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY availability_pct)::numeric, 1) AS "Availability %"
FROM v_sequence_availability
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY $__timeGroup(bucket, $__interval), sequence_id
ORDER BY time
```

**Panel options:**
- Legend: As table, to the right
- Y-axis: 0–100, Unit: Percent (0-100)

---

### Panel 3B: Performance Trend

- **Visualization:** Time series
- **Panel title:** Performance Trend

```sql
SELECT
    $__timeGroup(bucket, $__interval) AS time,
    sequence_id::text AS metric,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY performance_pct)::numeric, 1) AS "Performance %"
FROM v_sequence_performance
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY $__timeGroup(bucket, $__interval), sequence_id
ORDER BY time
```

**Panel options:** Same as 3A

---

### Panel 3C: Cycle Time Trend

- **Visualization:** Time series
- **Panel title:** Cycle Time Trend

```sql
SELECT
    $__timeGroup(bucket, $__interval) AS time,
    sequence_id::text AS metric,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_cycle_sec)::numeric, 2) AS "Cycle Time (s)"
FROM v_sequence_cycle_times
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY $__timeGroup(bucket, $__interval), sequence_id
ORDER BY time
```

**Panel options:**
- Add a constant threshold line at target cycle time (17s)
- Y-axis unit: seconds (s)

---

## Row 4: Downtime & Breaks

---

### Panel 4A: Downtime Breakdown (Stacked Bar)

- **Visualization:** Bar chart (stacked)
- **Panel title:** Downtime Breakdown

```sql
SELECT
    sequence_id::text AS "Sequence",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_fault_sec)::numeric, 0) AS "Fault",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_blocked_sec)::numeric, 0) AS "Blocked",
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_starved_sec)::numeric, 0) AS "Starved"
FROM v_sequence_downtime
WHERE $__timeFilter(bucket)
  AND sequence_id IN ($sequence)
GROUP BY sequence_id
ORDER BY sequence_id
```

**Panel options:**
- Stacking: Normal
- Colour: Fault = Red, Blocked = Orange, Starved = Blue

---

### Panel 4B: Break Compliance (Table)

- **Visualization:** Table
- **Panel title:** Break Compliance

```sql
SELECT
    break_start::timestamp(0) AS "Started",
    break_name AS "Break",
    shift_number AS "Shift",
    actual_duration_min AS "Actual (min)",
    scheduled_duration_min AS "Scheduled (min)",
    CASE
        WHEN early_start_minutes > 0 THEN early_start_minutes || ' min early'
        ELSE 'On time'
    END AS "Start",
    CASE
        WHEN late_end_minutes > 0 THEN late_end_minutes || ' min late'
        ELSE 'On time'
    END AS "End",
    compliance_status AS "Status"
FROM v_break_compliance
WHERE $__timeFilter(break_start)
ORDER BY break_start DESC
```

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│ Row 1: Line-Level Summary                               │
│ ┌──────────┐ ┌──────────┐ ┌────────────────────────┐   │
│ │ OEE %    │ │Quality % │ │ Good / Reject / Rework │   │
│ │ (Stat)   │ │ (Stat)   │ │ (Stat)                 │   │
│ └──────────┘ └──────────┘ └────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│ Row 2: Per-Sequence Comparison                          │
│ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐   │
│ │ Avail % Bars │ │ Perf % Bars  │ │ Detail Table   │   │
│ │ (Bar Chart)  │ │ (Bar Chart)  │ │ (Table)        │   │
│ └──────────────┘ └──────────────┘ └────────────────┘   │
├─────────────────────────────────────────────────────────┤
│ Row 3: Trends Over Time                                 │
│ ┌──────────────────┐ ┌──────────────────┐               │
│ │ Availability     │ │ Performance      │               │
│ │ (Time Series)    │ │ (Time Series)    │               │
│ └──────────────────┘ └──────────────────┘               │
│ ┌──────────────────────────────────────────┐            │
│ │ Cycle Time Trend (Time Series)           │            │
│ └──────────────────────────────────────────┘            │
├─────────────────────────────────────────────────────────┤
│ Row 4: Downtime & Breaks                                │
│ ┌──────────────────┐ ┌──────────────────────┐           │
│ │ Downtime Stacked │ │ Break Compliance     │           │
│ │ (Bar Chart)      │ │ (Table)              │           │
│ └──────────────────┘ └──────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

---

## Grafana Macros Quick Reference

| Macro | What it does |
|-------|--------------|
| `$__timeFilter(bucket)` | Filters by dashboard time picker range |
| `$__timeGroup(bucket, $__interval)` | Auto-calculates bucket size based on range and panel width |
| `$sequence` | Replaced by selected sequence IDs from variable dropdown |
| `IN ($sequence)` | Works with multi-value variables |

---

## Dashboard Settings

| Setting | Recommended Value |
|---------|-------------------|
| Time picker default | Last 1 hour |
| Auto-refresh | 10s (matches collector interval) |
| Timezone | Browser |

---

## Tips

- **Performance > 100%** means actual cycle time is faster than target — normal and good
- **Sequence filter** defaults to All — use the dropdown to focus on specific sequences
- **Time range** drives everything — zoom into a shift, a day, or the full week
- **Break compliance** only shows data when the break detector is running and detecting TA freezes
- **If a panel shows "No data"** check that the time range contains data: `SELECT COUNT(*) FROM cycle_times WHERE time > NOW() - INTERVAL '1 hour';`
