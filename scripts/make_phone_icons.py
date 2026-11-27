"""Draw the phone page's home-screen icons (src/abdoh/phone/web/icon-*.png) from Abdoh's logo:
white sound bars on its green gradient. Full squares: the phone rounds the corners itself, and
the bars stay inside the middle 60% (safe for Android's round "maskable" icons).

    python scripts/make_phone_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parents[1] / "src" / "abdoh" / "phone" / "web"
TOP_LEFT, BOTTOM_RIGHT = (13, 150, 104), (19, 178, 163)  # #0d9668 to #13b2a3, as docs/favicon
# The logo's bars in its 24-unit box: (x, top, bottom); each 2.6 wide, round ends.
BARS = [(2.6, 9, 15), (6.8, 6, 18), (11, 2.5, 21.5), (15.2, 6, 18), (19.4, 9, 15)]
SIZES = {"icon-180.png": 180, "icon-192.png": 192, "icon-512.png": 512}
SCALE = 4  # drawn bigger, then shrunk: smooth edges


def icon(size: int) -> Image.Image:
    big = size * SCALE
    image = Image.new("RGB", (big, big))
    pixels = image.load()
    pairs = list(zip(TOP_LEFT, BOTTOM_RIGHT, strict=True))
    for y in range(big):
        for x in range(big):
            t = (x + y) / (2 * (big - 1))
            pixels[x, y] = tuple(round(a + (b - a) * t) for a, b in pairs)
    draw = ImageDraw.Draw(image)
    box = big * 0.56  # the logo's 24 units
    unit = box / 24
    left = top = (big - box) / 2
    for x, y0, y1 in BARS:
        draw.rounded_rectangle(
            (left + x * unit, top + y0 * unit, left + (x + 2.6) * unit, top + y1 * unit),
            radius=1.3 * unit, fill="white",
        )  # fmt: skip
    return image.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    WEB.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        icon(size).save(WEB / name, optimize=True)
        print("wrote", WEB / name)
