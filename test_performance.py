#!/usr/bin/env python3
"""
Performance Test Suite for CEREBRO Optimizations
================================================

Tests and demonstrates the performance improvements.

Usage:
    python test_performance.py --test-dir /path/to/test
    python test_performance.py --benchmark
    python test_performance.py --compare
"""

import sys
import time
import argparse
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass
import json


# Add project to path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))


@dataclass
class TestResult:
    """Test result data."""
    name: str
    files_scanned: int
    elapsed_seconds: float
    files_per_second: float
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'files_scanned': self.files_scanned,
            'elapsed_seconds': round(self.elapsed_seconds, 2),
            'files_per_second': round(self.files_per_second, 0),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': round(self.cache_hit_rate, 1),
        }


def test_turbo_scanner(test_dir: Path) -> TestResult:
    """Test TurboScanner performance."""
    print("\n" + "="*60)
    print("Testing TURBO SCANNER")
    print("="*60)
    
    from cerebro.core.scanners.turbo_scanner import TurboScanner, TurboScanConfig
    
    config = TurboScanConfig(
        use_cache=True,
        incremental=True,
        use_quick_hash=True,
        use_full_hash=False,
    )
    
    start = time.time()
    
    with TurboScanner(config) as scanner:
        file_count = 0
        for _ in scanner.scan([test_dir]):
            file_count += 1
        
        elapsed = time.time() - start
        stats = scanner.stats
        
        result = TestResult(
            name="TurboScanner",
            files_scanned=file_count,
            elapsed_seconds=elapsed,
            files_per_second=file_count / elapsed if elapsed > 0 else 0,
            cache_hits=stats.get('hash_cache_hits', 0),
            cache_misses=stats.get('hash_cache_misses', 0),
            cache_hit_rate=(
                stats.get('hash_cache_hits', 0) / 
                max(1, stats.get('hash_cache_hits', 0) + stats.get('hash_cache_misses', 0))
                * 100
            ),
        )
    
    print_result(result)
    return result


def test_optimized_discovery(test_dir: Path) -> TestResult:
    """Test OptimizedFileDiscovery performance."""
    print("\n" + "="*60)
    print("Testing OPTIMIZED DISCOVERY")
    print("="*60)
    
    from cerebro.core.discovery_optimized import OptimizedFileDiscovery
    
    engine = OptimizedFileDiscovery(max_workers=32, use_cache=True)
    
    start = time.time()
    files = engine.discover_files([test_dir], min_size=1024, skip_hidden=True)
    elapsed = time.time() - start
    
    result = TestResult(
        name="OptimizedDiscovery",
        files_scanned=len(files),
        elapsed_seconds=elapsed,
        files_per_second=len(files) / elapsed if elapsed > 0 else 0,
    )
    
    print_result(result)
    return result


def test_optimized_hashing(test_dir: Path) -> TestResult:
    """Test OptimizedHashingEngine performance."""
    print("\n" + "="*60)
    print("Testing OPTIMIZED HASHING")
    print("="*60)
    
    from cerebro.core.hashing_optimized import SmartHashingPipeline
    from cerebro.services.hash_cache import HashCache
    
    # First discover files
    print("Discovering files...")
    from cerebro.core.discovery_optimized import OptimizedFileDiscovery
    engine = OptimizedFileDiscovery()
    discovered = engine.discover_files([test_dir], min_size=1024)
    file_paths = [f.path for f in discovered]
    
    print(f"Found {len(file_paths)} files, computing hashes...")
    
    # Setup cache
    cache_path = Path.home() / ".cerebro" / "cache" / "hash_cache.sqlite"
    cache = HashCache(cache_path)
    cache.open()
    
    try:
        pipeline = SmartHashingPipeline(cache, max_workers=64)
        
        start = time.time()
        duplicates = pipeline.find_duplicates(file_paths)
        elapsed = time.time() - start
        
        stats = pipeline.get_stats()
        
        result = TestResult(
            name="OptimizedHashing",
            files_scanned=stats.get('files_hashed', 0),
            elapsed_seconds=elapsed,
            files_per_second=stats.get('files_hashed', 0) / elapsed if elapsed > 0 else 0,
            cache_hits=stats.get('cache_hits', 0),
            cache_misses=stats.get('cache_misses', 0),
            cache_hit_rate=stats.get('cache_hit_rate', 0),
        )
    
    finally:
        cache.close()
    
    print_result(result)
    return result


def test_scanner_adapter(test_dir: Path) -> TestResult:
    """Test ScannerAdapter performance."""
    print("\n" + "="*60)
    print("Testing SCANNER ADAPTER")
    print("="*60)
    
    from cerebro.core.scanner_adapter import create_optimized_scanner
    
    scanner = create_optimized_scanner()
    
    start = time.time()
    file_count = 0
    
    for _ in scanner.scan([test_dir]):
        file_count += 1
    
    elapsed = time.time() - start
    
    result = TestResult(
        name="ScannerAdapter",
        files_scanned=file_count,
        elapsed_seconds=elapsed,
        files_per_second=file_count / elapsed if elapsed > 0 else 0,
    )
    
    scanner.close()
    
    print_result(result)
    return result


def print_result(result: TestResult):
    """Print test result."""
    print(f"\nResults:")
    print(f"  Files scanned: {result.files_scanned:,}")
    print(f"  Time: {result.elapsed_seconds:.2f}s")
    print(f"  Speed: {result.files_per_second:.0f} files/sec")
    
    if result.cache_hits > 0 or result.cache_misses > 0:
        print(f"\nCache Performance:")
        print(f"  Hits: {result.cache_hits:,}")
        print(f"  Misses: {result.cache_misses:,}")
        print(f"  Hit rate: {result.cache_hit_rate:.1f}%")


def run_comparison(test_dir: Path):
    """Run comparison between all implementations."""
    print("\n" + "="*70)
    print(" PERFORMANCE COMPARISON ".center(70, "="))
    print("="*70)
    
    results = []
    
    # Test each implementation
    tests = [
        ("Discovery", test_optimized_discovery),
        ("Hashing", test_optimized_hashing),
        ("Turbo Scanner", test_turbo_scanner),
        ("Scanner Adapter", test_scanner_adapter),
    ]
    
    for name, test_func in tests:
        try:
            result = test_func(test_dir)
            results.append(result)
        except Exception as e:
            print(f"\n❌ {name} failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Print summary
    print("\n" + "="*70)
    print(" SUMMARY ".center(70, "="))
    print("="*70)
    
    print(f"\n{'Implementation':<20} {'Files':<10} {'Time':<10} {'Speed':<15} {'Cache Hit Rate':<15}")
    print("-" * 70)
    
    for result in results:
        print(f"{result.name:<20} {result.files_scanned:<10,} "
              f"{result.elapsed_seconds:<10.2f} "
              f"{result.files_per_second:<15,.0f} "
              f"{result.cache_hit_rate:<15.1f}%")
    
    # Save results
    output_file = ROOT_DIR / "performance_results.json"
    with open(output_file, 'w') as f:
        json.dump([r.to_dict() for r in results], f, indent=2)
    
    print(f"\n✓ Results saved to: {output_file}")


def run_cache_test(test_dir: Path):
    """Test cache effectiveness with multiple scans."""
    print("\n" + "="*70)
    print(" CACHE EFFECTIVENESS TEST ".center(70, "="))
    print("="*70)
    
    from cerebro.core.scanners.turbo_scanner import TurboScanner, TurboScanConfig
    from cerebro.services.hash_cache import HashCache
    
    # Clear cache first
    cache_path = Path.home() / ".cerebro" / "cache" / "hash_cache.sqlite"
    if cache_path.exists():
        cache = HashCache(cache_path)
        cache.open()
        cache.clear_cache()
        cache.close()
        print("✓ Cache cleared")
    
    config = TurboScanConfig(use_cache=True, use_quick_hash=True)
    
    # Run multiple scans
    scan_results = []
    
    for scan_num in range(1, 4):
        print(f"\n--- Scan #{scan_num} ---")
        
        with TurboScanner(config) as scanner:
            start = time.time()
            file_count = 0
            
            for _ in scanner.scan([test_dir]):
                file_count += 1
            
            elapsed = time.time() - start
            stats = scanner.stats
            
            hit_rate = 0.0
            if stats.get('hash_cache_hits', 0) + stats.get('hash_cache_misses', 0) > 0:
                hit_rate = (
                    stats['hash_cache_hits'] / 
                    (stats['hash_cache_hits'] + stats['hash_cache_misses'])
                    * 100
                )
            
            scan_results.append({
                'scan': scan_num,
                'files': file_count,
                'time': elapsed,
                'speed': file_count / elapsed if elapsed > 0 else 0,
                'cache_hit_rate': hit_rate,
            })
            
            print(f"  Files: {file_count:,}")
            print(f"  Time: {elapsed:.2f}s")
            print(f"  Speed: {file_count / elapsed:.0f} files/sec")
            print(f"  Cache hit rate: {hit_rate:.1f}%")
    
    # Print comparison
    print("\n" + "="*70)
    print(" CACHE PERFORMANCE SUMMARY ".center(70, "="))
    print("="*70)
    
    print(f"\n{'Scan':<10} {'Time':<15} {'Speed':<20} {'Hit Rate':<15} {'Speedup':<10}")
    print("-" * 70)
    
    baseline_time = scan_results[0]['time']
    
    for result in scan_results:
        speedup = baseline_time / result['time'] if result['time'] > 0 else 0
        print(f"#{result['scan']:<9} {result['time']:<15.2f} "
              f"{result['speed']:<20,.0f} {result['cache_hit_rate']:<15.1f}% "
              f"{speedup:<10.1f}x")


def run_benchmark(test_dir: Path):
    """Run comprehensive benchmark suite."""
    print("\n" + "="*70)
    print(" BENCHMARK SUITE ".center(70, "="))
    print("="*70)
    
    # Run all tests
    run_comparison(test_dir)
    run_cache_test(test_dir)
    
    print("\n" + "="*70)
    print(" BENCHMARK COMPLETE ".center(70, "="))
    print("="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Test CEREBRO performance optimizations"
    )
    parser.add_argument(
        '--test-dir',
        type=Path,
        help='Directory to test (uses sample data if not provided)'
    )
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='Run full benchmark suite'
    )
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare all implementations'
    )
    parser.add_argument(
        '--cache',
        action='store_true',
        help='Test cache effectiveness'
    )
    parser.add_argument(
        '--turbo',
        action='store_true',
        help='Test turbo scanner only'
    )
    parser.add_argument(
        '--discovery',
        action='store_true',
        help='Test discovery engine only'
    )
    parser.add_argument(
        '--hashing',
        action='store_true',
        help='Test hashing engine only'
    )
    
    args = parser.parse_args()
    
    # Determine test directory
    if args.test_dir:
        test_dir = args.test_dir
    else:
        # Use user's home directory as test (safe default)
        test_dir = Path.home() / "Desktop"
        if not test_dir.exists():
            test_dir = Path.home() / "Documents"
        if not test_dir.exists():
            test_dir = Path.home()
        
        print(f"⚠️  No test directory specified, using: {test_dir}")
        print(f"   Use --test-dir to specify a different directory\n")
    
    if not test_dir.exists():
        print(f"❌ Test directory does not exist: {test_dir}")
        return 1
    
    # Run requested tests
    try:
        if args.benchmark:
            run_benchmark(test_dir)
        elif args.compare:
            run_comparison(test_dir)
        elif args.cache:
            run_cache_test(test_dir)
        elif args.turbo:
            test_turbo_scanner(test_dir)
        elif args.discovery:
            test_optimized_discovery(test_dir)
        elif args.hashing:
            test_optimized_hashing(test_dir)
        else:
            # Default: run comparison
            print("Running comparison test (use --help for more options)")
            run_comparison(test_dir)
        
        print("\n✓ All tests completed successfully")
        return 0
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
