import os, json, sys, re, math
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ===== SHEET / DISCORD CONFIG =====
GSHEET_ID = os.environ.get("GSHEET_ID", "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw")
TAB_NAME = os.environ.get("TAB_NAME", "Test")
BG_FILENAME = os.environ.get("BG_FILENAME", "background.png")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "output")

# ===== REFERENCE CLONE GEOMETRY =====
CANVAS_W = int(os.environ.get("CANVAS_W", "1038"))
CANVAS_H = int(os.environ.get("CANVAS_H", "757"))
FRAME_PAD = 10
X0 = int(os.environ.get("TABLE_X", "15"))
Y0 = int(os.environ.get("TABLE_Y", "17"))
HEADER_H = int(os.environ.get("HEADER_H", "21"))
ROW_H = int(os.environ.get("ROW_H", "20"))
SEP_H = int(os.environ.get("SEP_H", "20"))
BOTTOM_Y = CANVAS_H - 15

COL_NAMES = ["League", "PST", "MTN", "EST", "Player 1", "Player 2", "BET", "Unit", "History", "Split %", "Set Break Down"]
# Pixel widths locked to the target screenshot rhythm. Sum = 1008, 15px side margins on 1038 canvas.
COL_WIDTHS = [109, 61, 61, 61, 137, 138, 77, 76, 124, 77, 87]
TABLE_W = sum(COL_WIDTHS)

BRAND_LEFT = os.environ.get("BRAND_LEFT", "x.com/balihq").lower()
BRAND_MID = os.environ.get("BRAND_MID", "official property of balihqbets").lower()
BRAND_RIGHT = os.environ.get("BRAND_RIGHT", "join.balihqbets.com").lower()

# ===== COLORS — tuned to the provided reference =====
HEADER_TOP = (55, 139, 201, 255)
HEADER_BOT = (30, 101, 167, 255)
BAR_TOP = (55, 135, 198, 255)
BAR_BOT = (31, 100, 164, 255)
BAR_SHADOW = (0, 45, 78, 255)
GREEN = (0, 181, 45, 255)
GREEN_DARK = (0, 83, 31, 255)
BLACK = (0, 0, 0, 255)
GRID = (0, 0, 0, 92)
GRID_SOFT = (0, 0, 0, 32)
WHITE = (255, 255, 255, 255)
TEXT = (0, 0, 0, 255)
ROW_LIGHT = (246, 251, 253, 98)
ROW_DARK = (178, 199, 208, 116)
TT_CUP = (245, 224, 19, 255)
TT_ELITE = (252, 242, 203, 245)
CZECH = (0, 91, 127, 255)
BET_UNDER = (0, 91, 132, 255)
BET_OVER = (248, 239, 216, 245)
BET_SPLIT = (230, 230, 230, 245)

TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)$", re.I)
HIST_RE = re.compile(r"^\d+\s*/\s*\d+$")
PCT_RE = re.compile(r"^\d+\s*%$")
SET_RE = re.compile(r"^\d+\s*-\s*\d+\s*-\s*\d+$")

ROOT = Path(__file__).resolve().parent


def _font_candidates(names):
    """Find fonts reliably in GitHub Actions.

    The previous renderer could silently fall back to DejaVu if the current
    working directory was different or if the file lived in /fonts. This scans
    the repo root, common font folders, then the whole project tree using a
    case-insensitive match. The exact font path prints in the Actions log.
    """
    wanted = {n.lower(): n for n in names}
    wanted_norm = {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names}
    roots = [ROOT, Path.cwd(), Path(os.environ.get("GITHUB_WORKSPACE", "/github/workspace"))]
    folders = []
    for r in roots:
        try:
            if r.exists():
                folders += [r, r / "fonts", r / "Fonts", r / "assets", r / "Assets", r / "font"]
        except Exception:
            pass

    for folder in folders:
        if not folder.exists():
            continue
        for child in folder.iterdir():
            if child.is_file() and (child.name.lower() in wanted or re.sub(r"[^a-z0-9]", "", child.name.lower()) in wanted_norm):
                return str(child)

    for child in ROOT.rglob("*.ttf"):
        if child.name.lower() in wanted or re.sub(r"[^a-z0-9]", "", child.name.lower()) in wanted_norm:
            return str(child)
    for child in ROOT.rglob("*.otf"):
        if child.name.lower() in wanted or re.sub(r"[^a-z0-9]", "", child.name.lower()) in wanted_norm:
            return str(child)
    for base in [Path.cwd(), Path(os.environ.get("GITHUB_WORKSPACE", "/github/workspace"))]:
        try:
            for child in list(base.rglob("*.ttf")) + list(base.rglob("*.otf")):
                if child.name.lower() in wanted or re.sub(r"[^a-z0-9]", "", child.name.lower()) in wanted_norm:
                    return str(child)
        except Exception:
            pass
    print(f"FONT DEBUG: looked for {names}; cwd={Path.cwd()}; root={ROOT}")
    return None


_LOADED_FONT_PATHS = {}


def font(size, role="body"):
    # Sheet text uses normal Lexend Regular — the same family/look Google Sheets uses.
    # Put the font at: ./fonts/Lexend-Regular.ttf
    if role == "brand":
        names = ["superchargestraight.ttf", "SuperchargeStraight.ttf", "supercharge_straight.ttf", "supercharge-straight.ttf"]
    elif role == "header":
        names = ["Lexend-Regular.ttf", "Lexend.Regular.ttf", "Lexend.ttf", "Lexend-Regular.otf", "LexendRegular.ttf"]
    else:
        names = ["Lexend-Regular.ttf", "Lexend.ttf", "Lexend-Regular.otf"]

    found = _font_candidates(names)
    if found:
        key = f"{role}:{Path(found).name}"
        if key not in _LOADED_FONT_PATHS:
            print(f"FONT OK [{role}]: {found}")
            _LOADED_FONT_PATHS[key] = found
        return ImageFont.truetype(found, size)

    # Do NOT fail silently anymore. The log tells you exactly why it looks wrong.
    print(f"FONT MISSING [{role}]: expected one of {names} in repo root or /fonts. Falling back to system font.")
    fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    ]
    if role == "brand":
        fallbacks = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    for fp in fallbacks:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

FONT_HEADER = font(10, "header")
FONT_BODY = font(9, "body")
FONT_NAME = font(9, "body")
FONT_BRAND = font(11, "brand")
FONT_BRAND_SMALL = font(10, "brand")

def build_fonts(row_h, sep_h):
    # One-image mode: shrink text only when the sheet has more rows than the reference can hold.
    body_size = max(7, min(10, row_h - 5))
    brand_size = max(7, min(9, sep_h - 9))
    return {
        "header": font(10, "header"),
        "body": font(body_size, "body"),
        "name": font(body_size, "body"),
        "brand": font(brand_size, "brand"),
        "brand_small": font(max(7, brand_size - 1), "brand"),
    }


def get_data():
    print("--- STEP 1: CONNECTING TO GOOGLE ---")
    creds_raw = os.environ.get("GSHEET_JSON")
    if not creds_raw:
        print("ERROR: GSHEET_JSON secret is missing from GitHub.")
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


def text_size(draw, text, f):
    b = draw.textbbox((0, 0), str(text), font=f)
    return b[2] - b[0], b[3] - b[1]


def fit_text(draw, text, f, max_w):
    s = str(text).strip()
    if text_size(draw, s, f)[0] <= max_w:
        return s
    while s and text_size(draw, s + "…", f)[0] > max_w:
        s = s[:-1]
    return s + "…" if s else "…"


def center_text(draw, box, text, f, fill, stroke=0, stroke_fill=(0,0,0,225), yoff=-1):
    x1, y1, x2, y2 = box
    s = fit_text(draw, text, f, max(1, x2 - x1 - 4))
    tw, th = text_size(draw, s, f)
    draw.text((x1 + (x2-x1-tw)/2, y1 + (y2-y1-th)/2 + yoff), s, font=f, fill=fill,
              stroke_width=stroke, stroke_fill=stroke_fill if stroke else None)


def gradient(draw, xy, top, bot):
    x1,y1,x2,y2 = [int(v) for v in xy]
    h = max(1, y2-y1)
    for i in range(h):
        t = i / max(1, h-1)
        c = tuple(int(top[k]*(1-t)+bot[k]*t) for k in range(4))
        draw.line((x1, y1+i, x2, y1+i), fill=c)


def background():
    p = ROOT / BG_FILENAME
    if not p.exists():
        print(f"ERROR: {BG_FILENAME} missing.")
        sys.exit(1)
    bg = Image.open(p).convert("RGB")
    bw,bh = bg.size
    target = CANVAS_W / CANVAS_H
    if bw / bh > target:
        nw = int(bh * target); left = (bw-nw)//2
        bg = bg.crop((left,0,left+nw,bh))
    else:
        nh = int(bw / target); top = max(0,(bh-nh)//2)
        bg = bg.crop((0,top,bw,top+nh))
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Contrast(bg).enhance(1.12)
    bg = ImageEnhance.Sharpness(bg).enhance(1.18)
    bg = ImageEnhance.Color(bg).enhance(1.08)
    return bg.convert("RGBA")


def is_blank(row):
    return not any(str(c).strip() for c in row)


def extract_row(raw):
    cells = [str(c).strip() for c in raw]
    if not any(cells): return None
    low = " ".join(c.lower() for c in cells)
    if "league" in low and "player" in low: return "HEADER"
    out = [""] * len(COL_NAMES)
    league_i = None
    for i,c in enumerate(cells):
        u = c.upper()
        if "TT CUP" in u or "TT ELITE" in u or "CZECH" in u:
            league_i = i; out[0] = c; break
    if league_i is None: return None
    times = [(i,c) for i,c in enumerate(cells[league_i+1:], league_i+1) if TIME_RE.match(c)]
    for k in range(min(3,len(times))): out[1+k] = times[k][1].upper()
    after_time = times[2][0] + 1 if len(times) >= 3 else league_i + 4
    bet_i = None
    for i in range(after_time, len(cells)):
        u = cells[i].upper()
        if u in ("OVER", "UNDER", "SPLIT"):
            bet_i = i; out[6] = u; break
    names = [c for c in cells[after_time:bet_i] if c] if bet_i is not None else []
    if names: out[4] = names[0]
    if len(names) > 1: out[5] = names[1]
    tail = [c for c in cells[(bet_i+1 if bet_i is not None else after_time):] if c]
    for c in tail:
        if not out[8] and HIST_RE.match(c): out[8] = c.replace(" ", "")
        elif not out[9] and PCT_RE.match(c): out[9] = c.replace(" ", "")
        elif not out[10] and SET_RE.match(c): out[10] = c.replace(" ", "")
        elif not out[7]:
            try:
                v = float(c); out[7] = str(int(v)) if v.is_integer() else str(v).rstrip("0").rstrip(".")
            except Exception: pass
    return out


def normalize(rows):
    clean, prev_sep = [], False
    for raw in rows:
        if is_blank(raw):
            if clean and not prev_sep:
                clean.append(None); prev_sep = True
            continue
        r = extract_row(raw)
        if r == "HEADER": continue
        if r:
            clean.append(r); prev_sep = False
    while clean and clean[-1] is None: clean.pop()
    return clean


def league_style(v):
    u = str(v).upper()
    if "CZECH" in u: return CZECH, WHITE
    if "TT CUP" in u: return TT_CUP, (31,27,0,255)
    return TT_ELITE, TEXT


def bet_style(v):
    u = str(v).upper()
    if "UNDER" in u: return BET_UNDER, WHITE
    if "SPLIT" in u: return BET_SPLIT, TEXT
    return BET_OVER, TEXT


def draw_header(draw, xs):
    gradient(draw, (X0,Y0,X0+TABLE_W,Y0+HEADER_H), HEADER_TOP, HEADER_BOT)
    draw.line((X0, Y0+1, X0+TABLE_W, Y0+1), fill=(130,190,225,125), width=1)
    for i,name in enumerate(COL_NAMES):
        x1,x2 = xs[i], xs[i+1]
        label = "Set Break..." if name == "Set Break Down" else name
        if i in (0,6):
            cx,cy = x1+13, Y0+HEADER_H//2
            draw.ellipse((cx-4,cy-3,cx+4,cy+3), outline=(230,245,255,220), width=1)
            draw.ellipse((cx-1,cy-1,cx+1,cy+1), fill=(230,245,255,220))
        center_text(draw, (x1+5,Y0,x2-16,Y0+HEADER_H), label, FONT_HEADER, WHITE, yoff=-1)
        draw.polygon([(x2-13,Y0+8),(x2-5,Y0+8),(x2-9,Y0+15)], fill=(224,240,250,240))
        draw.line((x2,Y0,x2,Y0+HEADER_H), fill=(0,42,79,255), width=1)
    draw.line((X0,Y0,X0+TABLE_W,Y0), fill=GREEN_DARK, width=1)
    draw.line((X0,Y0+HEADER_H,X0+TABLE_W,Y0+HEADER_H), fill=GREEN_DARK, width=1)


def draw_bar(draw, y):
    gradient(draw, (X0,y,X0+TABLE_W,y+SEP_H), BAR_TOP, BAR_BOT)
    draw.line((X0,y+1,X0+TABLE_W,y+1), fill=(126,186,226,135), width=1)
    draw.line((X0,y+SEP_H-2,X0+TABLE_W,y+SEP_H-2), fill=BAR_SHADOW, width=1)
    draw.line((X0, y, X0+TABLE_W, y), fill=GREEN_DARK, width=1)
    draw.line((X0, y+SEP_H-1, X0+TABLE_W, y+SEP_H-1), fill=GREEN_DARK, width=1)
    center_text(draw, (X0+7,y,X0+258,y+SEP_H), BRAND_LEFT, FONT_BRAND, WHITE, stroke=1, yoff=-1)
    center_text(draw, (X0+242,y,X0+TABLE_W-242,y+SEP_H), BRAND_MID, FONT_BRAND, WHITE, stroke=1, yoff=-1)
    center_text(draw, (X0+TABLE_W-258,y,X0+TABLE_W-7,y+SEP_H), BRAND_RIGHT, FONT_BRAND_SMALL, WHITE, stroke=1, yoff=-1)


def draw_row(draw, xs, y, row, idx):
    draw.rectangle((X0,y,X0+TABLE_W,y+ROW_H), fill=ROW_LIGHT if idx%2==0 else ROW_DARK)
    lf, lt = league_style(row[0]); bf, bt = bet_style(row[6])
    draw.rectangle((xs[0],y,xs[1],y+ROW_H), fill=lf)
    draw.rectangle((xs[6],y,xs[7],y+ROW_H), fill=bf)
    for j,xx in enumerate(xs):
        if j in (0, len(xs)-1):
            draw.line((xx,y,xx,y+ROW_H), fill=GREEN, width=2)
        else:
            draw.line((xx,y,xx,y+ROW_H), fill=GRID, width=2 if j in (8,9) else 1)
    draw.line((X0,y+ROW_H,X0+TABLE_W,y+ROW_H), fill=GRID_SOFT, width=1)
    for i,c in enumerate(row):
        f = FONT_NAME if i in (4,5) else FONT_BODY
        fill = lt if i == 0 else bt if i == 6 else TEXT
        center_text(draw, (xs[i]+2,y,xs[i+1]-2,y+ROW_H), str(c).upper() if i == 6 else c, f, fill, yoff=-1)


def compact_items(items):
    out, last_sep = [], False
    for item in items:
        if item is None:
            if out and not last_sep:
                out.append(None)
                last_sep = True
            continue
        out.append(item)
        last_sep = False
    while out and out[-1] is None:
        out.pop()
    out.append(None)
    return out


def layout_for_single_image(items):
    row_count = sum(1 for x in items if x is not None)
    bar_count = sum(1 for x in items if x is None)
    usable_h = BOTTOM_Y - (Y0 + HEADER_H)
    sep_h = SEP_H
    row_h = ROW_H

    if row_count * row_h + bar_count * sep_h > usable_h:
        # Keep the Discord post as ONE image. Dense sheets must shrink vertically.
        sep_h = max(12, min(SEP_H, int((usable_h * 0.15) / max(1, bar_count))))
        row_h = max(10, int((usable_h - bar_count * sep_h) / max(1, row_count)))
        if row_count * row_h + bar_count * sep_h > usable_h:
            sep_h = max(9, int((usable_h - row_count * row_h) / max(1, bar_count)))

    return row_h, sep_h


def draw_header2(draw, xs, fonts):
    gradient(draw, (X0,Y0,X0+TABLE_W,Y0+HEADER_H), HEADER_TOP, HEADER_BOT)
    draw.line((X0, Y0+1, X0+TABLE_W, Y0+1), fill=(130,190,225,125), width=1)
    for i,name in enumerate(COL_NAMES):
        x1,x2 = xs[i], xs[i+1]
        label = "Set Break..." if name == "Set Break Down" else name
        if i in (0,6):
            cx,cy = x1+13, Y0+HEADER_H//2
            draw.ellipse((cx-4,cy-3,cx+4,cy+3), outline=(230,245,255,220), width=1)
            draw.ellipse((cx-1,cy-1,cx+1,cy+1), fill=(230,245,255,220))
        center_text(draw, (x1+5,Y0,x2-16,Y0+HEADER_H), label, fonts["header"], WHITE, yoff=-1)
        draw.polygon([(x2-13,Y0+8),(x2-5,Y0+8),(x2-9,Y0+15)], fill=(224,240,250,240))
        draw.line((x2,Y0,x2,Y0+HEADER_H), fill=(0,42,79,255), width=1)
    draw.line((X0,Y0,X0+TABLE_W,Y0), fill=GREEN_DARK, width=1)
    draw.line((X0,Y0+HEADER_H,X0+TABLE_W,Y0+HEADER_H), fill=GREEN_DARK, width=1)


def draw_bar2(draw, y, sep_h, fonts):
    gradient(draw, (X0,y,X0+TABLE_W,y+sep_h), BAR_TOP, BAR_BOT)
    draw.line((X0,y+1,X0+TABLE_W,y+1), fill=(126,186,226,135), width=1)
    draw.line((X0,y+sep_h-2,X0+TABLE_W,y+sep_h-2), fill=BAR_SHADOW, width=1)
    draw.line((X0, y, X0+TABLE_W, y), fill=GREEN_DARK, width=1)
    draw.line((X0, y+sep_h-1, X0+TABLE_W, y+sep_h-1), fill=GREEN_DARK, width=1)
    center_text(draw, (X0+7,y,X0+258,y+sep_h), BRAND_LEFT.lower(), fonts["brand"], WHITE, stroke=0, yoff=-1)
    center_text(draw, (X0+242,y,X0+TABLE_W-242,y+sep_h), BRAND_MID.lower(), fonts["brand"], WHITE, stroke=0, yoff=-1)
    center_text(draw, (X0+TABLE_W-258,y,X0+TABLE_W-7,y+sep_h), BRAND_RIGHT.lower(), fonts["brand_small"], WHITE, stroke=0, yoff=-1)


def draw_row2(draw, xs, y, row, idx, row_h, fonts):
    draw.rectangle((X0,y,X0+TABLE_W,y+row_h), fill=ROW_LIGHT if idx%2==0 else ROW_DARK)
    lf, lt = league_style(row[0]); bf, bt = bet_style(row[6])
    draw.rectangle((xs[0],y,xs[1],y+row_h), fill=lf)
    draw.rectangle((xs[6],y,xs[7],y+row_h), fill=bf)
    for j,xx in enumerate(xs):
        if j in (0, len(xs)-1):
            draw.line((xx,y,xx,y+row_h), fill=GREEN, width=2)
        else:
            draw.line((xx,y,xx,y+row_h), fill=GRID, width=2 if j in (8,9) else 1)
    draw.line((X0,y+row_h,X0+TABLE_W,y+row_h), fill=GRID_SOFT, width=1)
    for i,c in enumerate(row):
        f = fonts["name"] if i in (4,5) else fonts["body"]
        fill = lt if i == 0 else bt if i == 6 else TEXT
        center_text(draw, (xs[i]+2,y,xs[i+1]-2,y+row_h), str(c).upper() if i == 6 else c, f, fill, yoff=-1)


def render_single(items):
    items = compact_items(items)
    row_h, sep_h = layout_for_single_image(items)
    fonts = build_fonts(row_h, sep_h)

    img = background(); draw = ImageDraw.Draw(img, "RGBA")
    xs = [X0]
    for w in COL_WIDTHS:
        xs.append(xs[-1]+w)

    draw.rectangle((FRAME_PAD, FRAME_PAD, CANVAS_W-FRAME_PAD, CANVAS_H-FRAME_PAD), outline=GREEN, width=5)

    draw_header2(draw, xs, fonts)
    y = Y0 + HEADER_H
    row_idx = 0
    for item in items:
        if item is None:
            draw_bar2(draw, y, sep_h, fonts)
            y += sep_h
        else:
            draw_row2(draw, xs, y, item, row_idx, row_h, fonts)
            y += row_h
            row_idx += 1

    edge_y = min(y, BOTTOM_Y)
    draw.rectangle((X0,Y0,X0+TABLE_W,edge_y), outline=GREEN, width=3)
    draw.line((X0, Y0, X0, edge_y), fill=GREEN, width=3)
    draw.line((X0+TABLE_W, Y0, X0+TABLE_W, edge_y), fill=GREEN, width=3)
    draw.line((X0, Y0, X0+TABLE_W, Y0), fill=GREEN, width=3)
    draw.line((X0, edge_y, X0+TABLE_W, edge_y), fill=GREEN, width=3)
    out = f"{OUTPUT_PREFIX}.png"
    img.convert("RGB").save(out, quality=98, optimize=True)
    print(f"SUCCESS: Rendered ONE image: rows={row_idx}, row_h={row_h}, sep_h={sep_h}, file={out}")
    return out, row_idx


def create_graphics(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    try:
        items = normalize(rows)
        out, total_rows = render_single(items)
        print(f"SUCCESS: Rendered {total_rows} rows into ONE image: {out}")
        return [out]
    except Exception as e:
        print(f"ERROR IN GRAPHIC CREATION: {e}")
        return []


def send_to_discord(files):
    print("--- STEP 3: SENDING TO DISCORD ---")
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK secret missing.")
        return
    for fn in files:
        with open(fn, "rb") as f:
            r = requests.post(webhook, files={"file": (fn, f, "image/png")})
        if r.status_code in (200,204):
            print(f"SUCCESS: Sent {fn} to Discord.")
        else:
            print(f"DISCORD ERROR {r.status_code}: {r.text}")


if __name__ == "__main__":
    data = get_data()
    files = create_graphics(data)
    if files:
        send_to_discord(files)
