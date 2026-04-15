from pathlib import Path

from PIL import Image, ImageDraw

from cerebro.engines.image_dedup_engine import ImageDedupEngine


def _write_stripes(path: Path, colors: tuple[tuple[int, int, int], tuple[int, int, int]]) -> None:
    img = Image.new("RGB", (128, 128), colors[0])
    draw = ImageDraw.Draw(img)
    for x in range(0, 128, 8):
        draw.rectangle([x, 0, x + 3, 127], fill=colors[1])
    img.save(path)


def test_groups_identical_images(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _write_stripes(a, ((0, 0, 0), (255, 255, 255)))
    _write_stripes(b, ((0, 0, 0), (255, 255, 255)))

    engine = ImageDedupEngine()
    engine.configure([tmp_path], [], {"phash_threshold": 8, "dhash_threshold": 10})
    groups = engine._group_images([a, b])  # direct unit-level clustering check
    assert len(groups) == 1
    assert len(groups[0].files) == 2


def test_does_not_group_different_stripes_default_thresholds(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _write_stripes(a, ((255, 0, 0), (0, 0, 255)))
    _write_stripes(b, ((0, 255, 0), (255, 255, 0)))

    engine = ImageDedupEngine()
    engine.configure([tmp_path], [], {"phash_threshold": 8, "dhash_threshold": 10})
    groups = engine._group_images([a, b])
    assert groups == []
