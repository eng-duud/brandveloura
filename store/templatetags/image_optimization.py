"""Template filters for optimized Cloudinary images."""

from django import template

from store.image_optimization import (
    cloudinary_webp_srcset as build_cloudinary_webp_srcset,
    cloudinary_webp_url,
)

register = template.Library()


@register.filter
def cloudinary_webp(url, width=640):
    """Optimize Cloudinary images; pass through non-Cloudinary URLs unchanged."""
    return cloudinary_webp_url(url, width)


@register.filter
def cloudinary_webp_srcset(url, widths="320,640,960"):
    """Build responsive candidates only for URLs Cloudinary can transform."""
    return build_cloudinary_webp_srcset(url, widths)
