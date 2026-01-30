# 🚀 QUICK START - Updated Version

## What's Fixed

✅ Namespace changed to 3  
✅ Node paths updated for your PLC  
✅ Security working (Basic256Sha256)  
✅ Docker Compose V2 compatible  

---

## 5-Minute Setup

### 1. Generate Certificates
```powershell
pip install cryptography
python generate_certs.py
```

### 2. Update Active Sequences

Edit `config/opcua_nodes.json` line 18:
```json
"active_sequences": [1, 2, 3, 4, 5]  // <- Only sequences that exist!
```

### 3. Start Services
```powershell
docker compose up -d
```

### 4. Start Collector
```powershell
python data_collector.py
```

Should see:
```
INFO - [OK] OPC UA connection established
INFO - [OK] Database connection established
INFO - [OK] Collected: X states, Y cycles, Z TA records
```

### 5. Open Grafana
http://localhost:3000 (admin/admin)

---

## If You Get Errors

**"BadNodeIdUnknown"**
→ Update `active_sequences` in config to only include sequences that exist

**"BadCertificateUriInvalid"**
→ Regenerate certificates: `python generate_certs.py`

**"docker-compose not found"**
→ Use `docker compose` (with space)

**"No data in Grafana"**
→ Check data collector is running and showing "Collected: X states..."

---

## Configuration Your PLC Uses

```json
{
  "connection": {
    "namespace": 3,               // NOT 2!
    "plc_name": "",                // Empty!
    "security_policy": "Basic256Sha256",
    "security_mode": "SignAndEncrypt"
  }
}
```

Node format: `ns=3;s="GlobalData"."sequence"[50]."state"`

---

## Daily Usage

**Start:**
```powershell
docker compose up -d
python data_collector.py
```

**Stop:**
```powershell
Ctrl+C  # Stop data collector
docker compose stop
```

**View data:**
```powershell
docker exec -it production_db psql -U collector -d production
```
```sql
SELECT * FROM sequences LIMIT 5;
SELECT COUNT(*) FROM sequence_states;
\q
```

---

That's it! 🎉
