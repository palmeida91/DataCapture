-- ============================================================================
-- Seed Break Definitions
-- ============================================================================
-- Populates the break_definitions table with the scheduled breaks.
-- Must match the break schedule in collector_config.json.
--
-- Usage:
--   psql -U collector -d production -h localhost -f database/seed_breaks.sql
--
-- Run AFTER create_database.sql
-- ============================================================================

BEGIN;

-- Clear existing break definitions (safe to re-run)
TRUNCATE break_definitions RESTART IDENTITY CASCADE;

-- ============================================================================
-- MONDAY TO THURSDAY (days 1-4) - Same schedule each day
-- ============================================================================
-- Shift 1 (06:00-14:00)
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time) VALUES
(1, 1, 'Morning Break',    '08:00', '08:10'),
(1, 1, 'Lunch',            '10:00', '10:30'),
(1, 1, 'Afternoon Break',  '12:00', '12:10'),
-- Shift 2 (14:00-22:00)
(1, 2, 'Afternoon Break',  '16:00', '16:10'),
(1, 2, 'Dinner',           '18:00', '18:30'),
(1, 2, 'Evening Break',    '20:00', '20:10'),
-- Shift 3 (22:00-06:00)
(1, 3, 'Midnight Break',       '00:00', '00:10'),
(1, 3, 'Night Lunch',          '02:00', '02:30'),
(1, 3, 'Early Morning Break',  '04:00', '04:10');

-- Copy Monday breaks to Tuesday, Wednesday, Thursday
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time)
SELECT day_val, shift_number, break_name, start_time, end_time
FROM break_definitions
CROSS JOIN (VALUES (2), (3), (4)) AS days(day_val)
WHERE day_of_week = 1;

-- ============================================================================
-- FRIDAY (day 5) - Different shift times
-- ============================================================================
-- Shift 1 (06:00-13:30)
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time) VALUES
(5, 1, 'Morning Break',    '08:00', '08:10'),
(5, 1, 'Lunch',            '10:00', '10:30'),
(5, 1, 'Afternoon Break',  '12:00', '12:10'),
-- Shift 2 (13:30-21:00)
(5, 2, 'Afternoon Break',  '16:00', '16:10'),
(5, 2, 'Dinner',           '18:00', '18:30'),
(5, 2, 'Evening Break',    '19:30', '19:40'),
-- Shift 3 (21:00-04:30)
(5, 3, 'Late Evening Break',   '23:00', '23:10'),
(5, 3, 'Night Lunch',          '01:00', '01:30'),
(5, 3, 'Early Morning Break',  '03:00', '03:10');

COMMIT;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT 
    day_of_week AS "Day",
    shift_number AS "Shift",
    break_name AS "Break",
    start_time AS "Start",
    end_time AS "End",
    duration_minutes AS "Min"
FROM break_definitions
ORDER BY day_of_week, shift_number, start_time;
