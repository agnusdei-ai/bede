"""
COPPA readiness, control C-35 (docs/COPPA_READINESS_CHECKLIST.md): the
records-of-processing inventory in docs/COPPA_READINESS_TEMPLATES.md must
name every table that holds a family's child-scoped data.

The authoritative list of child-scoped tables is the cascade in
services/student_deletion.py: a table is in that cascade because it is
scoped to one student. The inventory is a human document, so the check is
that each cascade table, and the student key store, appears in it by name.
A table added to the cascade without an inventory row fails here.

Verified by breaking it: deleting a row from the inventory fails the
parametrised case for that table.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API = REPO / "homeschool-api"
INVENTORY = REPO / "docs" / "COPPA_READINESS_TEMPLATES.md"


def _cascade_models() -> list[str]:
    """Model class names in services/student_deletion.py's deletion tuples."""
    tree = ast.parse((API / "services" / "student_deletion.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            first, second = node.elts
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and isinstance(second, ast.Name)
                and second.id[:1].isupper()
            ):
                names.append(second.id)
    return sorted(set(names))


def _table_name_for(model: str) -> str:
    """The __tablename__ of a model class in core/database.py."""
    source = (API / "core" / "database.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == model:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets
                ):
                    return stmt.value.value
    raise AssertionError(f"{model} has no __tablename__ in core/database.py")


def _inventory_tables() -> set[str]:
    text = INVENTORY.read_text(encoding="utf-8")
    section = text.split("## C-35.", 1)[1]
    return set(re.findall(r"^\| \d+ \| `([a-z_]+)` \|", section, flags=re.MULTILINE))


CASCADE_TABLES = sorted({_table_name_for(m) for m in _cascade_models()} | {"student_keys"})


def test_the_cascade_list_is_not_empty():
    """Guard on the guard: if the parser finds nothing, every parametrised
    case below silently disappears and the test passes."""
    assert len(_cascade_models()) >= 15


@pytest.mark.parametrize("table", CASCADE_TABLES)
def test_every_child_scoped_table_is_in_the_processing_inventory(table):
    assert table in _inventory_tables(), (
        f"{table} is deleted by services/student_deletion.py (or is the student key store) "
        "but has no row in the C-35 processing inventory in docs/COPPA_READINESS_TEMPLATES.md"
    )
