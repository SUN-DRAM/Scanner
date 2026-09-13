"""Bundled fonts and the cover logo (contract §7.14 / Step 1 decision 1.1).

Space Grotesk, Inter and JetBrains Mono are bundled as local WOFF files and
registered via `@font-face` rather than left to WeasyPrint's system font
fallback — the Step 1 decision's whole point ("whatever renderer you pick
will silently fall back to a default face if those aren't available inside
the container"). `tests/test_pdf_fonts.py` asserts the rendered PDF actually
embeds them, not a fallback.

Font files are Google Fonts (OFL-licensed) static WOFF instances — Space
Grotesk Regular/Medium/Bold, Inter Regular/SemiBold, JetBrains Mono
Regular/Medium — chosen to cover every weight the templates below actually
use, no more.
"""

from __future__ import annotations

from pathlib import Path

PDF_DIR = Path(__file__).parent
FONTS_DIR = PDF_DIR / "fonts"
ASSETS_DIR = PDF_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "logo.svg"


def logo_available() -> bool:
    """Rule 7 ("never guess") applies here too: an empty or missing logo file
    must render *no image* on the cover, never a broken `<img>` pretending to
    be one."""
    try:
        return LOGO_PATH.is_file() and LOGO_PATH.stat().st_size > 0
    except OSError:
        return False


# (family, weight, filename) — the exact set the templates in styles.py use.
_FONT_FILES: tuple[tuple[str, int, str], ...] = (
    ("Space Grotesk", 400, "SpaceGrotesk-Regular.woff"),
    ("Space Grotesk", 500, "SpaceGrotesk-Medium.woff"),
    ("Space Grotesk", 700, "SpaceGrotesk-Bold.woff"),
    ("Inter", 400, "Inter-Regular.woff"),
    ("Inter", 600, "Inter-SemiBold.woff"),
    ("JetBrains Mono", 400, "JetBrainsMono-Regular.woff"),
    ("JetBrains Mono", 500, "JetBrainsMono-Medium.woff"),
)


def font_face_css() -> str:
    """`url(...)` paths are relative to `renderer.py`'s `base_url` (this
    package's own directory), so they resolve the same way in every
    environment without an absolute filesystem path baked into the CSS."""
    rules = []
    for family, weight, filename in _FONT_FILES:
        rules.append(
            f"""@font-face {{
  font-family: "{family}";
  font-weight: {weight};
  font-style: normal;
  src: url("fonts/{filename}") format("woff");
}}"""
        )
    return "\n".join(rules)
