"""Cloudinary delivery transformations for responsive storefront images."""

import re
from urllib.parse import urlsplit, urlunsplit

_CLOUDINARY_UPLOAD_PATH = re.compile(r"^(/[^/]+/image/upload/)(.*)$", re.IGNORECASE)
_TRANSFORMATION_COMPONENT = re.compile(
    r"(?:[a-z]{1,2}_[^/]+)(?:,(?:[a-z]{1,2}_[^/]+))*$", re.IGNORECASE
)


def cloudinary_webp_url(url, width=640):
    """Return a size-limited WebP URL for Cloudinary, leaving other hosts intact."""
    if not url:
        return ""

    original = str(url).strip()
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = 640
    width = min(max(width, 48), 2560)

    parts = urlsplit(original)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return original

    match = _CLOUDINARY_UPLOAD_PATH.match(parts.path)
    if not match:
        return original

    upload_prefix, image_path = match.groups()
    components = image_path.split("/") if image_path else []
    insert_at = 0
    while insert_at < len(components) and _TRANSFORMATION_COMPONENT.fullmatch(
        components[insert_at]
    ):
        insert_at += 1

    components.insert(insert_at, f"f_webp,q_auto:eco,w_{width},c_limit")
    transformed_path = upload_prefix + "/".join(components)
    return urlunsplit(
        (parts.scheme, parts.netloc, transformed_path, parts.query, parts.fragment)
    )


def cloudinary_webp_srcset(url, widths="320,640,960"):
    """Build srcset only when Cloudinary actually transforms each candidate."""
    if not url:
        return ""

    original = str(url).strip()
    candidates = []
    for value in str(widths).split(","):
        try:
            width = int(value.strip())
        except (TypeError, ValueError):
            continue
        if width < 48 or width > 2560:
            continue
        candidate = cloudinary_webp_url(original, width)
        if candidate == original:
            continue
        if all(existing_width != width for existing_width, _ in candidates):
            candidates.append((width, candidate))

    return ", ".join(
        f"{candidate} {width}w" for width, candidate in sorted(candidates)
    )
