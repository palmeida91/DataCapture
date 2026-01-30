# Updated Grafana Queries - Serial Line OEE (Bottleneck-Based)

After running `update_line_oee.sql`, your dashboards will show **bottleneck-based Line OEE**.

---

## 🎯 Key Changes

- **Line OEE** = Slowest station OEE × Quality from last station
- **Quality** counted only from final station output
- **Fault times** use worst station (bottleneck), not summed

---

## 📊 Updated Dashboard Panels

### Panel 1: Production Line OEE (No Changes Needed!)

Your existing query still works - it now uses bottleneck logic:

```sql
SELECT 
    'Line OEE' as metric,
    oee_percent as value
FROM current_oee;
```

**What changed:** The view now calculates OEE using the bottleneck station instead of averaging.

---

### Panel 2: OEE Components (Updated)

Shows which component is limiting your line:

```sql
SELECT 
    'Availability' as metric,
    availability_percent as value
FROM current_oee

UNION ALL

SELECT 
    'Performance' as metric,
    performance_percent as value
FROM current_oee

UNION ALL

SELECT 
    'Quality' as metric,
    quality_percent as value
FROM current_oee;
```

**Note:** Availability and Performance now reflect the **bottleneck station** values.

---

### Panel 3: Bottleneck Information (NEW!)

Shows which station is limiting the line:

```sql
SELECT 
    bottleneck_name as "Bottleneck Station",
    ROUND(bottleneck_oee_percent::numeric, 1) as "Station OEE %",
    ROUND(oee_percent::numeric, 1) as "Line OEE %"
FROM current_oee;
```

**Visualization:** Table or Stat
**Purpose:** Identify which station needs improvement

---

### Panel 4: Station OEE Comparison (NEW - IMPORTANT!)

Compare all stations to find the bottleneck:

```sql
SELECT 
    sequence_name as metric,
    ROUND(station_oee_percent::numeric, 1) as value
FROM station_oee
ORDER BY station_oee_percent;
```

**Visualization:** Bar gauge (horizontal)
**Settings:**
- Display mode: Gradient
- Sort: Ascending (bottleneck shows first!)
- Unit: Percent (0-100)
- Thresholds: Red 0-60, Yellow 60-85, Green 85-100

**This panel is critical** - it shows which station is limiting your line!

---

### Panel 5: Station Performance Breakdown (NEW)

Detailed view of each station:

```sql
SELECT 
    sequence_name as "Station",
    ROUND(station_oee_percent::numeric, 1) || '%' as "Station OEE",
    ROUND(availability_percent::numeric, 1) || '%' as "TA",
    ROUND(performance_percent::numeric, 1) || '%' as "Performance",
    ROUND(last_cycle_time::numeric, 1) || 's' as "Cycle Time",
    ROUND(desired_cycle_time::numeric, 1) || 's' as "Target"
FROM current_sequence_status
ORDER BY station_oee_percent;
```

**Visualization:** Table
**Purpose:** See exactly why each station has its OEE

---

### Panel 6: Hourly OEE Trend (Updated)

Your existing hourly trend now uses bottleneck logic:

```sql
SELECT 
    hour as time,
    oee_percent as "Line OEE %"
FROM hourly_oee_trend
WHERE hour >= NOW() - INTERVAL '24 hours'
ORDER BY hour;
```

**No changes needed** - the view handles the bottleneck calculation!

---

### Panel 7: Station vs Line OEE (NEW)

Compare station OEE to line OEE:

```sql
WITH line_oee AS (
    SELECT oee_percent as line_oee FROM current_oee
)
SELECT 
    sequence_name as metric,
    station_oee_percent as "Station OEE"
FROM station_oee

UNION ALL

SELECT 
    'Line OEE' as metric,
    line_oee as "Station OEE"
FROM line_oee
ORDER BY "Station OEE";
```

**Visualization:** Bar gauge
**Purpose:** See gap between stations and overall line performance

---

### Panel 8: Bottleneck Downtime Analysis (NEW)

Focus on what's stopping your bottleneck station:

```sql
WITH bottleneck AS (
    SELECT sequence_id 
    FROM station_oee 
    ORDER BY station_oee_percent 
    LIMIT 1
)
SELECT 
    'Fault Time' as metric,
    ROUND(fault_time_sec::numeric, 0) as value
FROM current_sequence_status
WHERE sequence_id = (SELECT sequence_id FROM bottleneck)

UNION ALL

SELECT 
    'Blocked Time' as metric,
    ROUND(blocked_time_sec::numeric, 0)
FROM current_sequence_status
WHERE sequence_id = (SELECT sequence_id FROM bottleneck)

UNION ALL

SELECT 
    'Starved Time' as metric,
    ROUND(starved_time_sec::numeric, 0)
FROM current_sequence_status
WHERE sequence_id = (SELECT sequence_id FROM bottleneck);
```

**Visualization:** Bar gauge
**Unit:** seconds (s)
**Purpose:** Understand what's causing downtime at the bottleneck

---

## 🎨 Recommended Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Production Line OEE          │  Bottleneck Station Info     │
│  [GAUGE: 54%]                 │  [TABLE: Operator 2, 60%]    │
├──────────────────────────────────────────────────────────────┤
│  TA    │  Performance  │  Quality                            │
│  82%   │  71%         │  93%                                 │
├──────────────────────────────────────────────────────────────┤
│  Station OEE Comparison (Horizontal Bars)                    │
│  Operator 2 ████████ 60% [RED - BOTTLENECK!]                │
│  Operator 1 ████████████ 75% [YELLOW]                       │
│  (Shows which station is limiting the line)                  │
├──────────────────────────────────────────────────────────────┤
│  Hourly OEE Trend (Line Chart)                              │
│  [Shows bottleneck-based line OEE over last 24 hours]       │
├──────────────────────────────────────────────────────────────┤
│  Station Performance Table                                   │
│  [Detailed breakdown per station]                           │
├──────────────────────────────────────────────────────────────┤
│  Bottleneck Downtime  │  Parts Produced Last 2 Hours        │
│  [Bar gauge]          │  [Table]                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔑 Understanding the New Metrics

### Before (Incorrect):
```
Operator 1 OEE: 75%
Operator 2 OEE: 60%
Average = 67.5% ← WRONG! (doesn't show line is limited by Op 2)
```

### After (Correct):
```
Operator 1 OEE: 75%
Operator 2 OEE: 60% ← BOTTLENECK!
Line OEE = 60% × Quality = 55.8% ← CORRECT!
```

**The line can only go as fast as Operator 2!**

---

## 🎯 How to Use the Dashboards

### Daily Operations:

1. **Check Line OEE panel** - Is it meeting target (85%)?
2. **Look at Station Comparison** - Which station is the bottleneck?
3. **Review Bottleneck Details** - Why is it slow? (TA? Performance? Downtime?)
4. **Focus improvement there** - Fixing the bottleneck improves line OEE!

### Example Decision Flow:

```
Line OEE = 54% (target 85%)
    ↓
Station Comparison shows Operator 2 at 60% (bottleneck)
    ↓
Operator 2 details show: TA 95%, Performance 63%
    ↓
Performance is the issue! (cycle time 28s vs target 17s)
    ↓
ACTION: Investigate why Operator 2 is slow
    ↓
Fix Operator 2 → Line OEE improves immediately!
```

---

## 🚀 Next Steps After Update

1. **Run the update script:** `update_line_oee.sql`
2. **Refresh Grafana dashboards** (may need to reload page)
3. **Add the new panels** (especially Station OEE Comparison!)
4. **Identify your current bottleneck station**
5. **Focus improvement efforts on that station**

---

## 📊 Quick Verification Queries

Test the new views in PostgreSQL:

```sql
-- Show current line OEE with bottleneck info
SELECT * FROM current_oee;

-- Show all stations ranked by OEE (bottleneck first)
SELECT * FROM station_oee ORDER BY station_oee_percent;

-- Show hourly trends
SELECT * FROM hourly_oee_trend ORDER BY hour DESC LIMIT 24;

-- Show current status of all stations
SELECT * FROM current_sequence_status;
```

---

## ⚠️ Important Notes

### Quality Counters:
- **Only final station counts** - earlier stations may produce parts that get scrapped
- Your current setup uses plant-wide quality counters (good!)
- These represent the final output of the line

### Fault Times:
- **Not summed across stations** - that would double-count downtime
- Uses **worst station** (bottleneck) - that's what limits the line
- If Op1 and Op2 both fault for 30min, line downtime = 30min (not 60min!)

### Performance:
- Bottleneck station performance **limits the entire line**
- Speeding up non-bottleneck stations **doesn't help** line OEE
- Focus improvement on **bottleneck only**

---

## 🎓 Theory of Constraints

Your system now implements **Theory of Constraints** principles:

1. **Identify the constraint** (bottleneck station)
2. **Exploit the constraint** (maximize bottleneck utilization)
3. **Subordinate everything else** (other stations serve the bottleneck)
4. **Elevate the constraint** (improve bottleneck capacity)
5. **Repeat** (find new bottleneck after fixing the first)

---

**Your OEE calculations are now accurate for a serial production line!** 🏭✅
