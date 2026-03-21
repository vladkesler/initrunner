---
name: step-by-step
description: >
  Decompose mathematical problems into sub-expressions, evaluate each
  one with the calculator tool, and present the full working chain.
  Handles arithmetic, trigonometry, logarithms, and financial formulas.
---

Step-by-step computation skill.

## When to activate

Use this skill when the user asks you to:
- Solve a math problem or evaluate an expression
- Show your working or explain how to compute something
- Calculate financial values (interest, payments, returns)
- Convert units or work with formulas
- Verify a number or check a calculation

## Methodology

### 1. Parse the problem

Use the think tool to identify:
- What quantity the user wants computed
- Which formula or approach applies
- What the input values are (with units)
- Whether any values need conversion first

### 2. Decompose into steps

Break the problem into calculator-sized sub-expressions. Each step
should evaluate to a single number. Plan the sequence so each step
builds on the previous result.

Example decomposition for compound interest `A = P(1 + r/n)^(nt)`:
1. Calculate the periodic rate: `r / n`
2. Add 1: `1 + <step1>`
3. Calculate the exponent: `n * t`
4. Raise to power: `<step2> ** <step3>`
5. Multiply by principal: `P * <step4>`

### 3. Evaluate each step

Call the calculator for every sub-expression. Present each step as:

```
Step N: <description>
  <expression> = <result>
```

Never skip steps or do mental arithmetic. The calculator is exact and
its results are auditable.

### 4. Handle calculator limitations

The calculator supports:
- Arithmetic: `+`, `-`, `*`, `/`, `//`, `%`, `**`
- Functions: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sqrt`,
  `log`, `log10`, `log2`, `exp`, `abs`, `ceil`, `floor`, `round`, `pow`
- Constants: `pi`, `e`, `tau`, `inf`

It does NOT support:
- Variable assignment (`x = 5`)
- Summation, product, or loop notation
- Symbolic algebra
- Matrix operations
- Complex numbers

For unsupported operations, use the python tool. State clearly when
you are switching to python and why.

### 5. Verify the result

After computing the final answer, verify it using one of:
- **Reverse calculation**: work backwards from the answer
- **Estimation**: check the order of magnitude makes sense
- **Alternative formula**: use a different approach to get the same result

### 6. Present the answer

State the final answer with:
- The value, rounded appropriately for context
- Units (if applicable)
- A one-line summary of what it means in plain language

## MUST

- Call the calculator for every arithmetic step, no exceptions
- Show every intermediate step and its result
- Include units throughout the working
- Verify the final answer with a check step
- Use the think tool to plan the decomposition before calculating

## MUST NOT

- Present a number without having calculated it with a tool
- Skip intermediate steps even if they seem obvious
- Use the calculator for problems it cannot handle (use python instead)
- Round intermediate results -- keep full precision until the final answer
- Assume formula correctness from memory -- derive or verify first
