"""
Production Monitoring System - Complete OEE Data Collector
Collects cycle times, TA data, quality counters, and calculates OEE
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import json
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
        logging.FileHandler('data_collector_oee.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class OEEDataCollector:
    """Complete OEE data collector with cycle times, TA, and quality counters"""
    
    def __init__(self, config_path: str = "config/opcua_nodes_oee.json"):
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
            self.client.session_timeout = 30000
            self.client.application_uri = "urn:ProductionMonitoring:OpcuaClient"
            
            # Set security
            security_policy = self.config['connection'].get('security_policy')
            security_mode = self.config['connection'].get('security_mode')
            
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
            return False
    
    def _get_current_shift_and_hour(self) -> Tuple[int, int]:
        """
        Determine current shift (1-3) and hour within shift (0-7)
        Returns: (shift_number, hour_index)
        """
        now = datetime.now()
        current_time = now.time()
        
        # Define shift times (24-hour format)
        # Shift 1: 06:00-14:00 (hours 0-7)
        # Shift 2: 14:00-22:00 (hours 0-7)
        # Shift 3: 22:00-06:00 (hours 0-7)
        
        shift_1_start = dt_time(6, 0)
        shift_2_start = dt_time(14, 0)
        shift_3_start = dt_time(22, 0)
        
        # Determine shift
        if shift_1_start <= current_time < shift_2_start:
            shift = 1
            # Calculate hour index (0-7)
            minutes_since_shift_start = (current_time.hour - 6) * 60 + current_time.minute
        elif shift_2_start <= current_time < shift_3_start:
            shift = 2
            minutes_since_shift_start = (current_time.hour - 14) * 60 + current_time.minute
        else:  # Shift 3 (22:00-06:00, crosses midnight)
            shift = 3
            if current_time >= shift_3_start:
                # After 22:00
                minutes_since_shift_start = (current_time.hour - 22) * 60 + current_time.minute
            else:
                # Before 06:00 (next day)
                minutes_since_shift_start = (current_time.hour + 2) * 60 + current_time.minute
        
        # Calculate hour index (0-7)
        hour_index = minutes_since_shift_start // 60
        hour_index = min(hour_index, 7)  # Cap at 7
        
        return shift, hour_index
    
    async def read_cycle_times(self) -> List[Dict]:
        """Read cycle time data for active sequences"""
        cycle_data = []
        active_seqs = self.config['machine']['active_sequences']
        
        for seq_id in active_seqs:
            try:
                # Last cycle time from TA database (excludes downtime - blocked/starved/fault)
                # This gives us the actual running cycle time, not time between parts
                node_id = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."Last"'
                last_cycle = await self.client.get_node(node_id).read_value()
                
                # Desired cycle time from TA database
                # Note: PLC has typo "Desiered" instead of "Desired"
                desired_node_id = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."Desiered"'
                try:
                    desired_cycle = await self.client.get_node(desired_node_id).read_value()
                    # If desired is 0 or None, fall back to config default
                    if not desired_cycle or desired_cycle == 0:
                        desired_cycle = self.config['machine'].get('target_cycle_time_seconds', 17) * 1000
                except:
                    desired_cycle = self.config['machine'].get('target_cycle_time_seconds', 17) * 1000  # Default 17 seconds in ms
                
                if last_cycle is not None and last_cycle > 0:
                    cycle_data.append({
                        'sequence_id': seq_id,
                        'cycle_time_sec': float(last_cycle) / 1000.0,
                        'desired_cycle_sec': float(desired_cycle) / 1000.0,
                    })
                
            except Exception as e:
                logger.warning(f"  Could not read cycle time for seq {seq_id}: {e}")
        
        return cycle_data
    
    async def read_ta_data(self) -> List[Dict]:
        """Read TA data (current hour only) for active sequences"""
        ta_data = []
        active_seqs = self.config['machine']['active_sequences']
        
        for seq_id in active_seqs:
            try:
                # Read current hour values (index 0)
                ta_node = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."TA"[0]'
                blocked_node = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."blockedTime"[0]'
                starved_node = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."starvedTime"[0]'
                fault_node = f'ns=3;s="cycleTimeScreenInterfaceTADB"."Type"[{seq_id}]."FaultTime"[0]'
                
                ta_percent = await self.client.get_node(ta_node).read_value()
                blocked_time = await self.client.get_node(blocked_node).read_value()
                starved_time = await self.client.get_node(starved_node).read_value()
                fault_time = await self.client.get_node(fault_node).read_value()
                
                ta_data.append({
                    'sequence_id': seq_id,
                    'ta_percent': float(ta_percent) if ta_percent else 0.0,
                    'blocked_time_sec': float(blocked_time) / 1000.0 if blocked_time else 0.0,
                    'starved_time_sec': float(starved_time) / 1000.0 if starved_time else 0.0,
                    'fault_time_sec': float(fault_time) / 1000.0 if fault_time else 0.0,
                })
                
            except Exception as e:
                logger.warning(f"  Could not read TA for seq {seq_id}: {e}")
        
        return ta_data
    
    async def read_quality_counters(self) -> Dict:
        """Read quality counters for current shift and hour"""
        shift, hour = self._get_current_shift_and_hour()
        
        try:
            # Read counters for current shift and hour
            # Type 1 = Good, 2 = Reject, 3 = Rework
            good_node = f'ns=3;s="Counter_Interface"."shifts"[{shift}]."types"[1]."data"[{hour}]'
            reject_node = f'ns=3;s="Counter_Interface"."shifts"[{shift}]."types"[2]."data"[{hour}]'
            rework_node = f'ns=3;s="Counter_Interface"."shifts"[{shift}]."types"[3]."data"[{hour}]'
            
            good = await self.client.get_node(good_node).read_value()
            reject = await self.client.get_node(reject_node).read_value()
            rework = await self.client.get_node(rework_node).read_value()
            
            return {
                'shift': shift,
                'hour': hour,
                'good': int(good) if good else 0,
                'reject': int(reject) if reject else 0,
                'rework': int(rework) if rework else 0,
            }
            
        except Exception as e:
            logger.error(f"  Could not read quality counters: {e}")
            return None
    
    async def store_cycle_times(self, cycles: List[Dict]):
        """Store cycle time data"""
        if not cycles:
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
        except Exception as e:
            logger.error(f"[ERROR] Cycle time insert failed: {e}")
    
    async def store_ta_data(self, ta_data: List[Dict]):
        """Store TA data"""
        if not ta_data:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.executemany("""
                    INSERT INTO technical_availability 
                    (time, sequence_id, ta_percent, fault_time_seconds, 
                     blocked_time_seconds, starved_time_seconds)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, [
                    (
                        datetime.now(),
                        ta['sequence_id'],
                        ta['ta_percent'],
                        ta['fault_time_sec'],
                        ta['blocked_time_sec'],
                        ta['starved_time_sec']
                    )
                    for ta in ta_data
                ])
        except Exception as e:
            logger.error(f"[ERROR] TA insert failed: {e}")
    
    async def store_quality_counters(self, counters: Dict):
        """Store quality counter data"""
        if not counters:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO quality_counters 
                    (time, shift_number, hour_index, good_parts, reject_parts, rework_parts)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (time, shift_number, hour_index) 
                    DO UPDATE SET 
                        good_parts = EXCLUDED.good_parts,
                        reject_parts = EXCLUDED.reject_parts,
                        rework_parts = EXCLUDED.rework_parts
                """, datetime.now(), counters['shift'], counters['hour'],
                    counters['good'], counters['reject'], counters['rework'])
        except Exception as e:
            logger.error(f"[ERROR] Quality counter insert failed: {e}")
    
    async def collect_once(self):
        """Single data collection cycle"""
        try:
            shift, hour = self._get_current_shift_and_hour()
            
            logger.info("=" * 70)
            logger.info(f"Collecting data from PLC (Shift {shift}, Hour {hour})...")
            
            # Read all data
            cycles = await self.read_cycle_times()
            ta_data = await self.read_ta_data()
            counters = await self.read_quality_counters()
            
            # Log what we collected
            logger.info(f"[DATA] Cycle Times: {len(cycles)} sequences")
            for c in cycles:
                logger.info(f"  Seq {c['sequence_id']}: {c['cycle_time_sec']:.1f}s (target: {c['desired_cycle_sec']:.1f}s)")
            
            logger.info(f"[DATA] TA Data: {len(ta_data)} sequences")
            for ta in ta_data:
                logger.info(f"  Seq {ta['sequence_id']}: TA={ta['ta_percent']:.1f}%, Fault={ta['fault_time_sec']:.0f}s, Blocked={ta['blocked_time_sec']:.0f}s, Starved={ta['starved_time_sec']:.0f}s")
            
            if counters:
                logger.info(f"[DATA] Quality Counters (Shift {counters['shift']}, Hour {counters['hour']})")
                logger.info(f"  Good: {counters['good']}, Reject: {counters['reject']}, Rework: {counters['rework']}")
            
            # Store in database
            await self.store_cycle_times(cycles)
            await self.store_ta_data(ta_data)
            await self.store_quality_counters(counters)
            
            logger.info(f"[OK] Data stored successfully")
            
        except Exception as e:
            logger.error(f"[ERROR] Error during data collection: {e}")
    
    async def run(self, interval_seconds: int = 10):
        """Main data collection loop"""
        logger.info("=" * 70)
        logger.info("COMPLETE OEE DATA COLLECTOR")
        logger.info("=" * 70)
        logger.info(f"Starting data collector (interval: {interval_seconds}s)")
        
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
        logger.info("=" * 70)
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
        logger.info("=" * 70)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Complete OEE Data Collector")
    parser.add_argument('--config', default='config/opcua_nodes_oee.json',
                       help='Path to configuration file')
    parser.add_argument('--interval', type=int, default=10,
                       help='Data collection interval in seconds')
    
    args = parser.parse_args()
    
    collector = OEEDataCollector(args.config)
    await collector.run(interval_seconds=args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nGoodbye!")
