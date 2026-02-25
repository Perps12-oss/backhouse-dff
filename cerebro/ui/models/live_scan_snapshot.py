# cerebro/ui/models/live_scan_snapshot.py
"""
LiveScanSnapshot - Single source of truth for scan telemetry.

This model provides a consistent, validated view of scan progress,
aggregating signals from multiple sources and applying telemetry
validity rules before UI consumption.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple, Any
import math


class ScanPhase(Enum):
    """Defined phases of a scan operation."""
    READY = auto()
    DISCOVERING = auto()
    HASHING = auto()
    GROUPING = auto()
    FINALIZING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()
    PAUSED = auto()

    @property
    def display_name(self) -> str:
        """Human-readable phase name."""
        names = {
            ScanPhase.READY: "Ready",
            ScanPhase.DISCOVERING: "Discovering files…",
            ScanPhase.HASHING: "Hashing files…",
            ScanPhase.GROUPING: "Grouping duplicates…",
            ScanPhase.FINALIZING: "Finalizing…",
            ScanPhase.COMPLETED: "Completed",
            ScanPhase.CANCELLED: "Cancelled",
            ScanPhase.FAILED: "Failed",
            ScanPhase.PAUSED: "Paused",
        }
        return names.get(self, str(self.name).capitalize())
    
    @property
    def is_active(self) -> bool:
        """Whether this phase indicates active scanning."""
        return self in {
            ScanPhase.DISCOVERING,
            ScanPhase.HASHING,
            ScanPhase.GROUPING,
            ScanPhase.FINALIZING,
        }


@dataclass
class ThroughputMetrics:
    """Calculated speed and throughput metrics."""
    files_per_second: float = 0.0
    megabytes_per_second: float = 0.0
    eta_seconds: Optional[float] = None
    is_measuring: bool = True
    
    def format_files_per_second(self) -> str:
        """Format files/sec with appropriate precision."""
        if not self.files_per_second:
            return "—"
        if self.files_per_second < 1:
            return f"{self.files_per_second:.2f} files/s"
        elif self.files_per_second < 10:
            return f"{self.files_per_second:.1f} files/s"
        else:
            return f"{int(self.files_per_second)} files/s"
    
    def format_throughput(self) -> str:
        """Format MB/s with appropriate precision."""
        if not self.megabytes_per_second:
            return "—"
        if self.megabytes_per_second < 0.1:
            return f"{self.megabytes_per_second * 1024:.0f} KB/s"
        elif self.megabytes_per_second < 1:
            return f"{self.megabytes_per_second:.2f} MB/s"
        elif self.megabytes_per_second < 10:
            return f"{self.megabytes_per_second:.1f} MB/s"
        else:
            return f"{int(self.megabytes_per_second)} MB/s"
    
    def format_eta(self) -> str:
        """Format ETA in human-readable form."""
        if self.eta_seconds is None or self.eta_seconds <= 0:
            return "—"
        
        seconds = int(self.eta_seconds)
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"


@dataclass
class TelemetryValidity:
    """Validity flags for telemetry data."""
    has_file_counts: bool = False
    has_byte_counts: bool = False
    has_current_file: bool = False
    has_speed_measurements: bool = False
    totals_known: bool = False
    is_initial_warmup: bool = True  # First 1-2 seconds
    
    @property
    def show_skeleton_for_totals(self) -> bool:
        """Whether to show skeleton placeholders for totals."""
        return self.is_active and not self.totals_known
    
    @property
    def is_active(self) -> bool:
        """Whether any scanning activity is happening."""
        return self.has_file_counts or self.has_current_file


@dataclass
class LiveScanSnapshot:
    """
    Single source of truth for scan telemetry.
    
    All UI components should read from this snapshot only.
    Controller updates this snapshot via throttled updates.
    """
    
    # Core state
    scan_id: Optional[str] = None
    phase: ScanPhase = ScanPhase.READY
    is_active: bool = False
    is_paused: bool = False
    is_cancelling: bool = False
    
    # Progress metrics (0.0 to 1.0)
    progress_normalized: float = 0.0  # Always valid 0.0-1.0
    progress_weighted: float = 0.0    # Weighted by phase importance
    
    # File counts
    files_processed: int = 0
    files_total: Optional[int] = None
    
    # Byte counts
    bytes_processed: int = 0
    bytes_total: Optional[int] = None
    
    # Current activity
    current_file: Optional[str] = None
    current_operation: Optional[str] = None
    
    # Results
    groups_found: int = 0
    duplicates_found: int = 0
    warnings: List[str] = field(default_factory=list)
    warnings_count: int = 0
    
    # Throughput
    throughput: ThroughputMetrics = field(default_factory=ThroughputMetrics)
    
    # Timestamps for rate calculation
    _start_time: Optional[float] = None
    _last_update_time: Optional[float] = None
    _last_throughput_update: Optional[float] = None
    _last_file_count: int = 0
    _last_byte_count: int = 0
    
    # Validity
    validity: TelemetryValidity = field(default_factory=TelemetryValidity)
    
    # Internal smoothing buffers
    _file_rate_buffer: List[Tuple[float, int]] = field(default_factory=list)
    _byte_rate_buffer: List[Tuple[float, int]] = field(default_factory=list)
    _progress_buffer: List[float] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialize timestamps after dataclass creation."""
        if self.is_active and self._start_time is None:
            self._start_time = time.time()
    
    # ------------------------------------------------------------------------
    # Public API for Controller Updates
    # ------------------------------------------------------------------------
    
    def update_from_controller(
        self,
        *,
        phase: Optional[str] = None,
        progress: Optional[float] = None,
        current_file: Optional[str] = None,
        files_processed: Optional[int] = None,
        files_total: Optional[int] = None,
        bytes_processed: Optional[int] = None,
        bytes_total: Optional[int] = None,
        groups_found: Optional[int] = None,
        duplicates_found: Optional[int] = None,
        warnings: Optional[List[str]] = None,
    ) -> None:
        """
        Update snapshot from controller signals.
        Applies validity rules and smoothing.
        """
        now = time.time()
        
        # Update phase
        if phase is not None:
            self._update_phase(phase)
        
        # Update file counts with validity checks
        if files_processed is not None:
            self._update_file_counts(files_processed, files_total, now)
        
        # Update byte counts with validity checks
        if bytes_processed is not None:
            self._update_byte_counts(bytes_processed, bytes_total, now)
        
        # Update current file with sanitization
        if current_file is not None:
            self._update_current_file(current_file)
        
        # Update progress with smoothing
        if progress is not None:
            self._update_progress(progress, now)
        
        # Update groups and warnings
        if groups_found is not None:
            self.groups_found = max(0, groups_found)
        
        if duplicates_found is not None:
            self.duplicates_found = max(0, duplicates_found)
        
        if warnings is not None:
            self.warnings = warnings[:10]  # Keep last 10 warnings
            self.warnings_count = len(warnings)
        
        # Update throughput calculations
        self._update_throughput(now)
        
        # Apply telemetry validity rules
        self._apply_validity_rules(now)
        
        self._last_update_time = now

    def apply_updates(
        self,
        *,
        phase: Optional[str] = None,
        progress_percent: Optional[float] = None,
        scanned_files: Optional[int] = None,
        scanned_bytes: Optional[int] = None,
        elapsed_seconds: Optional[float] = None,
        current_file: Optional[str] = None,
        groups_found: Optional[int] = None,
        duplicates_found: Optional[int] = None,
        warnings: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Apply buffered updates from the controller (progress_percent, scanned_files, etc.)."""
        now = time.time()
        if phase is not None:
            self._update_phase(phase)
        if progress_percent is not None:
            self._update_progress(progress_percent / 100.0, now)
        if scanned_files is not None:
            self._update_file_counts(scanned_files, kwargs.get("files_total"), now)
        if scanned_bytes is not None:
            self._update_byte_counts(scanned_bytes, kwargs.get("bytes_total"), now)
        if current_file is not None:
            self._update_current_file(current_file)
        if groups_found is not None:
            self.groups_found = max(0, groups_found)
        if duplicates_found is not None:
            self.duplicates_found = max(0, duplicates_found)
        if warnings is not None:
            self.warnings = warnings[:10]
            self.warnings_count = len(warnings)
        self._update_throughput(now)
        self._apply_validity_rules(now)
        self._last_update_time = now
    
    def start_scan(self, scan_id: str) -> None:
        """Initialize snapshot for a new scan."""
        self.scan_id = scan_id
        self.phase = ScanPhase.DISCOVERING
        self.is_active = True
        self._start_time = time.time()
        self._last_update_time = self._start_time
        self.validity.is_initial_warmup = True
        
        # Reset metrics
        self.files_processed = 0
        self.files_total = None
        self.bytes_processed = 0
        self.bytes_total = None
        self.groups_found = 0
        self.duplicates_found = 0
        self.warnings.clear()
        self.warnings_count = 0
        self.progress_normalized = 0.0
        self.progress_weighted = 0.0
        
        # Reset buffers
        self._file_rate_buffer.clear()
        self._byte_rate_buffer.clear()
        self._progress_buffer.clear()
    
    def complete_scan(self) -> None:
        """Mark scan as completed."""
        self.phase = ScanPhase.COMPLETED
        self.is_active = False
        
        # Force 100% progress
        self.progress_normalized = 1.0
        self.progress_weighted = 1.0
        
        # Clear current file
        self.current_file = None
        self.current_operation = None
        
        # Stop throughput measurements
        self.throughput.is_measuring = False
    
    def cancel_scan(self) -> None:
        """Mark scan as cancelling or cancelled."""
        if self.is_cancelling:
            self.phase = ScanPhase.CANCELLED
            self.is_active = False
            self.is_cancelling = False
        else:
            self.is_cancelling = True
            self.current_operation = "Cancelling…"
    
    def pause_scan(self) -> None:
        """Pause the scan."""
        if self.is_active and not self.is_paused:
            self.is_paused = True
            self.phase = ScanPhase.PAUSED
            self.current_operation = "Paused"
    
    def resume_scan(self) -> None:
        """Resume the scan."""
        if self.is_paused:
            self.is_paused = False
            self.phase = ScanPhase.DISCOVERING  # Will be updated by controller
            self.current_operation = None
    
    # ------------------------------------------------------------------------
    # Telemetry Validity Rules
    # ------------------------------------------------------------------------
    
    def _apply_validity_rules(self, now: float) -> None:
        """Apply all telemetry validity rules."""
        # Rule 1: If active, status cannot be "Ready"
        if self.is_active and self.phase == ScanPhase.READY:
            self.phase = ScanPhase.DISCOVERING
        
        # Rule 2: If files_processed == files_total, progress must be 1.0
        if (self.files_total is not None and 
            self.files_processed >= self.files_total):
            self.progress_normalized = 1.0
        
        # Rule 3: If current_file empty, show phase instead
        if not self.current_file and self.is_active:
            self.current_file = f"{self.phase.display_name}…"
        
        # Rule 4: Handle unknown totals with placeholders
        self.validity.totals_known = (
            self.files_total is not None and 
            self.bytes_total is not None and
            self.files_total > 0
        )
        
        # Rule 5: Initial warmup period (first 2 seconds)
        if self._start_time:
            self.validity.is_initial_warmup = (now - self._start_time) < 2.0
        
        # Rule 6: Determine what data we have
        self.validity.has_file_counts = self.files_processed > 0 or self.files_total is not None
        self.validity.has_byte_counts = self.bytes_processed > 0 or self.bytes_total is not None
        self.validity.has_current_file = bool(self.current_file)
        self.validity.has_speed_measurements = len(self._file_rate_buffer) >= 2
    
    # ------------------------------------------------------------------------
    # Update Helpers with Smoothing
    # ------------------------------------------------------------------------
    
    def _update_phase(self, phase_str: str) -> None:
        """Update phase from string, with validation."""
        phase_lower = phase_str.lower().strip()
        
        phase_map = {
            "ready": ScanPhase.READY,
            "discovering": ScanPhase.DISCOVERING,
            "hashing": ScanPhase.HASHING,
            "grouping": ScanPhase.GROUPING,
            "finalizing": ScanPhase.FINALIZING,
            "completed": ScanPhase.COMPLETED,
            "cancelled": ScanPhase.CANCELLED,
            "failed": ScanPhase.FAILED,
            "paused": ScanPhase.PAUSED,
        }
        
        self.phase = phase_map.get(phase_lower, ScanPhase.DISCOVERING)
        
        # Set phase-appropriate weights for progress calculation
        if self.phase == ScanPhase.DISCOVERING:
            self.current_operation = "Finding files…"
        elif self.phase == ScanPhase.HASHING:
            self.current_operation = "Calculating hashes…"
        elif self.phase == ScanPhase.GROUPING:
            self.current_operation = "Finding duplicates…"
        elif self.phase == ScanPhase.FINALIZING:
            self.current_operation = "Finalizing results…"
    
    def _update_file_counts(
        self, 
        processed: int, 
        total: Optional[int], 
        now: float
    ) -> None:
        """Update file counts with rate calculation."""
        if processed < 0:
            processed = 0
        
        # Add to rate buffer for smoothing
        self._file_rate_buffer.append((now, processed))
        
        # Keep only last 5 seconds of data
        cutoff = now - 5.0
        self._file_rate_buffer = [
            (t, c) for t, c in self._file_rate_buffer 
            if t >= cutoff
        ]
        
        # Update counts
        self.files_processed = processed
        if total is not None and total > 0:
            self.files_total = total
            
            # Auto-calculate progress if not provided
            if self.progress_normalized == 0.0:
                self.progress_normalized = min(1.0, processed / total)
    
    def _update_byte_counts(
        self, 
        processed: int, 
        total: Optional[int], 
        now: float
    ) -> None:
        """Update byte counts with rate calculation."""
        if processed < 0:
            processed = 0
        
        # Add to rate buffer for smoothing
        self._byte_rate_buffer.append((now, processed))
        
        # Keep only last 5 seconds of data
        cutoff = now - 5.0
        self._byte_rate_buffer = [
            (t, c) for t, c in self._byte_rate_buffer 
            if t >= cutoff
        ]
        
        # Update counts
        self.bytes_processed = processed
        if total is not None and total > 0:
            self.bytes_total = total
    
    def _update_current_file(self, path: str) -> None:
        """Sanitize and update current file path."""
        if not path or path.lower() == "none":
            self.current_file = None
            return
        
        # Truncate very long paths
        if len(path) > 80:
            # Keep beginning and end
            start = path[:40]
            end = path[-35:]
            self.current_file = f"{start}...{end}"
        else:
            self.current_file = path
    
    def _update_progress(self, progress: float, now: float) -> None:
        """Update progress with smoothing."""
        if not 0 <= progress <= 1:
            progress = max(0.0, min(1.0, progress))
        
        # Add to smoothing buffer
        self._progress_buffer.append(progress)
        
        # Keep only last 10 samples
        if len(self._progress_buffer) > 10:
            self._progress_buffer.pop(0)
        
        # Apply exponential moving average
        if self._progress_buffer:
            smoothed = 0.0
            alpha = 0.3  # Smoothing factor
            for i, p in enumerate(reversed(self._progress_buffer)):
                weight = alpha * ((1 - alpha) ** i)
                smoothed += p * weight
            
            # Normalize (weights don't sum to 1 with finite samples)
            total_weight = sum(alpha * ((1 - alpha) ** i) 
                             for i in range(len(self._progress_buffer)))
            if total_weight > 0:
                smoothed /= total_weight
            
            self.progress_normalized = smoothed
        
        # Calculate weighted progress based on phase
        phase_weights = {
            ScanPhase.DISCOVERING: 0.2,
            ScanPhase.HASHING: 0.6,
            ScanPhase.GROUPING: 0.15,
            ScanPhase.FINALIZING: 0.05,
        }
        
        base_progress = self.progress_normalized
        phase_weight = phase_weights.get(self.phase, 0.5)
        
        # Simple weighted calculation
        if self.phase == ScanPhase.DISCOVERING:
            self.progress_weighted = base_progress * 0.2
        elif self.phase == ScanPhase.HASHING:
            self.progress_weighted = 0.2 + base_progress * 0.6
        elif self.phase == ScanPhase.GROUPING:
            self.progress_weighted = 0.8 + base_progress * 0.15
        elif self.phase == ScanPhase.FINALIZING:
            self.progress_weighted = 0.95 + base_progress * 0.05
        else:
            self.progress_weighted = base_progress
    
    def _update_throughput(self, now: float) -> None:
        """Calculate throughput metrics."""
        if not self._file_rate_buffer or len(self._file_rate_buffer) < 2:
            self.throughput.is_measuring = True
            return
        
        # Calculate file rate
        oldest_time, oldest_count = self._file_rate_buffer[0]
        newest_time, newest_count = self._file_rate_buffer[-1]
        
        time_diff = newest_time - oldest_time
        count_diff = newest_count - oldest_count
        
        if time_diff > 0.1:  # Need at least 100ms for measurement
            files_per_second = count_diff / time_diff
            
            # Apply smoothing (simple moving average of last 3 calculations)
            self.throughput.files_per_second = (
                self.throughput.files_per_second * 0.7 + 
                files_per_second * 0.3
            )
            
            # Calculate byte rate if available
            if self._byte_rate_buffer and len(self._byte_rate_buffer) >= 2:
                _, oldest_bytes = self._byte_rate_buffer[0]
                _, newest_bytes = self._byte_rate_buffer[-1]
                byte_diff = newest_bytes - oldest_bytes
                
                megabytes_per_second = (byte_diff / time_diff) / (1024 * 1024)
                self.throughput.megabytes_per_second = (
                    self.throughput.megabytes_per_second * 0.7 +
                    megabytes_per_second * 0.3
                )
            
            # Calculate ETA
            if (self.files_total is not None and 
                self.throughput.files_per_second > 0):
                files_remaining = self.files_total - self.files_processed
                self.throughput.eta_seconds = files_remaining / self.throughput.files_per_second
            
            self.throughput.is_measuring = False
            self._last_throughput_update = now
    
    # ------------------------------------------------------------------------
    # UI Helper Methods
    # ------------------------------------------------------------------------
    
    def format_files_processed(self) -> str:
        """Format files processed with skeleton for unknowns."""
        if not self.validity.has_file_counts:
            return "—"
        
        if self.files_total is not None:
            return f"{self.files_processed:,}/{self.files_total:,}"
        else:
            return f"{self.files_processed:,}"
    
    def format_bytes_processed(self) -> str:
        """Format bytes processed with skeleton for unknowns."""
        if not self.validity.has_byte_counts:
            return "—"
        
        if self.bytes_total is not None:
            return self._format_bytes(self.bytes_processed)
        else:
            return self._format_bytes(self.bytes_processed)
    
    def format_bytes_total(self) -> str:
        """Format total bytes with skeleton for unknowns."""
        if not self.validity.has_byte_counts or self.bytes_total is None:
            return "…"
        
        return self._format_bytes(self.bytes_total)
    
    def format_progress_percentage(self) -> str:
        """Format progress as percentage."""
        percentage = self.progress_weighted * 100
        
        # Special cases
        if self.phase == ScanPhase.COMPLETED:
            return "100%"
        elif self.phase == ScanPhase.CANCELLED:
            return "—"
        elif self.phase == ScanPhase.FAILED:
            return "—"
        
        # Show 100% if files match (even if progress says otherwise)
        if (self.files_total is not None and 
            self.files_processed >= self.files_total):
            return "100%"
        
        # Format with appropriate precision
        if percentage < 1:
            return f"{percentage:.1f}%"
        elif percentage < 10:
            return f"{percentage:.1f}%"
        else:
            return f"{int(percentage)}%"
    
    def format_current_file_display(self) -> str:
        """Format current file for display."""
        if self.current_file:
            # Clean up path for display
            return self.current_file.replace('\\', '/')
        elif self.is_active:
            return f"{self.phase.display_name}…"
        else:
            return "Ready"
    
    def format_phase_display(self) -> str:
        """Format phase for display."""
        if self.is_cancelling:
            return "Cancelling…"
        elif self.is_paused:
            return "Paused"
        else:
            return self.phase.display_name
    
    @staticmethod
    def _format_bytes(bytes_count: int) -> str:
        """Format bytes count to human-readable string."""
        if bytes_count < 1024:
            return f"{bytes_count} B"
        elif bytes_count < 1024 * 1024:
            return f"{bytes_count / 1024:.1f} KB"
        elif bytes_count < 1024 * 1024 * 1024:
            return f"{bytes_count / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"