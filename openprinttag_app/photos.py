"""Bounded, inert photo attachments stored with the inventory database."""
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 4 * 1024 * 1024
MAX_PHOTOS = 8
MAX_STORED = 900 * 1024


def normalize_photo(content):
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_UPLOAD:
        raise ValueError("Choisissez une image JPEG, PNG ou WebP de moins de 4 Mo.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"} or source.width * source.height > 20_000_000 or getattr(source, "is_animated", False):
                    raise ValueError("Format ou dimensions de photo non pris en charge.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1600, 1600))
        # Re-encoding drops EXIF, names, location and any trailing uploaded data.
        output = BytesIO()
        image.save(output, "JPEG", quality=82)
        while output.tell() > MAX_STORED:
            image.thumbnail((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))
            output = BytesIO()
            image.save(output, "JPEG", quality=80)
        thumbnail = image.copy()
        thumbnail.thumbnail((320, 240))
        small = BytesIO()
        thumbnail.save(small, "JPEG", quality=75)
        return output.getvalue(), small.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("La photo est illisible ou trop volumineuse.") from None


def validate_saved_photo(row):
    """Restore only the same inert JPEG representation accepted on upload."""
    from datetime import datetime
    import uuid
    uuid.UUID(row["id"])
    if not datetime.fromisoformat(row["created_at"]).tzinfo:
        raise ValueError("Date de photo invalide.")
    if type(row["width"]) is not int or type(row["height"]) is not int or not 1 <= row["width"] <= 1600 or not 1 <= row["height"] <= 1600:
        raise ValueError("Dimensions de photo invalides.")
    try:
        for key, limit in (("image", MAX_STORED), ("thumbnail", 100_000)):
            value = row[key]
            if not isinstance(value, bytes) or not 1 <= len(value) <= limit:
                raise ValueError("Photo sauvegardée invalide.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(value)) as image:
                    bound = (320, 240) if key == "thumbnail" else (1600, 1600)
                    if image.format != "JPEG" or image.getexif() or image.width > bound[0] or image.height > bound[1]:
                        raise ValueError("Photo sauvegardée invalide.")
                    image.load()
                    if key == "image" and image.size != (row["width"], row["height"]):
                        raise ValueError("Dimensions de photo incohérentes.")
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Photo sauvegardée invalide.") from None
