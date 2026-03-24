"""Calculator tool: safe AST-based math expression evaluator."""

from __future__ import annotations

import ast
import math
import operator
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema.tools import CalculatorToolConfig
from initrunner.agent.tools._registry import register_tool

if TYPE_CHECKING:
    from initrunner.agent.tools._registry import ToolBuildContext

_MAX_AST_NODES = 100

_ALLOWED_NAMES: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}

_ALLOWED_FUNCS: dict[str, object] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "pow": pow,
}

_BIN_OPS: dict[type, object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type, object] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _count_nodes(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def _safe_eval(node: ast.AST) -> float | int:
    """Recursively evaluate an AST node using only allowed operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        raise ValueError(f"unknown name: {node.id!r}")

    if isinstance(node, ast.BinOp):
        op_func = _BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return op_func(left, right)  # type: ignore[operator]

    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op_func(_safe_eval(node.operand))  # type: ignore[operator]

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only direct function calls are allowed")
        func = _ALLOWED_FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(f"unknown function: {node.func.id!r}")
        args = [_safe_eval(arg) for arg in node.args]
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        return func(*args)  # type: ignore[operator]

    raise ValueError(f"unsupported expression type: {type(node).__name__}")


def _evaluate(expression: str, max_length: int) -> str:
    """Evaluate a math expression safely and return the result as a string."""
    if len(expression) > max_length:
        return f"Error: expression exceeds maximum length ({max_length} chars)"

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return f"Error: invalid expression: {exc.msg}"

    if _count_nodes(tree) > _MAX_AST_NODES:
        return f"Error: expression too complex (>{_MAX_AST_NODES} nodes)"

    try:
        result = _safe_eval(tree)
    except ZeroDivisionError:
        return "Error: division by zero"
    except OverflowError:
        return "Error: result too large (overflow)"
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: evaluation failed: {exc}"

    if isinstance(result, float):
        if result == int(result) and not (math.isinf(result) or math.isnan(result)):
            return str(int(result))
        return str(result)
    return str(result)


@register_tool("calculator", CalculatorToolConfig)
def build_calculator_toolset(
    config: CalculatorToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset with a single ``calculate`` tool."""
    toolset = FunctionToolset()

    @toolset.tool_plain
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression and return the result.

        Supports arithmetic (+, -, *, /, //, %, **), math functions
        (sin, cos, tan, sqrt, log, exp, abs, ceil, floor, round, pow),
        and constants (pi, e, tau, inf).

        Examples: "2 + 3 * 4", "sqrt(16)", "sin(pi / 2)", "log(100, 10)"

        Args:
            expression: The mathematical expression to evaluate.
        """
        return _evaluate(expression, config.max_expression_length)

    return toolset
