"""Document file classification for multimodal pipeline.

Routes files to the appropriate Kimi API endpoint:
- Text-based formats (PDF/DOCX/TXT/etc.) → /v1/files purpose="file-extract"
- Image formats (JPEG/PNG/WEBP/etc.) → vision API base64 image
"""

from enum import Enum
from pathlib import Path


class ParseMethod(Enum):
    FILE_EXTRACT = "file-extract"   # Text extraction via /v1/files
    IMAGE_VISION = "image"           # Native vision (base64-encoded)


# Formats supported by Kimi /v1/files file-extract
TEXT_FORMATS: set[str] = {
    ".pdf", ".doc", ".docx", ".txt", ".csv", ".md",
    ".html", ".json", ".epub", ".mobi",
    ".xls", ".xlsx", ".ppt", ".pptx", ".dot",
}

# Image formats supported by Kimi vision API
IMAGE_FORMATS: set[str] = {
    ".jpeg", ".jpg", ".png", ".bmp", ".gif", ".svg",
    ".webp", ".ico", ".tif", ".tiff", ".avif", ".apng",
}


class UnsupportedFormatError(ValueError):
    """Raised when a file format is not supported by any pipeline."""


def classify_file(filename: str) -> ParseMethod:
    """Classify a file by extension into the correct parsing pipeline.

    Args:
        filename: Original filename with extension.

    Returns:
        ParseMethod indicating which pipeline to use.

    Raises:
        UnsupportedFormatError: If the file format is not supported.
    """
    ext = Path(filename).suffix.lower()
    if ext in TEXT_FORMATS:
        return ParseMethod.FILE_EXTRACT
    if ext in IMAGE_FORMATS:
        return ParseMethod.IMAGE_VISION
    raise UnsupportedFormatError(
        f"Unsupported file format: {ext}. "
        f"Supported text: {sorted(TEXT_FORMATS)}. "
        f"Supported image: {sorted(IMAGE_FORMATS)}."
    )


def is_image_format(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_FORMATS


def is_text_format(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in TEXT_FORMATS


# Size limit: 10 MB (Kimi /v1/files limit is higher, but we cap for UX)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
