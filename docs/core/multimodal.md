# Multimodal Input

InitRunner supports sending images, audio, video, and documents alongside text prompts. Multimodal input works across the CLI, interactive REPL, OpenAI-compatible API server, and web dashboard.

## Supported File Types

| Category | Extensions | Notes |
|----------|-----------|-------|
| Image | `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` | Most models support these natively |
| Audio | `.mp3`, `.wav`, `.ogg`, `.flac`, `.aac` | Requires model support (e.g. `gpt-4o-audio-preview`) |
| Video | `.mp4`, `.webm`, `.mov`, `.mkv` | Limited model support |
| Document | `.pdf`, `.docx`, `.xlsx` | Sent as binary content |
| Text | `.txt`, `.md`, `.csv`, `.html` | Inlined as text in the prompt |

**Size limit:** 20 MB per file.

## CLI Usage

Use `--attach` (or `-A`) to attach files or URLs to a prompt. The flag is repeatable.

```bash
# Single file
initrunner run role.yaml -p "Describe this image" -A photo.png

# Multiple files
initrunner run role.yaml -p "Compare these" -A before.png -A after.png

# URL attachment
initrunner run role.yaml -p "What's in this image?" -A https://example.com/photo.jpg

# Mixed files and URLs
initrunner run role.yaml -p "Summarize" -A report.pdf -A https://example.com/chart.png
```

`--attach` requires `-p` (or piped stdin). Without a prompt, the command exits with an error.

## Interactive REPL

In interactive mode (`-i`), three commands manage attachments:

| Command | Description |
|---------|-------------|
| `/attach <path_or_url>` | Queue a file or URL for the next prompt |
| `/attachments` | List queued attachments |
| `/clear-attachments` | Clear all queued attachments |

Queued attachments are sent with your next message and then cleared automatically.

```
> /attach diagram.png
Queued attachment: diagram.png
> /attach notes.pdf
Queued attachment: notes.pdf
> /attachments
  1. diagram.png
  2. notes.pdf
> What do these show?
[assistant response with both attachments]
> /attachments
No attachments queued.
```

## Server API (OpenAI Format)

The `initrunner serve` endpoint accepts multimodal content in the standard OpenAI format. The `content` field of a `ChatMessage` can be a string or a list of content parts.

### Content Part Types

| Type | Field | Description |
|------|-------|-------------|
| `text` | `text` | Plain text content |
| `image_url` | `image_url` | Image via HTTP URL or base64 `data:` URI |
| `input_audio` | `input_audio` | Audio as base64 with format specifier |

### Image via URL

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}}
      ]
    }]
  }'
```

### Image via Base64

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this image."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}}
      ]
    }]
  }'
```

### Audio Input

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Transcribe this audio."},
        {"type": "input_audio", "input_audio": {"data": "<base64>", "format": "mp3"}}
      ]
    }]
  }'
```

The `format` field defaults to `"mp3"` if omitted.

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="unused")

response = client.chat.completions.create(
    model="my-agent",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
        ],
    }],
)
print(response.choices[0].message.content)
```

## Web Dashboard

The chat interface supports file uploads via a button or drag-and-drop.

**Upload flow:**

1. Files are uploaded to `POST /roles/{role_id}/chat/upload` and staged in memory
2. The server returns a list of attachment IDs
3. Attachment IDs are passed to the SSE stream endpoint with the next prompt
4. Staged files expire after **5 minutes** if unused

**Limits:** 20 MB per file, same supported file types as the CLI.

## Model Support

Not all models support all modalities. If a model doesn't support a given content type, the provider API will return an error.

| Modality | Example models |
|----------|---------------|
| Images | `gpt-4o`, `gpt-5-mini`, `claude-sonnet-4-5-20250929`, `gemini-2.0-flash` |
| Audio | `gpt-4o-audio-preview` |
| Video | `gemini-2.0-flash` |
| Documents (PDF) | `gpt-4o`, `claude-sonnet-4-5-20250929`, `gemini-2.0-flash` |

When in doubt, use `gpt-4o` or a Claude model for broad multimodal support.

## Error Handling

| Condition | Error |
|-----------|-------|
| File not found | `Attachment file not found: <path>` |
| No file extension | `Cannot determine file type — file has no extension: <path>` |
| Unsupported extension | `Unsupported file type '<ext>' for: <path>. Supported: ...` |
| File exceeds 20 MB | `File too large (<size> MB): <path>. Maximum: 20 MB` |
| Dashboard upload too large | `File too large: <filename> (max 20 MB)` (HTTP 400) |

In the interactive REPL, attachment errors are printed and the prompt is not sent. In the CLI, the command exits with a non-zero status.
