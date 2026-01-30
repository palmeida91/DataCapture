# Production Monitoring System - Updated for Namespace 3

Complete OEE monitoring solution for industrial automation lines with Siemens S7-1518 PLC.

## 🎯 What's New in This Version

**Fixed for your specific PLC configuration:**
- ✅ Namespace changed from 2 to 3
- ✅ OPC UA paths updated to use direct global variable access (e.g., `"GlobalData"."sequence"[50]."state"`)
- ✅ Security working with Basic256Sha256 / SignAndEncrypt
- ✅ Docker Compose V2 compatibility (`docker compose` instead of `docker-compose`)
- ✅ Certificate generator included
- ✅ Application URI correctly set

---

## 🚀 Quick Start

### 1. Generate Certificates (First Time Only)

```powershell
pip install cryptography
python generate_certs.py
```

This creates:
- `client_cert.der` (certificate)
- `client_key.pem` (private key)
- `client_cert.pem` (certificate in PEM format)

### 2. Configure Your Active Sequences

Edit `config/opcua_nodes.json`:

```json
"active_sequences": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 30, 31, 32, 33]
```

**Update this list** to include only the sequences that exist on your machine.

### 3. Start Docker Containers

```powershell
docker compose up -d
```

Or use the batch file:
```powershell
.\scripts\start_services.bat
```

### 4. Start Data Collector

```powershell
python data_collector.py
```

You should see:
```
2026-01-29 - INFO - Connecting to OPC UA server: opc.tcp://192.168.61.2:4840
2026-01-29 - INFO - Using security: Basic256Sha256 / SignAndEncrypt
2026-01-29 - INFO - [OK] OPC UA connection established
2026-01-29 - INFO - [OK] Database connection established
2026-01-29 - INFO - Collecting data from PLC...
2026-01-29 - INFO - [OK] Collected: 14 states, 8 cycles, 14 TA records, counters OK
```

### 5. Open Grafana

- URL: http://localhost:3000
- Login: `admin` / `admin`
- Follow the dashboard creation guide below

---

## ⚙️ Configuration

### Your Current Settings

**PLC Connection:**
- URL: `opc.tcp://192.168.61.2:4840`
- Namespace: `3` (direct global variable access)
- Security: Basic256Sha256 with SignAndEncrypt

**OPC UA Node Structure:**
```
Sequences: ns=3;s="GlobalData"."sequence"[ID]."state"
TA Data:   ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[ID]."TA"
Counters:  ns=3;s="Counter_Interface"."shifts"[SHIFT]."types"[TYPE]."data"[HOUR]."value"
```

### Updating Active Sequences

1. Check which sequences exist in UaExpert
2. Edit `config/opcua_nodes.json`:
   ```json
   "active_sequences": [1, 2, 3, 5, 7, 10, 30, 31]
   ```
3. Restart data collector (Ctrl+C, then `python data_collector.py`)

---

## 📊 Creating Grafana Dashboard

### Step 1: Verify Data Source

1. Login to Grafana (admin/admin)
2. ☰ Menu → Connections → Data sources
3. Click **ProductionDB** (should already be configured)
4. Verify "Database Connection OK" message

### Step 2: Check Data is Collecting

```powershell
docker exec -it production_db psql -U collector -d production
```

```sql
SELECT COUNT(*) FROM sequence_states;    -- Should be > 0
SELECT COUNT(*) FROM technical_availability;
SELECT * FROM sequences LIMIT 5;         -- See your sequences
\q
```

### Step 3: Create Dashboard

**Method A: Manual Panel Creation**

1. ☰ → Dashboards → New → New Dashboard
2. Add visualization → Select **ProductionDB**

**Panel 1 - Current OEE:**
```sql
SELECT 
    oee_percent as "OEE %",
    availability_percent as "Availability %",
    performance_percent as "Performance %",
    quality_percent as "Quality %"
FROM current_oee;
```
- Visualization: **Stat** or **Gauge**
- Thresholds: Red (0-75), Yellow (75-85), Green (85-100)

**Panel 2 - Sequence Status Table:**
```sql
SELECT 
    sequence_id as "Seq",
    sequence_name as "Name",
    state as "State",
    ROUND(ta_percent::numeric, 1) as "TA %",
    ROUND(last_cycle_time::numeric, 1) as "Cycle (s)"
FROM current_sequence_status
ORDER BY sequence_id;
```
- Visualization: **Table**
- Auto refresh: 5s

**Panel 3 - OEE Trend:**
```sql
SELECT 
    hour as time,
    oee_percent as "OEE %"
FROM hourly_oee_trend
WHERE hour >= NOW() - INTERVAL '24 hours'
ORDER BY hour;
```
- Visualization: **Time series**
- Add threshold line at 85%

3. Save dashboard: Name it "Production Supervisor Dashboard"

---

## 🔧 Troubleshooting

### Issue: "BadNodeIdUnknown" errors

**Cause:** Trying to read sequences that don't exist.

**Fix:** Update `active_sequences` in `config/opcua_nodes.json` to only include sequences that exist on your machine.

### Issue: No data in Grafana

**Check:**
1. Is data collector running? (should show "Collected: X states..." every 5 seconds)
2. Are there database errors? Check `data_collector.log`
3. Query database directly:
   ```powershell
   docker exec -it production_db psql -U collector -d production -c "SELECT COUNT(*) FROM sequence_states;"
   ```

### Issue: Certificate errors

**Fix:**
```powershell
# Delete old certificates
del client_cert.*
del client_key.pem

# Regenerate
python generate_certs.py

# Restart data collector
python data_collector.py
```

### Issue: Docker compose command not found

**Fix:** Use `docker compose` (with space, not hyphen):
```powershell
docker compose up -d
docker compose stop
docker compose ps
```

---

## 📁 File Structure

```
production_monitoring_system/
├── data_collector.py          # Main OPC UA data collector
├── generate_certs.py           # Certificate generator
├── config/
│   └── opcua_nodes.json       # PLC connection & paths (NAMESPACE 3)
├── database/
│   ├── schema.sql             # Database schema
│   └── seed_config.sql        # Initial data
├── docker-compose.yml         # Infrastructure setup
├── scripts/
│   ├── start_services.bat     # Start Docker
│   ├── stop_services.bat      # Stop Docker
│   └── setup.ps1              # Automated setup
└── README.md                  # This file
```

---

## 🎓 Key Differences from Standard Setup

**Your PLC uses direct global variable access:**

| Standard Setup | Your PLC (Namespace 3) |
|----------------|------------------------|
| `ns=2;s=PLC.DataBlocksGlobal.GlobalData...` | `ns=3;s="GlobalData"..."` |
| Hierarchical path | Direct path with quotes |
| PLC name included | No PLC name |

This is **normal** and actually **simpler** - just a different way Siemens exposes OPC UA data.

---

## 📞 Daily Operation

**Start everything:**
```powershell
docker compose up -d
python data_collector.py
```

**Stop everything:**
```powershell
# Press Ctrl+C in data collector window
docker compose stop
```

**View logs:**
```powershell
# Data collector
type data_collector.log

# Docker containers
docker compose logs -f postgres
docker compose logs -f grafana
```

---

## 💾 Backup

**Database backup:**
```powershell
docker exec production_db pg_dump -U collector production > backup.sql
```

**Restore:**
```powershell
docker exec -i production_db psql -U collector production < backup.sql
```

---

## ✅ Verification Checklist

Before asking for help, verify:

- [ ] Certificates generated (`client_cert.der` and `client_key.pem` exist)
- [ ] `config/opcua_nodes.json` has `"namespace": 3`
- [ ] `active_sequences` only includes sequences that exist
- [ ] Docker containers running (`docker compose ps`)
- [ ] Data collector shows "[OK] Collected: X states..." every 5 seconds
- [ ] Database has data (`docker exec -it production_db psql -U collector -d production -c "SELECT COUNT(*) FROM sequence_states;"`)
- [ ] Grafana accessible at http://localhost:3000

---

**Version:** 1.0.1 (Namespace 3 Fix)  
**Last Updated:** January 2026
