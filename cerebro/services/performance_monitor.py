import logging
# cerebro/services/performance_monitor.py

import os
import sys
import time
import threading
import psutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import deque
import platform
import warnings
logger = logging.getLogger(__name__)

try:
    import GPUtil
    HAS_GPU = True
except ImportError:
    HAS_GPU = False
    warnings.warn("GPUtil not installed, GPU monitoring disabled")


@dataclass
class SystemMetrics:
    """Collection of system performance metrics."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_read_mb: float
    disk_write_mb: float
    network_sent_mb: float
    network_recv_mb: float
    process_count: int
    thread_count: int
    gpu_percent: Optional[float] = None
    gpu_memory_percent: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_used_mb': self.memory_used_mb,
            'memory_total_mb': self.memory_total_mb,
            'disk_read_mb': self.disk_read_mb,
            'disk_write_mb': self.disk_write_mb,
            'network_sent_mb': self.network_sent_mb,
            'network_recv_mb': self.network_recv_mb,
            'process_count': self.process_count,
            'thread_count': self.thread_count,
            'gpu_percent': self.gpu_percent,
            'gpu_memory_percent': self.gpu_memory_percent
        }


@dataclass
class ProcessMetrics:
    """Metrics for the current process."""
    pid: int
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    thread_count: int
    open_files: int
    io_read_mb: float
    io_write_mb: float
    create_time: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'pid': self.pid,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_mb': self.memory_mb,
            'thread_count': self.thread_count,
            'open_files': self.open_files,
            'io_read_mb': self.io_read_mb,
            'io_write_mb': self.io_write_mb,
            'create_time': self.create_time
        }


@dataclass
class PerformanceHistory:
    """Historical performance data."""
    timestamps: List[float] = field(default_factory=list)
    cpu_percent: List[float] = field(default_factory=list)
    memory_mb: List[float] = field(default_factory=list)
    disk_io: List[float] = field(default_factory=list)
    
    def add_sample(self, metrics: SystemMetrics):
        """Add a metrics sample to history."""
        self.timestamps.append(metrics.timestamp)
        self.cpu_percent.append(metrics.cpu_percent)
        self.memory_mb.append(metrics.memory_used_mb)
        self.disk_io.append(metrics.disk_read_mb + metrics.disk_write_mb)
        
        # Keep only last hour of data (assuming 1 second intervals)
        max_samples = 3600
        if len(self.timestamps) > max_samples:
            self.timestamps = self.timestamps[-max_samples:]
            self.cpu_percent = self.cpu_percent[-max_samples:]
            self.memory_mb = self.memory_mb[-max_samples:]
            self.disk_io = self.disk_io[-max_samples:]
            
    def get_averages(self, window_minutes: int = 5) -> Dict[str, float]:
        """
        Get average metrics over specified window.
        
        Args:
            window_minutes: Time window in minutes
            
        Returns:
            Dictionary of average values
        """
        window_seconds = window_minutes * 60
        cutoff = time.time() - window_seconds
        
        # Filter samples within window
        recent_samples = [
            (t, cpu, mem, io)
            for t, cpu, mem, io in zip(
                self.timestamps, self.cpu_percent, self.memory_mb, self.disk_io
            )
            if t >= cutoff
        ]
        
        if not recent_samples:
            return {
                'avg_cpu': 0.0,
                'avg_memory_mb': 0.0,
                'avg_disk_io': 0.0,
                'sample_count': 0
            }
            
        # Calculate averages
        _, cpu_values, mem_values, io_values = zip(*recent_samples)
        
        return {
            'avg_cpu': sum(cpu_values) / len(cpu_values),
            'avg_memory_mb': sum(mem_values) / len(mem_values),
            'avg_disk_io': sum(io_values) / len(io_values),
            'sample_count': len(recent_samples)
        }


class PerformanceMonitor:
    """Monitors system and application performance."""
    
    def __init__(self, update_interval: float = 1.0):
        """
        Initialize performance monitor.
        
        Args:
            update_interval: Update interval in seconds
        """
        self.update_interval = update_interval
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Current metrics
        self.current_system_metrics: Optional[SystemMetrics] = None
        self.current_process_metrics: Optional[ProcessMetrics] = None
        
        # Historical data
        self.history = PerformanceHistory()
        
        # Disk I/O counters
        self.last_disk_read = 0.0
        self.last_disk_write = 0.0
        
        # Network counters
        self.last_net_sent = 0.0
        self.last_net_recv = 0.0
        
        # Process reference
        self.process = psutil.Process()
        
        # Lock for thread safety
        self.lock = threading.RLock()
        
        # Alerts
        self.alerts_enabled = True
        self.alert_thresholds = {
            'cpu_percent': 90.0,
            'memory_percent': 85.0,
            'disk_io_mb': 100.0,  # MB/s
            'process_memory_mb': 4096,  # 4GB
        }
        
        # Callbacks for alerts
        self.alert_callbacks: List[callable] = []
        
    def start(self):
        """Start performance monitoring."""
        if self.is_running:
            return
            
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
    def stop(self):
        """Stop performance monitoring."""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
            
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.is_running:
            try:
                self._update_metrics()
                time.sleep(self.update_interval)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
                # Log error but continue monitoring
                logger.info(f"Performance monitoring error: {e}")
                
    def _update_metrics(self):
        """Update all performance metrics."""
        with self.lock:
            # Get system-wide metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk_io = psutil.disk_io_counters()
            net_io = psutil.net_io_counters()
            
            # Calculate disk I/O rates
            if disk_io:
                disk_read_mb = (disk_io.read_bytes - self.last_disk_read) / (1024 * 1024)
                disk_write_mb = (disk_io.write_bytes - self.last_disk_write) / (1024 * 1024)
                self.last_disk_read = disk_io.read_bytes
                self.last_disk_write = disk_io.write_bytes
            else:
                disk_read_mb = 0.0
                disk_write_mb = 0.0
                
            # Calculate network rates
            net_sent_mb = (net_io.bytes_sent - self.last_net_sent) / (1024 * 1024)
            net_recv_mb = (net_io.bytes_recv - self.last_net_recv) / (1024 * 1024)
            self.last_net_sent = net_io.bytes_sent
            self.last_net_recv = net_io.bytes_recv
            
            # Get GPU metrics if available
            gpu_percent = None
            gpu_memory_percent = None
            
            if HAS_GPU:
                try:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu = gpus[0]  # Use first GPU
                        gpu_percent = gpu.load * 100
                        gpu_memory_percent = (gpu.memoryUsed / gpu.memoryTotal) * 100
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
                    
            # Create system metrics
            self.current_system_metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / (1024 * 1024),
                memory_total_mb=memory.total / (1024 * 1024),
                disk_read_mb=disk_read_mb,
                disk_write_mb=disk_write_mb,
                network_sent_mb=net_sent_mb,
                network_recv_mb=net_recv_mb,
                process_count=len(psutil.pids()),
                thread_count=psutil.cpu_count(logical=True),
                gpu_percent=gpu_percent,
                gpu_memory_percent=gpu_memory_percent
            )
            
            # Add to history
            self.history.add_sample(self.current_system_metrics)
            
            # Get process metrics
            try:
                process_memory = self.process.memory_info()
                process_io = self.process.io_counters()
                
                self.current_process_metrics = ProcessMetrics(
                    pid=self.process.pid,
                    cpu_percent=self.process.cpu_percent(),
                    memory_percent=self.process.memory_percent(),
                    memory_mb=process_memory.rss / (1024 * 1024),
                    thread_count=self.process.num_threads(),
                    open_files=len(self.process.open_files()),
                    io_read_mb=process_io.read_bytes / (1024 * 1024) if process_io else 0,
                    io_write_mb=process_io.write_bytes / (1024 * 1024) if process_io else 0,
                    create_time=self.process.create_time()
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process may have ended or we don't have permission
                pass
                
            # Check for alerts
            self._check_alerts()
            
    def _check_alerts(self):
        """Check if any metrics exceed alert thresholds."""
        if not self.alerts_enabled or not self.current_system_metrics:
            return
            
        alerts = []
        
        # Check CPU
        if self.current_system_metrics.cpu_percent > self.alert_thresholds['cpu_percent']:
            alerts.append(f"High CPU usage: {self.current_system_metrics.cpu_percent:.1f}%")
            
        # Check memory
        if self.current_system_metrics.memory_percent > self.alert_thresholds['memory_percent']:
            alerts.append(f"High memory usage: {self.current_system_metrics.memory_percent:.1f}%")
            
        # Check disk I/O
        total_disk_io = (self.current_system_metrics.disk_read_mb + 
                        self.current_system_metrics.disk_write_mb)
        if total_disk_io > self.alert_thresholds['disk_io_mb']:
            alerts.append(f"High disk I/O: {total_disk_io:.1f} MB/s")
            
        # Check process memory
        if self.current_process_metrics:
            if (self.current_process_metrics.memory_mb > 
                self.alert_thresholds['process_memory_mb']):
                alerts.append(f"High process memory: {self.current_process_metrics.memory_mb:.1f} MB")
                
        # Trigger callbacks for alerts
        if alerts and self.alert_callbacks:
            for callback in self.alert_callbacks:
                try:
                    callback(alerts)
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
                    
    def get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        with self.lock:
            if self.current_system_metrics:
                return self.current_system_metrics.cpu_percent
            return psutil.cpu_percent(interval=0.1)
            
    def get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        with self.lock:
            if self.current_system_metrics:
                return self.current_system_metrics.memory_used_mb
            memory = psutil.virtual_memory()
            return memory.used / (1024 * 1024)
            
    def get_disk_io(self) -> float:
        """Get current disk I/O in MB/s."""
        with self.lock:
            if self.current_system_metrics:
                return (self.current_system_metrics.disk_read_mb + 
                       self.current_system_metrics.disk_write_mb)
            return 0.0
            
    def get_network_io(self) -> Tuple[float, float]:
        """Get current network I/O in MB/s (sent, received)."""
        with self.lock:
            if self.current_system_metrics:
                return (self.current_system_metrics.network_sent_mb,
                       self.current_system_metrics.network_recv_mb)
            return (0.0, 0.0)
            
    def get_thread_count(self) -> int:
        """Get current thread count."""
        with self.lock:
            if self.current_system_metrics:
                return self.current_system_metrics.thread_count
            return psutil.cpu_count(logical=True)
            
    def get_process_metrics(self) -> Optional[ProcessMetrics]:
        """Get metrics for the current process."""
        with self.lock:
            return self.current_process_metrics
            
    def get_system_metrics(self) -> Optional[SystemMetrics]:
        """Get current system metrics."""
        with self.lock:
            return self.current_system_metrics
            
    def get_history(self) -> PerformanceHistory:
        """Get performance history."""
        with self.lock:
            return self.history
            
    def get_average_metrics(self, window_minutes: int = 5) -> Dict[str, float]:
        """
        Get average metrics over specified time window.
        
        Args:
            window_minutes: Time window in minutes
            
        Returns:
            Dictionary of average metrics
        """
        with self.lock:
            return self.history.get_averages(window_minutes)
            
    def add_alert_callback(self, callback: callable):
        """
        Add callback for performance alerts.
        
        Args:
            callback: Function that receives list of alert messages
        """
        self.alert_callbacks.append(callback)
        
    def remove_alert_callback(self, callback: callable):
        """Remove alert callback."""
        if callback in self.alert_callbacks:
            self.alert_callbacks.remove(callback)
            
    def set_alert_threshold(self, metric: str, threshold: float):
        """
        Set alert threshold for a metric.
        
        Args:
            metric: One of 'cpu_percent', 'memory_percent', 'disk_io_mb', 'process_memory_mb'
            threshold: Threshold value
        """
        if metric in self.alert_thresholds:
            self.alert_thresholds[metric] = threshold
            
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        info = {
            'platform': platform.platform(),
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'cpu_count_physical': psutil.cpu_count(logical=False),
            'cpu_count_logical': psutil.cpu_count(logical=True),
            'cpu_freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        }
        
        # Add GPU info if available
        if HAS_GPU:
            try:
                gpus = GPUtil.getGPUs()
                info['gpus'] = [{
                    'name': gpu.name,
                    'memory_total': gpu.memoryTotal,
                    'driver': gpu.driver
                } for gpu in gpus]
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                info['gpus'] = []
                
        return info
        
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive performance report.
        
        Returns:
            Dictionary with performance report
        """
        with self.lock:
            report = {
                'timestamp': datetime.now().isoformat(),
                'system_info': self.get_system_info(),
                'current_metrics': {
                    'system': self.current_system_metrics.to_dict() if self.current_system_metrics else None,
                    'process': self.current_process_metrics.to_dict() if self.current_process_metrics else None,
                },
                'averages_5min': self.history.get_averages(5),
                'averages_1hour': self.history.get_averages(60),
                'alerts': {
                    'enabled': self.alerts_enabled,
                    'thresholds': self.alert_thresholds,
                },
                'history': {
                    'samples': len(self.history.timestamps),
                    'duration_hours': (self.history.timestamps[-1] - self.history.timestamps[0]) / 3600 
                    if len(self.history.timestamps) > 1 else 0,
                }
            }
            
            return report


# Singleton instance
_performance_monitor_instance: Optional[PerformanceMonitor] = None


def get_performance_monitor(update_interval: float = 1.0) -> PerformanceMonitor:
    """
    Get or create global performance monitor instance.
    
    Args:
        update_interval: Update interval in seconds
        
    Returns:
        PerformanceMonitor instance
    """
    global _performance_monitor_instance
    
    if _performance_monitor_instance is None:
        _performance_monitor_instance = PerformanceMonitor(update_interval)
        _performance_monitor_instance.start()
        
    return _performance_monitor_instance