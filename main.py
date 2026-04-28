import os
import json
import sys
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- CONFIGURATION ---
GSHEET_ID = os.environ.get("GSHEET_ID", "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw")
TAB_NAME = os.environ.get("TAB_NAME", "Test")
BG_FILENAME = os.environ.get("BG_FILENAME", "background.png")
OUTPUT_FILENAME = os.environ.get("OUTPUT_FILENAME", "output.png")

# Final Discord image size. This matches your reference card ratio closely.
CANVAS_W = int(os.environ.get("CANVAS_W", "1035"))
CANVAS_H = int(os.environ.get("CANVAS_H", "757"))

# Table geometry tuned to the screenshot.
MARGIN_X = 16
TOP_Y = 17
TABLE_W = CANVAS_W - (MARGIN_X * 2)
HEADER_H = 22
ROW_H = 20
SEP_H = 20
BOTTOM_PAD = 16

# Sheet columns expected:
# League, PST, MTN, EST, Player 1, Player 2, BET, Unit, History, Split %, Set Break Down
COL_NAMES = ["League", "PST", "MTN", "EST", "Player 1", "Player 2", "BET", "Unit", "History", "Split %", "Set Break Down"]
COL_WIDTHS = [108, 60, 61, 61, 136, 137, 77, 76, 124, 76, 87]  # sum = 1003

BRAND_LEFT = "X.COM/BALIHQ"
BRAND_MID = "OFFICIAL PROPERTY OF BALIHQBETS"
BRAND_RIGHT = "JOIN.BALIHQBETS.COM"


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
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


FONT_HEADER = _font(10, True)
FONT_CELL = _font(9, True)
FONT_SMALL = _font(8, True)
FONT_BRAND = _font(14, True)


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


def _center_text(draw, box, text, font, fill):
    x1, y1, x2, y2 = box
    text = _fit_text(draw, text, font, max(1, x2 - x1 - 6))
    tw, th = _text_size(draw, text, font)
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2 - 1), text, font=font, fill=fill)


def _normalize_rows(rows):
    if not rows:
        return COL_NAMES, []

    header = [c.strip() for c in rows[0]][: len(COL_NAMES)]
    if len(header) < len(COL_NAMES):
        header += COL_NAMES[len(header) :]
    # If the sheet header is blank or messy, force the clean labels from the design.
    if not any(header):
        header = COL_NAMES

    clean = []
    for row in rows[1:]:
        row = [str(c).strip() for c in row[: len(COL_NAMES)]]
        row += [""] * (len(COL_NAMES) - len(row))
        clean.append(row)
    return header, clean


def _is_separator(row):
    return not any(str(c).strip() for c in row)


def _league_color(league):
    league = league.upper()
    if "CZECH" in league:
        return (0, 92, 126, 255), (255, 255, 255, 255)
    if "TT CUP" in league:
        return (239, 216, 47, 255), (25, 25, 25, 255)
    return (248, 235, 188, 255), (40, 40, 40, 255)


def _bet_color(bet):
    bet = bet.upper()
    if "UNDER" in bet:
        return (0, 89, 130, 255), (255, 255, 255, 255)
    if "OVER" in bet:
        return (245, 237, 210, 255), (20, 20, 20, 255)
    return (230, 230, 230, 255), (20, 20, 20, 255)


def _draw_shadow(draw, xy, radius=7):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle((x1 + 4, y1 + 5, x2 + 4, y2 + 5), radius=radius, fill=(0, 0, 0, 115))


def _prep_background():
    if not Path(BG_FILENAME).exists():
        print(f"ERROR: {BG_FILENAME} is missing from repo.")
        sys.exit(1)

    bg = Image.open(BG_FILENAME).convert("RGB")
    # Center-crop to Discord card ratio, then resize.
    bw, bh = bg.size
    target_ratio = CANVAS_W / CANVAS_H
    bg_ratio = bw / bh
    if bg_ratio > target_ratio:
        new_w = int(bh * target_ratio)
        left = (bw - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, bh))
    else:
        new_h = int(bw / target_ratio)
        top = (bh - new_h) // 2
        bg = bg.crop((0, top, bw, top + new_h))
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)

    # Slightly calm the background so table text wins.
    veil = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 80, 85, 35))
    bg = bg.convert("RGBA")
    bg.alpha_composite(veil)
    return bg


def create_graphic(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    try:
        header, data_rows = _normalize_rows(rows)
        img = _prep_background()
        draw = ImageDraw.Draw(img)

        # Card frame.
        table_bottom = CANVAS_H - BOTTOM_PAD
        card = (MARGIN_X, TOP_Y, MARGIN_X + TABLE_W, table_bottom)
        _draw_shadow(draw, card, radius=8)
        draw.rounded_rectangle(card, radius=8, fill=(235, 245, 247, 58), outline=(0, 95, 132, 255), width=3)

        x0 = MARGIN_X
        y = TOP_Y

        def col_xs():
            xs = [x0]
            acc = x0
            for w in COL_WIDTHS:
                acc += w
                xs.append(acc)
            return xs

        xs = col_xs()

        def draw_header(ypos):
            draw.rectangle((x0, ypos, x0 + TABLE_W, ypos + HEADER_H), fill=(43, 112, 172, 245))
            for i, name in enumerate(COL_NAMES):
                x1, x2 = xs[i], xs[i + 1]
                draw.line((x2, ypos, x2, ypos + HEADER_H), fill=(15, 55, 86, 255), width=1)
                _center_text(draw, (x1 + 3, ypos, x2 - 13, ypos + HEADER_H), name, FONT_HEADER, (255, 255, 255, 255))
                # tiny dropdown triangle, like the source sheet screenshot
                cx = x2 - 9
                cy = ypos + HEADER_H // 2 + 1
                draw.polygon([(cx - 3, cy - 2), (cx + 3, cy - 2), (cx, cy + 2)], fill=(212, 235, 244, 255))
            draw.line((x0, ypos + HEADER_H, x0 + TABLE_W, ypos + HEADER_H), fill=(0, 0, 0, 255), width=2)

        def draw_separator(ypos):
            draw.rectangle((x0, ypos, x0 + TABLE_W, ypos + SEP_H), fill=(46, 105, 164, 252))
            draw.line((x0, ypos, x0 + TABLE_W, ypos), fill=(0, 32, 70, 255), width=1)
            draw.line((x0, ypos + SEP_H - 1, x0 + TABLE_W, ypos + SEP_H - 1), fill=(0, 32, 70, 255), width=1)
            _center_text(draw, (x0 + 2, ypos, x0 + 230, ypos + SEP_H), BRAND_LEFT, FONT_BRAND, (245, 245, 245, 255))
            _center_text(draw, (x0 + 230, ypos, x0 + TABLE_W - 230, ypos + SEP_H), BRAND_MID, FONT_BRAND, (245, 245, 245, 255))
            _center_text(draw, (x0 + TABLE_W - 230, ypos, x0 + TABLE_W - 2, ypos + SEP_H), BRAND_RIGHT, FONT_BRAND, (245, 245, 245, 255))

        def draw_row(ypos, row, idx):
            base = (236, 245, 248, 220) if idx % 2 == 0 else (213, 225, 230, 220)
            draw.rectangle((x0, ypos, x0 + TABLE_W, ypos + ROW_H), fill=base)
            draw.line((x0, ypos + ROW_H, x0 + TABLE_W, ypos + ROW_H), fill=(0, 0, 0, 190), width=1)

            # Custom colored columns.
            league_fill, league_text = _league_color(row[0])
            draw.rectangle((xs[0], ypos, xs[1], ypos + ROW_H), fill=league_fill)
            bet_fill, bet_text = _bet_color(row[6])
            draw.rectangle((xs[6], ypos, xs[7], ypos + ROW_H), fill=bet_fill)

            # vertical grid. Make the important split lines thicker.
            for j, xx in enumerate(xs):
                width = 3 if j in [0, 8, 9, len(xs) - 1] else 1
                draw.line((xx, ypos, xx, ypos + ROW_H), fill=(0, 0, 0, 210), width=width)

            for i, cell in enumerate(row):
                x1, x2 = xs[i], xs[i + 1]
                fill = (0, 0, 0, 255)
                font = FONT_CELL
                text = cell
                if i == 0:
                    fill = league_text
                    font = FONT_SMALL
                elif i == 6:
                    fill = bet_text
                    text = str(cell).upper()
                elif i in [1, 2, 3, 7, 8, 9, 10]:
                    font = FONT_SMALL
                _center_text(draw, (x1 + 2, ypos, x2 - 2, ypos + ROW_H), text, font, fill)

        draw_header(y)
        y += HEADER_H
        row_count = 0
        last_was_sep = False

        for row in data_rows:
            if y + ROW_H > table_bottom:
                break

            if _is_separator(row):
                # Avoid stacked blank bars from accidental empty rows.
                if not last_was_sep and y + SEP_H <= table_bottom:
                    draw_separator(y)
                    y += SEP_H
                    last_was_sep = True
                continue

            draw_row(y, row, row_count)
            y += ROW_H
            row_count += 1
            last_was_sep = False

        # Fill leftover with final branding bar if room exists.
        if y + SEP_H <= table_bottom:
            draw_separator(y)

        img.convert("RGB").save(OUTPUT_FILENAME, quality=95)
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
