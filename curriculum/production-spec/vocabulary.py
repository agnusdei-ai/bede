"""Read current diagnostic vocabulary literals without importing database services."""
import ast

from schema import ContractError


def literal_vocabulary(path, symbol):
    """Fail closed if upstream stops declaring its vocabulary as literal data."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
            value = node.value
        else:
            continue
        if name == symbol:
            try:
                values = ast.literal_eval(value)
            except (ValueError, TypeError) as error:
                raise ContractError("upstream vocabulary needs adapter reconciliation") from error
            if not isinstance(values, (tuple, list)) or not all(
                isinstance(item, str) and item for item in values
            ):
                raise ContractError("unexpected upstream vocabulary")
            return set(values)
    raise ContractError(f"missing upstream vocabulary: {symbol}")


def existing_skills(root, math_module):
    """Mirror known_skill_ids' current union; factory uses that function directly."""
    skills = set(math_module.SKILL_MAP)
    for module, symbol in (
        ("phonics", "DOMAINS"), ("literacy", "DOMAINS"),
        ("composition", "DOMAINS"), ("language_exposure", "LANGUAGES"),
        ("music", "DOMAINS"),
    ):
        skills.update(literal_vocabulary(
            root / f"homeschool-api/services/diagnostic/{module}.py", symbol))
    return skills
