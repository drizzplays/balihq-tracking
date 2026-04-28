import os
import json
import gspread
import requests
import sys
from PIL import Image, ImageDraw
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
GSHEET_ID = "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw" 
TAB_NAME = "Test"
BG_FILENAME = "background.png"

def get_data():
    print("--- STEP 1: CONNECTING TO GOOGLE ---")
    creds_raw = os.environ.get('GSHEET_JSON')
    
    if not creds_raw:
        print("ERROR: GSHEET_JSON secret is empty or not found.")
        sys.exit(1)
        
    try:
        creds_dict = json.loads(creds_raw)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        print(f"Accessing Sheet ID: {GSHEET_ID}...")
        sheet = client.open_by_key(GSHEET_ID).worksheet(TAB_NAME)
        rows = sheet.get_all_values()
        print(f"SUCCESS: Found {len(rows)} rows.")
        return rows
    except json.JSONDecodeError:
        print("ERROR: GSHEET_JSON is not a valid JSON. Make sure you copied the WHOLE file contents including { and }.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR CONNECTING TO GOOGLE: {e}")
        sys.exit(1)

def create_graphic(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    if not os.path.exists(BG_FILENAME):
        print(f"ERROR: {BG_FILENAME} is missing from your GitHub repo. Upload it!")
        sys.exit(1)

    try:
        bg_img = Image.open(BG_FILENAME).convert('RGB')
        width, height = bg_img.size
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        img.paste(bg_img, (0, 0))

        # BaliHQ Grid
        Y_START, ROW_H = 85, 34
        COL_WS = [113, 62, 60, 60, 150, 150, 77, 45, 100, 70, 110]
        
        # Header
        headers = rows[0]
        
        def draw_row(y, row_data, is_header=False, is_sep=False):
            current_x = 0
            # Backgrounds
            bg_color = (47, 49, 54, 255) if is_sep else (32, 34, 37, 240) if is_header else (35, 39, 42, 180)
            overlay = Image.new('RGBA', (width, ROW_H), bg_color)
            img.paste(overlay, (0, y), overlay)

            if is_sep:
                sep_text = "X.COM/BALIHQ           OFFICIAL PROPERTY OF BALIHQBETS           JOIN.BALIHQBETS.COM"
                draw.text((width // 2, y + 8), sep_text, fill=(255, 255, 255), anchor="mm")
                return

            for i, (cell, w) in enumerate(zip(row_data, COL_WS)):
                txt_color = (255, 255, 255)
                val = str(cell).upper().strip()
                if is_header: txt_color = (114, 137, 218)
                elif i == 0 and "TT CUP" in val:
                    draw.rectangle([current_x+2, y+2, current_x+w-2, y+ROW_H-2], fill=(180, 160, 0))
                    txt_color = (0, 0, 0)
                elif i == 6:
                    if "OVER" in val:
                        draw.rectangle([current_x+5, y+5, current_x+w-5, y+ROW_H-5], fill=(32, 64, 48), outline=(0, 255, 0))
                        txt_color = (0, 255, 0)
                    elif "UNDER" in val:
                        draw.rectangle([current_x+5, y+5, current_x+w-5, y+ROW_H-5], fill=(64, 32, 32), outline=(255, 0, 0))
                        txt_color = (255, 0, 0)
                draw.text((current_x + 10, y + 8), str(cell)[:20], fill=txt_color)
                current_x += w

        # Draw Table
        draw_row(Y_START, headers, is_header=True)
        curr_y = Y_START + ROW_H
        for row in rows[1:]:
            is_empty = not row[0].strip() if len(row) > 0 else True
            draw_row(curr_y, [] if is_empty else row, is_sep=is_empty)
            curr_y += ROW_H
            if curr_y + ROW_H > height: break

        img.save('output.png')
        print("SUCCESS: output.png created.")
        return True
    except Exception as e:
        print(f"ERROR CREATING GRAPHIC: {e}")
        sys.exit(1)

def send_to_discord():
    print("--- STEP 3: SENDING TO DISCORD ---")
    webhook = os.environ.get('DISCORD_WEBHOOK')
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK secret is missing.")
        sys.exit(1)

    with open('output.png', 'rb') as f:
        r = requests.post(webhook, files={'file': f})
    
    if r.status_code in [200, 204]:
        print("SUCCESS: Post sent to Discord!")
    else:
        print(f"DISCORD ERROR {r.status_code}: {r.text}")
        sys.exit(1)

if __name__ == "__main__":
    data = get_data()
    if create_graphic(data):
        send_to_discord()
