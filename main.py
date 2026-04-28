import os, json, sys, re
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# =========================
# CONFIG
# =========================
GSHEET_ID = os.environ.get("GSHEET_ID", "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw")
TAB_NAME = os.environ.get("TAB_NAME", "Test")
BG_FILENAME = os.environ.get("BG_FILENAME", "background.png")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "output")

ROOT = Path(__file__).resolve().parent
FONTS_DIR = ROOT / "fonts"

# Render larger so Discord previews/attachments stay sharp.
# Use RENDER_SCALE=1 if you need the original small output.
RENDER_SCALE = int(os.environ.get("RENDER_SCALE", "2"))

def sc(v: int) -> int:
    return int(round(v * RENDER_SCALE))

CANVAS_W = sc(int(os.environ.get("CANVAS_W", "1038")))
CANVAS_H = sc(int(os.environ.get("CANVAS_H", "757")))
FRAME_PAD = sc(10)
X0 = sc(int(os.environ.get("TABLE_X", "15")))
Y0 = sc(int(os.environ.get("TABLE_Y", "17")))
HEADER_H = sc(int(os.environ.get("HEADER_H", "21")))
BOTTOM_Y = CANVAS_H - sc(15)

COL_NAMES = ["League", "PST", "MTN", "EST", "Player 1", "Player 2", "BET", "Unit", "History", "Split %", "Set Break Down"]
COL_WIDTHS = [sc(v) for v in [109, 61, 61, 61, 137, 138, 77, 76, 124, 77, 87]]
TABLE_W = sum(COL_WIDTHS)

BRAND_LEFT = os.environ.get("BRAND_LEFT", "x.com/balihq").lower()
BRAND_MID = os.environ.get("BRAND_MID", "official property of balihqbets").lower()
BRAND_RIGHT = os.environ.get("BRAND_RIGHT", "join.balihqbets.com").lower()

# =========================
# COLORS
# =========================
HEADER_TOP = (55, 139, 201, 255)
HEADER_BOT = (30, 101, 167, 255)
BAR_TOP = (55, 135, 198, 255)
BAR_BOT = (31, 100, 164, 255)
BAR_SHADOW = (0, 45, 78, 255)
GREEN = (0, 181, 45, 255)
GRID = (0, 0, 0, 92)
GRID_SOFT = (0, 0, 0, 38)
WHITE = (255, 255, 255, 255)
TEXT = (0, 0, 0, 255)
ROW_LIGHT = (242, 250, 253, 108)
ROW_DARK = (181, 201, 210, 108)
TT_CUP = (245, 224, 19, 255)
TT_ELITE = (252, 242, 203, 242)
CZECH = (0, 91, 127, 255)
BET_UNDER = (0, 91, 132, 255)
BET_OVER = (248, 239, 216, 242)
BET_SPLIT = (230, 230, 230, 242)

TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)$", re.I)
HIST_RE = re.compile(r"^\d+\s*/\s*\d+$")
PCT_RE = re.compile(r"^\d+\s*%$")
SET_RE = re.compile(r"^\d+\s*-\s*\d+\s*-\s*\d+$")

# =========================
# FONT FIX: download valid Lexend every run if local file is bad/missing
# =========================
FONT_URLS = {
    "Lexend-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/lexend/static/Lexend-Regular.ttf",
    "Lexend-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/lexend/static/Lexend-Bold.ttf",
    "BebasNeue-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
}


def font_is_valid(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 10_000:
            return False
        ImageFont.truetype(str(path), 10)
        return True
    except Exception:
        return False


def download_font(filename: str) -> Path:
    FONTS_DIR.mkdir(exist_ok=True)
    path = FONTS_DIR / filename
    url = FONT_URLS[filename]
    print(f"FONT DOWNLOAD: {filename}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    path.write_bytes(r.content)
    if not font_is_valid(path):
        raise RuntimeError(f"Downloaded font is still invalid: {path} size={path.stat().st_size}")
    return path


def get_lexend(filename: str) -> Path:
    path = FONTS_DIR / filename
    if font_is_valid(path):
        print(f"FONT OK: {path}")
        return path
    # Delete junk files with same name so bad uploads cannot poison PIL.
    if path.exists():
        print(f"FONT BAD, REPLACING: {path} size={path.stat().st_size}")
        try:
            path.unlink()
        except Exception:
            pass
    return download_font(filename)


def find_brand_font() -> Path | None:
    # The blue filler/banner strip should use Bebas Neue.
    # Put the file here: /fonts/BebasNeue-Regular.ttf
    preferred_names = {
        "bebasneue-regular.ttf",
        "bebas neue regular.ttf",
        "bebasneue.ttf",
        "bebas-neue.ttf",
    }
    fallback_names = {
        "superchargestraight.ttf",
        "supercharge straight.ttf",
        "supercharge_straight.ttf",
    }

    for names, label in [(preferred_names, "BEBAS BRAND FONT"), (fallback_names, "FALLBACK BRAND FONT")]:
        for folder in [FONTS_DIR, ROOT, ROOT / "assets"]:
            if not folder.exists():
                continue
            for p in folder.iterdir():
                if p.is_file() and p.name.lower() in names and font_is_valid(p):
                    print(f"{label} OK: {p}")
                    return p

    try:
        print("BEBAS BRAND FONT MISSING: downloading BebasNeue-Regular.ttf")
        return download_font("BebasNeue-Regular.ttf")
    except Exception as e:
        print(f"BEBAS DOWNLOAD FAILED: {e}")

    print("BRAND FONT MISSING/BAD: using Lexend fallback for filler text")
    return None


LEXEND_REGULAR = get_lexend("Lexend-Regular.ttf")
LEXEND_BOLD = get_lexend("Lexend-Bold.ttf")
BRAND_FONT_PATH = find_brand_font()


def fnt(size: int, role: str = "body"):
    if role == "brand" and BRAND_FONT_PATH:
        return ImageFont.truetype(str(BRAND_FONT_PATH), size)
    if role == "header":
        return ImageFont.truetype(str(LEXEND_BOLD), size)
    return ImageFont.truetype(str(LEXEND_REGULAR), size)


# =========================
# GOOGLE SHEET
# =========================
def get_data():
    print("--- STEP 1: CONNECTING TO GOOGLE ---")
    creds_raw = os.environ.get("GSHEET_JSON")
    if not creds_raw:
        print("ERROR: GSHEET_JSON secret is missing.")
        sys.exit(1)
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(json.loads(creds_raw), scopes=scopes)
        sheet = gspread.authorize(creds).open_by_key(GSHEET_ID).worksheet(TAB_NAME)
        rows = sheet.get_all_values()
        print(f"SUCCESS: Found {len(rows)} rows in tab '{TAB_NAME}'.")
        return rows
    except Exception as e:
        print(f"ERROR CONNECTING TO GOOGLE: {e}")
        sys.exit(1)


# =========================
# DATA NORMALIZATION
# =========================
def is_blank(row):
    return not any(str(c).strip() for c in row)


def extract_row(raw):
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

    times = [(i, c) for i, c in enumerate(cells[league_i + 1:], league_i + 1) if TIME_RE.match(c)]
    for k in range(min(3, len(times))):
        out[1 + k] = times[k][1].upper()

    after_time = times[2][0] + 1 if len(times) >= 3 else league_i + 4
    bet_i = None
    for i in range(after_time, len(cells)):
        u = cells[i].upper()
        if u in ("OVER", "UNDER", "SPLIT"):
            bet_i = i
            out[6] = u
            break

    names = [c for c in cells[after_time:bet_i] if c] if bet_i is not None else []
    if names:
        out[4] = names[0]
    if len(names) > 1:
        out[5] = names[1]

    tail = [c for c in cells[(bet_i + 1 if bet_i is not None else after_time):] if c]
    for c in tail:
        clean = c.replace(" ", "")
        if not out[8] and HIST_RE.match(c):
            out[8] = clean
        elif not out[9] and PCT_RE.match(c):
            out[9] = clean
        elif not out[10] and SET_RE.match(c):
            out[10] = clean
        elif not out[7]:
            try:
                v = float(c)
                out[7] = str(int(v)) if v.is_integer() else str(v).rstrip("0").rstrip(".")
            except Exception:
                pass
    return out


def normalize(rows):
    clean, prev_sep = [], False
    for raw in rows:
        if is_blank(raw):
            if clean and not prev_sep:
                clean.append(None)
                prev_sep = True
            continue
        r = extract_row(raw)
        if r == "HEADER":
            continue
        if r:
            clean.append(r)
            prev_sep = False
    while clean and clean[-1] is None:
        clean.pop()
    clean.append(None)  # bottom filler bar like your sheet
    return clean


# =========================
# DRAW HELPERS
# =========================
def text_size(draw, text, font):
    b = draw.textbbox((0, 0), str(text), font=font)
    return b[2] - b[0], b[3] - b[1]


def fit_text(draw, text, font, max_w):
    s = str(text).strip()
    if text_size(draw, s, font)[0] <= max_w:
        return s
    while s and text_size(draw, s + "…", font)[0] > max_w:
        s = s[:-1]
    return s + "…" if s else "…"


def center_text(draw, box, text, font, fill, stroke=0, stroke_fill=(0, 0, 0, 220), yoff=-1):
    x1, y1, x2, y2 = box
    s = fit_text(draw, text, font, max(1, x2 - x1 - 4))
    tw, th = text_size(draw, s, font)
    x = x1 + (x2 - x1 - tw) / 2
    y = y1 + (y2 - y1 - th) / 2 + yoff
    draw.text((x, y), s, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill if stroke else None)


def gradient(draw, xy, top, bot):
    x1, y1, x2, y2 = [int(v) for v in xy]
    h = max(1, y2 - y1)
    for i in range(h):
        t = i / max(1, h - 1)
        c = tuple(int(top[k] * (1 - t) + bot[k] * t) for k in range(4))
        draw.line((x1, y1 + i, x2, y1 + i), fill=c)


def background():
    p = ROOT / BG_FILENAME
    if not p.exists():
        print(f"ERROR: {BG_FILENAME} missing.")
        sys.exit(1)
    bg = Image.open(p).convert("RGB")
    bw, bh = bg.size
    target = CANVAS_W / CANVAS_H
    if bw / bh > target:
        nw = int(bh * target)
        left = (bw - nw) // 2
        bg = bg.crop((left, 0, left + nw, bh))
    else:
        nh = int(bw / target)
        top = max(0, (bh - nh) // 2)
        bg = bg.crop((0, top, bw, top + nh))
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Contrast(bg).enhance(1.12)
    bg = ImageEnhance.Sharpness(bg).enhance(1.15)
    bg = ImageEnhance.Color(bg).enhance(1.08)
    return bg.convert("RGBA")


def league_style(v):
    u = str(v).upper()
    if "CZECH" in u:
        return CZECH, WHITE
    if "TT CUP" in u:
        return TT_CUP, (31, 27, 0, 255)
    return TT_ELITE, TEXT


def bet_style(v):
    u = str(v).upper()
    if "UNDER" in u:
        return BET_UNDER, WHITE
    if "SPLIT" in u:
        return BET_SPLIT, TEXT
    return BET_OVER, TEXT


def layout_for_single_image(items):
    row_count = sum(1 for x in items if x is not None)
    bar_count = sum(1 for x in items if x is None)
    usable_h = BOTTOM_Y - (Y0 + HEADER_H)

    # Target reference density. Shrinks only enough to keep ONE image.
    target_row_h = sc(20)
    target_sep_h = sc(20)
    if row_count * target_row_h + bar_count * target_sep_h <= usable_h:
        return target_row_h, target_sep_h

    sep_h = sc(17)
    row_h = max(sc(10), int((usable_h - bar_count * sep_h) / max(1, row_count)))
    if row_h < sc(13):
        sep_h = sc(14)
        row_h = max(sc(9), int((usable_h - bar_count * sep_h) / max(1, row_count)))
    return row_h, sep_h


def build_fonts(row_h, sep_h):
    body_size = max(sc(7), min(sc(10), row_h - sc(6)))
    header_size = sc(10)

    # Blue filler/banner strip: Bebas Neue needs to be larger than the old filler font.
    brand_size = max(sc(9), min(sc(14), sep_h - sc(4)))
    return {
        "header": fnt(header_size, "header"),
        "body": fnt(body_size, "body"),
        "name": fnt(body_size, "body"),
        "brand": fnt(brand_size, "brand"),
        "brand_small": fnt(max(sc(8), brand_size - sc(1)), "brand"),
    }


def draw_header(draw, xs, fonts):
    gradient(draw, (X0, Y0, X0 + TABLE_W, Y0 + HEADER_H), HEADER_TOP, HEADER_BOT)
    draw.line((X0, Y0 + 1, X0 + TABLE_W, Y0 + 1), fill=(130, 190, 225, 125), width=1)
    for i, name in enumerate(COL_NAMES):
        x1, x2 = xs[i], xs[i + 1]
        label = "Set Break..." if name == "Set Break Down" else name
        if i in (0, 6):
            cx, cy = x1 + 13, Y0 + HEADER_H // 2
            draw.ellipse((cx - 4, cy - 3, cx + 4, cy + 3), outline=(230, 245, 255, 220), width=1)
            draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=(230, 245, 255, 220))
        center_text(draw, (x1 + 5, Y0, x2 - 16, Y0 + HEADER_H), label, fonts["header"], WHITE, yoff=-1)
        draw.polygon([(x2 - 13, Y0 + 8), (x2 - 5, Y0 + 8), (x2 - 9, Y0 + 15)], fill=(224, 240, 250, 240))
        draw.line((x2, Y0, x2, Y0 + HEADER_H), fill=(0, 42, 79, 230), width=1)
    draw.line((X0, Y0, X0 + TABLE_W, Y0), fill=GREEN, width=1)
    draw.line((X0, Y0 + HEADER_H, X0 + TABLE_W, Y0 + HEADER_H), fill=(0, 42, 79, 210), width=1)


def draw_bar(draw, y, sep_h, fonts):
    gradient(draw, (X0, y, X0 + TABLE_W, y + sep_h), BAR_TOP, BAR_BOT)
    draw.line((X0, y + 1, X0 + TABLE_W, y + 1), fill=(126, 186, 226, 135), width=1)
    draw.line((X0, y + sep_h - 2, X0 + TABLE_W, y + sep_h - 2), fill=BAR_SHADOW, width=1)
    draw.line((X0, y, X0 + TABLE_W, y), fill=(0, 42, 79, 185), width=1)
    draw.line((X0, y + sep_h - 1, X0 + TABLE_W, y + sep_h - 1), fill=(0, 42, 79, 185), width=1)
    center_text(draw, (X0 + sc(7), y, X0 + sc(258), y + sep_h), BRAND_LEFT.upper(), fonts["brand"], WHITE, stroke=0, yoff=-1)
    center_text(draw, (X0 + sc(242), y, X0 + TABLE_W - sc(242), y + sep_h), BRAND_MID.upper(), fonts["brand"], WHITE, stroke=0, yoff=-1)
    center_text(draw, (X0 + TABLE_W - sc(258), y, X0 + TABLE_W - sc(7), y + sep_h), BRAND_RIGHT.upper(), fonts["brand_small"], WHITE, stroke=0, yoff=-1)


def draw_row(draw, xs, y, row, idx, row_h, fonts):
    draw.rectangle((X0, y, X0 + TABLE_W, y + row_h), fill=ROW_LIGHT if idx % 2 == 0 else ROW_DARK)
    lf, lt = league_style(row[0])
    bf, bt = bet_style(row[6])
    draw.rectangle((xs[0], y, xs[1], y + row_h), fill=lf)
    draw.rectangle((xs[6], y, xs[7], y + row_h), fill=bf)

    for j, xx in enumerate(xs):
        width = 2 if j in (0, 8, 9, len(xs) - 1) else 1
        draw.line((xx, y, xx, y + row_h), fill=GRID, width=width)
    draw.line((X0, y + row_h, X0 + TABLE_W, y + row_h), fill=GRID_SOFT, width=1)

    for i, c in enumerate(row):
        font = fonts["name"] if i in (4, 5) else fonts["body"]
        fill = lt if i == 0 else bt if i == 6 else TEXT
        value = str(c).upper() if i == 6 else c
        center_text(draw, (xs[i] + 2, y, xs[i + 1] - 2, y + row_h), value, font, fill, yoff=-1)


def render_single(items):
    row_h, sep_h = layout_for_single_image(items)
    fonts = build_fonts(row_h, sep_h)

    img = background()
    draw = ImageDraw.Draw(img, "RGBA")
    xs = [X0]
    for w in COL_WIDTHS:
        xs.append(xs[-1] + w)

    # No full-canvas green frame. The green outline belongs on the sheet only.

    draw_header(draw, xs, fonts)
    y = Y0 + HEADER_H
    row_idx = 0
    for item in items:
        if item is None:
            draw_bar(draw, y, sep_h, fonts)
            y += sep_h
        else:
            draw_row(draw, xs, y, item, row_idx, row_h, fonts)
            y += row_h
            row_idx += 1

    # Sheet outline: green only.
    draw.rectangle((X0, Y0, X0 + TABLE_W, min(y, BOTTOM_Y)), outline=GREEN, width=sc(3))

    out = f"{OUTPUT_PREFIX}.png"
    img.convert("RGB").save(out, quality=98, optimize=True)
    print(f"SUCCESS: Rendered ONE image: rows={row_idx}, row_h={row_h}, sep_h={sep_h}, size={CANVAS_W}x{CANVAS_H}, file={out}")
    return out


def create_graphics(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    items = normalize(rows)
    return [render_single(items)]


def send_to_discord(files):
    print("--- STEP 3: SENDING TO DISCORD ---")
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK secret missing.")
        return
    for fn in files:
        with open(fn, "rb") as f:
            r = requests.post(webhook, files={"file": (fn, f, "image/png")})
        if r.status_code in (200, 204):
            print(f"SUCCESS: Sent {fn} to Discord.")
        else:
            print(f"DISCORD ERROR {r.status_code}: {r.text}")


if __name__ == "__main__":
    data = get_data()
    files = create_graphics(data)
    if files:
        send_to_discord(files)
