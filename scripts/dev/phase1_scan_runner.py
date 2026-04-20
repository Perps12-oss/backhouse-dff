"""Phase 1 diagnostic scan runner — re-run capability for post-v1 audit.

Relocated from diagnostics/_run_phase1_scan.py (Phase 1 closure commit).
Log output written to diagnostics/ (gitignored).

Usage:
    python scripts/dev/phase1_scan_runner.py <path>
    python scripts/dev/phase1_scan_runner.py  # defaults to jhjl test tree
"""
import sys
import os
import logging
import time
from pathlib import Path
from datetime import datetime

# Repo root on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_dir = ROOT / "diagnostics"
log_dir.mkdir(exist_ok=True)
log_path = log_dir / f"phase1_scan_{stamp}.log"

from cerebro.services.logger import get_logger, configure  # noqa: E402
configure(level=logging.INFO, log_to_file=False)

diag_fh = logging.FileHandler(str(log_path), encoding="utf-8")
diag_fh.setLevel(logging.INFO)
diag_fh.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
)
logging.getLogger("CEREBRO").addHandler(diag_fh)

logger = get_logger(__name__)

if len(sys.argv) > 1:
    TARGET = Path(sys.argv[1])
else:
    TARGET = Path(r"C:\Users\S8633\Downloads\jhjl")

logger.info("=== Phase 1 diagnostic scan START root=%s ===", TARGET)

from cerebro.core.scanners.turbo_scanner import TurboScanner, TurboScanConfig  # noqa: E402

config = TurboScanConfig(
    use_quick_hash=True,
    use_full_hash=False,
    skip_hidden=True,
    min_size=1024,
    use_cache=False,   # disabled: avoids SQLite contention in diagnostic runs
    incremental=False,
)
scanner = TurboScanner(config)
t0 = time.time()
results = list(scanner.scan([TARGET]))
elapsed = time.time() - t0
logger.info(
    "=== Phase 1 diagnostic scan END elapsed=%.2fs emitted=%d groups=%d ===",
    elapsed, len(results), len(scanner.last_groups),
)
diag_fh.flush()
diag_fh.close()
scanner.close()

print(f"Log written : {log_path}")
print(f"Elapsed     : {elapsed:.2f}s")
print(f"Emitted     : {len(results)}")
print(f"Groups      : {len(scanner.last_groups)}")
