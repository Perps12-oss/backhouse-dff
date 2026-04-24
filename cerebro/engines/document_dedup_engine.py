"""
Document Deduplication Engine

Detects near-duplicate documents using MinHash/Jaccard similarity.
Supports: .pdf, .doc, .docx, .txt, .odt, .rtf, .csv
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)
from cerebro.engines.image_formats import UnionFind

try:
    import pypdf as _pypdf
    HAS_PYPDF = True
except ImportError:
    try:
        import PyPDF2 as _pypdf  # type: ignore[no-redef]
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False
        _pypdf = None  # type: ignore[assignment]

try:
    import docx as _docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    _docx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.odt', '.rtf', '.csv'}


def _minhash(tokens: set, n_hashes: int = 128) -> list:
    """Compute MinHash signature for a set of tokens."""
    sig = []
    for seed in range(n_hashes):
        min_val = 2 ** 32
        for tok in tokens:
            h = int(hashlib.md5(f"{seed}:{tok}".encode()).hexdigest()[:8], 16)
            if h < min_val:
                min_val = h
        sig.append(min_val)
    return sig


def _jaccard_from_minhash(a: list, b: list) -> float:
    """Estimate Jaccard similarity from two MinHash signatures."""
    if not a:
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def _shingles(text: str, k: int = 3) -> set:
    """Extract k-char shingles from text."""
    text = text.lower().strip()
    if len(text) < k:
        return {text} if text else set()
    return {text[i:i + k] for i in range(len(text) - k + 1)}


def _extract_text(path: Path) -> str:
    """Extract text content from a document file."""
    ext = path.suffix.lower()

    if ext in ('.txt', '.csv'):
        try:
            return path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return ''

    if ext == '.pdf':
        if HAS_PYPDF:
            try:
                text_parts = []
                with open(path, 'rb') as fh:
                    reader = _pypdf.PdfReader(fh)
                    for page in reader.pages:
                        text_parts.append(page.extract_text() or '')
                return ' '.join(text_parts)
            except Exception:
                pass
        # Fallback: raw bytes, keep printable
        try:
            raw = path.read_bytes()
            return ''.join(chr(b) for b in raw if 32 <= b < 127)
        except OSError:
            return ''

    if ext == '.docx':
        if HAS_DOCX:
            try:
                doc = _docx.Document(str(path))
                return ' '.join(p.text for p in doc.paragraphs)
            except Exception:
                pass
        # Fallback: raw bytes
        try:
            raw = path.read_bytes()
            return ''.join(chr(b) for b in raw if 32 <= b < 127)
        except OSError:
            return ''

    # .doc, .odt, .rtf — raw text extraction
    try:
        raw = path.read_bytes()
        return ''.join(chr(b) for b in raw if 32 <= b < 127)
    except OSError:
        return ''


class DocumentDedupEngine(BaseEngine):
    """Document deduplication engine using MinHash/Jaccard similarity."""

    def __init__(self) -> None:
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[ScanProgress], None]] = None
        self._default_options = {
            'similarity_threshold': 0.8,
            'min_chars': 100,
            'include_hidden': False,
            'n_hashes': 128,
        }

    def get_name(self) -> str:
        return "Document Deduplication"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name='similarity_threshold',
                display_name='Similarity Threshold',
                type='float',
                default=0.8,
                min_value=0.5,
                max_value=1.0,
                tooltip='Jaccard similarity cutoff. Higher = more strict matching.',
            ),
            EngineOption(
                name='min_chars',
                display_name='Minimum Characters',
                type='int',
                default=100,
                min_value=0,
                max_value=100000,
                tooltip='Skip documents with fewer than this many characters.',
            ),
            EngineOption(
                name='include_hidden',
                display_name='Include Hidden Files',
                type='bool',
                default=False,
                tooltip='Include hidden documents in scan.',
            ),
            EngineOption(
                name='n_hashes',
                display_name='MinHash Signatures',
                type='int',
                default=128,
                min_value=32,
                max_value=512,
                tooltip='Number of MinHash hash functions. More = higher accuracy, slower.',
            ),
        ]

    def configure(self, folders: List[Path], protected: List[Path], options: dict) -> None:
        self._folders = [Path(f) for f in folders]
        self._protected = [Path(p) for p in protected]
        merged = self._default_options.copy()
        merged.update(options)
        self._options = merged

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._cancel_event.clear()
        self._pause_event.clear()
        self._results = []
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._callback = progress_callback
        self._run_scan(progress_callback)

    def _run_scan(self, cb: Callable[[ScanProgress], None]) -> None:
        try:
            doc_files = self._collect_files()
            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                cb(ScanProgress(state=ScanState.CANCELLED))
                return

            total = len(doc_files)
            self._progress = ScanProgress(
                state=ScanState.SCANNING,
                files_total=total,
                files_scanned=0,
                stage='extracting_text',
            )
            cb(self._progress)

            threshold = float(self._options.get('similarity_threshold', 0.8))
            min_chars = int(self._options.get('min_chars', 100))
            n_hashes = int(self._options.get('n_hashes', 128))

            records: list[dict] = []
            for i, path in enumerate(doc_files):
                if self._cancel_event.is_set():
                    self._state = ScanState.CANCELLED
                    cb(ScanProgress(state=ScanState.CANCELLED))
                    return

                while self._pause_event.is_set():
                    time.sleep(0.05)

                text = _extract_text(path)
                if len(text) < min_chars:
                    if (i + 1) % 10 == 0 and self._callback:
                        cb(ScanProgress(
                            state=ScanState.SCANNING,
                            files_total=total,
                            files_scanned=i + 1,
                            stage='extracting_text',
                            current_file=str(path),
                        ))
                    continue

                try:
                    stat = path.stat()
                    size = stat.st_size
                    modified = stat.st_mtime
                except OSError:
                    size = 0
                    modified = 0.0

                tokens = _shingles(text)
                sig = _minhash(tokens, n_hashes)
                records.append({
                    'path': path,
                    'size': size,
                    'modified': modified,
                    'sig': sig,
                })

                if (i + 1) % 10 == 0 and self._callback:
                    cb(ScanProgress(
                        state=ScanState.SCANNING,
                        files_total=total,
                        files_scanned=i + 1,
                        stage='extracting_text',
                        current_file=str(path),
                    ))

            groups = self._build_groups(records, threshold)
            self._results = groups
            self._state = ScanState.COMPLETED
            cb(ScanProgress(
                state=ScanState.COMPLETED,
                files_scanned=total,
                files_total=total,
                groups_found=len(groups),
                duplicates_found=sum(len(g.files) - 1 for g in groups),
                bytes_reclaimable=sum(g.reclaimable for g in groups),
            ))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError) as e:
            cb(ScanProgress(
                state=ScanState.ERROR,
                current_file=f'Error: {e}',
            ))

    def _collect_files(self) -> List[Path]:
        files: List[Path] = []
        include_hidden = bool(self._options.get('include_hidden', False))

        for folder in self._folders:
            try:
                for item in folder.rglob('*'):
                    if self._cancel_event.is_set():
                        return []
                    if not item.is_file():
                        continue
                    if not include_hidden and item.name.startswith('.'):
                        continue
                    if self._protected and any(p in item.parents for p in self._protected):
                        continue
                    if item.suffix.lower() in DOCUMENT_EXTENSIONS:
                        files.append(item)
            except PermissionError as exc:
                logger.warning('Permission denied: %s', exc)

        return files

    def _build_groups(self, records: list, threshold: float) -> List[DuplicateGroup]:
        n = len(records)
        if n < 2:
            return []

        uf = UnionFind()
        for i in range(n):
            uf.add(i)

        # Track pairwise jaccard scores for representative calculation
        pair_scores: dict[tuple[int, int], float] = {}
        for i in range(n):
            for j in range(i + 1, n):
                score = _jaccard_from_minhash(records[i]['sig'], records[j]['sig'])
                if score >= threshold:
                    uf.union(i, j)
                    pair_scores[(i, j)] = score

        groups: List[DuplicateGroup] = []
        group_id = 0
        for indices in uf.get_groups():
            if len(indices) < 2:
                continue

            group_records = [records[i] for i in indices]
            # Representative is the largest file
            rep_record = max(group_records, key=lambda r: r['size'])
            rep_path = rep_record['path']
            rep_idx = indices[group_records.index(rep_record)]

            files_list: List[DuplicateFile] = []
            for idx, rec in zip(indices, group_records):
                i, j = (min(idx, rep_idx), max(idx, rep_idx))
                if i == j:
                    sim = 1.0
                else:
                    sim = pair_scores.get((i, j), _jaccard_from_minhash(rec['sig'], rep_record['sig']))
                files_list.append(DuplicateFile(
                    path=rec['path'],
                    size=rec['size'],
                    modified=rec['modified'],
                    extension=rec['path'].suffix.lower(),
                    is_keeper=(rec['path'] == rep_path),
                    similarity=sim,
                ))

            total_size = sum(r['size'] for r in group_records)
            reclaimable = total_size - rep_record['size']
            groups.append(DuplicateGroup(
                group_id=group_id,
                files=files_list,
                total_size=total_size,
                reclaimable=reclaimable,
                similarity_type='document',
            ))
            group_id += 1

        return groups

    def pause(self) -> None:
        self._pause_event.set()
        self._state = ScanState.PAUSED

    def resume(self) -> None:
        self._pause_event.clear()
        self._state = ScanState.SCANNING

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.clear()

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress
