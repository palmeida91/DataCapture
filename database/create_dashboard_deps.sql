-- ============================================================================
-- Missing Objects for Existing Grafana Dashboards
-- ============================================================================
-- Your existing OEE and OEE_Detailed_Station dashboards need these two
-- objects that weren't included in create_database.sql.
--
-- Usage:
--   psql -U collector -d production -h localhost -f database/create_dashboard_deps.sql
--
-- Run AFTER create_database.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. SEQUENCES TABLE
-- ============================================================================
-- Used by dashboard queries to get sequence names and active status.
-- JOINed as: JOIN sequences s ON ct.sequence_id = s.sequence_id
-- Columns used: sequence_id, sequence_name, is_active
-- ============================================================================
CREATE TABLE IF NOT EXISTS sequences (
    sequence_id     INTEGER PRIMARY KEY,
    sequence_name   VARCHAR(100) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    safety_area_id  INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- 2. CURRENT_OEE VIEW
-- ============================================================================
-- Used by the QUALITY stat panel:
--   SELECT 'Quality' as metric, quality_percent as value FROM current_oee;
-- ============================================================================
CREATE OR REPLACE VIEW current_oee AS
SELECT
    CASE
        WHEN (good_parts + reject_parts + rework_parts) > 0 THEN
            ROUND(
                (good_parts::numeric /
                (good_parts + reject_parts + rework_parts) * 100), 1
            )
        ELSE 100
    END AS quality_percent,
    good_parts,
    reject_parts,
    rework_parts,
    shift_number,
    hour_index
FROM quality_counters
ORDER BY time DESC
LIMIT 1;

COMMIT;

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================
GRANT ALL ON sequences TO collector;
GRANT SELECT ON current_oee TO collector;

-- ============================================================================
-- SEED SEQUENCES
-- ============================================================================
-- Update this list to match the active_sequences in your collector_config.json
-- Format: (sequence_id, 'Name for Grafana display', is_active)
--
-- For the Linux laptop (2 sequences currently):
-- Edit the VALUES below to match YOUR sequences and names.
-- ============================================================================
INSERT INTO sequences (sequence_id, sequence_name, is_active) VALUES
    -- =====================================================
    -- EDIT THESE to match your collector_config.json
    -- =====================================================
    (5,  'TT527',   true),
    (8,  '550R01',  true),
    (9,  '550R02',  true),
    (10, '555R01',  true),
    (11, '560R01',  true),
    (15, 'PR565',   true),
    (18, 'Plate Push',  true),
    (19, 'CV570 580LD', true),
    (21, '570R01',  true),
    (22, '575R01',  true),
    (23, '580R01',  true),
    (24, '580R02',  true),
    (30, 'CV570 583UL',  true),
    (31, '583R01',  true),
    (39, 'CV590_Load', true),
    (40, 'CV590_Unload', true),
    (41, 'PR594',  true),
    (43, 'LM598',  true),
    (44, '590R01', true),
    (47, 'MC595',  true),
    (48, 'MC596',  true),
    (49, 'MC597',  true),
    (50, 'Operator 1', true),
    (51, 'Operator 2', true)
ON CONFLICT (sequence_id) DO UPDATE SET
    sequence_name = EXCLUDED.sequence_name,
    is_active = EXCLUDED.is_active;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT 'Dashboard dependencies created!' AS status;
SELECT sequence_id, sequence_name, is_active FROM sequences ORDER BY sequence_id;
