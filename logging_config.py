"""
Centralized logging configuration for OEE Data Collector
Provides clean, fault-focused logging with single log file output
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


class CollectorFormatter(logging.Formatter):
    """Custom formatter with color support for console"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        # Add color to console output only
        if hasattr(self, 'use_color') and self.use_color:
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        
        return super().format(record)


def setup_logging(log_level=logging.INFO):
    """
    Configure logging for the data collector
    
    Strategy:
    - Single log file: ./logs/collector.log
    - Console output: INFO and above
    - File output: All levels
    - Startup: Log initial connection success
    - Runtime: Only log faults, warnings, and errors
    - No data reading logs (too verbose)
    """
    
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Log file path
    log_file = log_dir / "collector.log"
    
    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_formatter = CollectorFormatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_formatter.use_color = True
    
    # File handler - captures everything
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler - INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    root_logger.handlers.clear()
    
    # Add our handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy libraries
    logging.getLogger('asyncua').setLevel(logging.ERROR)  # Suppress connection close warnings
    logging.getLogger('asyncua.client').setLevel(logging.ERROR)
    logging.getLogger('asyncua.common').setLevel(logging.ERROR)
    logging.getLogger('asyncpg').setLevel(logging.WARNING)
    
    return root_logger


class DataCollectionLogger:
    """
    Wrapper for logging data collection events
    Provides structured logging with minimal verbosity
    """
    
    def __init__(self, logger_name='data_collector'):
        self.logger = logging.getLogger(logger_name)
        self.last_error = None
        self.error_count = 0
    
    def startup_success(self, message):
        """Log successful startup events"""
        self.logger.info(f"✓ {message}")
    
    def startup_failure(self, message):
        """Log startup failures"""
        self.logger.error(f"✗ {message}")
    
    def connection_event(self, event_type, details):
        """Log connection events (connect/disconnect/reconnect)"""
        if event_type == 'connected':
            self.logger.info(f"🔌 Connected: {details}")
        elif event_type == 'disconnected':
            self.logger.warning(f"⚠ Disconnected: {details}")
        elif event_type == 'reconnecting':
            self.logger.info(f"🔄 Reconnecting: {details}")
        elif event_type == 'reconnected':
            self.logger.info(f"✓ Reconnected: {details}")
    
    def break_event(self, event_type, break_name, details=""):
        """Log break detection events"""
        if event_type == 'started':
            self.logger.info(f"☕ Break started: {break_name} {details}")
        elif event_type == 'ended':
            self.logger.info(f"▶ Break ended: {break_name} {details}")
        elif event_type == 'compliance':
            self.logger.info(f"📊 Break compliance: {break_name} {details}")
    
    def fault(self, component, message):
        """Log faults and errors"""
        # Deduplicate identical consecutive errors
        error_key = f"{component}:{message}"
        if error_key != self.last_error:
            self.logger.error(f"⚠ [{component}] {message}")
            self.last_error = error_key
            self.error_count = 1
        else:
            self.error_count += 1
            if self.error_count % 10 == 0:  # Log every 10th duplicate
                self.logger.error(f"⚠ [{component}] {message} (x{self.error_count})")
    
    def warning(self, component, message):
        """Log warnings"""
        self.logger.warning(f"⚠ [{component}] {message}")
    
    def debug(self, message):
        """Log debug information"""
        self.logger.debug(message)
    
    def data_summary(self, cycle_count, ta_count, quality_dict=None):
        """
        Log data collection summary (minimal)
        Only called once per collection cycle, not per sequence
        """
        summary = f"📥 Collected: {cycle_count} cycles, {ta_count} TA readings"
        if quality_dict:
            summary += f", Quality: {quality_dict['good']}G/{quality_dict['reject']}R/{quality_dict['rework']}RW"
        self.logger.debug(summary)
    
    def info(self, message):
        """General info logging"""
        self.logger.info(message)


# Example usage for reference
if __name__ == "__main__":
    # Setup logging
    setup_logging(log_level=logging.INFO)
    
    # Create logger instance
    log = DataCollectionLogger()
    
    # Startup logs
    log.startup_success("OPC UA connection established")
    log.startup_success("Database connection established")
    log.startup_success("Break schedule loaded (4 breaks)")
    
    # Connection events
    log.connection_event('connected', 'opc.tcp://192.168.1.100:4840')
    log.connection_event('disconnected', 'Connection timeout')
    log.connection_event('reconnecting', 'Attempt 3/∞, backoff: 10s')
    log.connection_event('reconnected', 'Connection restored')
    
    # Break events
    log.break_event('started', 'Morning Break', '(10:00-10:10)')
    log.break_event('ended', 'Morning Break', 'on time')
    log.break_event('compliance', 'Lunch Break', 'Started 5 min late, ended on time')
    
    # Data collection (minimal)
    log.data_summary(cycle_count=24, ta_count=24, quality_dict={'good': 58, 'reject': 0, 'rework': 2})
    
    # Faults
    log.fault('OPC_UA', 'Connection lost - initiating reconnect')
    log.fault('DATABASE', 'Insert failed - retrying')
    log.warning('BREAK_DETECTOR', 'TA frozen outside scheduled break window')
