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
    print(f"Connecting to Google Sheet ID: {GSHEET_ID}...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds_raw = os.environ.get('GSHEET_JSON')
    if not creds_raw:
        raise ValueError("CRITICAL: GSHEET_JSON secret is missing from GitHub Settings.")
    
    creds_dict = json.loads(creds_raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_key(GSHEET_ID).worksheet(TAB_NAME)
    rows = sheet.get_all_values()
    print(f"Successfully pulled {len(rows)} rows from '{TAB_NAME}'.")
    return rows

def create_graphic(rows):
    if not rows or len(rows) < 1:
        print("Error: No data found in the sheet.")
        return False
        
    if not os.path.exists(BG_FILENAME):
        print(f"Error: {BG_FILENAME} not found in repository root.")
        return False

    bg_img = Image.open(BG_FILENAME).convert('RGB')
    width, height = bg_img.size
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    img.paste(bg_img, (0, 0))

    Y_START = 85
    ROW_H = 34
    COL_WS = [113, 62, 60, 60, 150, 150, 77, 45, 100, 70, 110]
    
    headers = rows[0]
    data_rows = rows[1:]

    def draw_row(y, row_data, is_header=False, is_sep=False):
        current_x = 0
        if is_header:
            overlay = Image.new('RGBA', (width, ROW_H), (32, 34, 37, 240))
        elif is_sep:
            overlay = Image.new('RGBA', (width, ROW_H), (47, 49, 54, 255))
        else:
            overlay = Image.new('RGBA', (width, ROW_H), (35, 39, 42, 180))
        img.paste(overlay, (0, y), overlay)

        if is_sep:
            sep_text = "X.COM/BALIHQ           OFFICIAL PROPERTY OF BALIHQBETS           JOIN.BALIHQBETS.COM"
            draw.text((width // 2, y + 8), sep_text, fill=(255, 255, 255), anchor="mm")
            return

        for i, (cell, w) in enumerate(zip(row_data, COL_WS)):
            txt_color = (255, 255, 255)
            val = str(cell).upper().strip()
            if is_header:
                txt_color = (114, 137, 218)
            else:
                if i == 0 and "TT CUP" in val:
                    draw.rectangle([current_x+2, y+2, current_x+w-2, y+ROW_H-2], fill=(180, 160, 0))
                    txt_color = (0, 0, 0)
                if i == 6: 
                    if "OVER" in val:
                        draw.rectangle([current_x+5, y+5, current_x+w-5, y+ROW_H-5], fill=(32, 64, 48), outline=(0, 255, 0))
                        txt_color = (0, 255, 0)
                    elif "UNDER" in val:
                        draw.rectangle([current_x+5, y+5, current_x+w-5, y+ROW_H-5], fill=(64, 32, 32), outline=(255, 0, 0))
                        txt_color = (255, 0, 0)

            draw.text((current_x + 10, y + 8), str(cell)[:20], fill=txt_color)
            current_x += w

    draw_row(Y_START, headers, is_header=True)
    current_y = Y_START + ROW_H

    for row in data_rows:
        is_empty = not row[0].strip() if len(row) > 0 else True
        draw_row(current_y, [] if is_empty else row, is_sep=is_empty)
        current_y += ROW_H
        if current_y + ROW_H > height: break

    img.save('output.png')
    print("Graphic 'output.png' generated.")
    return True

def send_to_discord():
    webhook = os.environ.get('DISCORD_WEBHOOK')
    if not webhook:
        print("Error: DISCORD_WEBHOOK secret is missing.")
        return

    with open('output.png', 'rb') as f:
        r = requests.post(webhook, files={'file': f})
    
    if r.status_code in [200, 204]:
        print("Post sent successfully to Discord!")
    else:
        print(f"Discord Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    try:
        data = get_data()
        if create_graphic(data):
            send_to_discord()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1) # This forces the GitHub Action to show a Red X
