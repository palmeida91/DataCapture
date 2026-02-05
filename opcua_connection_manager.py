"""
OPC UA Connection Manager with Auto-Reconnection
Handles connection lifecycle with exponential backoff retry logic
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable
from asyncua import Client
from logging_config import DataCollectionLogger


class OPCUAConnectionManager:
    """
    Manages OPC UA connection with automatic reconnection on failure
    
    Features:
    - Exponential backoff (1s → 2s → 5s → 10s → 30s → 60s max)
    - Infinite retry attempts
    - Connection monitoring task
    - Callbacks for connection state changes
    - Database event logging
    """
    
    # Exponential backoff intervals (seconds)
    BACKOFF_INTERVALS = [1, 2, 5, 10, 30, 60]
    
    # Connection check interval (seconds)
    HEALTH_CHECK_INTERVAL = 30
    
    def __init__(
        self,
        endpoint: str,
        logger: Optional[DataCollectionLogger] = None,
        db_pool = None,
        on_connected: Optional[Callable] = None,
        on_disconnected: Optional[Callable] = None,
        security_policy: Optional[str] = None,
        security_mode: Optional[str] = None,
        certificate_path: Optional[str] = None,
        key_path: Optional[str] = None
    ):
        """
        Initialize connection manager
        
        Args:
            endpoint: OPC UA server endpoint (e.g., 'opc.tcp://192.168.1.100:4840')
            logger: DataCollectionLogger instance
            db_pool: asyncpg connection pool for logging events
            on_connected: Async callback when connection established
            on_disconnected: Async callback when connection lost
            security_policy: OPC UA security policy (e.g., 'Basic256Sha256')
            security_mode: OPC UA security mode (e.g., 'SignAndEncrypt')
            certificate_path: Path to client certificate (.der file)
            key_path: Path to client private key (.pem file)
        """
        self.endpoint = endpoint
        self.logger = logger or DataCollectionLogger()
        self.db_pool = db_pool
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        
        # Security configuration
        self.security_policy = security_policy
        self.security_mode = security_mode
        self.certificate_path = certificate_path
        self.key_path = key_path
        
        self.client: Optional[Client] = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.monitor_task: Optional[asyncio.Task] = None
        self.should_run = False
        
        self.last_disconnect_time: Optional[datetime] = None
        self.last_connect_time: Optional[datetime] = None
    
    async def connect(self) -> bool:
        """
        Establish connection to OPC UA server
        Returns True if successful, False otherwise
        """
        try:
            self.client = Client(url=self.endpoint)
            self.client.session_timeout = 30000
            self.client.application_uri = "urn:ProductionMonitoring:OpcuaClient"
            
            # Apply security configuration if provided
            if self.security_policy and self.security_mode:
                cert_path = self.certificate_path or 'client_cert.der'
                key_path = self.key_path or 'client_key.pem'
                
                self.logger.debug(f"Applying security: {self.security_policy}/{self.security_mode}")
                security_string = f"{self.security_policy},{self.security_mode},{cert_path},{key_path}"
                await self.client.set_security_string(security_string)
            
            await self.client.connect()
            
            self.is_connected = True
            self.reconnect_attempts = 0
            self.last_connect_time = datetime.now()
            
            # Log to database
            await self._log_connection_event('connected', 'Initial connection established')
            
            self.logger.connection_event('connected', self.endpoint)
            
            # Call user callback
            if self.on_connected:
                await self.on_connected()
            
            return True
            
        except Exception as e:
            self.is_connected = False
            self.logger.fault('OPC_UA', f"Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Gracefully disconnect from OPC UA server"""
        if self.client:
            try:
                await self.client.disconnect()
                self.logger.connection_event('disconnected', 'Graceful shutdown')
            except:
                pass
        
        self.is_connected = False
        self.client = None
    
    async def _attempt_reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff
        Returns True if reconnection successful
        """
        # Determine backoff interval
        backoff_index = min(self.reconnect_attempts, len(self.BACKOFF_INTERVALS) - 1)
        backoff_seconds = self.BACKOFF_INTERVALS[backoff_index]
        
        self.reconnect_attempts += 1
        
        self.logger.connection_event(
            'reconnecting',
            f"Attempt {self.reconnect_attempts}/∞, backoff: {backoff_seconds}s"
        )
        
        # Wait before retry
        await asyncio.sleep(backoff_seconds)
        
        # Attempt connection
        try:
            # Clean up old client
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
            
            # Create new client and connect
            self.client = Client(url=self.endpoint)
            self.client.session_timeout = 30000
            self.client.application_uri = "urn:ProductionMonitoring:OpcuaClient"
            
            # Apply security configuration if provided
            if self.security_policy and self.security_mode:
                cert_path = self.certificate_path or 'client_cert.der'
                key_path = self.key_path or 'client_key.pem'
                
                security_string = f"{self.security_policy},{self.security_mode},{cert_path},{key_path}"
                await self.client.set_security_string(security_string)
            
            await self.client.connect()
            
            self.is_connected = True
            self.last_connect_time = datetime.now()
            
            # Calculate downtime
            downtime_seconds = None
            if self.last_disconnect_time:
                downtime = self.last_connect_time - self.last_disconnect_time
                downtime_seconds = int(downtime.total_seconds())
            
            # Log to database
            await self._log_connection_event(
                'reconnected',
                f'Reconnected after {self.reconnect_attempts} attempts, downtime: {downtime_seconds}s'
            )
            
            self.logger.connection_event(
                'reconnected',
                f"After {self.reconnect_attempts} attempts (downtime: {downtime_seconds}s)"
            )
            
            # Reset attempt counter
            self.reconnect_attempts = 0
            
            # Call user callback
            if self.on_connected:
                await self.on_connected()
            
            return True
            
        except Exception as e:
            self.is_connected = False
            self.logger.debug(f"Reconnect attempt {self.reconnect_attempts} failed: {e}")
            return False
    
    async def _monitor_connection(self):
        """
        Background task to monitor connection health
        Triggers reconnection if connection is lost
        """
        self.logger.debug("Connection monitor started")
        
        while self.should_run:
            try:
                # Wait before next check
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                
                # Skip check if already reconnecting
                if not self.is_connected:
                    continue
                
                # Test connection by reading server status
                try:
                    await self.client.get_namespace_array()
                except Exception as e:
                    # Connection lost
                    self.logger.fault('OPC_UA', f"Connection health check failed: {e}")
                    await self._handle_disconnect()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.fault('CONNECTION_MONITOR', f"Monitor error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_disconnect(self):
        """Handle disconnection event and initiate reconnection"""
        if not self.is_connected:
            return  # Already handling disconnect
        
        self.is_connected = False
        self.last_disconnect_time = datetime.now()
        
        # Log to database
        await self._log_connection_event('disconnected', 'Connection lost - initiating reconnect')
        
        self.logger.connection_event('disconnected', 'Connection lost - initiating reconnect')
        
        # Call user callback
        if self.on_disconnected:
            try:
                await self.on_disconnected()
            except Exception as e:
                self.logger.fault('CALLBACK', f"on_disconnected callback failed: {e}")
        
        # Start reconnection loop
        while self.should_run and not self.is_connected:
            success = await self._attempt_reconnect()
            if success:
                break
    
    async def _log_connection_event(self, event_type: str, details: str):
        """
        Log connection event to database
        Only logs connect/disconnect/reconnect events (not during disconnected period)
        """
        if not self.db_pool:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO connection_events 
                    (event_time, event_type, endpoint, details)
                    VALUES ($1, $2, $3, $4)
                """, datetime.now(), event_type, self.endpoint, details)
        except Exception as e:
            self.logger.warning('DATABASE', f"Failed to log connection event: {e}")
    
    async def start(self) -> bool:
        """
        Start connection manager
        Establishes initial connection and starts monitoring
        Returns True if initial connection successful
        """
        self.should_run = True
        
        # Attempt initial connection
        success = await self.connect()
        
        if success:
            # Start connection monitoring task
            self.monitor_task = asyncio.create_task(self._monitor_connection())
            return True
        else:
            # Initial connection failed, start reconnection loop
            self.logger.warning('OPC_UA', "Initial connection failed - starting reconnection loop")
            
            while self.should_run and not self.is_connected:
                success = await self._attempt_reconnect()
                if success:
                    # Start monitoring after successful reconnection
                    self.monitor_task = asyncio.create_task(self._monitor_connection())
                    return True
            
            return False
    
    async def stop(self):
        """Stop connection manager and cleanup"""
        self.should_run = False
        
        # Cancel monitor task
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect
        await self.disconnect()
        
        self.logger.debug("Connection manager stopped")
    
    def get_client(self) -> Optional[Client]:
        """Get the underlying OPC UA client (only if connected)"""
        if self.is_connected and self.client:
            return self.client
        return None
    
    @property
    def connected(self) -> bool:
        """Check if currently connected"""
        return self.is_connected


# Example usage for reference
async def example_usage():
    """Example of how to use OPCUAConnectionManager"""
    from logging_config import setup_logging, DataCollectionLogger
    
    # Setup logging
    setup_logging()
    logger = DataCollectionLogger()
    
    # Callbacks
    async def on_connected():
        logger.info("✓ Application received connection callback")
    
    async def on_disconnected():
        logger.warning("⚠ Application received disconnect callback")
    
    # Create connection manager
    manager = OPCUAConnectionManager(
        endpoint='opc.tcp://192.168.1.100:4840',
        logger=logger,
        db_pool=None,  # Would be asyncpg pool in real usage
        on_connected=on_connected,
        on_disconnected=on_disconnected
    )
    
    # Start connection
    if await manager.start():
        logger.startup_success("OPC UA connection manager started")
        
        # Use the client
        client = manager.get_client()
        if client:
            # Read something from PLC
            pass
        
        # Run for a while
        await asyncio.sleep(60)
        
        # Stop
        await manager.stop()
    else:
        logger.startup_failure("Failed to start connection manager")


if __name__ == "__main__":
    asyncio.run(example_usage())
