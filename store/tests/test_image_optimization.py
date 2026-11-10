from django.test import SimpleTestCase

from store.image_optimization import cloudinary_webp_srcset, cloudinary_webp_url


class CloudinaryWebPUrlTests(SimpleTestCase):
    def test_adds_webp_quality_and_width_before_cloudinary_version(self):
        url = "https://res.cloudinary.com/demo/image/upload/v1700000000/products/perfume.jpg"

        self.assertEqual(
            cloudinary_webp_url(url, 320),
            "https://res.cloudinary.com/demo/image/upload/"
            "f_webp,q_auto:eco,w_320,c_limit/v1700000000/products/perfume.jpg",
        )

    def test_preserves_existing_transformations_query_and_fragment(self):
        url = (
            "https://res.cloudinary.com/demo/image/upload/q_auto:good,w_900/"
            "v1700000000/products/perfume.jpg?token=ok#preview"
        )

        result = cloudinary_webp_url(url, 640)

        self.assertIn(
            "/image/upload/q_auto:good,w_900/f_webp,q_auto:eco,w_640,c_limit/",
            result,
        )
        self.assertTrue(result.endswith("?token=ok#preview"))

    def test_leaves_non_cloudinary_images_unchanged(self):
        url = "https://images.example.test/photo.jpg?width=800"

        self.assertEqual(cloudinary_webp_url(url, 320), url)

    def test_clamps_width_to_safe_limits(self):
        url = "https://res.cloudinary.com/demo/image/upload/v1/photo.jpg"

        self.assertIn("w_48,c_limit", cloudinary_webp_url(url, 1))
        self.assertIn("w_2560,c_limit", cloudinary_webp_url(url, 9000))

    def test_builds_sorted_responsive_srcset_for_cloudinary(self):
        url = "https://res.cloudinary.com/demo/image/upload/v1/photo.jpg"

        result = cloudinary_webp_srcset(url, "640,320,640,invalid")

        self.assertEqual(
            result,
            "https://res.cloudinary.com/demo/image/upload/"
            "f_webp,q_auto:eco,w_320,c_limit/v1/photo.jpg 320w, "
            "https://res.cloudinary.com/demo/image/upload/"
            "f_webp,q_auto:eco,w_640,c_limit/v1/photo.jpg 640w",
        )

    def test_does_not_claim_responsive_widths_for_other_hosts(self):
        self.assertEqual(
            cloudinary_webp_srcset("https://images.example.test/photo.jpg"), ""
        )

    def test_template_srcset_filter_uses_cloudinary_only_responsive_candidates(self):
        self.assertEqual(
            cloudinary_webp_srcset_filter("https://images.example.test/photo.jpg"),
            "",
        )
from store.image_optimization import cloudinary_webp_srcset, cloudinary_webp_url
from store.templatetags.image_optimization import (
    cloudinary_webp_srcset as cloudinary_webp_srcset_filter,
)
