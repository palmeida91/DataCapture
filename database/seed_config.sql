-- Initial configuration data

-- Insert safety areas
INSERT INTO safety_areas (id, name, description) VALUES
(1, 'Safety Area 1', 'Main assembly area - Sequences 1-28'),
(2, 'Safety Area 2', 'Secondary assembly and inspection area - Sequences 30-61')
ON CONFLICT (id) DO NOTHING;

-- Insert shift definitions (Monday-Thursday)
INSERT INTO shift_definitions (day_of_week, shift_number, start_time, end_time) VALUES
(1, 1, '06:00', '14:00'), (1, 2, '14:00', '22:00'), (1, 3, '22:00', '06:00'),
(2, 1, '06:00', '14:00'), (2, 2, '14:00', '22:00'), (2, 3, '22:00', '06:00'),
(3, 1, '06:00', '14:00'), (3, 2, '14:00', '22:00'), (3, 3, '22:00', '06:00'),
(4, 1, '06:00', '14:00'), (4, 2, '14:00', '22:00'), (4, 3, '22:00', '06:00')
ON CONFLICT DO NOTHING;

-- Friday shifts
INSERT INTO shift_definitions (day_of_week, shift_number, start_time, end_time) VALUES
(5, 1, '06:00', '13:30'), (5, 2, '13:30', '21:00'), (5, 3, '21:00', '04:30')
ON CONFLICT DO NOTHING;

-- Insert break definitions (Monday-Thursday, Shift 1)
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time) VALUES
(1, 1, 'Morning Break', '08:00', '08:10'),
(1, 1, 'Lunch', '10:00', '10:30'),
(1, 1, 'Afternoon Break', '12:00', '12:10'),
(1, 2, 'Afternoon Break', '16:00', '16:10'),
(1, 2, 'Dinner', '18:00', '18:30'),
(1, 2, 'Evening Break', '20:00', '20:10'),
(1, 3, 'Midnight Break', '00:00', '00:10'),
(1, 3, 'Night Lunch', '02:00', '02:30'),
(1, 3, 'Early Morning Break', '04:00', '04:10')
ON CONFLICT DO NOTHING;

-- Repeat for Tuesday-Thursday (days 2-4)
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time)
SELECT 
    day_val,
    shift_number,
    break_name,
    start_time,
    end_time
FROM break_definitions
CROSS JOIN (VALUES (2), (3), (4)) AS days(day_val)
WHERE day_of_week = 1
ON CONFLICT DO NOTHING;

-- Friday breaks
INSERT INTO break_definitions (day_of_week, shift_number, break_name, start_time, end_time) VALUES
(5, 1, 'Morning Break', '08:00', '08:10'),
(5, 1, 'Lunch', '10:00', '10:30'),
(5, 1, 'Afternoon Break', '12:00', '12:10'),
(5, 2, 'Afternoon Break', '16:00', '16:10'),
(5, 2, 'Dinner', '18:00', '18:30'),
(5, 2, 'Evening Break', '19:30', '19:40'),
(5, 3, 'Late Evening Break', '23:00', '23:10'),
(5, 3, 'Night Lunch', '01:00', '01:30'),
(5, 3, 'Early Morning Break', '03:00', '03:10')
ON CONFLICT DO NOTHING;

-- Insert initial sequences (you'll update names after reading from PLC)
INSERT INTO sequences (id, name, safety_area_id, is_active, display_order) VALUES
(1, 'Sequence 1', 1, true, 1),
(2, 'Sequence 2', 1, true, 2),
(3, 'Sequence 3', 1, true, 3),
(4, 'Sequence 4', 1, true, 4),
(5, 'Sequence 5', 1, true, 5),
(6, 'Sequence 6', 1, true, 6),
(7, 'Sequence 7', 1, true, 7),
(8, 'Sequence 8', 1, true, 8),
(9, 'Sequence 9', 1, true, 9),
(10, 'Sequence 10', 1, true, 10),
(30, 'Sequence 30', 2, true, 11),
(31, 'Sequence 31', 2, true, 12),
(32, 'Sequence 32', 2, true, 13),
(33, 'Sequence 33', 2, true, 14)
ON CONFLICT (id) DO UPDATE SET
    safety_area_id = EXCLUDED.safety_area_id,
    is_active = EXCLUDED.is_active,
    display_order = EXCLUDED.display_order;

-- Add more sequences as inactive (can be activated later)
INSERT INTO sequences (id, name, safety_area_id, is_active, display_order)
SELECT 
    i,
    'Sequence ' || i,
    CASE WHEN i <= 28 THEN 1 ELSE 2 END,
    false,
    100 + i
FROM generate_series(11, 28) AS i
WHERE i NOT IN (SELECT id FROM sequences)
ON CONFLICT DO NOTHING;

INSERT INTO sequences (id, name, safety_area_id, is_active, display_order)
SELECT 
    i,
    'Sequence ' || i,
    2,
    false,
    100 + i
FROM generate_series(34, 61) AS i
WHERE i NOT IN (SELECT id FROM sequences)
ON CONFLICT DO NOTHING;
