import os
import json
import sys
import re
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

CANVAS_W = int(os.environ.get("CANVAS_W", "1038"))
CANVAS_H = int(os.environ.get("CANVAS_H", "757"))
MARGIN_X = int(os.environ.get("MARGIN_X", "15"))
TOP_Y = int(os.environ.get("TOP_Y", "15"))
HEADER_H = int(os.environ.get("HEADER_H", "21"))
ROW_H_DEFAULT = int(os.environ.get("ROW_H", "20"))
SEP_H_DEFAULT = int(os.environ.get("SEP_H", "20"))
BOTTOM_PAD = int(os.environ.get("BOTTOM_PAD", "12"))

COL_NAMES = ["League", "PST", "MTN", "EST", "Player 1", "Player 2", "BET", "Unit", "History", "Split %", "Set Break Down"]
# Sum = 1008. On a 1038 canvas with 15px margins this lands exactly like the reference.
COL_WIDTHS = [109, 61, 61, 61, 137, 138, 77, 76, 124, 77, 87]
TABLE_W = sum(COL_WIDTHS)

BRAND_LEFT = os.environ.get("BRAND_LEFT", "x.com/balihq")
BRAND_MID = os.environ.get("BRAND_MID", "official property of balihqbets")
BRAND_RIGHT = os.environ.get("BRAND_RIGHT", "join.balihqbets.com")

# Reference-grade colors.
BLUE_HEADER_TOP = (50, 128, 190, 255)
BLUE_HEADER_BOT = (35, 101, 164, 255)
BLUE_BAR_TOP = (56, 134, 196, 255)
BLUE_BAR_BOT = (28, 100, 162, 255)
BLUE_BAR_DARK = (0, 52, 84, 255)
GRID_BLACK = (0, 0, 0, 235)
GRID_SOFT = (0, 0, 0, 102)
OUTLINE_GREEN = (0, 177, 44, 255)
TEXT_DARK = (0, 0, 0, 255)
TEXT_WHITE = (255, 255, 255, 255)
ROW_LIGHT = (240, 250, 252, 108)
ROW_DARK = (190, 207, 216, 108)
LEAGUE_TT_CUP = (244, 223, 27, 255)
LEAGUE_TT_ELITE = (252, 241, 202, 244)
LEAGUE_CZECH = (0, 92, 128, 255)
BET_UNDER = (0, 91, 132, 255)
BET_OVER = (248, 239, 214, 244)
BET_SPLIT = (230, 230, 230, 244)

TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)$", re.I)
HIST_RE = re.compile(r"^\d+\s*/\s*\d+$")
PCT_RE = re.compile(r"^\d+\s*%$")
SET_RE = re.compile(r"^\d+\s*-\s*\d+\s*-\s*\d+$")


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


def _font(size, kind="sheet"):
    """Loads requested repo fonts first. Put both .ttf files beside main.py/background.png."""
    root = Path(__file__).resolve().parent
    preferred = []
    if kind == "brand":
        preferred += [
            root / "superchargestraight.ttf",
            root / "SuperchargeStraight.ttf",
            Path("superchargestraight.ttf"),
        ]
    else:
        preferred += [
            root / "Lexend-Regular.ttf",
            root / "lexend-regular.ttf",
            Path("Lexend-Regular.ttf"),
        ]
    fallback = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in preferred + [Path(x) for x in fallback]:
        if Path(p).exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


FONT_HEADER = _font(11, "sheet")
FONT_CELL = _font(9, "sheet")
FONT_NAME = _font(9, "sheet")
FONT_BRAND = _font(13, "brand")
FONT_BRAND_SMALL = _font(12, "brand")


def _text_size(draw, text, font):
    b = draw.textbbox((0, 0), str(text), font=font)
    return b[2] - b[0], b[3] - b[1]


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


def _center_text(draw, box, text, font, fill, stroke=0, y_offset=0):
    x1, y1, x2, y2 = box
    text = _fit_text(draw, text, font, max(1, x2 - x1 - 4))
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2 - 1 + y_offset),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 205) if stroke else None,
    )


def _is_separator_raw(row):
    return not any(str(c).strip() for c in row)


def _extract_row(raw):
    cells = [str(c).strip() for c in raw]
    if not any(cells):
        return None
    low = " ".join(c.lower() for c in cells)
    if "league" in low and "player" in low:
        return "HEADER"

    out = [""] * len(COL_NAMES)
    league_i = None
    for i, c in enumerate(cells):
        u = c.upper()
        if "TT CUP" in u or "TT ELITE" in u or "CZECH" in u:
            league_i = i
            out[0] = c
            break
    if league_i is None:
        return None

    times = [(i, c) for i, c in enumerate(cells[league_i + 1:], start=league_i + 1) if TIME_RE.match(c)]
    for k in range(min(3, len(times))):
        out[1 + k] = times[k][1]
    after_time = times[2][0] + 1 if len(times) >= 3 else league_i + 4

    bet_i = None
    for i in range(after_time, len(cells)):
        u = cells[i].upper()
        if u in {"OVER", "UNDER", "SPLIT"}:
            bet_i = i
            out[6] = u
            break

    name_cells = [c for c in cells[after_time:bet_i] if c] if bet_i is not None else []
    if name_cells:
        out[4] = name_cells[0]
    if len(name_cells) > 1:
        out[5] = name_cells[1]

    search_start = bet_i + 1 if bet_i is not None else after_time
    tail = [c for c in cells[search_start:] if c]
    for c in tail:
        if not out[8] and HIST_RE.match(c):
            out[8] = c.replace(" ", "")
        elif not out[9] and PCT_RE.match(c):
            out[9] = c.replace(" ", "")
        elif not out[10] and SET_RE.match(c):
            out[10] = c.replace(" ", "")
        elif not out[7]:
            try:
                float(c)
                out[7] = c.rstrip("0").rstrip(".") if "." in c else c
            except ValueError:
                pass
    return out


def _normalize_rows(rows):
    clean = []
    previous_sep = False
    for raw in rows:
        if _is_separator_raw(raw):
            if clean and not previous_sep:
                clean.append(None)
                previous_sep = True
            continue
        row = _extract_row(raw)
        if row == "HEADER":
            continue
        if row:
            clean.append(row)
            previous_sep = False
    while clean and clean[-1] is None:
        clean.pop()
    return clean


def _league_color(league):
    league = str(league).upper()
    if "CZECH" in league:
        return LEAGUE_CZECH, TEXT_WHITE
    if "TT CUP" in league:
        return LEAGUE_TT_CUP, (30, 26, 0, 255)
    return LEAGUE_TT_ELITE, (18, 18, 18, 255)


def _bet_color(bet):
    bet = str(bet).upper()
    if "UNDER" in bet:
        return BET_UNDER, TEXT_WHITE
    if "OVER" in bet:
        return BET_OVER, TEXT_DARK
    return BET_SPLIT, TEXT_DARK


def _prep_background(canvas_h):
    if not Path(BG_FILENAME).exists():
        print(f"ERROR: {BG_FILENAME} is missing from repo.")
        sys.exit(1)
    bg = Image.open(BG_FILENAME).convert("RGB")
    bw, bh = bg.size
    target = CANVAS_W / canvas_h
    ratio = bw / bh
    if ratio > target:
        nw = int(bh * target)
        left = (bw - nw) // 2
        bg = bg.crop((left, 0, left + nw, bh))
    else:
        nh = int(bw / target)
        top = max(0, (bh - nh) // 2)
        bg = bg.crop((0, top, bw, top + nh))
    bg = bg.resize((CANVAS_W, canvas_h), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Contrast(bg).enhance(1.10)
    bg = ImageEnhance.Sharpness(bg).enhance(1.18)
    bg = ImageEnhance.Color(bg).enhance(1.08)
    return bg.convert("RGBA")


def _draw_gradient_rect(draw, xy, top, bottom):
    x1, y1, x2, y2 = map(int, xy)
    h = max(1, y2 - y1)
    for yy in range(h):
        t = yy / max(1, h - 1)
        col = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(4))
        draw.line((x1, y1 + yy, x2, y1 + yy), fill=col)


def _draw_tiny_filter(draw, x, y, color=(224, 240, 250, 255)):
    draw.polygon([(x - 4, y - 3), (x + 4, y - 3), (x, y + 4)], fill=color)


def _draw_header(draw, x0, xs, y):
    _draw_gradient_rect(draw, (x0, y, x0 + TABLE_W, y + HEADER_H), BLUE_HEADER_TOP, BLUE_HEADER_BOT)
    # subtle top shine
    draw.line((x0 + 1, y + 1, x0 + TABLE_W - 1, y + 1), fill=(117, 178, 219, 115), width=1)
    for i, name in enumerate(COL_NAMES):
        x1, x2 = xs[i], xs[i + 1]
        draw.line((x2, y, x2, y + HEADER_H), fill=(0, 43, 80, 255), width=1)
        label = "Set Break D..." if name == "Set Break Down" else name
        _center_text(draw, (x1 + 4, y, x2 - 15, y + HEADER_H), label, FONT_HEADER, TEXT_WHITE)
        _draw_tiny_filter(draw, x2 - 10, y + HEADER_H // 2 + 1)
    # small eye-like pills in first and bet headers to mimic the sheet UI
    for col in (0, 6):
        cx = xs[col] + 14
        cy = y + HEADER_H // 2
        draw.ellipse((cx - 4, cy - 3, cx + 4, cy + 3), outline=(218, 239, 250, 210), width=1)
        draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=(218, 239, 250, 210))
    draw.line((x0, y, x0 + TABLE_W, y), fill=GRID_BLACK, width=2)
    draw.line((x0, y + HEADER_H, x0 + TABLE_W, y + HEADER_H), fill=GRID_BLACK, width=2)


def _draw_separator(draw, x0, y, sep_h):
    # Lowercase by design: superchargestraight.ttf renders cleaner in lowercase.
    _draw_gradient_rect(draw, (x0, y, x0 + TABLE_W, y + sep_h), BLUE_BAR_TOP, BLUE_BAR_BOT)
    draw.rectangle((x0, y, x0 + TABLE_W, y + sep_h), outline=(0, 0, 0, 245), width=1)
    draw.line((x0, y + 1, x0 + TABLE_W, y + 1), fill=(126, 187, 226, 150), width=1)
    draw.line((x0, y + sep_h - 2, x0 + TABLE_W, y + sep_h - 2), fill=(0, 47, 80, 190), width=1)
    _center_text(draw, (x0 + 8, y, x0 + 258, y + sep_h), BRAND_LEFT.lower(), FONT_BRAND, TEXT_WHITE, stroke=1, y_offset=-1)
    _center_text(draw, (x0 + 245, y, x0 + TABLE_W - 245, y + sep_h), BRAND_MID.lower(), FONT_BRAND, TEXT_WHITE, stroke=1, y_offset=-1)
    _center_text(draw, (x0 + TABLE_W - 258, y, x0 + TABLE_W - 8, y + sep_h), BRAND_RIGHT.lower(), FONT_BRAND_SMALL, TEXT_WHITE, stroke=1, y_offset=-1)

def _draw_row(draw, x0, xs, y, row, idx, row_h):
    base = ROW_LIGHT if idx % 2 == 0 else ROW_DARK
    draw.rectangle((x0, y, x0 + TABLE_W, y + row_h), fill=base)
    league_fill, league_text = _league_color(row[0])
    bet_fill, bet_text = _bet_color(row[6])
    draw.rectangle((xs[0], y, xs[1], y + row_h), fill=league_fill)
    draw.rectangle((xs[6], y, xs[7], y + row_h), fill=bet_fill)

    # right-side dark separators in the reference are heavier.
    for j, xx in enumerate(xs):
        width = 3 if j in (0, 8, 9, len(xs) - 1) else 1
        draw.line((xx, y, xx, y + row_h), fill=GRID_BLACK, width=width)
    draw.line((x0, y + row_h, x0 + TABLE_W, y + row_h), fill=GRID_SOFT, width=1)

    for i, cell in enumerate(row):
        font = FONT_NAME if i in (4, 5) else FONT_CELL
        fill = TEXT_DARK
        text = cell
        if i == 0:
            fill = league_text
        elif i == 6:
            fill = bet_text
            text = str(cell).upper()
        _center_text(draw, (xs[i] + 2, y, xs[i + 1] - 2, y + row_h), text, font, fill)


def _fit_vertical(rows):
    sep_count = sum(1 for r in rows if r is None) + 1
    data_count = sum(1 for r in rows if r is not None)
    available = CANVAS_H - TOP_Y - HEADER_H - BOTTOM_PAD
    row_h = ROW_H_DEFAULT
    sep_h = SEP_H_DEFAULT
    needed = data_count * row_h + sep_count * sep_h
    if needed > available and data_count + sep_count > 0:
        scale = available / needed
        row_h = max(14, int(row_h * scale))
        sep_h = max(15, int(sep_h * scale))
        while data_count * row_h + sep_count * sep_h > available and row_h > 13:
            row_h -= 1
        while data_count * row_h + sep_count * sep_h > available and sep_h > 13:
            sep_h -= 1
    return row_h, sep_h, CANVAS_H

def create_graphic(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    try:
        data_rows = _normalize_rows(rows)
        row_h, sep_h, canvas_h = _fit_vertical(data_rows)
        img = _prep_background(canvas_h)
        draw = ImageDraw.Draw(img, "RGBA")

        x0 = MARGIN_X
        table_bottom = canvas_h - BOTTOM_PAD
        xs = [x0]
        for w in COL_WIDTHS:
            xs.append(xs[-1] + w)

        # Crisp rectangular frame like the reference sheet. No rounded shadow-card.
        draw.rectangle((9, 9, CANVAS_W - 9, table_bottom + 6), outline=OUTLINE_GREEN, width=5)
        draw.rectangle((14, 14, CANVAS_W - 14, table_bottom + 1), outline=(0, 75, 25, 230), width=1)
        draw.rectangle((x0, TOP_Y, x0 + TABLE_W, table_bottom), fill=(225, 245, 248, 4))

        y = TOP_Y
        _draw_header(draw, x0, xs, y)
        y += HEADER_H

        row_count = 0
        last_was_sep = False
        for row in data_rows:
            if row is None:
                if not last_was_sep:
                    _draw_separator(draw, x0, y, sep_h)
                    y += sep_h
                    last_was_sep = True
                continue
            _draw_row(draw, x0, xs, y, row, row_count, row_h)
            y += row_h
            row_count += 1
            last_was_sep = False

        _draw_separator(draw, x0, y, sep_h)
        y += sep_h
        draw.rectangle((x0, TOP_Y, x0 + TABLE_W, y), outline=GRID_BLACK, width=2)

        img.convert("RGB").save(OUTPUT_FILENAME, quality=98, optimize=True)
        print(f"SUCCESS: Rendered {row_count} rows as {OUTPUT_FILENAME} ({CANVAS_W}x{canvas_h}).")
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
