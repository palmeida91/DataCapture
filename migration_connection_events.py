"""
Database Migration: Add connection_events table
Tracks OPC UA connection lifecycle events (connect/disconnect/reconnect)
"""

import asyncio
import asyncpg
from datetime import datetime


async def create_connection_events_table():
    """Create connection_events table for tracking OPC UA connection health"""
    
    # Database connection parameters
    DB_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'database': 'production',
        'user': 'collector',
        'password': 'secure_password_here'
    }
    
    conn = await asyncpg.connect(**DB_CONFIG)
    
    try:
        print("Creating connection_events table...")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS connection_events (
                event_id SERIAL PRIMARY KEY,
                event_time TIMESTAMPTZ NOT NULL,
                event_type TEXT NOT NULL,  -- 'connected', 'disconnected', 'reconnected'
                endpoint TEXT NOT NULL,     -- OPC UA endpoint URL
                details TEXT,               -- Additional information (error messages, downtime, etc.)
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        print("✓ Table created successfully")
        
        # Create index for faster queries
        print("Creating index on event_time...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_connection_events_time 
            ON connection_events (event_time DESC)
        """)
        
        print("✓ Index created successfully")
        
        # Create TimescaleDB hypertable for time-series optimization
        print("Converting to TimescaleDB hypertable...")
        try:
            await conn.execute("""
                SELECT create_hypertable(
                    'connection_events', 
                    'event_time',
                    if_not_exists => TRUE
                )
            """)
            print("✓ Hypertable created successfully")
        except Exception as e:
            print(f"⚠ Hypertable creation skipped (may already exist): {e}")
        
        # Add data retention policy (keep 90 days like other tables)
        print("Adding data retention policy (90 days)...")
        try:
            await conn.execute("""
                SELECT add_retention_policy(
                    'connection_events',
                    INTERVAL '90 days',
                    if_not_exists => TRUE
                )
            """)
            print("✓ Retention policy added successfully")
        except Exception as e:
            print(f"⚠ Retention policy skipped: {e}")
        
        # Insert a test record
        print("\nInserting test record...")
        await conn.execute("""
            INSERT INTO connection_events 
            (event_time, event_type, endpoint, details)
            VALUES ($1, $2, $3, $4)
        """, datetime.now(), 'test', 'opc.tcp://test:4840', 'Migration test record')
        
        print("✓ Test record inserted")
        
        # Verify table structure
        print("\nVerifying table structure...")
        columns = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'connection_events'
            ORDER BY ordinal_position
        """)
        
        print("\nTable structure:")
        for col in columns:
            print(f"  {col['column_name']}: {col['data_type']}")
        
        print("\n" + "="*70)
        print("Migration completed successfully!")
        print("="*70)
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        raise
    
    finally:
        await conn.close()


async def verify_table():
    """Verify the connection_events table exists and is working"""
    
    DB_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'database': 'production',
        'user': 'collector',
        'password': 'secure_password_here'
    }
    
    conn = await asyncpg.connect(**DB_CONFIG)
    
    try:
        print("\nVerifying connection_events table...")
        
        # Check if table exists
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'connection_events'
            )
        """)
        
        if exists:
            print("✓ Table exists")
            
            # Count records
            count = await conn.fetchval("SELECT COUNT(*) FROM connection_events")
            print(f"✓ Table has {count} records")
            
            # Show recent events
            recent = await conn.fetch("""
                SELECT event_time, event_type, endpoint, details
                FROM connection_events
                ORDER BY event_time DESC
                LIMIT 5
            """)
            
            if recent:
                print("\nRecent connection events:")
                for event in recent:
                    print(f"  {event['event_time'].strftime('%Y-%m-%d %H:%M:%S')} | "
                          f"{event['event_type']:12} | {event['endpoint']} | {event['details']}")
            
        else:
            print("✗ Table does not exist")
        
    finally:
        await conn.close()


# Useful SQL queries for monitoring
EXAMPLE_QUERIES = """
-- Recent connection events (last 24 hours)
SELECT 
    event_time,
    event_type,
    endpoint,
    details
FROM connection_events
WHERE event_time >= NOW() - INTERVAL '24 hours'
ORDER BY event_time DESC;

-- Count disconnections by day
SELECT 
    DATE(event_time) as date,
    COUNT(*) as disconnect_count,
    AVG(EXTRACT(EPOCH FROM (
        LEAD(event_time) OVER (ORDER BY event_time) - event_time
    ))) as avg_downtime_seconds
FROM connection_events
WHERE event_type = 'disconnected'
GROUP BY DATE(event_time)
ORDER BY date DESC;

-- Current connection status (most recent event)
SELECT 
    event_time,
    event_type,
    endpoint,
    details
FROM connection_events
ORDER BY event_time DESC
LIMIT 1;

-- Connection uptime percentage (last 7 days)
WITH events AS (
    SELECT 
        event_time,
        event_type,
        LEAD(event_time) OVER (ORDER BY event_time) as next_event_time
    FROM connection_events
    WHERE event_time >= NOW() - INTERVAL '7 days'
),
downtime AS (
    SELECT 
        SUM(EXTRACT(EPOCH FROM (next_event_time - event_time))) as total_downtime_seconds
    FROM events
    WHERE event_type = 'disconnected'
)
SELECT 
    ROUND(100.0 - (total_downtime_seconds / (7 * 24 * 3600) * 100), 2) as uptime_percentage
FROM downtime;
"""


if __name__ == "__main__":
    print("="*70)
    print("Database Migration: connection_events table")
    print("="*70)
    print()
    
    # Run migration
    asyncio.run(create_connection_events_table())
    
    # Verify
    print()
    asyncio.run(verify_table())
    
    # Show example queries
    print("\n" + "="*70)
    print("Example queries for connection monitoring:")
    print("="*70)
    print(EXAMPLE_QUERIES)
