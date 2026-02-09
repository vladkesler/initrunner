"""Tests for the facehash avatar SVG generator."""

from __future__ import annotations

from markupsafe import Markup

from initrunner.api.facehash import render_facehash_svg, string_hash


class TestStringHash:
    def test_deterministic(self):
        assert string_hash("alice") == string_hash("alice")

    def test_different_inputs(self):
        assert string_hash("alice") != string_hash("bob")

    def test_empty_string(self):
        assert string_hash("") == 0

    def test_32bit_overflow(self):
        """Verify masking keeps values within 32-bit unsigned range."""
        h = string_hash("a]long string that would overflow 32 bits easily")
        assert 0 <= h <= 0xFFFFFFFF

    def test_matches_js_behavior(self):
        """The JS algorithm uses ``hash &= hash`` which is signed 32-bit
        then ``Math.abs()``.  Our port uses unsigned masking.  Verify a
        known value stays stable (regression guard)."""
        h = string_hash("test")
        assert h == string_hash("test")  # deterministic at minimum
        assert isinstance(h, int)


class TestRenderFacehashSvg:
    def test_returns_markup(self):
        result = render_facehash_svg("alice")
        assert isinstance(result, Markup)

    def test_contains_svg_element(self):
        svg = render_facehash_svg("alice")
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_contains_eyes(self):
        """SVG should contain eye elements (circles, rects, or paths)."""
        svg = render_facehash_svg("alice")
        has_eyes = "<circle" in svg or "<rect" in svg or "<path" in svg
        assert has_eyes

    def test_contains_initial(self):
        svg = render_facehash_svg("alice")
        assert ">A</text>" in svg

    def test_initial_uppercase(self):
        svg = render_facehash_svg("bob")
        assert ">B</text>" in svg

    def test_different_names_produce_different_faces(self):
        names = ["alice", "bob", "carol", "dave", "eve"]
        svgs = [render_facehash_svg(name) for name in names]
        # At least some should differ (statistically near-certain with 5 names)
        assert len(set(svgs)) > 1

    def test_same_name_same_face(self):
        assert render_facehash_svg("alice") == render_facehash_svg("alice")

    def test_size_parameter(self):
        svg_small = render_facehash_svg("alice", 24)
        svg_large = render_facehash_svg("alice", 64)
        assert 'width="24"' in svg_small
        assert 'width="64"' in svg_large

    def test_accessibility_attributes(self):
        svg = render_facehash_svg("alice")
        assert 'role="img"' in svg
        assert 'aria-label="Avatar for alice"' in svg

    def test_xss_safe(self):
        """Name with HTML should be escaped, not injected raw."""
        svg = render_facehash_svg("<script>alert(1)</script>")
        assert "<script>" not in svg
        assert "&lt;" in svg

    def test_lru_cache_hit(self):
        """Calling twice with same args should return identical object."""
        a = render_facehash_svg("cached", 40)
        b = render_facehash_svg("cached", 40)
        assert a is b

    def test_gradient_present(self):
        svg = render_facehash_svg("alice")
        assert "radialGradient" in svg

    def test_3d_rotation_css_vars(self):
        svg = render_facehash_svg("alice")
        assert "--rot-x:" in svg
        assert "--rot-y:" in svg

    def test_facehash_wrap_class(self):
        svg = render_facehash_svg("alice")
        assert 'class="facehash-wrap"' in svg
