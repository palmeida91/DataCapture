"""
Production Monitoring System - Simplified Data Collector
Only collects cycle time data (proven to work)
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import logging

try:
    from asyncua import Client
    import asyncpg
except ImportError as e:
    print(f"ERROR: Missing required library: {e}")
    print("Please run: pip install asyncua asyncpg")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_collector_simple.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class SimplifiedDataCollector:
    """Simplified data collector - only cycle times"""
    
    def __init__(self, config_path: str = "config/opcua_nodes.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.client: Optional[Client] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.running = False
        
    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
    
    async def connect_opcua(self) -> bool:
        """Connect to OPC UA server"""
        url = self.config['connection']['url']
        
        try:
            logger.info(f"Connecting to OPC UA server: {url}")
            self.client = Client(url)
            
            # Set timeout
            self.client.session_timeout = 30000  # 30 seconds
            
            # Set application URI
            self.client.application_uri = "urn:ProductionMonitoring:OpcuaClient"
            
            # Set security
            security_policy = self.config['connection'].get('security_policy', None)
            security_mode = self.config['connection'].get('security_mode', None)
            
            if security_policy and security_mode:
                cert_path = self.config['connection'].get('certificate_path', 'client_cert.der')
                key_path = self.config['connection'].get('key_path', 'client_key.pem')
                
                logger.info(f"Using security: {security_policy} / {security_mode}")
                
                security_string = f"{security_policy},{security_mode},{cert_path},{key_path}"
                await self.client.set_security_string(security_string)
            
            await self.client.connect()
            logger.info("[OK] OPC UA connection established")
            
            return True
            
        except Exception as e:
            logger.error(f"[ERROR] OPC UA connection failed: {e}")
            return False
    
    async def connect_database(self) -> bool:
        """Connect to PostgreSQL database"""
        try:
            logger.info("Connecting to PostgreSQL database...")
            
            self.db_pool = await asyncpg.create_pool(
                host="localhost",
                port=5432,
                database="production",
                user="collector",
                password="secure_password_here",
                min_size=2,
                max_size=10
            )
            
            logger.info("[OK] Database connection established")
            return True
            
        except Exception as e:
            logger.error(f"[ERROR] Database connection failed: {e}")
            logger.error("   Make sure PostgreSQL container is running: docker compose ps")
            return False
    
    async def read_cycle_times(self) -> List[Dict]:
        """Read cycle time data for active sequences"""
        cycle_data = []
        active_seqs = self.config['machine']['active_sequences']
        
        logger.info(f"Reading cycle times for sequences: {active_seqs}")
        
        for seq_id in active_seqs:
            try:
                # Build node path for Last cycle time
                # Format: ns=3;s="cycleTimeScreenInterfaceDB"."Type"[50]."Last"
                node_id = f'ns=3;s="cycleTimeScreenInterfaceDB"."Type"[{seq_id}]."Last"'
                
                # Read value
                node = self.client.get_node(node_id)
                last_cycle = await node.read_value()
                
                # Also try to read Desired cycle time
                desired_node_id = f'ns=3;s="cycleTimeScreenInterfaceDB"."Type"[{seq_id}]."Desired"'
                try:
                    desired_node = self.client.get_node(desired_node_id)
                    desired_cycle = await desired_node.read_value()
                except:
                    desired_cycle = 17000  # Default 17 seconds in milliseconds
                
                # Only record if we got a valid cycle time
                if last_cycle is not None and last_cycle > 0:
                    cycle_data.append({
                        'sequence_id': seq_id,
                        'cycle_time_ms': float(last_cycle),
                        'desired_cycle_ms': float(desired_cycle),
                        'cycle_time_sec': float(last_cycle) / 1000.0,
                        'desired_cycle_sec': float(desired_cycle) / 1000.0,
                    })
                    logger.info(f"  Seq {seq_id}: {last_cycle}ms ({last_cycle/1000.0:.1f}s)")
                
            except Exception as e:
                logger.warning(f"  Could not read cycle time for sequence {seq_id}: {e}")
        
        return cycle_data
    
    async def store_cycle_times(self, cycles: List[Dict]):
        """Store cycle time data in database"""
        if not cycles:
            logger.warning("No cycle time data to store")
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.executemany("""
                    INSERT INTO cycle_times 
                    (time, sequence_id, cycle_time_seconds, desired_cycle_time_seconds, 
                     deviation_seconds, deviation_percent)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, [
                    (
                        datetime.now(), 
                        c['sequence_id'], 
                        c['cycle_time_sec'], 
                        c['desired_cycle_sec'],
                        c['cycle_time_sec'] - c['desired_cycle_sec'],
                        ((c['cycle_time_sec'] - c['desired_cycle_sec']) / c['desired_cycle_sec'] * 100) if c['desired_cycle_sec'] > 0 else 0
                    )
                    for c in cycles
                ])
                logger.info(f"[OK] Stored {len(cycles)} cycle time records to database")
        except Exception as e:
            logger.error(f"[ERROR] Database insert failed: {e}")
    
    async def collect_once(self):
        """Single data collection cycle"""
        try:
            logger.info("=" * 60)
            logger.info("Collecting data from PLC...")
            
            # Read cycle times
            cycles = await self.read_cycle_times()
            
            # Store in database
            if cycles:
                await self.store_cycle_times(cycles)
                logger.info(f"[SUCCESS] Collected {len(cycles)} cycle times")
            else:
                logger.warning("[WARNING] No data collected this cycle")
            
        except Exception as e:
            logger.error(f"[ERROR] Error during data collection: {e}")
    
    async def run(self, interval_seconds: int = 5):
        """Main data collection loop"""
        logger.info("=" * 60)
        logger.info("SIMPLIFIED DATA COLLECTOR - Cycle Times Only")
        logger.info("=" * 60)
        logger.info(f"Starting data collector (interval: {interval_seconds}s)")
        
        # Connect to OPC UA and database
        if not await self.connect_opcua():
            logger.error("Cannot start without OPC UA connection")
            return
        
        if not await self.connect_database():
            logger.error("Cannot start without database connection")
            await self.client.disconnect()
            return
        
        logger.info("")
        logger.info("Active sequences: " + str(self.config['machine']['active_sequences']))
        logger.info("Collection will start in 3 seconds...")
        logger.info("")
        await asyncio.sleep(3)
        
        self.running = True
        
        try:
            while self.running:
                await self.collect_once()
                logger.info(f"Waiting {interval_seconds} seconds until next collection...")
                logger.info("")
                await asyncio.sleep(interval_seconds)
                
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Clean shutdown"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Shutting down data collector...")
        self.running = False
        
        if self.client:
            try:
                await self.client.disconnect()
                logger.info("   OPC UA disconnected")
            except:
                pass
        
        if self.db_pool:
            try:
                await self.db_pool.close()
                logger.info("   Database disconnected")
            except:
                pass
        
        logger.info("Shutdown complete")
        logger.info("=" * 60)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Simplified Production Monitoring Data Collector")
    parser.add_argument('--config', default='config/opcua_nodes.json',
                       help='Path to configuration file')
    parser.add_argument('--interval', type=int, default=10,
                       help='Data collection interval in seconds')
    
    args = parser.parse_args()
    
    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    
    # Start data collector
    collector = SimplifiedDataCollector(args.config)
    await collector.run(interval_seconds=args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nGoodbye!")
