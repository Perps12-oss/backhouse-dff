# cerebro/core/performance.py
"""
Cerebro v2 Performance - Thread/Process Pool Management

Provides adaptive thread and process pool sizing based on system resources.
Uses concurrent.futures for parallel execution.

Usage:
    from cerebro.core import ThreadPoolManager, ProcessPoolManager

    # For I/O-bound work (file walking, reading)
    thread_pool = ThreadPoolManager()
    futures = thread_pool.submit_all(tasks)
    results = thread_pool.gather(futures)

    # For CPU-bound work (hash computation, image processing)
    process_pool = ProcessPoolManager()
    futures = process_pool.submit_all(tasks)
    results = process_pool.gather(futures)
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, Future
from typing import Any, Callable, List, Optional, TypeVar

T = TypeVar("T")


# ============================================================================
# System Resource Detection
# ============================================================================


def _get_cpu_count() -> int:
    """
    Get CPU core count with safety limits.

    Returns:
        Number of CPU cores, capped at 8 for performance.
    """
    try:
        cpu_count = os.cpu_count() or 1
        # Cap at 8 to avoid diminishing returns
        return min(cpu_count, 8)
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return 1


def _get_optimal_thread_count() -> int:
    """
    Calculate optimal thread count for I/O-bound work.

    Returns:
        Thread count = CPU cores * 2 (for I/O work)
    """
    return _get_cpu_count() * 2


def _get_optimal_process_count() -> int:
    """
    Calculate optimal process count for CPU-bound work.

    Returns:
        Process count = CPU cores (one worker per core)
    """
    return _get_cpu_count()


# ============================================================================
# Thread Pool Manager
# ============================================================================


class ThreadPoolManager:
    """
    Manages a ThreadPoolExecutor for I/O-bound parallel work.

    Use cases:
        - File system operations (walk, stat, read)
        - Network requests
        - Any I/O-bound task that benefits from concurrency

    Thread safety:
        Safe to use from any thread.
    """

    def __init__(self, max_workers: Optional[int] = None) -> None:
        """
        Initialize thread pool.

        Args:
            max_workers: Override default worker count.
                        None = auto (CPU * 2).
        """
        self._max_workers = max_workers or _get_optimal_thread_count()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: List[Future[Any]] = []

    def __enter__(self) -> ThreadPoolManager:
        """Context manager entry - create executor."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - shutdown executor."""
        self.shutdown(wait=True)

    def start(self) -> None:
        """Create the thread pool if not already started."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="cerebro-worker-",
            )

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the thread pool.

        Args:
            wait: If True, wait for pending work to complete.
        """
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._futures.clear()

    def submit(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
        """
        Submit a single function to the thread pool.

        Args:
            fn: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Future object for the submitted work.
        """
        if self._executor is None:
            self.start()
        future = self._executor.submit(fn, *args, **kwargs)
        self._futures.append(future)
        return future

    def submit_all(
        self, fn: Callable[..., T], args_list: List[tuple[Any, ...]]
    ) -> List[Future[T]]:
        """
        Submit multiple calls to the same function with different arguments.

        Args:
            fn: Function to execute
            args_list: List of argument tuples

        Returns:
            List of Future objects.
        """
        if self._executor is None:
            self.start()
        futures = [self._executor.submit(fn, *args) for args in args_list]
        self._futures.extend(futures)
        return futures

    def map(
        self, fn: Callable[..., T], iterable: List[Any]
    ) -> List[T]:
        """
        Map function over iterable using thread pool.

        Args:
            fn: Function to apply
            iterable: List of items to process

        Returns:
            List of results in order.
        """
        if self._executor is None:
            self.start()
        return list(self._executor.map(fn, iterable))

    def gather(self, futures: List[Future[T]], timeout: Optional[float] = None) -> List[T]:
        """
        Wait for multiple futures to complete and return results.

        Args:
            futures: List of Future objects
            timeout: Optional timeout in seconds

        Returns:
            List of results from completed futures.
        """
        results = []
        for future in futures:
            try:
                result = future.result(timeout=timeout)
                results.append(result)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
                # Return None or handle errors as needed
                results.append(None)
        return results

    def wait_all(self, timeout: Optional[float] = None) -> None:
        """
        Wait for all submitted futures to complete.

        Args:
            timeout: Optional timeout in seconds
        """
        import concurrent.futures

        concurrent.futures.wait(self._futures, timeout=timeout)

    def cancel_all(self) -> None:
        """Cancel all pending futures."""
        for future in self._futures:
            if not future.done():
                future.cancel()

    @property
    def active_count(self) -> int:
        """Number of currently executing tasks."""
        if self._executor is None:
            return 0
        # Return approximate count (futures - completed)
        return sum(1 for f in self._futures if not f.done())

    @property
    def max_workers(self) -> int:
        """Maximum number of worker threads."""
        return self._max_workers


# ============================================================================
# Process Pool Manager
# ============================================================================


class ProcessPoolManager:
    """
    Manages a ProcessPoolExecutor for CPU-bound parallel work.

    Use cases:
        - Hash computation (SHA256, Blake3)
        - Image processing (perceptual hashing)
        - Any CPU-intensive task

    Note:
        On Windows, ProcessPoolExecutor has limitations with pickling.
        Functions submitted must be importable at module level.
    """

    def __init__(self, max_workers: Optional[int] = None) -> None:
        """
        Initialize process pool.

        Args:
            max_workers: Override default worker count.
                        None = auto (CPU cores).
        """
        self._max_workers = max_workers or _get_optimal_process_count()
        self._executor: Optional[ProcessPoolExecutor] = None
        self._futures: List[Future[Any]] = []

    def __enter__(self) -> ProcessPoolManager:
        """Context manager entry - create executor."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - shutdown executor."""
        self.shutdown(wait=True)

    def start(self) -> None:
        """Create the process pool if not already started."""
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
            )

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the process pool.

        Args:
            wait: If True, wait for pending work to complete.
        """
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._futures.clear()

    def submit(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
        """
        Submit a single function to the process pool.

        Args:
            fn: Function to execute (must be picklable)
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Future object for the submitted work.
        """
        if self._executor is None:
            self.start()
        future = self._executor.submit(fn, *args, **kwargs)
        self._futures.append(future)
        return future

    def submit_all(
        self, fn: Callable[..., T], args_list: List[tuple[Any, ...]]
    ) -> List[Future[T]]:
        """
        Submit multiple calls to the same function with different arguments.

        Args:
            fn: Function to execute (must be picklable)
            args_list: List of argument tuples

        Returns:
            List of Future objects.
        """
        if self._executor is None:
            self.start()
        futures = [self._executor.submit(fn, *args) for args in args_list]
        self._futures.extend(futures)
        return futures

    def map(
        self, fn: Callable[..., T], iterable: List[Any], chunksize: int = 1
    ) -> List[T]:
        """
        Map function over iterable using process pool.

        Args:
            fn: Function to apply (must be picklable)
            iterable: List of items to process
            chunksize: Number of items per chunk

        Returns:
            List of results in order.
        """
        if self._executor is None:
            self.start()
        return list(self._executor.map(fn, iterable, chunksize=chunksize))

    def gather(self, futures: List[Future[T]], timeout: Optional[float] = None) -> List[T]:
        """
        Wait for multiple futures to complete and return results.

        Args:
            futures: List of Future objects
            timeout: Optional timeout in seconds

        Returns:
            List of results from completed futures.
        """
        results = []
        for future in futures:
            try:
                result = future.result(timeout=timeout)
                results.append(result)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
                # Return None or handle errors as needed
                results.append(None)
        return results

    def wait_all(self, timeout: Optional[float] = None) -> None:
        """
        Wait for all submitted futures to complete.

        Args:
            timeout: Optional timeout in seconds
        """
        import concurrent.futures

        concurrent.futures.wait(self._futures, timeout=timeout)

    def cancel_all(self) -> None:
        """Cancel all pending futures."""
        for future in self._futures:
            if not future.done():
                future.cancel()

    @property
    def active_count(self) -> int:
        """Number of currently executing tasks."""
        if self._executor is None:
            return 0
        return sum(1 for f in self._futures if not f.done())

    @property
    def max_workers(self) -> int:
        """Maximum number of worker processes."""
        return self._max_workers


# ============================================================================
# Utility Functions
# ============================================================================


def get_system_info() -> dict[str, Any]:
    """
    Return information about system resources.

    Returns:
        Dict with cpu_count, thread_pool_size, process_pool_size.
    """
    return {
        "cpu_count": _get_cpu_count(),
        "thread_pool_size": _get_optimal_thread_count(),
        "process_pool_size": _get_optimal_process_count(),
        "platform": os.name,
    }
