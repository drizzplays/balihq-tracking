import os
import json
import sys
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# --- CONFIGURATION ---
GSHEET_ID = os.environ.get("GSHEET_ID", "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw")
TAB_NAME = os.environ.get("TAB_NAME", "Test")
BG_FILENAME = os.environ.get("BG_FILENAME", "background.png")
OUTPUT_FILENAME = os.environ.get("OUTPUT_FILENAME", "output.png")

# Match the reference render closely.
CANVAS_W = int(os.environ.get("CANVAS_W", "1038"))
CANVAS_H = int(os.environ.get("CANVAS_H", "757"))
MARGIN_X = int(os.environ.get("MARGIN_X", "14"))
TOP_Y = int(os.environ.get("TOP_Y", "14"))
HEADER_H = int(os.environ.get("HEADER_H", "22"))
ROW_H = int(os.environ.get("ROW_H", "20"))
SEP_H = int(os.environ.get("SEP_H", "20"))
BOTTOM_PAD = int(os.environ.get("BOTTOM_PAD", "15"))

COL_NAMES = ["League", "PST", "MTN", "EST", "Player 1", "Player 2", "BET", "Unit", "History", "Split %", "Set Break Down"]
# Sums to 1010, which is 1038 - 2*14. These widths mirror the target screenshot.
COL_WIDTHS = [110, 60, 60, 60, 137, 137, 77, 76, 124, 77, 92]
TABLE_W = sum(COL_WIDTHS)

BRAND_LEFT = os.environ.get("BRAND_LEFT", "X.COM/BALIHQ")
BRAND_MID = os.environ.get("BRAND_MID", "OFFICIAL PROPERTY OF BALIHQBETS")
BRAND_RIGHT = os.environ.get("BRAND_RIGHT", "JOIN.BALIHQBETS.COM")

# Colors, tuned for the reference.
BLUE = (43, 112, 172, 255)
BLUE_DARK = (10, 67, 104, 255)
GRID = (0, 0, 0, 210)
GRID_SOFT = (0, 0, 0, 140)
OUTLINE_GREEN = (0, 150, 35, 255)
TEXT_DARK = (0, 0, 0, 255)
TEXT_WHITE = (255, 255, 255, 255)
ROW_LIGHT = (238, 247, 250, 178)
ROW_DARK = (207, 220, 226, 178)
LEAGUE_TT_CUP = (239, 219, 40, 245)
LEAGUE_TT_ELITE = (251, 238, 194, 230)
LEAGUE_CZECH = (0, 92, 126, 245)
BET_UNDER = (0, 89, 130, 250)
BET_OVER = (245, 238, 214, 232)
BET_SPLIT = (229, 229, 229, 232)


def get_data():
    print("--- STEP 1: CONNECTING TO GOOGLE ---")
    creds_raw = os.environ.get("GSHEET_JSON")
    if not creds_raw:
        print("ERROR: GSHEET_JSON secret is missing from GitHub.")
        sys.exit(1)
    try:
        creds_dict = json.loads(creds_raw)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GSHEET_ID).worksheet(TAB_NAME)
        rows = sheet.get_all_values()
        print(f"SUCCESS: Found {len(rows)} rows in tab '{TAB_NAME}'.")
        return rows
    except Exception as e:
        print(f"ERROR CONNECTING TO GOOGLE: {e}")
        sys.exit(1)


def _font(size, bold=False):
    names = []
    if bold:
        names += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    names += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in names:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

FONT_HEADER = _font(9, True)
FONT_CELL = _font(8, True)
FONT_NAME = _font(8, True)
FONT_BRAND = _font(14, True)
FONT_BRAND_SMALL = _font(13, True)


def _text_size(draw, text, font):
    box = draw.textbbox((0, 0), str(text), font=font)
    return box[2] - box[0], box[3] - box[1]


def _fit_text(draw, text, font, max_w):
    text = str(text).strip()
    if not text:
        return ""
    if _text_size(draw, text, font)[0] <= max_w:
        return text
    ell = "…"
    while text and _text_size(draw, text + ell, font)[0] > max_w:
        text = text[:-1]
    return text + ell if text else ell


def _center_text(draw, box, text, font, fill, stroke=0):
    x1, y1, x2, y2 = box
    text = _fit_text(draw, text, font, max(1, x2 - x1 - 6))
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2 - 1),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 180) if stroke else None,
    )


def _normalize_rows(rows):
    if not rows:
        return []
    start = 0
    first = [str(c).strip().lower() for c in rows[0][:len(COL_NAMES)]]
    if any("league" == c for c in first) or any("player" in c for c in first):
        start = 1
    clean = []
    for row in rows[start:]:
        row = [str(c).strip() for c in row[:len(COL_NAMES)]]
        row += [""] * (len(COL_NAMES) - len(row))
        clean.append(row)
    return clean


def _is_separator(row):
    return not any(str(c).strip() for c in row)


def _league_color(league):
    league = str(league).upper()
    if "CZECH" in league:
        return LEAGUE_CZECH, TEXT_WHITE
    if "TT CUP" in league:
        return LEAGUE_TT_CUP, (30, 25, 0, 255)
    return LEAGUE_TT_ELITE, (25, 25, 25, 255)


def _bet_color(bet):
    bet = str(bet).upper()
    if "UNDER" in bet:
        return BET_UNDER, TEXT_WHITE
    if "OVER" in bet:
        return BET_OVER, TEXT_DARK
    return BET_SPLIT, TEXT_DARK


def _prep_background():
    if not Path(BG_FILENAME).exists():
        print(f"ERROR: {BG_FILENAME} is missing from repo.")
        sys.exit(1)
    bg = Image.open(BG_FILENAME).convert("RGB")
    bw, bh = bg.size
    target = CANVAS_W / CANVAS_H
    ratio = bw / bh
    if ratio > target:
        nw = int(bh * target)
        left = (bw - nw) // 2
        bg = bg.crop((left, 0, left + nw, bh))
    else:
        nh = int(bw / target)
        top = (bh - nh) // 2
        bg = bg.crop((0, top, bw, top + nh))
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Contrast(bg).enhance(1.03)
    bg = ImageEnhance.Sharpness(bg).enhance(1.08)
    return bg.convert("RGBA")


def _draw_header(draw, x0, xs, y):
    draw.rectangle((x0, y, x0 + TABLE_W, y + HEADER_H), fill=BLUE)
    for i, name in enumerate(COL_NAMES):
        x1, x2 = xs[i], xs[i + 1]
        draw.line((x2, y, x2, y + HEADER_H), fill=(0, 50, 86, 255), width=1)
        _center_text(draw, (x1 + 4, y, x2 - 15, y + HEADER_H), name, FONT_HEADER, TEXT_WHITE)
        # Small filter arrow. It makes the bot output look like the Google Sheet render.
        cx = x2 - 10
        cy = y + HEADER_H // 2 + 1
        draw.polygon([(cx - 3, cy - 2), (cx + 3, cy - 2), (cx, cy + 3)], fill=(220, 238, 246, 255))
    draw.line((x0, y + HEADER_H, x0 + TABLE_W, y + HEADER_H), fill=(0, 0, 0, 255), width=2)


def _draw_separator(draw, x0, y):
    draw.rectangle((x0, y, x0 + TABLE_W, y + SEP_H), fill=BLUE)
    draw.line((x0, y, x0 + TABLE_W, y), fill=(0, 0, 0, 255), width=1)
    draw.line((x0, y + SEP_H - 1, x0 + TABLE_W, y + SEP_H - 1), fill=(0, 0, 0, 255), width=1)
    _center_text(draw, (x0 + 4, y, x0 + 250, y + SEP_H), BRAND_LEFT, FONT_BRAND, TEXT_WHITE, stroke=1)
    _center_text(draw, (x0 + 250, y, x0 + TABLE_W - 250, y + SEP_H), BRAND_MID, FONT_BRAND, TEXT_WHITE, stroke=1)
    _center_text(draw, (x0 + TABLE_W - 250, y, x0 + TABLE_W - 4, y + SEP_H), BRAND_RIGHT, FONT_BRAND_SMALL, TEXT_WHITE, stroke=1)


def _draw_row(draw, x0, xs, y, row, idx):
    base = ROW_LIGHT if idx % 2 == 0 else ROW_DARK
    draw.rectangle((x0, y, x0 + TABLE_W, y + ROW_H), fill=base)
    league_fill, league_text = _league_color(row[0])
    bet_fill, bet_text = _bet_color(row[6])
    draw.rectangle((xs[0], y, xs[1], y + ROW_H), fill=league_fill)
    draw.rectangle((xs[6], y, xs[7], y + ROW_H), fill=bet_fill)

    # Vertical grid: History/Split/Break columns get the heavy black dividers seen in the reference.
    for j, xx in enumerate(xs):
        width = 3 if j in (0, 8, 9, len(xs)-1) else 1
        draw.line((xx, y, xx, y + ROW_H), fill=GRID, width=width)
    draw.line((x0, y + ROW_H, x0 + TABLE_W, y + ROW_H), fill=GRID_SOFT, width=1)

    for i, cell in enumerate(row):
        font = FONT_NAME if i in (4, 5) else FONT_CELL
        fill = TEXT_DARK
        text = cell
        if i == 0:
            fill = league_text
        elif i == 6:
            fill = bet_text
            text = str(cell).upper()
        _center_text(draw, (xs[i] + 2, y, xs[i + 1] - 2, y + ROW_H), text, font, fill)


def create_graphic(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    try:
        data_rows = _normalize_rows(rows)
        img = _prep_background()
        draw = ImageDraw.Draw(img, "RGBA")

        x0 = MARGIN_X
        table_bottom = CANVAS_H - BOTTOM_PAD
        xs = [x0]
        for w in COL_WIDTHS:
            xs.append(xs[-1] + w)

        # Full green frame like the reference image, not a gray floating box.
        draw.rounded_rectangle((8, 8, CANVAS_W - 8, CANVAS_H - 8), radius=5, outline=OUTLINE_GREEN, width=5)
        draw.rectangle((x0, TOP_Y, x0 + TABLE_W, table_bottom), fill=(230, 245, 248, 42))

        y = TOP_Y
        _draw_header(draw, x0, xs, y)
        y += HEADER_H

        row_count = 0
        last_was_sep = False
        for row in data_rows:
            if _is_separator(row):
                if not last_was_sep and y + SEP_H <= table_bottom:
                    _draw_separator(draw, x0, y)
                    y += SEP_H
                    last_was_sep = True
                continue
            if y + ROW_H > table_bottom:
                break
            _draw_row(draw, x0, xs, y, row, row_count)
            y += ROW_H
            row_count += 1
            last_was_sep = False

        if y + SEP_H <= table_bottom:
            _draw_separator(draw, x0, y)
            y += SEP_H

        # Outer table outline on top for crisp edges.
        draw.rectangle((x0, TOP_Y, x0 + TABLE_W, min(y, table_bottom)), outline=(0, 0, 0, 255), width=2)

        img.convert("RGB").save(OUTPUT_FILENAME, quality=98, optimize=True)
        print(f"SUCCESS: Image rendered as {OUTPUT_FILENAME}")
        return True
    except Exception as e:
        print(f"ERROR IN GRAPHIC CREATION: {e}")
        return False


def send_to_discord():
    print("--- STEP 3: SENDING TO DISCORD ---")
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK secret missing.")
        return
    with open(OUTPUT_FILENAME, "rb") as f:
        r = requests.post(webhook, files={"file": (OUTPUT_FILENAME, f, "image/png")})
    if r.status_code in [200, 204]:
        print("SUCCESS: Post sent to Discord!")
    else:
        print(f"DISCORD ERROR {r.status_code}: {r.status_code} {r.text}")


if __name__ == "__main__":
    data = get_data()
    if create_graphic(data):
        send_to_discord()
