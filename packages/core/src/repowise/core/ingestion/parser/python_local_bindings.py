"""Python names a function binds locally, which shadow module-level names.

``C = make(); C()`` inside ``f`` calls the local value, never a module-level
``class C``. Only the enclosing function's own body counts: nested functions,
classes and lambdas have their own scope, and ``global`` / ``nonlocal``
declarations hand the name back to an outer scope.
"""

from __future__ import annotations

from tree_sitter import Node

from ..extractors import node_text

_SCOPES = frozenset({"function_definition", "class_definition", "lambda"})
_UNPACKING = frozenset(
    {
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "list_splat_pattern",
        "tuple",
        "list",
        "parenthesized_expression",
    }
)
_TARGET_FIELDS = {
    "assignment": "left",
    "augmented_assignment": "left",
    "for_statement": "left",
    "named_expression": "name",
    "for_in_clause": "left",
}


def _enclosing_function(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type == "function_definition":
            return parent
        if parent.type in ("class_definition", "lambda"):
            return None
        parent = parent.parent
    return None


def _target_names(target: Node, src: str) -> set[str]:
    """Bare identifiers *target* binds (``a``, ``a, b``, ``[a, *b]``)."""
    if target.type == "identifier":
        return {node_text(target, src)}
    if target.type in _UNPACKING:
        out: set[str] = set()
        for child in target.named_children:
            out |= _target_names(child, src)
        return out
    return set()  # attribute / subscript targets bind nothing local


def _bound_names(function: Node, src: str) -> tuple[set[str], set[str]]:
    """``(bound, declared outer)`` names of *function*'s own scope."""
    bound: set[str] = set()
    outer: set[str] = set()
    params = function.child_by_field_name("parameters")
    if params is not None:
        for param in params.named_children:
            ident = (
                param
                if param.type == "identifier"
                else next((c for c in param.named_children if c.type == "identifier"), None)
            )
            if ident is not None:
                bound |= _target_names(ident, src)
    body = function.child_by_field_name("body")
    stack = list(body.named_children) if body is not None else []
    while stack:
        node = stack.pop()
        if node.type in _SCOPES:
            # Its own scope. Its name is left alone: a nested def can itself be
            # the symbol a bare call means.
            continue
        if node.type in ("global_statement", "nonlocal_statement"):
            outer |= {node_text(c, src) for c in node.named_children if c.type == "identifier"}
            continue
        field = _TARGET_FIELDS.get(node.type)
        if field is not None:
            target = node.child_by_field_name(field)
            if target is not None:
                bound |= _target_names(target, src)
        if node.type == "as_pattern":
            alias = node.child_by_field_name("alias")
            if alias is not None:
                for c in [alias, *alias.named_children]:
                    bound |= _target_names(c, src)
        stack.extend(node.named_children)
    return bound, outer


def is_locally_bound(site_node: Node, name: str, src: str) -> bool:
    """Does the function enclosing *site_node* bind *name* in its own scope?"""
    function = _enclosing_function(site_node)
    if function is None:
        return False
    bound, outer = _bound_names(function, src)
    return name in bound and name not in outer
