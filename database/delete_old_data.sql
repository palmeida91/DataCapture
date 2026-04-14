-- clean_sequences.sql
-- Run after cloning laptop to clear all sequence data before reconfiguring

-- Delete child data first (references sequence_id)
DELETE FROM cycle_times WHERE sequence_id BETWEEN 1 AND 64;
DELETE FROM technical_availability WHERE sequence_id BETWEEN 1 AND 64;

-- Delete all sequences
DELETE FROM sequences WHERE sequence_id BETWEEN 1 AND 64;

-- Also clear connection events and actual breaks (stale cloned data)
TRUNCATE connection_events;
TRUNCATE actual_breaks;