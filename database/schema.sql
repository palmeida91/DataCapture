-- Database Schema Updates for Complete OEE Collector
-- Run this to update your existing database

-- Make TA columns nullable (we're only collecting current hour values)
ALTER TABLE technical_availability 
ALTER COLUMN fault_time_seconds DROP NOT NULL,
ALTER COLUMN blocked_time_seconds DROP NOT NULL,
ALTER COLUMN starved_time_seconds DROP NOT NULL;

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_cycle_times_sequence_time ON cycle_times(sequence_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_ta_sequence_time ON technical_availability(sequence_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_quality_shift_hour ON quality_counters(shift_number, hour_index, time DESC);

-- Create OEE calculation view
CREATE OR REPLACE VIEW current_oee AS
WITH latest_data AS (
    -- Get most recent cycle time per sequence
    SELECT DISTINCT ON (sequence_id)
        sequence_id,
        cycle_time_seconds,
        desired_cycle_time_seconds
    FROM cycle_times
    ORDER BY sequence_id, time DESC
),
latest_ta AS (
    -- Get most recent TA per sequence
    SELECT DISTINCT ON (sequence_id)
        sequence_id,
        ta_percent
    FROM technical_availability
    ORDER BY sequence_id, time DESC
),
latest_quality AS (
    -- Get most recent quality counters
    SELECT DISTINCT ON (shift_number, hour_index)
        shift_number,
        hour_index,
        good_parts,
        reject_parts,
        rework_parts,
        time
    FROM quality_counters
    ORDER BY shift_number, hour_index, time DESC
)
SELECT 
    ct.sequence_id,
    -- Availability (from TA)
    COALESCE(ta.ta_percent, 0) as availability_percent,
    
    -- Performance (ideal cycle time / actual cycle time)
    CASE 
        WHEN ct.cycle_time_seconds > 0 THEN 
            (ct.desired_cycle_time_seconds / ct.cycle_time_seconds * 100)
        ELSE 0 
    END as performance_percent,
    
    -- Quality (good parts / total parts)
    CASE 
        WHEN (q.good_parts + q.reject_parts + q.rework_parts) > 0 THEN
            (q.good_parts::float / (q.good_parts + q.reject_parts + q.rework_parts) * 100)
        ELSE 100
    END as quality_percent,
    
    -- Overall OEE
    CASE 
        WHEN ct.cycle_time_seconds > 0 AND (q.good_parts + q.reject_parts + q.rework_parts) > 0 THEN
            (COALESCE(ta.ta_percent, 0) / 100) * 
            (ct.desired_cycle_time_seconds / ct.cycle_time_seconds) * 
            (q.good_parts::float / (q.good_parts + q.reject_parts + q.rework_parts)) * 100
        ELSE 0
    END as oee_percent,
    
    -- Raw data for reference
    ct.cycle_time_seconds,
    ct.desired_cycle_time_seconds,
    q.good_parts,
    q.reject_parts,
    q.rework_parts,
    q.shift_number,
    q.hour_index
    
FROM latest_data ct
LEFT JOIN latest_ta ta ON ct.sequence_id = ta.sequence_id
CROSS JOIN latest_quality q;

-- Create hourly OEE trend view
CREATE OR REPLACE VIEW hourly_oee_trend AS
WITH hourly_avg AS (
    SELECT 
        date_trunc('hour', time) as hour,
        sequence_id,
        AVG(cycle_time_seconds) as avg_cycle_time,
        AVG(desired_cycle_time_seconds) as avg_desired_cycle
    FROM cycle_times
    WHERE time >= NOW() - INTERVAL '7 days'
    GROUP BY date_trunc('hour', time), sequence_id
),
hourly_ta AS (
    SELECT 
        date_trunc('hour', time) as hour,
        sequence_id,
        AVG(ta_percent) as avg_ta
    FROM technical_availability
    WHERE time >= NOW() - INTERVAL '7 days'
    GROUP BY date_trunc('hour', time), sequence_id
),
hourly_quality AS (
    SELECT 
        date_trunc('hour', time) as hour,
        SUM(good_parts) as total_good,
        SUM(reject_parts) as total_reject,
        SUM(rework_parts) as total_rework
    FROM quality_counters
    WHERE time >= NOW() - INTERVAL '7 days'
    GROUP BY date_trunc('hour', time)
)
SELECT 
    ct.hour,
    ct.sequence_id,
    COALESCE(ta.avg_ta, 0) as availability_percent,
    CASE 
        WHEN ct.avg_cycle_time > 0 THEN 
            (ct.avg_desired_cycle / ct.avg_cycle_time * 100)
        ELSE 0 
    END as performance_percent,
    CASE 
        WHEN (q.total_good + q.total_reject + q.total_rework) > 0 THEN
            (q.total_good::float / (q.total_good + q.total_reject + q.total_rework) * 100)
        ELSE 100
    END as quality_percent,
    CASE 
        WHEN ct.avg_cycle_time > 0 AND (q.total_good + q.total_reject + q.total_rework) > 0 THEN
            (COALESCE(ta.avg_ta, 0) / 100) * 
            (ct.avg_desired_cycle / ct.avg_cycle_time) * 
            (q.total_good::float / (q.total_good + q.total_reject + q.total_rework)) * 100
        ELSE 0
    END as oee_percent
FROM hourly_avg ct
LEFT JOIN hourly_ta ta ON ct.hour = ta.hour AND ct.sequence_id = ta.sequence_id
LEFT JOIN hourly_quality q ON ct.hour = q.hour
ORDER BY ct.hour DESC, ct.sequence_id;

-- Create view for current status per sequence
CREATE OR REPLACE VIEW current_sequence_status AS
SELECT 
    s.sequence_id,
    CASE 
        WHEN s.sequence_id = 50 THEN 'Operator 1'
        WHEN s.sequence_id = 51 THEN 'Operator 2'
        ELSE 'Sequence ' || s.sequence_id
    END as sequence_name,
    ROUND(ta.ta_percent::numeric, 1) as ta_percent,
    ROUND(ct.cycle_time_seconds::numeric, 1) as last_cycle_time,
    ROUND(ct.desired_cycle_time_seconds::numeric, 1) as desired_cycle_time,
    CASE 
        WHEN ct.cycle_time_seconds > ct.desired_cycle_time_seconds THEN 'Slow'
        WHEN ct.cycle_time_seconds < ct.desired_cycle_time_seconds THEN 'Fast'
        ELSE 'On Target'
    END as cycle_time_status,
    ROUND(ta.fault_time_seconds::numeric, 0) as fault_time_sec,
    ROUND(ta.blocked_time_seconds::numeric, 0) as blocked_time_sec,
    ROUND(ta.starved_time_seconds::numeric, 0) as starved_time_sec
FROM sequences s
LEFT JOIN LATERAL (
    SELECT * FROM cycle_times 
    WHERE sequence_id = s.sequence_id 
    ORDER BY time DESC LIMIT 1
) ct ON true
LEFT JOIN LATERAL (
    SELECT * FROM technical_availability 
    WHERE sequence_id = s.sequence_id 
    ORDER BY time DESC LIMIT 1
) ta ON true
WHERE s.is_active = true;

-- Grant permissions
GRANT SELECT ON current_oee TO collector;
GRANT SELECT ON hourly_oee_trend TO collector;
GRANT SELECT ON current_sequence_status TO collector;

-- Show results
SELECT 'Schema updated successfully!' as status;
SELECT 'OEE views created: current_oee, hourly_oee_trend, current_sequence_status' as info;
