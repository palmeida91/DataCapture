# Database Maintenance Scripts

## 📦 What's Included

1. **`retention_config.sql`** - Set up automatic data retention and compression
2. **`add_sequences.sql`** - Add new sequences/operators to monitor

---

## 🗄️ Script 1: Configure Data Retention

### What It Does

- **Compresses data** older than 7 days (saves 90% disk space)
- **Automatically deletes data** older than 90 days
- Keeps your database size manageable

### How to Run

```powershell
# Copy the script into your project folder, then run:
docker exec -it production_db psql -U collector -d production -f retention_config.sql
```

### Expected Output

```
Retention and compression policies configured successfully!
Data older than 90 days will be deleted automatically.
Data older than 7 days will be compressed to save space.
```

### Customizing Retention Period

Edit the script and change `INTERVAL '90 days'` to your preferred period:
- `INTERVAL '30 days'` - Keep only 1 month
- `INTERVAL '180 days'` - Keep 6 months
- `INTERVAL '365 days'` - Keep 1 year

---

## 👥 Script 2: Add New Sequences

### What It Does

- Adds new sequences/operators to the database
- Makes them available for monitoring and Grafana dashboards

### How to Use

1. **Edit the script** (`add_sequences.sql`)
2. **Replace the example sequences** with your actual data:

```sql
INSERT INTO sequences (sequence_id, sequence_name, is_active, safety_area_id)
VALUES 
    (52, 'Operator 3', true, 2),     -- Your sequence 52
    (53, 'Operator 4', true, 2),     -- Your sequence 53
    (54, 'Station A', true, 1),      -- Your sequence 54
    (55, 'Station B', true, 1);      -- Your sequence 55 (no comma on last line!)
```

3. **Run the script:**

```powershell
docker exec -it production_db psql -U collector -d production -f add_sequences.sql
```

4. **Update the config file** (`config/opcua_nodes_oee.json`):

```json
"active_sequences": [50, 51, 52, 53, 54, 55]
```

5. **Restart the data collector:**

```powershell
python data_collector_oee.py
```

---

## 🔧 Common Tasks

### View All Sequences

```powershell
docker exec -it production_db psql -U collector -d production
```

```sql
SELECT * FROM sequences ORDER BY sequence_id;
\q
```

### Check Database Size

```sql
-- Total database size
SELECT pg_size_pretty(pg_database_size('production'));

-- Size per table
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size('public.'||tablename) DESC;
```

### Verify Retention Policies

```sql
-- Show all active policies
SELECT 
    hypertable_name,
    proc_name,
    config
FROM timescaledb_information.jobs
WHERE proc_name IN ('policy_compression', 'policy_retention');
```

### Manually Compress Data Now

```sql
-- Compress all eligible chunks immediately (don't wait for automatic compression)
SELECT compress_chunk(show_chunks('cycle_times', older_than => INTERVAL '7 days'));
SELECT compress_chunk(show_chunks('technical_availability', older_than => INTERVAL '7 days'));
SELECT compress_chunk(show_chunks('quality_counters', older_than => INTERVAL '7 days'));
```

---

## ⚠️ Important Notes

### Retention Policy
- Data older than 90 days is **permanently deleted**
- Cannot be recovered after deletion
- Adjust retention period before running if needed

### Compression
- Compressed data is still **fully queryable**
- Grafana dashboards work normally with compressed data
- Saves 90%+ disk space
- Cannot insert new data into compressed chunks

### Safety Areas
- `safety_area_id` should match your PLC configuration
- Common values: 1, 2, 3
- Used for grouping sequences in reports

---

## 📊 Storage Estimates

### Without Retention (Unlimited Storage)
- ~25,000 records/day per table
- ~100 MB/month per table
- **~1.2 GB/year** for 3 tables

### With Compression Only (No Deletion)
- Same record count
- **~120 MB/year** (90% savings!)

### With Compression + 90-Day Retention
- Maximum ~2.3 million records per table
- **~30 MB total** (stable, never grows!)

---

## 🚀 Quick Start Checklist

- [ ] Run `retention_config.sql` to set up retention
- [ ] Edit `add_sequences.sql` with your sequences
- [ ] Run `add_sequences.sql` to add sequences to database
- [ ] Update `config/opcua_nodes_oee.json` with new sequence IDs
- [ ] Restart data collector
- [ ] Verify sequences appear in Grafana

---

## 📞 Troubleshooting

**"ERROR: function add_retention_policy does not exist"**
- TimescaleDB extension not installed
- Run: `CREATE EXTENSION IF NOT EXISTS timescaledb;`

**"ERROR: duplicate key value violates unique constraint"**
- Sequence already exists in database
- Check: `SELECT * FROM sequences WHERE sequence_id = XX;`
- Either use different sequence_id or delete the existing one

**"Sequences added but no data in Grafana"**
- Check data collector is running
- Verify sequences in config: `config/opcua_nodes_oee.json`
- Check collector logs: `type data_collector_oee.log`

---

## 📁 File Locations

```
D:\Dev\DataCollection\DataCapture\
├── retention_config.sql           # Database retention script
├── add_sequences.sql              # Add sequences script
├── data_collector_oee.py          # Main data collector
├── config/
│   └── opcua_nodes_oee.json       # Collector configuration
└── data_collector_oee.log         # Collector logs
```

---

**Your database is now configured for long-term production use!** 🎉
