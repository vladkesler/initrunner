# Math Assistant

Step-by-step computation agent powered by an exact calculator. Breaks problems into sub-expressions, evaluates each one, and shows the full working. Handles arithmetic, trigonometry, logarithms, financial formulas, and unit conversions. Falls back to Python for matrices, symbolic math, or statistics on large datasets.

## Quick start

```bash
# Install
initrunner install vladkesler/math-assistant

# Interactive session (with memory)
initrunner run math-assistant -i

# One-shot question
initrunner run math-assistant -p "What is the monthly payment on a $350k mortgage at 6.5% for 30 years?"
```

Requires `OPENAI_API_KEY` (or configure another provider in `spec.model`).

## Example prompts

```
What is the monthly payment on a $350k mortgage at 6.5% for 30 years?
Calculate compound interest on $10,000 at 5% compounded monthly for 10 years
Convert 72 degrees Fahrenheit to Celsius
What is sin(45 degrees) + cos(30 degrees)?
I have exam scores: 85, 92, 78, 95, 88. What's the mean and standard deviation?
What is the distance between points (3, 4) and (7, 1)?
Factor the total into a 70/20/10 split for $15,750
```

## Example session

```
$ initrunner run math-assistant -i

You: What is the monthly payment on a $350k mortgage at 6.5% for 30 years?

> think: Monthly mortgage payment formula: M = P * [r(1+r)^n] / [(1+r)^n - 1]
> where P = 350000, annual rate = 0.065, r = 0.065/12, n = 30*12 = 360

Step 1: Monthly interest rate
> calculate("0.065 / 12")
= 0.005416666666666667

Step 2: Number of payments
> calculate("30 * 12")
= 360

Step 3: (1 + r)^n
> calculate("(1 + 0.005416666666666667) ** 360")
= 6.991586759698737

Step 4: Numerator: r * (1 + r)^n
> calculate("0.005416666666666667 * 6.991586759698737")
= 0.037871011198284826

Step 5: Denominator: (1 + r)^n - 1
> calculate("6.991586759698737 - 1")
= 5.991586759698737

Step 6: Monthly payment: P * (numerator / denominator)
> calculate("350000 * (0.037871011198284826 / 5.991586759698737)")
= 2212.24

**Monthly payment: $2,212.24**

Over 30 years you would pay $2,212.24 x 360 = $796,406.40 total,
of which $446,406.40 is interest.

You: Now show me the amortization for the first 3 months

> calculate("350000 * 0.005416666666666667")
= 1895.83 (month 1 interest)

> calculate("2212.24 - 1895.83")
= 316.41 (month 1 principal)

...

| Month | Payment  | Principal | Interest  | Balance     |
|-------|----------|-----------|-----------|-------------|
| 1     | $2,212.24| $316.41   | $1,895.83 | $349,683.59 |
| 2     | $2,212.24| $318.12   | $1,894.12 | $349,365.47 |
| 3     | $2,212.24| $319.85   | $1,892.39 | $349,045.62 |
```

## Customization

### Python fallback

Python is available for problems beyond the calculator's scope. It runs sandboxed with no network:

```yaml
tools:
  - type: python
    timeout_seconds: 15     # increase for heavy computation
    network_disabled: true
```

### Memory

Memory stores user preferences (preferred units, detail level, domain context):

```yaml
memory:
  semantic:
    max_memories: 200   # increase if you want more preference history
```

### Token budget

```yaml
guardrails:
  max_tokens_per_run: 30000   # per interaction turn
  max_tool_calls: 30          # increase for longer multi-step problems
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
    temperature: 0.1
```
