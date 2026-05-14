"""Static wiring checks for ReviewPage ``DeleteService`` (no Flet page required)."""

from __future__ import annotations

import ast
from pathlib import Path


def _review_page_ast() -> ast.Module:
    root = Path(__file__).resolve().parent.parent
    path = root / "cerebro" / "v2" / "ui" / "flet_app" / "pages" / "review_page.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def _class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    return None


def _find_method(tree: ast.Module, method_name: str) -> ast.FunctionDef | None:
    found = _class_method(tree, "ReviewPage", method_name)
    if found is not None:
        return found
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == method_name:
                return item
    return None


def _calls_delete_service_constructor(fn: ast.FunctionDef) -> bool:
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "DeleteService":
            return True
    return False


def test_review_page_init_assigns_delete_service() -> None:
    tree = _review_page_ast()
    init = _class_method(tree, "ReviewPage", "__init__")
    assert init is not None
    found = False
    for st in init.body:
        if not isinstance(st, ast.Assign):
            continue
        for t in st.targets:
            if isinstance(t, ast.Attribute) and t.attr == "_delete_service":
                if isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Name):
                    assert st.value.func.id == "DeleteService"
                    found = True
    assert found, "ReviewPage.__init__ should assign self._delete_service = DeleteService()"


def test_execute_smart_delete_does_not_instantiate_delete_service() -> None:
    root = Path(__file__).resolve().parent.parent
    path = root / "cerebro" / "v2" / "ui" / "flet_app" / "pages" / "review" / "review_mixins.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = _find_method(tree, "_execute_smart_delete")
    assert fn is not None
    assert not _calls_delete_service_constructor(fn)


def test_undo_uses_classmethod_not_per_call_constructor() -> None:
    root = Path(__file__).resolve().parent.parent
    path = root / "cerebro" / "v2" / "ui" / "flet_app" / "pages" / "review" / "review_mixins.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = _find_method(tree, "_undo_last_trash_delete")
    assert fn is not None
    assert not _calls_delete_service_constructor(fn)
