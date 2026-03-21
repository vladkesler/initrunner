"""Tests for the calculator tool: config, safe evaluation, and registration."""

from __future__ import annotations

import math

from initrunner.agent.schema.tools import CalculatorToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types
from initrunner.agent.tools.calculator import _evaluate, build_calculator_toolset


def _make_ctx():
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestCalculatorConfig:
    def test_defaults(self):
        config = CalculatorToolConfig()
        assert config.type == "calculator"
        assert config.max_expression_length == 1000

    def test_summary(self):
        assert CalculatorToolConfig().summary() == "calculator"

    def test_round_trip(self):
        config = CalculatorToolConfig(max_expression_length=500)
        data = config.model_dump()
        restored = CalculatorToolConfig.model_validate(data)
        assert restored.max_expression_length == 500

    def test_from_dict(self):
        config = CalculatorToolConfig.model_validate({"type": "calculator"})
        assert config.type == "calculator"

    def test_in_agent_spec(self):
        from initrunner.agent.schema.role import parse_tool_list

        tools = parse_tool_list([{"type": "calculator"}])
        assert len(tools) == 1
        assert isinstance(tools[0], CalculatorToolConfig)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_basic_arithmetic(self):
        assert _evaluate("2 + 3", 1000) == "5"
        assert _evaluate("10 - 4", 1000) == "6"
        assert _evaluate("3 * 7", 1000) == "21"
        assert _evaluate("15 / 4", 1000) == "3.75"

    def test_integer_result_from_float(self):
        assert _evaluate("6 / 2", 1000) == "3"
        assert _evaluate("10.0 + 5.0", 1000) == "15"

    def test_operator_precedence(self):
        assert _evaluate("2 + 3 * 4", 1000) == "14"
        assert _evaluate("(2 + 3) * 4", 1000) == "20"

    def test_floor_division(self):
        assert _evaluate("7 // 2", 1000) == "3"

    def test_modulo(self):
        assert _evaluate("7 % 3", 1000) == "1"

    def test_power(self):
        assert _evaluate("2 ** 10", 1000) == "1024"

    def test_unary_minus(self):
        assert _evaluate("-5 + 3", 1000) == "-2"

    def test_math_functions(self):
        assert _evaluate("sqrt(16)", 1000) == "4"
        assert _evaluate("abs(-42)", 1000) == "42"
        assert _evaluate("ceil(3.2)", 1000) == "4"
        assert _evaluate("floor(3.8)", 1000) == "3"

    def test_trig(self):
        result = float(_evaluate("sin(pi / 2)", 1000))
        assert abs(result - 1.0) < 1e-10

    def test_log(self):
        assert _evaluate("log10(1000)", 1000) == "3"
        result = float(_evaluate("log(e)", 1000))
        assert abs(result - 1.0) < 1e-10

    def test_log_with_base(self):
        assert _evaluate("log(8, 2)", 1000) == "3"

    def test_nested_functions(self):
        assert _evaluate("sqrt(abs(-16))", 1000) == "4"

    def test_constants(self):
        result = float(_evaluate("pi", 1000))
        assert abs(result - math.pi) < 1e-10
        result = float(_evaluate("tau", 1000))
        assert abs(result - math.tau) < 1e-10

    def test_round_func(self):
        assert _evaluate("round(3.14159)", 1000) == "3"

    def test_pow_func(self):
        assert _evaluate("pow(2, 10)", 1000) == "1024"

    # --- error cases ---

    def test_division_by_zero(self):
        assert _evaluate("1 / 0", 1000).startswith("Error:")

    def test_syntax_error(self):
        assert _evaluate("2 +", 1000).startswith("Error:")

    def test_expression_too_long(self):
        result = _evaluate("1 + " * 500 + "1", 10)
        assert "exceeds maximum length" in result

    def test_unknown_name(self):
        result = _evaluate("x + 1", 1000)
        assert "unknown name" in result

    def test_unknown_function(self):
        result = _evaluate("foo(1)", 1000)
        assert "unknown function" in result

    def test_injection_import(self):
        result = _evaluate("__import__('os')", 1000)
        assert "Error:" in result

    def test_injection_open(self):
        result = _evaluate("open('/etc/passwd')", 1000)
        assert "Error:" in result

    def test_injection_eval(self):
        result = _evaluate("eval('1+1')", 1000)
        assert "Error:" in result

    def test_attribute_access_blocked(self):
        result = _evaluate("(1).__class__", 1000)
        assert "Error:" in result

    def test_string_constant_blocked(self):
        result = _evaluate("'hello'", 1000)
        assert "Error:" in result

    def test_keyword_args_blocked(self):
        result = _evaluate("round(3.14, ndigits=1)", 1000)
        assert "Error:" in result

    def test_too_many_nodes(self):
        # Build expression with many nodes
        expr = " + ".join(["1"] * 60)
        result = _evaluate(expr, 10000)
        assert "too complex" in result

    def test_overflow(self):
        result = _evaluate("exp(10000)", 1000)
        assert "Error:" in result


# ---------------------------------------------------------------------------
# Toolset builder
# ---------------------------------------------------------------------------


class TestCalculatorToolset:
    def test_builds_with_calculate(self):
        config = CalculatorToolConfig()
        toolset = build_calculator_toolset(config, _make_ctx())
        assert "calculate" in toolset.tools

    def test_calculate_basic(self):
        config = CalculatorToolConfig()
        toolset = build_calculator_toolset(config, _make_ctx())
        fn = toolset.tools["calculate"].function
        assert fn(expression="2 + 2") == "4"

    def test_calculate_respects_max_length(self):
        config = CalculatorToolConfig(max_expression_length=5)
        toolset = build_calculator_toolset(config, _make_ctx())
        fn = toolset.tools["calculate"].function
        result = fn(expression="1 + 2 + 3")
        assert "exceeds maximum length" in result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestCalculatorRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "calculator" in types
        assert types["calculator"] is CalculatorToolConfig
