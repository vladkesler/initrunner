# Jev typed judgments

A few decisions inside InitRunner are judgment calls. Which of these fifty roles should handle "turn last week's merged PRs into release notes"? Is this tool result trying to give the agent orders? Code can't answer those, and asking a chat model to "reply with JSON" is slow, costs output tokens, and breaks whenever the reply isn't valid JSON.

[Jev](https://docs.typesafe.ai) is TypeSafe's System One model. It doesn't write text. You give it a state (some text or JSON) and typed questions: pick one of these options, place this on a scale, yes or no. It returns a calibrated probability for every possible answer in about 250 ms. You pay for input tokens only ($42 per billion). InitRunner uses it, when you turn it on, for the judgment calls it makes on your behalf.

Jev is optional. Without the extra and a key, nothing on this page happens and InitRunner behaves exactly as before.

## Setup

```bash
uv pip install "initrunner[jev]"
export TYPESAFE_API_KEY=...            # keys: https://console.typesafe.ai/keys
```

The key can live in the [vault](../security/vault.md) instead of your shell:

```bash
initrunner vault set TYPESAFE_API_KEY
```

`initrunner doctor` shows whether it's ready:

```
Jev typed judgments: Ready (jev-1.13.0) (optional; see docs/core/jev.md)
```

or what's missing:

```
Jev typed judgments: typesafe-sdk installed but TYPESAFE_API_KEY not set
```

### Through OpenRouter

If your model traffic already goes through OpenRouter, point the SDK at it. These are the SDK's own variables; InitRunner passes them through.

```bash
export TYPESAFE_BASE_URL=https://openrouter.ai/api
export TYPESAFE_API_KEY=$OPENROUTER_API_KEY
export TYPESAFE_DEFAULT_MODEL=~typesafe/jev-latest
```

`jev-latest` is an alias that moves when TypeSafe ships a new version. The thresholds below were tuned on `jev-1.13.0`; see [Model version](#model-version).

## Where InitRunner uses it

| Seam | Turned on by | What Jev decides | When Jev can't be reached |
|------|--------------|------------------|---------------------------|
| [Role routing](#role-routing) | Installing the extra and setting the key | Which role or flow target handles a task | Falls back to keyword scoring and the LLM tiebreaker |

## Role routing

`initrunner run --sense`, `--sense` on a [group](../orchestration/groups.md), and `strategy: sense` on a [flow](../orchestration/flow.md#routing-strategy) delegate all pick an agent for a task. Without Jev that's keyword scoring on names, descriptions and tags, with an LLM tiebreaker when the scores are close. Keyword scoring can be confidently wrong: "turn last week's merged PRs into release notes" matches `pr-reviewer` on "PRs" and never reaches the tiebreaker.

With Jev, InitRunner asks one question with every candidate as an option:

```python
{"agent": {
    "type": "choice",
    "instructions": "Which agent is the best fit to carry out `task`?",
    "criteria": {
        "changelog-generator": "Generates a CHANGELOG.md from git commit history (tags: example, git, developer-tools)",
        "pr-reviewer": "Reviews PR changes and produces GitHub-flavored Markdown ... (tags: ...)",
        # ... one entry per candidate ...
        "none_of_these": "No agent above is built for this task.",
    },
}}
```

The state is `{"task": "<your prompt>"}`, or the upstream agent's output in a flow. Jev returns a probability for every option. The highest real candidate wins, and the panel shows `Jev (confidence 0.73)`.

- **Below 0.6** the panel also shows the runner-up, so when sensing asks "Use this role?" you can see the alternative.
- **When `none_of_these` wins**, `--sense` stops with `No role fits this task. Closest: ...` and exits 1. Flows never abstain, because their targets are a closed set you chose.
- **`--dry-run`** never calls Jev.
- **Every flow routing decision** is recorded as a delegate event with a reason like `jev 0.78`, visible in the dashboard's flow Events tab and in `initrunner flow events`.

On the 26-prompt calibration set in `tests/jev/fixtures/routing.yaml`, Jev picked an acceptable role every time. The keyword pass got 13 of the 23 prompts that have a fitting role. The details are in [Intent Sensing](intent_sensing.md#with-jev).

## Model version

InitRunner pins `jev-1.13.0`. Every threshold on this page was tuned against it, and the pin is in `initrunner/jev/questions.py` next to those thresholds. Set `TYPESAFE_DEFAULT_MODEL` to use a different version.

Before moving the pin, run the live calibration suite with a real key:

```bash
uv run --extra jev pytest tests/jev/test_live.py -v -s
```

It prints accuracy for every seam and fails when one drops below its bar. Adjust the thresholds in `questions.py` rather than rewording the questions first. A change in wording is a change in the question, and it needs the whole suite again.

## Privacy and cost

Everything Jev judges is sent to TypeSafe's API, or OpenRouter's if you route through it:

- **Role routing** sends the task text (your prompt, or the upstream agent's output in a flow) and the name, description and tags of every candidate.

Set `TYPESAFE_LOG_LEVEL=debug` only on a machine you trust. The SDK then logs full request and response bodies, and it does not redact them.

A routing call over the 71 example roles measured 3,551 input tokens, about $0.00015.

## Code layout

- `initrunner/jev/client.py` is the only module that imports `typesafe_sdk`. It holds one shared client and turns every SDK failure into `JevError`.
- `initrunner/jev/questions.py` holds every question InitRunner asks and every threshold that acts on the answers, next to the pinned model.
