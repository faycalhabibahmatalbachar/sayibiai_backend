"""Watermarking d'images et vidéos générées par ChadGPT."""

import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_WATERMARK_TEXT = "ChadGPT"


async def apply_image_watermark(
    image_bytes: bytes,
    text: str = _WATERMARK_TEXT,
    position: str = "bottom-right",
    opacity: float = 0.6,
) -> bytes:
    """
    Applique un watermark texte à une image.
    Retourne les bytes de l'image avec watermark.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io

        img = Image.open(_io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size

        # Couche watermark transparente
        watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        # Taille de police adaptative
        font_size = max(16, min(w, h) // 30)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

        # Calcul position
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        padding = 12

        if position == "bottom-right":
            x, y = w - text_w - padding, h - text_h - padding
        elif position == "bottom-left":
            x, y = padding, h - text_h - padding
        elif position == "top-right":
            x, y = w - text_w - padding, padding
        elif position == "top-left":
            x, y = padding, padding
        else:
            x, y = w - text_w - padding, h - text_h - padding

        alpha = int(255 * opacity)
        # Ombre portée
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, alpha // 2))
        # Texte principal blanc
        draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))

        out = Image.alpha_composite(img, watermark_layer).convert("RGB")
        buf = _io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except ImportError:
        logger.warning("Pillow non disponible — watermark ignoré")
        return image_bytes
    except Exception as e:
        logger.warning("Watermark error: %s", e)
        return image_bytes


async def apply_video_watermark_overlay(
    video_path: str,
    output_path: str,
    text: str = _WATERMARK_TEXT,
) -> bool:
    """
    Applique un watermark texte sur une vidéo via ffmpeg.
    Retourne True si succès.
    """
    try:
        import subprocess
        import shutil

        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg non trouvé — watermark vidéo ignoré")
            return False

        filter_complex = (
            f"drawtext=text='{text}':fontcolor=white@0.5:fontsize=24:"
            f"x=w-tw-10:y=h-th-10:shadowcolor=black@0.3:shadowx=1:shadowy=1"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", filter_complex,
            "-codec:a", "copy",
            "-preset", "fast",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        logger.warning("Video watermark error: %s", e)
        return False


def build_attribution_metadata(
    provider: str = "ChadGPT",
    model: str = "",
    user_id: str = "",
) -> dict:
    """Métadonnées d'attribution pour les médias générés."""
    return {
        "generated_by": provider,
        "model": model,
        "platform": "ChadGPT",
        "watermarked": True,
    }
