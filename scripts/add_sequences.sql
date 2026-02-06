-- ============================================================================
-- Add New Sequences to Production Monitoring System
-- ============================================================================
-- This script adds new sequences/operators to your monitoring system.
-- Edit the VALUES section below with your actual sequence numbers and names.
--
-- How to use:
-- 1. Edit the VALUES section with your sequence information
-- 2. Run: docker exec -it production_db psql -U collector -d production -f add_sequences.sql
--
-- After adding sequences, update config/opcua_nodes_oee.json:
--   "active_sequences": [50, 51, 52, 53, 54, ...]
-- ============================================================================

-- Start transaction (all-or-nothing operation)
BEGIN;

-- ============================================================================
-- ADD NEW SEQUENCES
-- ============================================================================
-- Insert new sequences into the database
-- 
-- Parameters:
--   sequence_id        : The sequence number from the PLC (must match OPC UA)
--   sequence_name      : Human-readable name for Grafana dashboards
--   is_active          : true = collect data, false = ignore
--   safety_area_id     : Which safety area this sequence belongs to (1, 2, 3, etc.)
--
-- Example: If PLC has sequence 52 called "Station 3 Operator", use:
--   (52, 'Station 3 Operator', true, 2)

INSERT INTO sequences (sequence_id, sequence_name, is_active, safety_area_id)
VALUES 
    -- ========================================================================
    -- EDIT THIS SECTION WITH YOUR SEQUENCES
    -- ========================================================================
    -- Format: (sequence_id, 'sequence_name', is_active, safety_area_id)
    
    -- Example sequences - REPLACE THESE WITH YOUR ACTUAL DATA:
    (31, '545_Unload', true, 2),      -- Sequence 31, Safety Area 2
    --(44, '590R01', true, 2),      -- Sequence 53, Safety Area 2
    --(5, 'TT527', true, 1),      -- Sequence 54, Safety Area 2
    --(18, 'Plate Push', true, 1),      -- Sequence 55, Safety Area 2
    --(11, '560R01', true, 1),       -- Sequence 56, Safety Area 2 (no comma on last line!)
    --(22, '575R01', true, 1) 
    -- Add more sequences as needed:
    -- (57, 'Operator 8', true, 2),
    -- (58, 'Operator 9', true, 2),
    -- (59, 'Operator 10', true, 2)
    
    -- ========================================================================
    
-- ON CONFLICT: If sequence already exists, do nothing (prevents duplicate errors)
ON CONFLICT (sequence_id) DO NOTHING;

-- Count how many sequences were added
SELECT COUNT(*) AS "Sequences Added" 
FROM sequences 
WHERE sequence_id IN (30, 44, 5, 18, 11, 22);  -- Update this list to match your sequence IDs


-- ============================================================================
-- VERIFY SEQUENCES
-- ============================================================================
-- Display all active sequences to verify they were added correctly

SELECT 
    sequence_id AS "Sequence ID",
    sequence_name AS "Sequence Name",
    CASE WHEN is_active THEN 'Yes' ELSE 'No' END AS "Active",
    safety_area_id AS "Safety Area",
    created_at AS "Added On"
FROM sequences
ORDER BY sequence_id;


-- ============================================================================
-- OPTIONAL: UPDATE EXISTING SEQUENCES
-- ============================================================================
-- If you need to rename or deactivate existing sequences, uncomment these:

-- Rename a sequence
-- UPDATE sequences 
-- SET sequence_name = 'New Name Here' 
-- WHERE sequence_id = 50;

-- Deactivate a sequence (stops data collection without deleting historical data)
-- UPDATE sequences 
-- SET is_active = false 
-- WHERE sequence_id = 50;

-- Reactivate a sequence
-- UPDATE sequences 
-- SET is_active = true 
-- WHERE sequence_id = 50;


-- ============================================================================
-- OPTIONAL: DELETE SEQUENCES
-- ============================================================================
-- WARNING: This deletes the sequence AND all its historical data!
-- Only use if you really need to remove a sequence permanently.

-- Delete a sequence (CAUTION: deletes all historical data!)
-- DELETE FROM sequences WHERE sequence_id = 99;


-- Commit transaction (make changes permanent)
COMMIT;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
SELECT 'Sequences added successfully!' AS "Status";
SELECT 'Next steps:' AS "Info";
SELECT '1. Update config/opcua_nodes_oee.json with new sequence IDs' AS "Step 1";
SELECT '2. Restart data collector: python data_collector_oee.py' AS "Step 2";
SELECT '3. Check Grafana dashboards to see new sequences' AS "Step 3";


-- ============================================================================
-- QUICK REFERENCE: COMMON OPERATIONS
-- ============================================================================
-- View all sequences:
--   SELECT * FROM sequences ORDER BY sequence_id;
--
-- View only active sequences:
--   SELECT * FROM sequences WHERE is_active = true ORDER BY sequence_id;
--
-- Count sequences per safety area:
--   SELECT safety_area_id, COUNT(*) FROM sequences GROUP BY safety_area_id;
--
-- View latest data for a specific sequence:
--   SELECT * FROM cycle_times WHERE sequence_id = 52 ORDER BY time DESC LIMIT 10;
-- ============================================================================
