"""Tests for pipeline executor: topological sort, interpolation, execution."""

from unittest.mock import MagicMock, patch

from initrunner.pipeline.executor import (
    StepResult,
    _eval_condition,
    _interpolate,
    _topological_sort,
    run_pipeline,
)
from initrunner.pipeline.schema import (
    PipelineDefinition,
    PipelineMetadata,
    PipelineSpec,
    PipelineStep,
)


def _make_step(name: str, depends_on: list[str] | None = None, **kwargs) -> PipelineStep:
    return PipelineStep(
        name=name,
        role_file=kwargs.pop("role_file", "./roles/agent.yaml"),
        prompt=kwargs.pop("prompt", "test"),
        depends_on=depends_on or [],
        **kwargs,
    )


def _make_pipeline(steps: list[PipelineStep], **kwargs) -> PipelineDefinition:
    return PipelineDefinition(
        apiVersion="initrunner/v1",
        kind="Pipeline",
        metadata=PipelineMetadata(name="test-pipeline"),
        spec=PipelineSpec(steps=steps, **kwargs),
    )


class TestTopologicalSort:
    def test_single_step(self):
        steps = [_make_step("a")]
        tiers = _topological_sort(steps)
        assert len(tiers) == 1
        assert tiers[0][0].name == "a"

    def test_independent_steps_same_tier(self):
        steps = [_make_step("a"), _make_step("b"), _make_step("c")]
        tiers = _topological_sort(steps)
        assert len(tiers) == 1
        assert len(tiers[0]) == 3

    def test_sequential_dependencies(self):
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["b"]),
        ]
        tiers = _topological_sort(steps)
        assert len(tiers) == 3
        assert tiers[0][0].name == "a"
        assert tiers[1][0].name == "b"
        assert tiers[2][0].name == "c"

    def test_diamond_dependency(self):
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["a"]),
            _make_step("d", depends_on=["b", "c"]),
        ]
        tiers = _topological_sort(steps)
        assert len(tiers) == 3
        assert tiers[0][0].name == "a"
        tier1_names = {s.name for s in tiers[1]}
        assert tier1_names == {"b", "c"}
        assert tiers[2][0].name == "d"


class TestInterpolation:
    def test_simple_variable(self):
        result = _interpolate("Hello {{name}}", {"name": "world"}, {})
        assert result == "Hello world"

    def test_step_output(self):
        outputs = {"step1": StepResult(name="step1", output="the result")}
        result = _interpolate("Got: {{steps.step1.output}}", {}, outputs)
        assert result == "Got: the result"

    def test_step_json_key(self):
        outputs = {
            "step1": StepResult(
                name="step1", output='{"summary": "hello"}', parsed_output={"summary": "hello"}
            )
        }
        result = _interpolate("Summary: {{steps.step1.output.summary}}", {}, outputs)
        assert result == "Summary: hello"

    def test_json_key_non_dict_fallback(self):
        outputs = {
            "step1": StepResult(name="step1", output="plain text", parsed_output="plain text")
        }
        result = _interpolate("{{steps.step1.output.key}}", {}, outputs)
        # Should leave unreplaced since parsed_output is not a dict
        assert result == "{{steps.step1.output.key}}"

    def test_unknown_variable_left_unreplaced(self):
        result = _interpolate("{{unknown}}", {}, {})
        assert result == "{{unknown}}"

    def test_unknown_step_left_unreplaced(self):
        result = _interpolate("{{steps.missing.output}}", {}, {})
        assert result == "{{steps.missing.output}}"

    def test_multiple_variables(self):
        result = _interpolate("{{greeting}} {{name}}!", {"greeting": "Hi", "name": "Alice"}, {})
        assert result == "Hi Alice!"


class TestConditionEvaluation:
    def test_true_values(self):
        for val in ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]:
            assert _eval_condition(val, {}, {}) is True

    def test_false_values(self):
        for val in ["false", "False", "FALSE", "0", "no", "No", "NO", ""]:
            assert _eval_condition(val, {}, {}) is False

    def test_variable_resolution(self):
        assert _eval_condition("{{enabled}}", {"enabled": "true"}, {}) is True
        assert _eval_condition("{{enabled}}", {"enabled": "false"}, {}) is False

    def test_nonempty_string_is_truthy(self):
        assert _eval_condition("some_value", {}, {}) is True


class TestRunPipeline:
    @patch("initrunner.pipeline.executor._execute_step")
    def test_single_step_success(self, mock_exec, tmp_path):
        mock_exec.return_value = StepResult(name="step1", output="done", success=True)

        pipe = _make_pipeline([_make_step("step1")])
        result = run_pipeline(pipe, base_dir=tmp_path)

        assert result.success is True
        assert len(result.step_results) == 1
        assert result.step_results[0].output == "done"

    @patch("initrunner.pipeline.executor._execute_step")
    def test_fail_fast_skips_remaining(self, mock_exec, tmp_path):
        def exec_side_effect(step, *args, **kwargs):
            if step.name == "a":
                return StepResult(name="a", success=False, error="boom")
            return StepResult(name=step.name, output="ok", success=True)

        mock_exec.side_effect = exec_side_effect

        pipe = _make_pipeline(
            [
                _make_step("a"),
                _make_step("b", depends_on=["a"]),
            ],
            error_strategy="fail-fast",
        )
        result = run_pipeline(pipe, base_dir=tmp_path)

        assert result.success is False
        assert result.step_results[0].success is False
        assert result.step_results[1].skipped is True

    @patch("initrunner.pipeline.executor._execute_step")
    def test_continue_strategy_runs_all(self, mock_exec, tmp_path):
        def exec_side_effect(step, *args, **kwargs):
            if step.name == "a":
                return StepResult(name="a", success=False, error="boom")
            return StepResult(name=step.name, output="ok", success=True)

        mock_exec.side_effect = exec_side_effect

        pipe = _make_pipeline(
            [
                _make_step("a"),
                _make_step("b", depends_on=["a"]),
            ],
            error_strategy="continue",
        )
        result = run_pipeline(pipe, base_dir=tmp_path)

        assert result.success is False
        assert not result.step_results[1].skipped

    @patch("initrunner.pipeline.executor._execute_step")
    def test_parallel_steps(self, mock_exec, tmp_path):
        def exec_fn(step, *args, **kwargs):
            return StepResult(name=step.name, output="done", success=True)

        mock_exec.side_effect = exec_fn

        pipe = _make_pipeline([_make_step("a"), _make_step("b"), _make_step("c")])
        result = run_pipeline(pipe, base_dir=tmp_path)

        assert result.success is True
        assert len(result.step_results) == 3

    @patch("initrunner.pipeline.executor._execute_step")
    def test_variables_passed_through(self, mock_exec, tmp_path):
        captured_vars = {}

        def exec_fn(step, variables, *args, **kwargs):
            captured_vars.update(variables)
            return StepResult(name=step.name, output="ok", success=True)

        mock_exec.side_effect = exec_fn

        pipe = _make_pipeline([_make_step("a")])
        run_pipeline(pipe, variables={"topic": "AI"}, base_dir=tmp_path)

        assert captured_vars["topic"] == "AI"

    @patch("initrunner.pipeline.executor._execute_step")
    def test_condition_skip(self, mock_exec, tmp_path):
        def exec_fn(step, variables, step_outputs, *args, **kwargs):
            sr = StepResult(name=step.name, skipped=True, skip_reason="Condition not met")
            return sr

        mock_exec.side_effect = exec_fn

        pipe = _make_pipeline([_make_step("a", condition="{{enabled}}")])
        result = run_pipeline(pipe, variables={"enabled": "false"}, base_dir=tmp_path)

        assert result.success is True  # Skipped steps don't count as failures

    @patch("initrunner.pipeline.executor._execute_step")
    def test_pipeline_result_has_id(self, mock_exec, tmp_path):
        mock_exec.return_value = StepResult(name="a", output="ok", success=True)
        pipe = _make_pipeline([_make_step("a")])
        result = run_pipeline(pipe, base_dir=tmp_path)

        assert len(result.pipeline_id) == 12
        assert result.pipeline_name == "test-pipeline"
        assert result.duration_ms >= 0


class TestExecuteStepIntegration:
    """Test _execute_step with real inline/mcp logic (mocked at agent level)."""

    def test_inline_step_with_mock_agent(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("test-step", prompt="hello world")

        mock_result = RunResult(run_id="r1", output="agent says hi", success=True)

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert sr.success is True
        assert sr.output == "agent says hi"

    def test_inline_step_json_output(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("json-step", prompt="give me json", output_format="json")

        mock_result = RunResult(
            run_id="r1",
            output='{"summary": "test", "score": 42}',
            success=True,
        )

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert sr.success is True
        assert isinstance(sr.parsed_output, dict)
        assert sr.parsed_output["summary"] == "test"
        assert sr.parsed_output["score"] == 42
        # Verify output_type=dict was passed for json steps
        build_kwargs = mock_build.call_args
        assert build_kwargs.kwargs["output_type"] is dict

    def test_inline_step_json_fallback(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("json-step", prompt="give me json", output_format="json")

        mock_result = RunResult(run_id="r1", output="not json at all", success=True)

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert sr.success is True
        assert sr.parsed_output == "not json at all"

    def test_condition_false_skips(self, tmp_path):
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("conditional", condition="false")
        sr = _execute_step(step, {}, {}, None, tmp_path)
        assert sr.skipped is True
        assert sr.skip_reason is not None and "Condition not met" in sr.skip_reason

    def test_condition_true_runs(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("conditional", condition="true")
        mock_result = RunResult(run_id="r1", output="ran", success=True)

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert not sr.skipped
        assert sr.success is True

    def test_mcp_step(self, tmp_path):
        from initrunner.agent.delegation import McpInvoker
        from initrunner.pipeline.executor import _execute_step

        step = PipelineStep(
            name="remote",
            url="http://agent:8000",
            mode="mcp",
            prompt="hello",
        )

        with patch.object(McpInvoker, "invoke", return_value="remote response"):
            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert sr.success is True
        assert sr.output == "remote response"

    def test_step_failure(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("failing")
        mock_result = RunResult(run_id="r1", success=False, error="API error")

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            sr = _execute_step(step, {}, {}, None, tmp_path)

        assert sr.success is False
        assert sr.error == "API error"

    def test_prompt_interpolation(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("interp", prompt="Research {{topic}}")
        mock_result = RunResult(run_id="r1", output="done", success=True)

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            _execute_step(step, {"topic": "AI safety"}, {}, None, tmp_path)

        call_args = mock_exec.call_args
        prompt_sent = call_args.args[2]
        assert "AI safety" in prompt_sent

    def test_text_step_uses_str_output_type(self, tmp_path):
        from initrunner.agent.executor import RunResult
        from initrunner.pipeline.executor import _execute_step

        step = _make_step("text-step", prompt="hello", output_format="text")
        mock_result = RunResult(run_id="r1", output="done", success=True)

        with (
            patch("initrunner.agent.loader.load_role") as mock_load,
            patch("initrunner.agent.loader.build_agent") as mock_build,
            patch("initrunner.agent.executor.execute_run") as mock_exec,
        ):
            mock_load.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            mock_exec.return_value = (mock_result, [])

            _execute_step(step, {}, {}, None, tmp_path)

        build_kwargs = mock_build.call_args
        assert build_kwargs.kwargs["output_type"] is str
