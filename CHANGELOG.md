# Changelog

## Version 1.0.1 (January 2026) - Namespace 3 Fix

### Fixed
- **OPC UA namespace changed from 2 to 3** for direct global variable access
- **Node path templates updated** to use quoted format (e.g., `"GlobalData"."sequence"[ID]."state"`)
- **_build_node_id method** now handles empty `plc_name` correctly
- **Docker Compose V2** compatibility - changed `docker-compose` to `docker compose`
- **Active sequences** reduced to avoid BadNodeIdUnknown errors

### Added
- **generate_certs.py** - Automatic certificate generation script
- **Application URI** automatically set to `urn:ProductionMonitoring:OpcuaClient`
- **Improved logging** - Removed emojis, using [OK], [ERROR], [WARN] tags
- **Better error messages** - Clearer troubleshooting guidance

### Changed
- Default namespace: 2 → 3
- PLC name: "=2+A2.1-PLC" → "" (empty)
- Node format: `plc.DataBlocksGlobal.path` → `"GlobalData".path`

---

## Version 1.0.0 (January 2026) - Initial Release

### Features
- OPC UA data collection from Siemens S7-1518 PLC
- Real-time OEE monitoring (Availability × Performance × Quality)
- Support for up to 64 sequences
- TimescaleDB time-series database with auto-retention
- Grafana dashboards for visualization
- Comprehensive OPC UA connection diagnostics
- Shift and break tracking
- Technical Availability (TA) monitoring per sequence
- Cycle time trending with deviation alerts
- Quality counters (good/reject/rework) per shift

### Components
- Python data collector with asyncua
- PostgreSQL + TimescaleDB for storage
- Grafana for visualization
- Docker Compose for easy deployment
- Automated setup scripts for Windows
