"""Deterministic tools for the demo support agent (no network, so evals are repeatable).

The shop, its policies and its orders are fictional.
"""

import ast
import operator
import re
from typing import Any


class ToolError(Exception):
    """A tool failed in a way the model should hear about (e.g. unknown order)."""


KB = {
    "returns": "Returns: items can be returned within 30 days of delivery for a full refund. "
    "Items must be unused. Return shipping is free for orders over $50.",
    "shipping": "Shipping: standard delivery takes 3-5 business days and costs $4.99; "
    "it is free for orders over $50. Express delivery takes 1-2 business days and costs $12.",
    "warranty": "Warranty: electronics carry a 2-year warranty covering manufacturing "
    "defects. Accidental damage is not covered.",
    "payment": "Payment: we accept Visa, Mastercard and PayPal. Refunds go back to the "
    "original payment method within 5 business days.",
}

ORDERS = {
    "A1001": {
        "status": "delivered",
        "item": "Wireless headphones",
        "total": 79.0,
        "delivered": "2026-11-02",
    },
    "A1002": {"status": "shipped", "item": "USB-C charger", "total": 19.5, "eta": "2026-11-18"},
    "A1003": {"status": "processing", "item": "Mechanical keyboard", "total": 129.0},
}


def search_kb(query: str) -> list[dict[str, str]]:
    """Help-centre articles ranked by how many query words they contain (top 2)."""
    words = set(re.findall(r"[a-z]+", query.lower()))
    scored = [(sum(w in text.lower() for w in words), topic, text) for topic, text in KB.items()]
    hits = [(s, t, x) for s, t, x in sorted(scored, key=lambda r: -r[0]) if s > 0][:2]
    return [{"topic": t, "text": x} for _, t, x in hits]


def get_order(order_id: str) -> dict[str, Any]:
    order = ORDERS.get(order_id.strip().upper())
    if order is None:
        raise ToolError(f"No order with id {order_id!r}.")
    return {"order_id": order_id.strip().upper(), **order}


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def calculate(expression: str) -> float:
    """Arithmetic only (+ - * / ** and parentheses); anything else is rejected."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 100:
                raise ToolError("Exponent too large.")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ToolError(f"Unsupported expression: {expression!r}")

    try:
        return ev(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ToolError(f"Cannot calculate {expression!r}: {exc}") from exc


TOOLS = {"search_kb": search_kb, "get_order": get_order, "calculate": calculate}

# JSON schemas the model sees.
DECLARATIONS = [
    {
        "name": "search_kb",
        "description": "Search the shop's help-centre articles (returns, shipping, "
        "warranty, payment). Use it for any policy question.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look up"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_order",
        "description": "Look up an order by its id (like A1001): status, item, total, dates.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate an arithmetic expression, e.g. '79 * 0.1'. Use it for any maths.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
]
