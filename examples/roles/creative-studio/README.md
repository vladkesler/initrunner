# Creative Studio

AI image generation assistant powered by DALL-E. Translates natural language descriptions into detailed generation prompts, generates images, iterates on style and composition, and edits existing images. Learns your visual preferences over time.

## Quick start

```bash
# Install
initrunner install vladkesler/creative-studio

# Create the output and input directories
mkdir -p output input

# Interactive session (with memory)
initrunner run creative-studio -i

# One-shot generation
initrunner run creative-studio -p "Generate a logo for a coffee shop called Brewed Awakening"
```

Requires `OPENAI_API_KEY` for DALL-E image generation.

## Example prompts

```
Generate a logo for a coffee shop called Brewed Awakening
Create a hero image for a tech blog about AI
Make a portrait-oriented phone wallpaper with a mountain sunset
Generate a minimalist icon set: home, settings, profile, search
Edit input/photo.png to add a dreamy watercolor effect
Create 3 variations of a social media banner for a product launch
I want something in the style of Japanese woodblock prints
Generate a professional headshot background, soft gradient, blue tones
```

## Example session

```
$ initrunner run creative-studio -i

You: Generate a logo for a coffee shop called Brewed Awakening

> think: The user wants a logo. Key considerations:
> - Subject: coffee shop logo
> - Name: "Brewed Awakening" (wordplay on "rude awakening")
> - Style: should feel warm, inviting, morning-themed
> - Note: DALL-E renders text poorly, so focus on the visual mark

> recall("style_preference")
No saved preferences yet.

I'll generate a visual logo mark (without text, since AI-generated text
in images is unreliable). Here's the prompt I'll use:

**Prompt**: A minimalist coffee shop logo mark, a steaming coffee cup
with sunrise rays emanating from behind it, warm golden and brown
tones, clean vector art style, centered composition on white background,
professional brand identity design

**Size**: 1024x1024 (square, standard for logos)
**Style**: natural
**Quality**: hd

Shall I generate this, or would you like to adjust the concept?

You: Looks good, go ahead

> generate_image(prompt="A minimalist coffee shop logo mark, a steaming
  coffee cup with sunrise rays emanating from behind it, warm golden and
  brown tones, clean vector art style, centered composition on white
  background, professional brand identity design",
  size="1024x1024", style="natural", quality="hd")

Generated: ./output/20260321_143052_a8f2.png

The image shows a clean coffee cup silhouette with stylized sunrise rays
in warm gold and espresso brown. The vector style keeps it versatile for
print and web use.

> remember("User is designing branding for 'Brewed Awakening' coffee shop.
  Prefers warm tones, minimalist/clean style, professional look.",
  category="style_preference")

Want me to generate variations with different styles, or adjust this one?
```

## Customization

### Output and input directories

Generated images are saved to `./output`. Source images for edits go in `./input`:

```yaml
tools:
  - type: image_gen
    output_dir: "./output"     # where generated images are saved
    input_root: "./input"      # where edit source images are read from
```

### Using Stability AI instead of DALL-E

```yaml
tools:
  - type: image_gen
    provider: stability
    api_key_env: "${STABILITY_API_KEY}"
    output_dir: "./output"
```

Note: `edit_image` and the `style`/`quality` parameters are OpenAI-only.

### Image defaults

```yaml
tools:
  - type: image_gen
    default_size: "1024x1024"    # 1024x1024, 1792x1024, 1024x1792
    default_quality: "standard"  # standard, hd
    default_style: "natural"     # natural, vivid
```

### Memory

Memory stores style preferences and prompt patterns that worked:

```yaml
memory:
  semantic:
    max_memories: 300    # style preferences, brand guidelines
  procedural:
    max_procedures: 100  # learned prompt patterns
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
    temperature: 0.3
```

The model handles prompt crafting and conversation. Image generation always uses the configured `image_gen` provider (OpenAI or Stability) regardless of the conversation model.
