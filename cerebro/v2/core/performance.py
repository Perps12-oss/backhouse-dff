"""
Performance Manager

Manages thread and process pools for optimal CPU utilization.
Provides adaptive sizing based on system resources and task type.
"""

from __future__ import annotations

import os
import concurrent.futures
from typing import Callable, TypeVar, Any, List, Optional
from contextlib import contextmanager
from functools import wraps
import time
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class PoolManager:
    """
    Manages ThreadPoolExecutor and ProcessPoolExecutor instances.

    Automatically sizes pools based on CPU count and task characteristics.
    Reuses pools to avoid overhead of repeated creation/destruction.
    """

    _instance: Optional["PoolManager"] = None

    def __init__(self):
        """Initialize the pool manager."""
        self._thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._process_pool: Optional[concurrent.futures.ProcessPoolExecutor] = None
        self._cpu_count = os.cpu_count() or 1
        self._max_threads = min(self._cpu_count, 8)
        self._max_processes = min(self._cpu_count, 4)

        logger.info(
            f"PoolManager initialized: {self._cpu_count} CPUs, "
            f"max_threads={self._max_threads}, max_processes={self._max_processes}"
        )

    @classmethod
    def get_instance(cls) -> "PoolManager":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def max_threads(self) -> int:
        """Maximum number of threads for I/O-bound tasks."""
        return self._max_threads

    @property
    def max_processes(self) -> int:
        """Maximum number of processes for CPU-bound tasks."""
        return self._max_processes

    @property
    def cpu_count(self) -> int:
        """Number of available CPU cores."""
        return self._cpu_count

    def get_thread_pool(self, max_workers: Optional[int] = None) -> concurrent.futures.ThreadPoolExecutor:
        """
        Get or create a thread pool.

        Args:
            max_workers: Maximum worker threads. Defaults to adaptive sizing.

        Returns:
            ThreadPoolExecutor instance.
        """
        if self._thread_pool is None or self._thread_pool._shutdown:
            workers = max_workers or self._max_threads
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="CerebroThread"
            )
            logger.debug(f"Created thread pool with {workers} workers")
        return self._thread_pool

    def get_process_pool(self, max_workers: Optional[int] = None) -> concurrent.futures.ProcessPoolExecutor:
        """
        Get or create a process pool.

        Args:
            max_workers: Maximum worker processes. Defaults to adaptive sizing.

        Returns:
            ProcessPoolExecutor instance.
        """
        if self._process_pool is None or self._process_pool._shutdown:
            workers = max_workers or self._max_processes
            self._process_pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=workers
            )
            logger.debug(f"Created process pool with {workers} workers")
        return self._process_pool

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown all pools.

        Args:
            wait: Whether to wait for pending work to complete.
        """
        if self._thread_pool:
            self._thread_pool.shutdown(wait=wait)
            self._thread_pool = None
            logger.debug("Thread pool shutdown")

        if self._process_pool:
            self._process_pool.shutdown(wait=wait)
            self._process_pool = None
            logger.debug("Process pool shutdown")


# Global instance
_manager: Optional[PoolManager] = None


def get_pool_manager() -> PoolManager:
    """Get the global pool manager instance."""
    global _manager
    if _manager is None:
        _manager = PoolManager.get_instance()
    return _manager


def run_parallel(
    func: Callable[..., T],
    items: List[Any],
    use_processes: bool = False,
    max_workers: Optional[int] = None,
    **kwargs
) -> List[T]:
    """
    Run a function on multiple items in parallel.

    Args:
        func: Function to execute on each item.
        items: List of items to process.
        use_processes: If True, use ProcessPoolExecutor (CPU-bound).
                      If False, use ThreadPoolExecutor (I/O-bound).
        max_workers: Maximum number of workers. Defaults to adaptive sizing.
        **kwargs: Additional keyword arguments passed to func.

    Returns:
        List of results in the same order as input items.
    """
    manager = get_pool_manager()

    if use_processes:
        executor = manager.get_process_pool(max_workers)
    else:
        executor = manager.get_thread_pool(max_workers)

    # Map function over items with partial application
    if kwargs:
        from functools import partial
        func = partial(func, **kwargs)

    futures = {executor.submit(func, item): item for item in items}

    results = [None] * len(items)
    index_map = {item: idx for idx, item in enumerate(items)}

    for future in concurrent.futures.as_completed(futures):
        item = futures[future]
        try:
            results[index_map[item]] = future.result()
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.error(f"Error processing {item}: {e}")
            results[index_map[item]] = None

    return results


def run_parallel_map(
    func: Callable[..., T],
    items: List[Any],
    use_processes: bool = False,
    max_workers: Optional[int] = None
) -> List[T]:
    """
    Run a function on multiple items using executor.map.

    Args:
        func: Function to execute on each item.
        items: List of items to process.
        use_processes: If True, use ProcessPoolExecutor (CPU-bound).
                      If False, use ThreadPoolExecutor (I/O-bound).
        max_workers: Maximum number of workers. Defaults to adaptive sizing.

    Returns:
        List of results in the same order as input items.
    """
    manager = get_pool_manager()

    if use_processes:
        executor = manager.get_process_pool(max_workers)
    else:
        executor = manager.get_thread_pool(max_workers)

    try:
        return list(executor.map(func, items))
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
        logger.error(f"Error in parallel map: {e}")
        raise


@contextmanager
def thread_context(max_workers: Optional[int] = None):
    """
    Context manager for a temporary thread pool.

    Args:
        max_workers: Maximum number of workers. Defaults to adaptive sizing.

    Yields:
        ThreadPoolExecutor instance.
    """
    manager = get_pool_manager()
    executor = manager.get_thread_pool(max_workers)
    try:
        yield executor
    finally:
        # Don't shutdown - let the manager handle it
        pass


@contextmanager
def process_context(max_workers: Optional[int] = None):
    """
    Context manager for a temporary process pool.

    Args:
        max_workers: Maximum number of workers. Defaults to adaptive sizing.

    Yields:
        ProcessPoolExecutor instance.
    """
    manager = get_pool_manager()
    executor = manager.get_process_pool(max_workers)
    try:
        yield executor
    finally:
        # Don't shutdown - let the manager handle it
        pass


def timing(func: Callable) -> Callable:
    """
    Decorator to measure and log function execution time.

    Args:
        func: Function to time.

    Returns:
        Wrapped function that logs execution time.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start_time
        logger.debug(f"{func.__name__} completed in {elapsed:.3f}s")
        return result
    return wrapper


def async_timing(func: Callable) -> Callable:
    """
    Decorator for async functions to measure execution time.

    Args:
        func: Async function to time.

    Returns:
        Wrapped async function that logs execution time.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        elapsed = time.time() - start_time
        logger.debug(f"{func.__name__} completed in {elapsed:.3f}s")
        return result
    return wrapper


class PerformanceMonitor:
    """
    Monitor and report performance metrics.

    Tracks execution times, throughput, and resource usage.
    """

    def __init__(self, name: str = "Performance"):
        """Initialize the monitor."""
        self.name = name
        self._timings: dict[str, List[float]] = {}
        self._counters: dict[str, int] = {}

    def time(self, label: str) -> Callable:
        """
        Decorator to time a function and record results.

        Args:
            label: Label to associate with timing.

        Returns:
            Decorator function.
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                self.record_timing(label, elapsed)
                return result
            return wrapper
        return decorator

    def record_timing(self, label: str, seconds: float) -> None:
        """
        Record a timing measurement.

        Args:
            label: Label for the timing.
            seconds: Elapsed time in seconds.
        """
        if label not in self._timings:
            self._timings[label] = []
        self._timings[label].append(seconds)

    def increment(self, label: str, amount: int = 1) -> None:
        """
        Increment a counter.

        Args:
            label: Label for the counter.
            amount: Amount to increment by.
        """
        self._counters[label] = self._counters.get(label, 0) + amount

    def get_stats(self) -> dict:
        """
        Get performance statistics.

        Returns:
            Dict with timing stats and counters.
        """
        stats = {
            'name': self.name,
            'timings': {},
            'counters': self._counters.copy()
        }

        for label, timings in self._timings.items():
            if timings:
                stats['timings'][label] = {
                    'count': len(timings),
                    'total': sum(timings),
                    'min': min(timings),
                    'max': max(timings),
                    'avg': sum(timings) / len(timings)
                }

        return stats

    def reset(self) -> None:
        """Reset all recorded metrics."""
        self._timings.clear()
        self._counters.clear()

    def report(self) -> str:
        """
        Generate a human-readable performance report.

        Returns:
            Formatted report string.
        """
        lines = [f"=== {self.name} Performance Report ==="]

        if self._counters:
            lines.append("\nCounters:")
            for label, count in sorted(self._counters.items()):
                lines.append(f"  {label}: {count}")

        if self._timings:
            lines.append("\nTimings:")
            for label, timings in sorted(self._timings.items()):
                if timings:
                    avg = sum(timings) / len(timings)
                    lines.append(f"  {label}: {len(timings)} calls, avg {avg:.3f}s")

        return "\n".join(lines)


def shutdown_all() -> None:
    """Shutdown all pool resources."""
    global _manager
    if _manager:
        _manager.shutdown()
        _manager = None
