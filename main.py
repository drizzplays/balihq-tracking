import os
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# =========================
# CONFIG
# =========================
ROOT = Path(__file__).parent
FONTS_DIR = ROOT / "fonts"
FONTS_DIR.mkdir(exist_ok=True)

LEXEND_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/lexend/static/Lexend-Regular.ttf"
LEXEND_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/lexend/static/Lexend-Bold.ttf"

LEXEND_PATH = FONTS_DIR / "Lexend-Regular.ttf"
LEXEND_BOLD_PATH = FONTS_DIR / "Lexend-Bold.ttf"

CANVAS_W, CANVAS_H = 1038, 757


# =========================
# DOWNLOAD FONT (REAL)
# =========================
def download_font(url, path):
    print(f"Downloading font → {url}")
    r = requests.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to download font: {url}")

    path.write_bytes(r.content)


# =========================
# VERIFY FONT BYTES
# =========================
def assert_real_font(path):
    data = Path(path).read_bytes()

    # valid font signatures
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"ttcf"):
        raise RuntimeError(
            f"\n❌ BAD FONT FILE: {path}\n"
            f"Starts with: {data[:40]!r}\n"
            f"This is NOT a real .ttf (likely HTML or corrupted)\n"
        )

    print(f"✅ VALID FONT: {path}")


# =========================
# ENSURE FONTS EXIST + VALID
# =========================
def ensure_fonts():
    if not LEXEND_PATH.exists():
        download_font(LEXEND_URL, LEXEND_PATH)

    if not LEXEND_BOLD_PATH.exists():
        download_font(LEXEND_BOLD_URL, LEXEND_BOLD_PATH)

    assert_real_font(LEXEND_PATH)
    assert_real_font(LEXEND_BOLD_PATH)


# =========================
# LOAD FONTS
# =========================
def load_fonts():
    font_body = ImageFont.truetype(str(LEXEND_PATH), 10)
    font_header = ImageFont.truetype(str(LEXEND_BOLD_PATH), 10)
    return font_body, font_header


# =========================
# RENDER SHEET (CLEAN BASE)
# =========================
def render():
    # background
    bg_path = ROOT / "background.png"
    if bg_path.exists():
        img = Image.open(bg_path).convert("RGBA").resize((CANVAS_W, CANVAS_H))
    else:
        img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (20, 30, 40))

    draw = ImageDraw.Draw(img)

    # fonts
    font_body, font_header = load_fonts()

    # layout
    margin = 20
    row_h = 20
    x = margin
    y = margin

    # green outline (NO black)
    draw.rectangle(
        [margin, margin, CANVAS_W - margin, CANVAS_H - margin],
        outline=(0, 255, 120),
        width=2
    )

    # header row
    headers = ["league", "pst", "player 1", "player 2", "bet", "unit", "history", "%"]

    col_widths = [80, 80, 180, 180, 100, 60, 120, 60]

    cx = x
    for i, h in enumerate(headers):
        draw.text((cx + 4, y + 2), h, font=font_header, fill=(255, 255, 255))
        cx += col_widths[i]

    y += row_h

    # sample rows (replace with your sheet data)
    rows = [
        ["nba", "7:00", "player a", "player b", "over", "1u", "5-2", "71%"],
        ["mlb", "8:30", "player c", "player d", "under", "0.5u", "3-1", "75%"],
    ]

    for row in rows:
        cx = x
        for i, val in enumerate(row):
            draw.text((cx + 4, y + 2), str(val), font=font_body, fill=(230, 240, 255))
            cx += col_widths[i]

        # light gridline (not harsh black)
        draw.line(
            [(x, y + row_h), (CANVAS_W - margin, y + row_h)],
            fill=(80, 120, 140),
            width=1
        )

        y += row_h

    # save
    out = ROOT / "output.png"
    img.save(out)
    print(f"✅ Saved → {out}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    ensure_fonts()
    render()
