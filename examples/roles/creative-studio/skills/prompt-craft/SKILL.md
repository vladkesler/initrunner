---
name: prompt-craft
description: >
  Translate natural language image descriptions into detailed,
  structured DALL-E prompts with subject, style, composition,
  lighting, and mood specifications.
---

Image prompt crafting skill.

## When to activate

Use this skill when you need to construct a prompt for generate_image
from a user's description. Always activate this before calling
generate_image.

## Methodology

### 1. Extract intent

Parse the user's description for:
- **Subject**: what is in the image (person, object, scene, abstract)
- **Style**: art style (photorealistic, illustration, watercolor, etc.)
- **Mood**: emotional tone (calm, energetic, mysterious, professional)
- **Colors**: specific colors or palette preferences
- **Composition**: framing, perspective, layout
- **Context**: where will this image be used (logo, social media,
  presentation, personal)

If any of these are missing and matter for the result, ask the user.

### 2. Check memory

Recall style preferences and brand guidelines:
```
recall("style_preference")
recall("brand_guideline")
```

Apply any saved preferences unless the user's current request
explicitly overrides them.

### 3. Build the prompt

Construct the prompt using this structure:

```
[Subject description], [style], [composition], [lighting], [mood], [details]
```

**Rules for effective prompts:**
- Be specific about the subject: "a golden retriever puppy sitting
  on a red cushion" not "a dog"
- Name the art style explicitly: "digital illustration", "oil painting
  style", "35mm film photography", "vector art"
- Specify lighting: "soft natural light", "dramatic side lighting",
  "neon glow", "golden hour"
- Include composition cues: "close-up", "wide angle", "bird's eye
  view", "centered", "rule of thirds"
- Add atmosphere: "moody", "minimalist", "vibrant", "muted tones"
- Keep prompts under 400 characters for best results
- Avoid negations ("no background") -- describe what you want, not
  what you do not want

### 4. Select parameters

Choose the right parameters for the use case:

| Use case | Size | Style | Quality |
|----------|------|-------|---------|
| Social media post | 1024x1024 | vivid | standard |
| Blog header | 1792x1024 | natural | hd |
| Phone wallpaper | 1024x1792 | vivid | hd |
| Logo / icon | 1024x1024 | natural | hd |
| Quick concept | 1024x1024 | natural | standard |

### 5. Present for confirmation

Show the user:
1. The crafted prompt (exact text that will be sent)
2. The chosen size, style, and quality
3. A brief explanation of what to expect

Wait for approval before generating.

### 6. Learn from feedback

After the user sees the result:
- If they like it, save the prompt pattern as a procedural memory
- If they want changes, note what to adjust and iterate
- If they express a style preference, save it to semantic memory

## MUST

- Always use the think tool to plan the prompt before presenting it
- Always present the prompt for confirmation before generating
- Always recall style preferences from memory before crafting
- Include an art style specification in every prompt
- Choose parameters that match the stated use case

## MUST NOT

- Generate without showing the prompt first
- Use vague prompts ("a nice picture of a sunset")
- Name specific living artists in prompts
- Include text-heavy prompts (DALL-E renders text poorly -- warn the
  user if they want text in the image)
- Ignore previously saved style preferences without reason
