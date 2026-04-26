"""Tests for DocumentDedupEngine."""

from __future__ import annotations

from pathlib import Path


from cerebro.engines.document_dedup_engine import (
    DocumentDedupEngine,
    _jaccard_from_minhash,
    _minhash,
)
from cerebro.engines.base_engine import ScanState


# ---------------------------------------------------------------------------
# Unit tests for pure functions
# ---------------------------------------------------------------------------


def test_get_name():
    engine = DocumentDedupEngine()
    assert engine.get_name() == "Document Deduplication"


def test_minhash_returns_correct_length():
    tokens = {"abc", "bcd", "cde", "def"}
    sig = _minhash(tokens, n_hashes=64)
    assert isinstance(sig, list)
    assert len(sig) == 64
    assert all(isinstance(v, int) for v in sig)


def test_minhash_default_length():
    tokens = {"hello", "world"}
    sig = _minhash(tokens)
    assert len(sig) == 128


def test_jaccard_identical_signatures():
    sig = _minhash({"a", "b", "c", "d", "e"}, n_hashes=128)
    score = _jaccard_from_minhash(sig, sig)
    assert score == 1.0


def test_jaccard_different_signatures():
    sig_a = _minhash({"aaa", "bbb", "ccc", "ddd", "eee"}, n_hashes=128)
    sig_b = _minhash({"xxx", "yyy", "zzz", "www", "vvv"}, n_hashes=128)
    score = _jaccard_from_minhash(sig_a, sig_b)
    assert score < 1.0


def test_jaccard_empty_signatures():
    assert _jaccard_from_minhash([], []) == 0.0


# ---------------------------------------------------------------------------
# Integration tests using tmp_path
# ---------------------------------------------------------------------------


def _run_scan(engine: DocumentDedupEngine, folder: Path, options: dict | None = None) -> list:
    """Helper: configure + run engine synchronously and return results."""
    opts = options or {}
    engine.configure([folder], [], opts)
    results = []

    def cb(progress):
        results.append(progress)

    engine.start(cb)
    return engine.get_results()


def test_identical_files_form_one_group(tmp_path: Path):
    content = "This is a sufficiently long document content for testing deduplication. " * 5
    (tmp_path / "doc_a.txt").write_text(content, encoding="utf-8")
    (tmp_path / "doc_b.txt").write_text(content, encoding="utf-8")

    engine = DocumentDedupEngine()
    groups = _run_scan(engine, tmp_path)

    assert len(groups) == 1
    assert len(groups[0].files) == 2
    assert groups[0].similarity_type == "document"


def test_completely_different_files_produce_no_groups(tmp_path: Path):
    # Create two files with completely different content
    words_a = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu "
    words_b = "one two three four five six seven eight nine ten eleven twelve thirteen "
    content_a = (words_a * 20)[:500]
    content_b = (words_b * 20)[:500]
    (tmp_path / "doc_a.txt").write_text(content_a, encoding="utf-8")
    (tmp_path / "doc_b.txt").write_text(content_b, encoding="utf-8")

    engine = DocumentDedupEngine()
    groups = _run_scan(engine, tmp_path, {"similarity_threshold": 0.9})

    assert len(groups) == 0


def test_file_below_min_chars_is_skipped(tmp_path: Path):
    short = "hi"
    long_content = "This document has quite enough text to pass the minimum character filter. " * 3
    (tmp_path / "short.txt").write_text(short, encoding="utf-8")
    (tmp_path / "long.txt").write_text(long_content, encoding="utf-8")

    engine = DocumentDedupEngine()
    # min_chars=100 — short.txt (2 chars) must be skipped, no pairable candidate
    groups = _run_scan(engine, tmp_path, {"min_chars": 100})

    assert len(groups) == 0


def test_similarity_threshold_filters_groups(tmp_path: Path):
    base = "The quick brown fox jumps over the lazy dog. " * 10
    # doc_b shares the base but has an extra distinct suffix
    different_suffix = " ".join(f"word{i}" for i in range(200))
    (tmp_path / "doc_a.txt").write_text(base, encoding="utf-8")
    (tmp_path / "doc_b.txt").write_text(base + different_suffix, encoding="utf-8")

    engine_strict = DocumentDedupEngine()
    groups_strict = _run_scan(engine_strict, tmp_path, {"similarity_threshold": 0.99})

    engine_lenient = DocumentDedupEngine()
    groups_lenient = _run_scan(engine_lenient, tmp_path, {"similarity_threshold": 0.5})

    # Lenient threshold should find the pair; strict may not
    assert len(groups_lenient) >= len(groups_strict)


def test_scan_completes_with_completed_state(tmp_path: Path):
    content = "Sample document content that is long enough. " * 5
    (tmp_path / "a.txt").write_text(content, encoding="utf-8")
    (tmp_path / "b.txt").write_text(content, encoding="utf-8")

    engine = DocumentDedupEngine()
    engine.configure([tmp_path], [], {})

    final_states = []

    def cb(progress):
        final_states.append(progress.state)

    engine.start(cb)
    assert ScanState.COMPLETED in final_states


def test_reclaimable_equals_sum_minus_largest(tmp_path: Path):
    content = "Shared content that is identical in both files. " * 5
    (tmp_path / "doc1.txt").write_text(content, encoding="utf-8")
    (tmp_path / "doc2.txt").write_text(content, encoding="utf-8")

    engine = DocumentDedupEngine()
    groups = _run_scan(engine, tmp_path)

    assert len(groups) == 1
    g = groups[0]
    sizes = [f.size for f in g.files]
    expected_reclaimable = sum(sizes) - max(sizes)
    assert g.reclaimable == expected_reclaimable
