"""
Production Monitoring System - V2 OEE Data Collector
Version 2 Features:
- OPC UA auto-reconnection with exponential backoff
- Clean, fault-focused logging (single log file)
- Connection event tracking in database
- Parts-counter based break detection (monitors production output)
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import json
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import asyncpg
except ImportError as e:
    print(f"ERROR: Missing required library: {e}")
    print("Please run: pip install asyncpg")
    sys.exit(1)

# Import V2 components
from logging_config import setup_logging, DataCollectionLogger
from opcua_connection_manager import OPCUAConnectionManager


class PartsBreakDetector:
    """
    Detects breaks by monitoring the shift parts counter on the last station.
    When operators leave for a break, parts stop being produced.
    
    Break start: parts counter stalls for stall_threshold_seconds AND current time
                 is within a scheduled break window (with configurable buffer).
    Break end:   parts counter increases by >= 2 within stall_threshold_seconds
                 (filters out single test parts built during break).
    
    Compliance is calculated as:
    - early_start_minutes: how many minutes before scheduled start the break began
    - late_end_minutes: how many minutes after scheduled end the break ended
    """
    
    EARLY_LATE_TOLERANCE_MIN = 1  # minutes, under this = on-time
    
    def __init__(self, logger: DataCollectionLogger, config: Dict):
        self.logger = logger
        
        # Config-driven parameters
        bc = config.get('break_compliance', {})
        self.monitor_sequence_id = bc.get('monitor_sequence_id', 1)
        self.buffer_before_min = bc.get('buffer_minutes_before', 5)
        self.buffer_after_min = bc.get('buffer_minutes_after', 5)
        self.stall_threshold_sec = bc.get('stall_threshold_seconds', 60)
        self.cycle_tolerance_sec = bc.get('cycle_tolerance_seconds', 20)
        
        # Parts counter tracking
        self.prev_total_parts: Optional[int] = None
        self.last_change_time: Optional[datetime] = None
        self.parts_at_break_start: Optional[int] = None
        
        # For break end detection: track recent part increments
        # List of (timestamp, total_parts) when counter increases during break
        self.resume_readings: List[Tuple[datetime, int]] = []
        
        # State
        self.in_break: bool = False
        self.break_detected_at: Optional[datetime] = None
        self.current_scheduled_break: Optional[Dict] = None
        self.current_break_id: Optional[int] = None
        
        # Scheduled breaks loaded from DB
        self.scheduled_breaks: List[Dict] = []
    
    async def load_scheduled_breaks(self, db_pool: asyncpg.Pool):
        """Load today's break schedule from break_definitions"""
        now = datetime.now()
        # Python weekday(): 0=Monday, so +1 to match our DB (1=Monday)
        day_of_week = now.weekday() + 1
        
        # Also load tomorrow for shift 3 (crosses midnight)
        tomorrow_dow = ((now.weekday() + 1) % 7) + 1
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT
                    id,
                    day_of_week,
                    shift_number,
                    break_name,
                    start_time,
                    end_time,
                    duration_minutes
                FROM break_definitions
                WHERE day_of_week IN ($1, $2)
                ORDER BY start_time
            """, day_of_week, tomorrow_dow)
            
            self.scheduled_breaks = [dict(r) for r in rows]
        
        self.logger.info(f"Break schedule loaded: {len(self.scheduled_breaks)} breaks")
        self.logger.info(f"Break monitor sequence: {self.monitor_sequence_id}, "
                        f"stall threshold: {self.stall_threshold_sec}s, "
                        f"buffer: {self.buffer_before_min}m before / {self.buffer_after_min}m after")
    
    def _get_current_shift(self) -> int:
        """Determine current shift number (1-3)"""
        current_time = datetime.now().time()
        if dt_time(6, 0) <= current_time < dt_time(14, 0):
            return 1
        elif dt_time(14, 0) <= current_time < dt_time(22, 0):
            return 2
        else:
            return 3
    
    def _find_scheduled_break(self) -> Optional[Dict]:
        """
        Find which scheduled break we're currently near based on time.
        Uses configurable buffer before/after the scheduled window.
        Returns the break definition or None.
        """
        now = datetime.now()
        current_time = now.time()
        shift = self._get_current_shift()
        
        for brk in self.scheduled_breaks:
            if brk['shift_number'] != shift:
                continue
            # Apply configurable buffer
            start = (datetime.combine(now.date(), brk['start_time']) 
                    - timedelta(minutes=self.buffer_before_min)).time()
            end = (datetime.combine(now.date(), brk['end_time']) 
                  + timedelta(minutes=self.buffer_after_min)).time()
            
            if start <= current_time <= end:
                return brk
        
        return None
    
    def is_in_scheduled_break_time(self) -> bool:
        """
        Check if current time is within a SCHEDULED break window (no buffer).
        Used to exclude cycle time logging during scheduled breaks only.
        Returns True if within scheduled break time, False otherwise.
        """
        now = datetime.now()
        current_time = now.time()
        shift = self._get_current_shift()
        
        for brk in self.scheduled_breaks:
            if brk['shift_number'] != shift:
                continue
            # Check EXACT scheduled time window (no buffer)
            if brk['start_time'] <= current_time <= brk['end_time']:
                return True
        
        return False
    
    async def read_shift_parts_total(self, client, opcua_nodes: Dict, shift: int) -> Optional[int]:
        """
        Read total parts (good + reject + rework) from the shift cumulative counter.
        Returns total parts count or None on error.
        """
        try:
            good_node_str = opcua_nodes['quality_good_shift'].format(shift=shift)
            reject_node_str = opcua_nodes['quality_reject_shift'].format(shift=shift)
            rework_node_str = opcua_nodes['quality_rework_shift'].format(shift=shift)
            
            good_node = client.get_node(good_node_str)
            reject_node = client.get_node(reject_node_str)
            rework_node = client.get_node(rework_node_str)
            
            good = await good_node.read_value()
            reject = await reject_node.read_value()
            rework = await rework_node.read_value()
            
            total = (int(good) if good else 0) + \
                    (int(reject) if reject else 0) + \
                    (int(rework) if rework else 0)
            
            return total
            
        except Exception as e:
            self.logger.warning('BREAK_PARTS_READ', f"Shift parts read failed: {e}")
            return None
    
    def _is_stalled(self, now: datetime) -> bool:
        """Check if parts counter has been stalled for longer than threshold"""
        if self.last_change_time is None:
            return False
        elapsed = (now - self.last_change_time).total_seconds()
        return elapsed >= self.stall_threshold_sec
    
    def _check_resume(self, now: datetime, total_parts: int) -> bool:
        """
        Check if production has resumed: 2+ parts built within stall_threshold_seconds.
        Filters out single test parts during break.
        """
        if self.parts_at_break_start is None:
            return False
        
        # Track when parts increment during break
        if total_parts > (self.parts_at_break_start + (len(self.resume_readings))):
            self.resume_readings.append((now, total_parts))
        
        # Clean old readings outside the stall window
        cutoff = now - timedelta(seconds=self.stall_threshold_sec)
        self.resume_readings = [(t, p) for t, p in self.resume_readings if t >= cutoff]
        
        # Need 2+ part increments within the window
        if len(self.resume_readings) >= 2:
            return True
        
        return False
    
    async def process(self, client, opcua_nodes: Dict, db_pool: asyncpg.Pool):
        """
        Main break detection logic - called every collection cycle.
        State machine: PRODUCING → IN_BREAK → PRODUCING
        """
        shift = self._get_current_shift()
        total_parts = await self.read_shift_parts_total(client, opcua_nodes, shift)
        
        if total_parts is None:
            return  # Read failed, skip this cycle
        
        now = datetime.now()
        
        # Update change tracking
        if self.prev_total_parts is None:
            # First reading
            self.prev_total_parts = total_parts
            self.last_change_time = now
            return
        
        if total_parts != self.prev_total_parts:
            # Parts counter changed
            if not self.in_break:
                self.last_change_time = now
            self.prev_total_parts = total_parts
        
        # --- State machine ---
        if not self.in_break:
            # Check for break start: stalled + near scheduled break
            if self._is_stalled(now):
                scheduled = self._find_scheduled_break()
                if scheduled:
                    self.in_break = True
                    self.break_detected_at = now
                    self.current_scheduled_break = scheduled
                    self.parts_at_break_start = total_parts
                    self.resume_readings = []
                    
                    self.current_break_id = await self._insert_break_start(
                        db_pool, scheduled, now
                    )
                    
                    start_time = scheduled['start_time'].strftime('%H:%M')
                    end_time = scheduled['end_time'].strftime('%H:%M')
                    self.logger.break_event('started', scheduled['break_name'],
                                           f"({start_time}-{end_time}) parts={total_parts}")
        else:
            # Check for break end: 2+ parts within stall threshold
            if self._check_resume(now, total_parts):
                if self.current_break_id:
                    compliance = await self._update_break_end(
                        db_pool, self.current_break_id,
                        self.current_scheduled_break, now
                    )
                    self.logger.break_event('ended', 
                                           self.current_scheduled_break['break_name'],
                                           f"{compliance}, parts={total_parts}")
                
                # Reset state
                self.in_break = False
                self.break_detected_at = None
                self.current_scheduled_break = None
                self.current_break_id = None
                self.parts_at_break_start = None
                self.resume_readings = []
                self.last_change_time = now
    
    async def _insert_break_start(self, db_pool: asyncpg.Pool, scheduled: Dict, 
                                   actual_start: datetime) -> int:
        """Insert actual_breaks row with start_time. Returns the new row id."""
        if actual_start.tzinfo is not None:
            actual_start = actual_start.replace(tzinfo=None)
        
        scheduled_start = datetime.combine(actual_start.date(), scheduled['start_time'])
        
        # Calculate early_start: how many minutes before scheduled did it actually start
        diff_seconds = (scheduled_start - actual_start).total_seconds()
        early_minutes = max(0, int(diff_seconds // 60))
        if early_minutes < self.EARLY_LATE_TOLERANCE_MIN:
            early_minutes = 0
        
        async with db_pool.acquire() as conn:
            row_id = await conn.fetchval("""
                INSERT INTO actual_breaks 
                (start_time, shift_number, is_scheduled, scheduled_break_id, early_start_minutes)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, actual_start, scheduled['shift_number'], True, scheduled['id'], early_minutes)
        
        return row_id
    
    async def _update_break_end(self, db_pool: asyncpg.Pool, break_id: int, 
                                 scheduled: Dict, actual_end: datetime) -> str:
        """
        Update actual_breaks row with end_time, duration, and late_end_minutes.
        Returns compliance string for logging.
        """
        if actual_end.tzinfo is not None:
            actual_end = actual_end.replace(tzinfo=None)
        
        scheduled_end = datetime.combine(actual_end.date(), scheduled['end_time'])
        
        # Calculate late_end: how many minutes after scheduled did it actually end
        diff_seconds = (actual_end - scheduled_end).total_seconds()
        late_minutes = max(0, int(diff_seconds // 60))
        if late_minutes < self.EARLY_LATE_TOLERANCE_MIN:
            late_minutes = 0
        
        async with db_pool.acquire() as conn:
            start_time = await conn.fetchval("""
                SELECT start_time FROM actual_breaks WHERE id = $1
            """, break_id)
            
            if start_time.tzinfo is not None:
                start_time = start_time.replace(tzinfo=None)
            
            duration = int((actual_end - start_time).total_seconds() // 60)
            
            await conn.execute("""
                UPDATE actual_breaks 
                SET end_time = $1, 
                    duration_minutes = $2,
                    late_end_minutes = $3
                WHERE id = $4
            """, actual_end, duration, late_minutes, break_id)
        
        # Build compliance string
        if late_minutes >= self.EARLY_LATE_TOLERANCE_MIN:
            return f"late return by {late_minutes} min"
        else:
            return "on time"


class OEEDataCollector:
    """Complete OEE data collector with cycle times, TA, quality counters and break detection"""
    
    def __init__(self, config_path: str = "config/collector_config.json"):
        # Setup logging
        setup_logging()
        self.logger = DataCollectionLogger('oee_collector')
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.connection_manager: Optional[OPCUAConnectionManager] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.running = False
        self.break_detector = PartsBreakDetector(self.logger, self.config)
        
    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.startup_failure(f"Configuration file not found: {self.config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.startup_failure(f"Invalid JSON in configuration: {e}")
            sys.exit(1)
    
    async def _on_opcua_connected(self):
        """Callback when OPC UA connection is established"""
        self.logger.debug("OPC UA connected callback triggered")
    
    async def _on_opcua_disconnected(self):
        """Callback when OPC UA connection is lost"""
        self.logger.debug("OPC UA disconnected callback triggered")
    
    async def connect_database(self) -> bool:
        """Connect to PostgreSQL database"""
        try:
            self.logger.info("Connecting to database...")
            
            db_config = self.config['database']
            
            self.db_pool = await asyncpg.create_pool(
                host=db_config['host'],
                port=db_config['port'],
                database=db_config['database'],
                user=db_config['user'],
                password=db_config['password'],
                min_size=db_config.get('min_pool_size', 2),
                max_size=db_config.get('max_pool_size', 10)
            )
            
            self.logger.startup_success("Database connection established")
            return True
            
        except Exception as e:
            self.logger.startup_failure(f"Database connection failed: {e}")
            return False
    
    def _get_current_shift_and_hour(self) -> Tuple[int, int]:
        """
        Determine current shift (1-3) and hour within shift (0-7)
        Returns: (shift_number, hour_index)
        """
        now = datetime.now()
        current_time = now.time()
        
        # Define shift times (24-hour format)
        #Monday to Thursday:
        # Shift 1: 06:00-14:00 (hours 0-7)
        # Shift 2: 14:00-22:00 (hours 0-7)
        # Shift 3: 22:00-06:00 (hours 0-7)
        #Friday:
        # Shift 1: 06:00-13:30 (hours 0-7)
        # Shift 2: 13:30-21:00 (hours 0-7)
        # Shift 3: 21:00-04:30 (hours 0-7)

        #Get current weekday (1=Monday, 7=Sunday)
        weekday = now.isoweekday()
        if weekday == 5:  # Friday
            shift_1_start = dt_time(6, 0)
            shift_2_start = dt_time(13, 30)
            shift_3_start = dt_time(21, 0)
        else:  # Monday to Thursday
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
        opcua_nodes = self.config['opcua_nodes']
        client = self.connection_manager.get_client()
        
        if not client:
            self.logger.fault('OPC_UA', 'No active client connection')
            return []
        
        for seq_id in active_seqs:
            try:
                seq_padded = f"{seq_id:02d}"
                
                # Last cycle time from TA database
                node_id_str = opcua_nodes['cycle_time_last'].format(
                    seq=seq_id, seq_padded=seq_padded
                )
                node_id = client.get_node(node_id_str)
                last_cycle = await node_id.read_value()
                
                # Desired cycle time from TA database
                desired_node_str = opcua_nodes['cycle_time_desired'].format(
                    seq=seq_id, seq_padded=seq_padded
                )
                try:
                    desired_node = client.get_node(desired_node_str)
                    desired_cycle = await desired_node.read_value()
                    if not desired_cycle or desired_cycle == 0:
                        desired_cycle = self.config['machine'].get('target_cycle_time_seconds', 17) * 1000
                except:
                    desired_cycle = self.config['machine'].get('target_cycle_time_seconds', 17) * 1000
                
                if last_cycle is not None and last_cycle > 0:
                    cycle_data.append({
                        'sequence_id': seq_id,
                        'cycle_time_sec': float(last_cycle) / 1000.0,
                        'desired_cycle_sec': float(desired_cycle) / 1000.0,
                    })
                
            except Exception as e:
                self.logger.warning('CYCLE_READ', f"Seq {seq_id} read failed: {e}")
        
        return cycle_data
    
    async def read_ta_data(self) -> List[Dict]:
        """Read TA data (current hour only) for active sequences"""
        ta_data = []
        active_seqs = self.config['machine']['active_sequences']
        opcua_nodes = self.config['opcua_nodes']
        client = self.connection_manager.get_client()
        shift, _ = self._get_current_shift_and_hour()

        if not client:
            self.logger.fault('OPC_UA', 'No active client connection')
            return []
        
        for seq_id in active_seqs:
            try:
                seq_padded = f"{seq_id:02d}"
                
                ta_node_str = opcua_nodes['ta_percent'].format(
                    seq=seq_id, seq_padded=seq_padded, shift=shift
                )
                blocked_node_str = opcua_nodes['blocked_time'].format(
                    seq=seq_id, seq_padded=seq_padded, shift=shift
                )
                starved_node_str = opcua_nodes['starved_time'].format(
                    seq=seq_id, seq_padded=seq_padded, shift=shift
                )
                fault_node_str = opcua_nodes['fault_time'].format(
                    seq=seq_id, seq_padded=seq_padded, shift=shift
                )
                
                ta_node = client.get_node(ta_node_str)
                blocked_node = client.get_node(blocked_node_str)
                starved_node = client.get_node(starved_node_str)
                fault_node = client.get_node(fault_node_str)
                
                ta_percent = await ta_node.read_value()
                blocked_time = await blocked_node.read_value()
                starved_time = await starved_node.read_value()
                fault_time = await fault_node.read_value()
                
                ta_data.append({
                    'sequence_id': seq_id,
                    'ta_percent': float(ta_percent) if ta_percent else 0.0,
                    'blocked_time_sec': float(blocked_time) / 1000.0 if blocked_time else 0.0,
                    'starved_time_sec': float(starved_time) / 1000.0 if starved_time else 0.0,
                    'fault_time_sec': float(fault_time) / 1000.0 if fault_time else 0.0,
                })
                
            except Exception as e:
                if 'BadNodeIdUnknown' in str(e) or 'BadAttributeIdInvalid' in str(e):
                    self.logger.debug(f"Seq {seq_id} TA not available: {e}")
                else:
                    self.logger.warning('TA_READ', f"Seq {seq_id} read failed: {e}")
        
        return ta_data
    
    async def read_quality_counters(self) -> Dict:
        """Read quality counters for current shift and hour"""
        shift, hour = self._get_current_shift_and_hour()
        client = self.connection_manager.get_client()
        opcua_nodes = self.config['opcua_nodes']

        if not client:
            self.logger.fault('OPC_UA', 'No active client connection')
            return None
        
        try:
            # Read counters for current shift and hour
            good_node = opcua_nodes['quality_good'].format(shift=shift, hour=hour)
            reject_node = opcua_nodes['quality_reject'].format(shift=shift, hour=hour)
            rework_node = opcua_nodes['quality_rework'].format(shift=shift, hour=hour)
            
            good = await client.get_node(good_node).read_value()
            reject = await client.get_node(reject_node).read_value()
            rework = await client.get_node(rework_node).read_value()
            
            return {
                'shift': shift,
                'hour': hour,
                'good': int(good) if good else 0,
                'reject': int(reject) if reject else 0,
                'rework': int(rework) if rework else 0,
            }
            
        except Exception as e:
            self.logger.fault('QUALITY_READ', f"Read failed: {e}")
            return None
    
    async def store_cycle_times(self, cycles: List[Dict]):
        """
        Store cycle time data.
        Filters out skip cycles for twin sync stations (seq 47, 48) where cycle < 10s.
        """
        if not cycles:
            return
        
        # Twin sync stations that alternate processing (skip cycles show ~5s)
        TWIN_SYNC_STATIONS = {47, 48}
        SKIP_CYCLE_THRESHOLD = 10.0
        
        # Filter cycles: exclude skip cycles for twin stations
        filtered_cycles = [c for c in cycles 
                          if not (c['sequence_id'] in TWIN_SYNC_STATIONS 
                                 and c['cycle_time_sec'] < SKIP_CYCLE_THRESHOLD)]
        
        if len(filtered_cycles) < len(cycles):
            skipped = len(cycles) - len(filtered_cycles)
            self.logger.debug(f"Filtered {skipped} passthrough cycles from twin sync stations")
        
        if not filtered_cycles:
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
                        ((c['cycle_time_sec'] - c['desired_cycle_sec']) / c['desired_cycle_sec'] * 100) 
                        if c['desired_cycle_sec'] > 0 else 0
                    )
                    for c in filtered_cycles
                ])
        except Exception as e:
            self.logger.fault('DATABASE', f"Cycle time insert failed: {e}")
    
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
            self.logger.fault('DATABASE', f"TA insert failed: {e}")
    
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
            self.logger.fault('DATABASE', f"Quality counter insert failed: {e}")
    
    async def collect_once(self):
        """Single data collection cycle"""
        try:
            # Check if we're in scheduled break time (for cycle time exclusion)
            in_scheduled_break = self.break_detector.is_in_scheduled_break_time()
            
            # Read all data
            cycles = await self.read_cycle_times()
            ta_data = await self.read_ta_data()
            counters = await self.read_quality_counters()
            
            # Store in database - SKIP cycle times during scheduled break
            if not in_scheduled_break:
                await self.store_cycle_times(cycles)
            else:
                self.logger.debug("Cycle times skipped (scheduled break)")
            
            # Always store TA and quality counters (even during breaks)
            await self.store_ta_data(ta_data)
            await self.store_quality_counters(counters)
            
            # Break detection - uses parts counter from OPC UA
            client = self.connection_manager.get_client()
            if client:
                await self.break_detector.process(
                    client, self.config['opcua_nodes'], self.db_pool
                )
            
            # Log summary (minimal)
            self.logger.data_summary(len(cycles), len(ta_data), counters)
            
        except Exception as e:
            self.logger.fault('COLLECTOR', f"Collection cycle error: {e}")
    
    async def run(self, interval_seconds: int = 10):
        """Main data collection loop"""
        self.logger.info("=" * 70)
        self.logger.info("OEE DATA COLLECTOR V2")
        self.logger.info("=" * 70)
        
        # Connect to database first
        if not await self.connect_database():
            self.logger.startup_failure("Cannot start without database connection")
            return
        
        # Create OPC UA connection manager
        url = self.config['machine']['opcua_endpoint']
        # Ensure full OPC UA URL format
        if not url.startswith('opc.tcp://'):
            url = f'opc.tcp://{url}'
        
        security_config = self.config.get('security', {})
        security_policy = security_config.get('policy')
        security_mode = security_config.get('mode')
        certificate_path = security_config.get('certificate_path', 'client_cert.der')
        key_path = security_config.get('key_path', 'client_key.pem')
        
        self.connection_manager = OPCUAConnectionManager(
            endpoint=url,
            logger=self.logger,
            db_pool=self.db_pool,
            on_connected=self._on_opcua_connected,
            on_disconnected=self._on_opcua_disconnected,
            security_policy=security_policy,
            security_mode=security_mode,
            certificate_path=certificate_path,
            key_path=key_path
        )
        
        # Start connection manager (will retry until connected)
        if security_policy and security_mode:
            self.logger.info(f"Using security: {security_policy}/{security_mode}")
        
        self.logger.info(f"Starting OPC UA connection to {url}...")
        if not await self.connection_manager.start():
            self.logger.startup_failure("Failed to start connection manager")
            await self.db_pool.close()
            return
        
        self.logger.startup_success("OPC UA connection manager started")
        
        # Load break schedule from database
        await self.break_detector.load_scheduled_breaks(self.db_pool)
        
        self.logger.info(f"Active sequences: {self.config['machine']['active_sequences']}")
        self.logger.info(f"Collection interval: {interval_seconds}s")
        self.logger.info("")
        self.logger.startup_success("System ready - starting data collection")
        self.logger.info("=" * 70)
        self.logger.info("")
        
        self.running = True
        
        try:
            while self.running:
                await self.collect_once()
                await asyncio.sleep(interval_seconds)
                
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")
        except Exception as e:
            self.logger.fault('SYSTEM', f"Fatal error: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Clean shutdown"""
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("Shutting down...")
        self.running = False
        
        # If we're mid-break when shutting down, close it out
        if self.break_detector.in_break and self.break_detector.current_break_id:
            self.logger.debug("Closing open break record on shutdown")
            try:
                await self.break_detector._update_break_end(
                    self.db_pool,
                    self.break_detector.current_break_id,
                    self.break_detector.current_scheduled_break,
                    datetime.now()
                )
            except Exception as e:
                self.logger.fault('BREAK_DETECTOR', f"Failed to close break: {e}")
        
        # Stop connection manager
        if self.connection_manager:
            await self.connection_manager.stop()
        
        # Close database
        if self.db_pool:
            try:
                await self.db_pool.close()
                self.logger.info("Database disconnected")
            except:
                pass
        
        self.logger.info("Shutdown complete")
        self.logger.info("=" * 70)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="OEE Data Collector V2")
    parser.add_argument('--config', default='config/collector_config.json',
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
        print("\nGoodbye!")
