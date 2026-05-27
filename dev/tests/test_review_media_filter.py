from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.media_filter import (
    file_media_bucket,
    filter_paths_for_media_scope,
    files_in_media_bucket,
)
from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import apply_rule_with_pipeline
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, SetSelection


def _file(name: str, ext: str, size: int = 1000) -> DuplicateFile:
    return DuplicateFile(
        path=Path(f"/tmp/mixed/{name}"),
        size=size,
        modified=0.0,
        extension=ext,
    )


def test_file_media_bucket() -> None:
    assert file_media_bucket(_file("a.jpg", "jpg")) == "pictures"
    assert file_media_bucket(_file("b.mp4", "mp4")) == "videos"


def test_filter_paths_for_media_scope() -> None:
    files = [_file("a.jpg", "jpg"), _file("b.mp4", "mp4"), _file("c.jpg", "jpg")]
    paths = {str(f.path) for f in files}
    scoped = filter_paths_for_media_scope(
        files, paths, enabled=True, media_type="pictures"
    )
    assert scoped == {str(files[0].path), str(files[2].path)}


def test_smart_rule_scoped_to_pictures_only() -> None:
    group = DuplicateGroup(
        group_id=1,
        files=[
            _file("old.jpg", "jpg", size=100),
            _file("new.jpg", "jpg", size=200),
            _file("clip.mp4", "mp4", size=300),
        ],
    )
    pictures = files_in_media_bucket(group.files, "pictures")
    keeper = apply_rule_with_pipeline("keep_largest", pictures)
    assert keeper.path.name == "new.jpg"

    state = ReviewFlowState(scan_results=[group])
    state.selection_media_filter_enabled = True
    state.selection_media_type = "pictures"

    sel = state.set_selections.setdefault(1, SetSelection())
    for f in group.files:
        p = str(f.path)
        if not state.file_in_selection_media_scope(f):
            continue
        if p == str(keeper.path):
            sel.kept_paths.add(p)
        else:
            sel.deleted_paths.add(p)
            state.marked_paths.add(p)

    assert str(group.files[2].path) not in state.marked_paths
    assert str(group.files[0].path) in state.marked_paths
    state._recompute_cart_counters()
    assert state.cart_delete_count == 1
    buckets = state.cart_buckets()
    assert len(buckets["delete"]) == 1
    assert buckets["delete"][0].path.name == "old.jpg"


def test_visible_groups_filter_by_media_type() -> None:
    g1 = DuplicateGroup(
        group_id=1,
        files=[_file("a.png", "png"), _file("b.png", "png")],
    )
    g2 = DuplicateGroup(
        group_id=2,
        files=[_file("x.py", "py"), _file("y.py", "py")],
    )
    g3 = DuplicateGroup(
        group_id=3,
        files=[_file("mix.png", "png"), _file("mix.py", "py")],
    )
    state = ReviewFlowState(scan_results=[g1, g2, g3])
    state.selection_media_filter_enabled = True
    state.selection_media_type = "pictures"
    visible = state.visible_groups()
    assert {g.group_id for g in visible} == {1, 3}


def test_prune_marks_outside_media_scope() -> None:
    g = DuplicateGroup(
        group_id=1,
        files=[_file("a.png", "png"), _file("b.py", "py")],
    )
    state = ReviewFlowState(scan_results=[g])
    state.marked_paths = {str(g.files[0].path), str(g.files[1].path)}
    state.selection_media_filter_enabled = True
    state.selection_media_type = "pictures"
    state.prune_marks_outside_media_scope()
    assert str(g.files[0].path) in state.marked_paths
    assert str(g.files[1].path) not in state.marked_paths
