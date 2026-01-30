"""
Production Monitoring System - Data Collector
Collects data from Siemens S7-1518 PLC via OPC UA and stores in PostgreSQL
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

try:
    from asyncua import Client, ua
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
        logging.FileHandler('data_collector.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class OPCUATroubleshooter:
    """Diagnoses and provides solutions for common OPC UA connection issues"""
    
    @staticmethod
    async def diagnose_connection(url: str, namespace: int, plc_name: str) -> Dict:
        """
        Comprehensive OPC UA connection troubleshooting
        Returns dict with status and detailed diagnostic information
        """
        results = {
            "success": False,
            "url": url,
            "issues": [],
            "suggestions": [],
            "details": {}
        }
        
        logger.info(f"[DIAG] Starting OPC UA connection diagnostics for {url}")
        
        # Test 1: Network connectivity
        try:
            import socket
            host = url.split("//")[1].split(":")[0]
            port = int(url.split(":")[-1].replace("/", ""))
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                results["details"]["network"] = "[OK] Network reachable"
                logger.info(f"[OK] Network connectivity OK: {host}:{port}")
            else:
                results["details"]["network"] = f"[ERROR] Cannot reach {host}:{port}"
                results["issues"].append(f"Network connection failed to {host}:{port}")
                results["suggestions"].append(
                    f"• Check if PLC IP address is correct: {host}\n"
                    f"• Verify PLC is powered on and connected to network\n"
                    f"• Ping the PLC: ping {host}\n"
                    f"• Check firewall settings on Beckhoff IPC\n"
                    f"• Verify network cable connections"
                )
                return results
        except Exception as e:
            results["details"]["network"] = f"[ERROR] Network test error: {e}"
            results["issues"].append(f"Network test failed: {e}")
            results["suggestions"].append(
                "• Verify URL format: opc.tcp://IP:PORT\n"
                "• Check network adapter settings"
            )
            return results
        
        # Test 2: OPC UA endpoint connection
        try:
            client = Client(url)
            client.session_timeout = 5000  # 5 seconds
            
            await client.connect()
            results["details"]["opcua_connect"] = "[OK] OPC UA endpoint connected"
            logger.info("[OK] OPC UA endpoint connection successful")
            
            # Test 3: Server information
            try:
                endpoints = await client.get_endpoints()
                results["details"]["endpoints"] = f"[OK] Found {len(endpoints)} endpoint(s)"
                logger.info(f"[OK] Server provides {len(endpoints)} endpoints")
                
                for i, ep in enumerate(endpoints):
                    logger.info(f"   Endpoint {i+1}: {ep.EndpointUrl}")
                    logger.info(f"   Security Mode: {ep.SecurityMode}")
                    logger.info(f"   Security Policy: {ep.SecurityPolicyUri}")
                
            except Exception as e:
                results["details"]["endpoints"] = f"[WARN] Could not enumerate endpoints: {e}"
                logger.warning(f"[WARN] Endpoint enumeration failed: {e}")
            
            # Test 4: Namespace check
            try:
                namespaces = await client.get_namespace_array()
                results["details"]["namespaces"] = f"[OK] Found {len(namespaces)} namespace(s)"
                logger.info(f"[OK] Available namespaces: {len(namespaces)}")
                
                for i, ns in enumerate(namespaces):
                    logger.info(f"   ns={i}: {ns}")
                
                if namespace >= len(namespaces):
                    results["issues"].append(f"Namespace index {namespace} does not exist")
                    results["suggestions"].append(
                        f"• Configured namespace: {namespace}\n"
                        f"• Available namespaces: 0 to {len(namespaces)-1}\n"
                        f"• Check opcua_nodes.json configuration"
                    )
                else:
                    results["details"]["namespace_check"] = f"[OK] Namespace {namespace} exists: {namespaces[namespace]}"
                    logger.info(f"[OK] Target namespace ns={namespace}: {namespaces[namespace]}")
                    
            except Exception as e:
                results["details"]["namespaces"] = f"[ERROR] Namespace check failed: {e}"
                results["issues"].append(f"Cannot read namespaces: {e}")
                results["suggestions"].append(
                    "• Server may not support namespace browsing\n"
                    "• Try different namespace index (usually 2 or 3 for Siemens)"
                )
            
            # Test 5: PLC root node access
            try:
                root = client.nodes.root
                objects = await root.get_child(["0:Objects"])
                children = await objects.get_children()
                
                results["details"]["browse_objects"] = f"[OK] Found {len(children)} objects"
                logger.info(f"[OK] Can browse Objects folder: {len(children)} children")
                
                # Look for PLC name
                plc_found = False
                for child in children:
                    browse_name = await child.read_browse_name()
                    node_name = browse_name.Name
                    logger.info(f"   Found node: {node_name}")
                    
                    if plc_name in node_name or node_name in plc_name:
                        plc_found = True
                        results["details"]["plc_node"] = f"[OK] Found PLC node: {node_name}"
                        logger.info(f"[OK] PLC node found: {node_name}")
                        
                        # Try to browse PLC structure
                        try:
                            plc_children = await child.get_children()
                            logger.info(f"   PLC has {len(plc_children)} child nodes:")
                            for plc_child in plc_children[:5]:  # Show first 5
                                child_name = await plc_child.read_browse_name()
                                logger.info(f"      - {child_name.Name}")
                        except Exception as e:
                            logger.warning(f"   Could not browse PLC children: {e}")
                        
                        break
                
                if not plc_found:
                    results["issues"].append(f"PLC node '{plc_name}' not found")
                    node_names = []
                    for child in children[:5]:
                        try:
                            bn = await child.read_browse_name()
                            node_names.append(bn.Name)
                        except:
                            pass
                    results["suggestions"].append(
                        f"• Expected PLC name: '{plc_name}'\n"
                        f"• Available nodes: {node_names}\n"
                        f"• Check 'plc_name' in config/opcua_nodes.json\n"
                        f"• Use UaExpert to verify exact node name"
                    )
                    
            except Exception as e:
                results["details"]["browse_objects"] = f"[ERROR] Cannot browse Objects: {e}"
                results["issues"].append(f"Cannot browse OPC UA nodes: {e}")
                results["suggestions"].append(
                    "• Check user permissions on PLC\n"
                    "• Verify OPC UA server is enabled in TIA Portal\n"
                    "• Check security settings (may need certificate)"
                )
            
            await client.disconnect()
            
            # If we got here, basic connection works
            if not results["issues"]:
                results["success"] = True
                results["details"]["overall"] = "[OK] All diagnostics passed!"
                logger.info("[OK] ============ DIAGNOSTICS PASSED ============")
            else:
                results["details"]["overall"] = "[WARN] Connection works but issues found"
                logger.warning("[WARN] Connection successful but configuration issues detected")
                
        except asyncio.TimeoutError:
            results["issues"].append("Connection timeout")
            results["suggestions"].append(
                "• OPC UA server may be disabled on PLC\n"
                "• Check TIA Portal: PLC properties -> OPC UA -> Server enabled\n"
                "• Verify correct port (default 4840)\n"
                "• Check if PLC firewall blocks OPC UA"
            )
            results["details"]["opcua_connect"] = "[ERROR] Connection timeout"
            logger.error("[ERROR] OPC UA connection timeout")
            
        except Exception as e:
            error_msg = str(e).lower()
            results["issues"].append(f"Connection error: {e}")
            results["details"]["opcua_connect"] = f"[ERROR] Connection failed: {e}"
            logger.error(f"[ERROR] OPC UA connection error: {e}")
            
            # Specific error suggestions
            if "certificate" in error_msg or "crypto" in error_msg or "security" in error_msg:
                results["suggestions"].append(
                    "CERTIFICATE/SECURITY ISSUE:\n"
                    "• PLC requires trusted certificate\n"
                    "• Generate certificates: python generate_certs.py\n"
                    "• Update config with security_policy and security_mode\n"
                    "• Security settings from UaExpert: Basic256Sha256 / SignAndEncrypt"
                )
            elif "refused" in error_msg:
                results["suggestions"].append(
                    "CONNECTION REFUSED:\n"
                    "• OPC UA server not enabled on PLC\n"
                    "• Wrong port number (check if 4840 is correct)\n"
                    "• Firewall blocking connection"
                )
            elif "timeout" in error_msg:
                results["suggestions"].append(
                    "TIMEOUT:\n"
                    "• PLC is not responding\n"
                    "• Network latency too high\n"
                    "• OPC UA server overloaded"
                )
            else:
                results["suggestions"].append(
                    "• Check TIA Portal OPC UA server settings\n"
                    "• Verify with UaExpert first\n"
                    "• Check Windows Firewall on Beckhoff IPC"
                )
        
        return results
    
    @staticmethod
    def print_diagnostics(results: Dict):
        """Pretty print diagnostic results"""
        print("\n" + "="*70)
        print("       OPC UA CONNECTION DIAGNOSTICS")
        print("="*70)
        
        print(f"\nTarget: {results['url']}")
        
        print("\nDiagnostic Results:")
        print("-" * 70)
        for key, value in results["details"].items():
            print(f"  {value}")
        
        if results["issues"]:
            print("\nIssues Found:")
            print("-" * 70)
            for i, issue in enumerate(results["issues"], 1):
                print(f"  {i}. {issue}")
        
        if results["suggestions"]:
            print("\nTroubleshooting Suggestions:")
            print("-" * 70)
            for suggestion in results["suggestions"]:
                print(f"\n{suggestion}")
        
        if results["success"]:
            print("\n[SUCCESS] Diagnostics completed successfully!")
        else:
            print("\n[WARN] Please address the issues above and try again.")
        
        print("\n" + "="*70 + "\n")


class ProductionDataCollector:
    """Main data collector class"""
    
    def __init__(self, config_path: str = "config/opcua_nodes.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.client: Optional[Client] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.running = False
        
        # State tracking
        self.last_quality_counters = {}
        self.line_idle_since: Optional[datetime] = None
        self.current_break: Optional[Dict] = None
        
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
    
    def _build_node_id(self, template: str, **kwargs) -> str:
        """Build OPC UA node ID from template"""
        plc_name = self.config['connection']['plc_name']
        ns = self.config['connection']['namespace']
        
        # Replace template variables
        path = template.format(**kwargs)
        
        # Build full node ID
        if plc_name:  # If PLC name exists, prepend it
            return f"ns={ns};s={plc_name}.{path}"
        else:  # If no PLC name, use path directly
            return f"ns={ns};s={path}"
    
    async def connect_opcua(self) -> bool:
        """Connect to OPC UA server with error handling"""
        url = self.config['connection']['url']
        
        try:
            logger.info(f"Connecting to OPC UA server: {url}")
            self.client = Client(url)
            
            # Set timeout
            self.client.session_timeout = 30000  # 30 seconds
            
            self.client.application_uri = "urn:ProductionMonitoring:OpcuaClient"
            
            # Set security if configured
            security_policy = self.config['connection'].get('security_policy', None)
            security_mode = self.config['connection'].get('security_mode', None)
            
            if security_policy and security_mode:
                cert_path = self.config['connection'].get('certificate_path', 'client_cert.der')
                key_path = self.config['connection'].get('key_path', 'client_key.pem')
                
                logger.info(f"Using security: {security_policy} / {security_mode}")
                logger.info(f"Certificate: {cert_path}, Key: {key_path}")
                
                # Set security string for asyncua
                security_string = f"{security_policy},{security_mode},{cert_path},{key_path}"
                await self.client.set_security_string(security_string)
            
            await self.client.connect()
            logger.info("[OK] OPC UA connection established")
            
            # Log server info
            try:
                server_info = await self.client.get_server_node()
                server_name = await server_info.read_display_name()
                logger.info(f"   Server: {server_name.Text}")
            except:
                pass
            
            return True
            
        except Exception as e:
            logger.error(f"[ERROR] OPC UA connection failed: {e}")
            logger.error("   Run with --diagnose flag for detailed troubleshooting")
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
            logger.error("   Make sure PostgreSQL container is running: docker-compose ps")
            return False
    
    def _get_current_shift(self) -> Tuple[int, bool]:
        """
        Determine current shift based on time
        Returns (shift_number, is_friday)
        """
        now = datetime.now()
        current_time = now.time()
        day_of_week = now.weekday()  # 0=Monday, 4=Friday
        
        is_friday = (day_of_week == 4)
        shifts = self.config['shifts']['friday' if is_friday else 'monday_to_thursday']
        
        for shift_num, times in shifts.items():
            start = datetime.strptime(times['start'], '%H:%M').time()
            end = datetime.strptime(times['end'], '%H:%M').time()
            
            # Handle overnight shifts
            if end < start:
                if current_time >= start or current_time < end:
                    return int(shift_num), is_friday
            else:
                if start <= current_time < end:
                    return int(shift_num), is_friday
        
        return 1, is_friday  # Default to shift 1
    
    def _categorize_state(self, state: str, state_type: str) -> str:
        """Categorize a state into productive/fault/idle/warning"""
        state_lower = state.lower()
        mappings = self.config['state_mappings'][f'{state_type}_states']
        
        for category, states in mappings.items():
            if state_lower in [s.lower() for s in states]:
                return category
        
        return 'unknown'
    
    async def read_sequence_states(self) -> List[Dict]:
        """Read current state of all sequences"""
        sequences = []
        active_seqs = self.config['machine']['active_sequences']
        
        for seq_id in active_seqs:
            try:
                # Build node path
                path_template = self.config['opcua_paths']['sequences']['state']
                node_id = self._build_node_id(
                    path_template.replace('{base}', self.config['opcua_paths']['sequences']['base']),
                    id=seq_id
                )
                
                # Read state
                node = self.client.get_node(node_id)
                state = await node.read_value()
                
                # Categorize
                category = self._categorize_state(state, 'sequence')
                
                # Get safety area
                safety_area_id = None
                for sa_id, seqs in self.config['machine']['safety_area_mapping'].items():
                    if seq_id in seqs:
                        safety_area_id = int(sa_id)
                        break
                
                sequences.append({
                    'sequence_id': seq_id,
                    'state': state,
                    'category': category,
                    'safety_area_id': safety_area_id
                })
                
            except Exception as e:
                logger.warning(f"Could not read sequence {seq_id}: {e}")
        
        return sequences
    
    async def read_cycle_times(self) -> List[Dict]:
        """Read cycle time data for all sequences"""
        cycle_data = []
        active_seqs = self.config['machine']['active_sequences']
        
        for seq_id in active_seqs:
            try:
                base_path = self.config['opcua_paths']['cycle_times']['base']
                
                # Read desired and last cycle time
                desired_node_id = self._build_node_id(
                    self.config['opcua_paths']['cycle_times']['desired'].replace('{base}', base_path),
                    seq=seq_id
                )
                last_node_id = self._build_node_id(
                    self.config['opcua_paths']['cycle_times']['last'].replace('{base}', base_path),
                    seq=seq_id
                )
                
                desired = await self.client.get_node(desired_node_id).read_value()
                last = await self.client.get_node(last_node_id).read_value()
                
                if last > 0:  # Only record completed cycles
                    cycle_data.append({
                        'sequence_id': seq_id,
                        'cycle_time': last,
                        'desired': desired,
                        'deviation': last - desired,
                        'deviation_percent': ((last - desired) / desired * 100) if desired > 0 else 0
                    })
                
            except Exception as e:
                logger.warning(f"Could not read cycle time for sequence {seq_id}: {e}")
        
        return cycle_data
    
    async def read_technical_availability(self) -> List[Dict]:
        """Read TA data for all sequences"""
        ta_data = []
        active_seqs = self.config['machine']['active_sequences']
        
        for seq_id in active_seqs:
            try:
                base_path = self.config['opcua_paths']['technical_availability']['base']
                
                # Read all TA fields
                ta_node_id = self._build_node_id(
                    self.config['opcua_paths']['technical_availability']['ta_percent'].replace('{base}', base_path),
                    seq=seq_id
                )
                fault_time_id = self._build_node_id(
                    self.config['opcua_paths']['technical_availability']['fault_time'].replace('{base}', base_path),
                    seq=seq_id
                )
                blocked_time_id = self._build_node_id(
                    self.config['opcua_paths']['technical_availability']['blocked_time'].replace('{base}', base_path),
                    seq=seq_id
                )
                starved_time_id = self._build_node_id(
                    self.config['opcua_paths']['technical_availability']['starved_time'].replace('{base}', base_path),
                    seq=seq_id
                )
                
                ta_percent = await self.client.get_node(ta_node_id).read_value()
                fault_time = await self.client.get_node(fault_time_id).read_value()
                blocked_time = await self.client.get_node(blocked_time_id).read_value()
                starved_time = await self.client.get_node(starved_time_id).read_value()
                
                ta_data.append({
                    'sequence_id': seq_id,
                    'ta_percent': ta_percent,
                    'fault_time': fault_time,
                    'blocked_time': blocked_time,
                    'starved_time': starved_time
                })
                
            except Exception as e:
                logger.warning(f"Could not read TA for sequence {seq_id}: {e}")
        
        return ta_data
    
    async def read_quality_counters(self) -> Dict:
        """Read quality counters for current shift"""
        shift_number, is_friday = self._get_current_shift()
        
        try:
            base_path = self.config['opcua_paths']['counters']['base']
            
            # Calculate which hour index (0-7) within the 8-hour shift
            now = datetime.now()
            shift_config = self.config['shifts']['friday' if is_friday else 'monday_to_thursday'][str(shift_number)]
            shift_start = datetime.strptime(shift_config['start'], '%H:%M').time()
            
            # Simplified: use current hour within shift
            hour_index = now.hour % 8
            
            # Read counters
            good_node_id = self._build_node_id(
                self.config['opcua_paths']['counters']['good'].replace('{base}', base_path),
                shift=shift_number,
                hour=hour_index
            )
            reject_node_id = self._build_node_id(
                self.config['opcua_paths']['counters']['reject'].replace('{base}', base_path),
                shift=shift_number,
                hour=hour_index
            )
            rework_node_id = self._build_node_id(
                self.config['opcua_paths']['counters']['rework'].replace('{base}', base_path),
                shift=shift_number,
                hour=hour_index
            )
            
            good = await self.client.get_node(good_node_id).read_value()
            reject = await self.client.get_node(reject_node_id).read_value()
            rework = await self.client.get_node(rework_node_id).read_value()
            
            return {
                'shift_number': shift_number,
                'hour_index': hour_index,
                'good': good,
                'reject': reject,
                'rework': rework
            }
            
        except Exception as e:
            logger.error(f"Could not read quality counters: {e}")
            return None
    
    async def store_sequence_states(self, states: List[Dict]):
        """Store sequence states in database"""
        if not states:
            return
        
        async with self.db_pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO sequence_states 
                (time, sequence_id, state, state_category, safety_area_id)
                VALUES ($1, $2, $3, $4, $5)
            """, [
                (datetime.now(), s['sequence_id'], s['state'], s['category'], s['safety_area_id'])
                for s in states
            ])
    
    async def store_cycle_times(self, cycles: List[Dict]):
        """Store cycle time data in database"""
        if not cycles:
            return
        
        async with self.db_pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO cycle_times 
                (time, sequence_id, cycle_time_seconds, desired_cycle_time_seconds, 
                 deviation_seconds, deviation_percent)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, [
                (datetime.now(), c['sequence_id'], c['cycle_time'], c['desired'],
                 c['deviation'], c['deviation_percent'])
                for c in cycles
            ])
    
    async def store_technical_availability(self, ta_data: List[Dict]):
        """Store TA data in database"""
        if not ta_data:
            return
        
        async with self.db_pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO technical_availability 
                (time, sequence_id, ta_percent, fault_time_seconds, 
                 blocked_time_seconds, starved_time_seconds)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, [
                (datetime.now(), ta['sequence_id'], ta['ta_percent'],
                 ta['fault_time'], ta['blocked_time'], ta['starved_time'])
                for ta in ta_data
            ])
    
    async def store_quality_counters(self, counters: Dict):
        """Store quality counter data in database"""
        if not counters:
            return
        
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
            """, datetime.now(), counters['shift_number'], counters['hour_index'],
                counters['good'], counters['reject'], counters['rework'])
    
    async def collect_once(self):
        """Single data collection cycle"""
        try:
            # Read all data from PLC
            logger.info("Collecting data from PLC...")
            
            sequences = await self.read_sequence_states()
            cycles = await self.read_cycle_times()
            ta_data = await self.read_technical_availability()
            counters = await self.read_quality_counters()
            
            # Store in database
            await self.store_sequence_states(sequences)
            await self.store_cycle_times(cycles)
            await self.store_technical_availability(ta_data)
            await self.store_quality_counters(counters)
            
            logger.info(f"[OK] Collected: {len(sequences)} states, {len(cycles)} cycles, "
                       f"{len(ta_data)} TA records, counters OK")
            
        except Exception as e:
            logger.error(f"Error during data collection: {e}")
    
    async def run(self, interval_seconds: int = 5):
        """Main data collection loop"""
        logger.info(f"Starting data collector (interval: {interval_seconds}s)")
        
        # Connect to OPC UA and database
        if not await self.connect_opcua():
            logger.error("Cannot start without OPC UA connection")
            return
        
        if not await self.connect_database():
            logger.error("Cannot start without database connection")
            await self.client.disconnect()
            return
        
        self.running = True
        
        try:
            while self.running:
                await self.collect_once()
                await asyncio.sleep(interval_seconds)
                
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Clean shutdown"""
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


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Production Monitoring Data Collector")
    parser.add_argument('--diagnose', action='store_true',
                       help='Run OPC UA connection diagnostics')
    parser.add_argument('--config', default='config/opcua_nodes.json',
                       help='Path to configuration file')
    parser.add_argument('--interval', type=int, default=5,
                       help='Data collection interval in seconds')
    
    args = parser.parse_args()
    
    # Load config for diagnostics
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        logger.error("   Make sure you're running from the project root directory")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Run diagnostics if requested
    if args.diagnose:
        troubleshooter = OPCUATroubleshooter()
        results = await troubleshooter.diagnose_connection(
            config['connection']['url'],
            config['connection']['namespace'],
            config['connection']['plc_name']
        )
        troubleshooter.print_diagnostics(results)
        return
    
    # Normal operation: start data collector
    collector = ProductionDataCollector(args.config)
    await collector.run(interval_seconds=args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nGoodbye!")
