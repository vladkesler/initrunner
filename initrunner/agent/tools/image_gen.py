"""Image generation tool: generate images via OpenAI or Stability AI."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._paths import validate_path_within
from initrunner.agent.schema.tools import ImageGenToolConfig
from initrunner.agent.tools._registry import register_tool

if TYPE_CHECKING:
    from initrunner.agent.tools._registry import ToolBuildContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _generate_openai(
    prompt: str,
    size: str,
    quality: str,
    style: str,
    model: str,
    api_key: str,
    timeout: int,
) -> bytes:
    """Generate an image via OpenAI DALL-E API, return raw PNG bytes."""
    from openai import OpenAI  # type: ignore[import-not-found]

    client = OpenAI(api_key=api_key, timeout=timeout)
    kwargs: dict = {
        "model": model or "dall-e-3",
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
        "n": 1,
    }
    if quality:
        kwargs["quality"] = quality
    if style:
        kwargs["style"] = style

    response = client.images.generate(**kwargs)
    b64 = response.data[0].b64_json
    return base64.b64decode(b64)


async def _generate_openai_async(
    prompt: str,
    size: str,
    quality: str,
    style: str,
    model: str,
    api_key: str,
    timeout: int,
) -> bytes:
    """Async variant of ``_generate_openai``."""
    from openai import AsyncOpenAI  # type: ignore[import-not-found]

    client = AsyncOpenAI(api_key=api_key, timeout=timeout)
    kwargs: dict = {
        "model": model or "dall-e-3",
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
        "n": 1,
    }
    if quality:
        kwargs["quality"] = quality
    if style:
        kwargs["style"] = style

    response = await client.images.generate(**kwargs)
    b64 = response.data[0].b64_json
    return base64.b64decode(b64)


def _generate_stability(
    prompt: str,
    size: str,
    api_key: str,
    timeout: int,
    model: str,
) -> bytes:
    """Generate an image via Stability AI REST API, return raw PNG bytes."""
    import httpx

    width, _, height = size.partition("x")
    body = {
        "text_prompts": [{"text": prompt}],
        "width": int(width) if width else 1024,
        "height": int(height) if height else 1024,
    }
    engine = model or "stable-diffusion-xl-1024-v1-0"
    url = f"https://api.stability.ai/v1/generation/{engine}/text-to-image"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    artifacts = data.get("artifacts", [])
    if not artifacts:
        raise RuntimeError("Stability API returned no artifacts")
    return base64.b64decode(artifacts[0]["base64"])


async def _generate_stability_async(
    prompt: str,
    size: str,
    api_key: str,
    timeout: int,
    model: str,
) -> bytes:
    """Async variant of ``_generate_stability``."""
    import httpx

    width, _, height = size.partition("x")
    body = {
        "text_prompts": [{"text": prompt}],
        "width": int(width) if width else 1024,
        "height": int(height) if height else 1024,
    }
    engine = model or "stable-diffusion-xl-1024-v1-0"
    url = f"https://api.stability.ai/v1/generation/{engine}/text-to-image"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    artifacts = data.get("artifacts", [])
    if not artifacts:
        raise RuntimeError("Stability API returned no artifacts")
    return base64.b64decode(artifacts[0]["base64"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _save_image(image_bytes: bytes, output_dir: Path) -> str:
    """Save image bytes to output_dir and return the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    h = hashlib.sha256(image_bytes).hexdigest()[:8]
    filename = f"image_{ts}_{h}.png"
    dest = output_dir / filename
    dest.write_bytes(image_bytes)
    return str(dest)


def _resolve_output_dir(config_dir: str) -> Path:
    """Resolve the output directory, using a tempdir if not configured."""
    if config_dir:
        return Path(config_dir).resolve()
    return Path(tempfile.mkdtemp(prefix="initrunner_img_"))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def _do_generate(
    prompt: str,
    size: str,
    quality: str,
    style: str,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    output_dir: Path,
) -> str:
    """Generate an image and save it. Returns the file path or an error."""
    try:
        if provider == "openai":
            image_bytes = _generate_openai(prompt, size, quality, style, model, api_key, timeout)
        elif provider == "stability":
            image_bytes = _generate_stability(prompt, size, api_key, timeout, model)
        else:
            return f"Error: unknown provider: {provider}"
    except Exception as exc:
        return f"Error: image generation failed: {exc}"

    return _save_image(image_bytes, output_dir)


async def _do_generate_async(
    prompt: str,
    size: str,
    quality: str,
    style: str,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    output_dir: Path,
) -> str:
    """Async variant of ``_do_generate``."""
    try:
        if provider == "openai":
            image_bytes = await _generate_openai_async(
                prompt, size, quality, style, model, api_key, timeout
            )
        elif provider == "stability":
            image_bytes = await _generate_stability_async(prompt, size, api_key, timeout, model)
        else:
            return f"Error: unknown provider: {provider}"
    except Exception as exc:
        return f"Error: image generation failed: {exc}"

    return _save_image(image_bytes, output_dir)


def _do_edit(
    image_path: str,
    prompt: str,
    size: str,
    model: str,
    api_key: str,
    timeout: int,
    output_dir: Path,
    allowed_roots: list[Path],
) -> str:
    """Edit an existing image via OpenAI. Returns the file path or an error."""
    target = Path(image_path)
    err, resolved = validate_path_within(
        target, allowed_roots, allowed_ext={".png", ".jpg", ".jpeg", ".webp"}
    )
    if err:
        return err
    if not resolved.exists():
        return f"Error: image not found: {image_path}"

    try:
        from openai import OpenAI  # type: ignore[import-not-found]

        client = OpenAI(api_key=api_key, timeout=timeout)
        with open(resolved, "rb") as f:
            response = client.images.edit(
                model=model or "dall-e-2",
                image=f,
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                response_format="b64_json",
                n=1,
            )
        b64 = response.data[0].b64_json
        image_bytes = base64.b64decode(b64)
    except Exception as exc:
        return f"Error: image edit failed: {exc}"

    return _save_image(image_bytes, output_dir)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@register_tool("image_gen", ImageGenToolConfig)
def build_image_gen_toolset(
    config: ImageGenToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for image generation and editing."""
    api_key = resolve_env_vars(config.api_key_env)
    output_dir = _resolve_output_dir(config.output_dir)

    # Allowed roots for edit_image input paths
    allowed_roots = [output_dir]
    if config.input_root:
        allowed_roots.append(Path(config.input_root).resolve())

    toolset = FunctionToolset()

    if ctx.prefer_async:

        @toolset.tool_plain
        async def generate_image(
            prompt: str,
            size: str = "",
            style: str = "",
            quality: str = "",
        ) -> str:
            """Generate an image from a text prompt and save it to disk.

            Returns the file path of the generated image.

            Args:
                prompt: Description of the image to generate.
                size: Image dimensions (e.g. "1024x1024"). Empty for default.
                style: Style preset (e.g. "natural", "vivid"). Empty for default.
                quality: Quality level (e.g. "standard", "hd"). Empty for default.
            """
            return await _do_generate_async(
                prompt,
                size or config.default_size,
                quality or config.default_quality,
                style or config.default_style,
                config.provider,
                config.model,
                api_key,
                config.timeout_seconds,
                output_dir,
            )

        @toolset.tool_plain
        async def edit_image(
            image_path: str,
            prompt: str,
            size: str = "",
        ) -> str:
            """Edit an existing image using a text prompt (OpenAI only).

            Returns the file path of the edited image.

            Args:
                image_path: Path to the source image file.
                prompt: Description of the desired edit.
                size: Output dimensions. Empty for default.
            """
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: _do_edit(
                    image_path,
                    prompt,
                    size or config.default_size,
                    config.model,
                    api_key,
                    config.timeout_seconds,
                    output_dir,
                    allowed_roots,
                ),
            )

    else:

        @toolset.tool_plain
        def generate_image(
            prompt: str,
            size: str = "",
            style: str = "",
            quality: str = "",
        ) -> str:
            """Generate an image from a text prompt and save it to disk.

            Returns the file path of the generated image.

            Args:
                prompt: Description of the image to generate.
                size: Image dimensions (e.g. "1024x1024"). Empty for default.
                style: Style preset (e.g. "natural", "vivid"). Empty for default.
                quality: Quality level (e.g. "standard", "hd"). Empty for default.
            """
            return _do_generate(
                prompt,
                size or config.default_size,
                quality or config.default_quality,
                style or config.default_style,
                config.provider,
                config.model,
                api_key,
                config.timeout_seconds,
                output_dir,
            )

        @toolset.tool_plain
        def edit_image(
            image_path: str,
            prompt: str,
            size: str = "",
        ) -> str:
            """Edit an existing image using a text prompt (OpenAI only).

            Returns the file path of the edited image.

            Args:
                image_path: Path to the source image file.
                prompt: Description of the desired edit.
                size: Output dimensions. Empty for default.
            """
            return _do_edit(
                image_path,
                prompt,
                size or config.default_size,
                config.model,
                api_key,
                config.timeout_seconds,
                output_dir,
                allowed_roots,
            )

    return toolset
