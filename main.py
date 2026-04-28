import os
import json
import gspread
import requests
import sys
from PIL import Image, ImageDraw
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
# Your Spreadsheet ID from the URL
GSHEET_ID = "1ZMRcWZlmzhc1UbGJEnct5eBkV2IV9NaMWPhcuXT5Zyw" 
TAB_NAME = "Test"
BG_FILENAME = "background.png"

def get_data():
    print("--- STEP 1: CONNECTING TO GOOGLE ---")
    creds_raw = os.environ.get('GSHEET_JSON')
    
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

def create_graphic(rows):
    print("--- STEP 2: CREATING GRAPHIC ---")
    if not os.path.exists(BG_FILENAME):
        print(f"ERROR: {BG_FILENAME} is missing from repo.")
        sys.exit(1)

    try:
        bg_img = Image.open(BG_FILENAME).convert('RGB')
        width, height = bg_img.size
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        img.paste(bg_img, (0, 0))

        # --- GRID SETTINGS ---
        # Y_START: Adjust if the table is too high or too low
        Y_START = 82  
        ROW_H = 34    
        # Column Widths: League, PST, MTN, EST, Player1, Player2, BET, Unit, History, Split, Break
        COL_WS = [113, 75, 75, 75, 160, 160, 77, 45, 90, 70, 110]
        
        headers = rows[0]
        data_rows = rows[1:]

        def draw_row(y, row_data, is_header=False, is_sep=False):
            current_x = 0
            
            # 1. Background Opacity (Fixed 'Ghosting' by using 220+ opacity)
            if is_header:
                bg_color = (15, 15, 20, 245)
            elif is_sep:
                bg_color = (40, 45, 50, 255) # Fully solid for branding bars
            else:
                bg_color = (25, 30, 35, 220) # Dark enough to read white text
            
            overlay = Image.new('RGBA', (width, ROW_H), bg_color)
            img.paste(overlay, (0, y), overlay)

            # 2. Branded Separator Logic
            if is_sep:
                sep_text = "X.COM/BALIHQ           OFFICIAL PROPERTY OF BALIHQBETS           JOIN.BALIHQBETS.COM"
                # Vertically center text in the bar
                draw.text((width // 2, y + (ROW_H // 2)), sep_text, fill=(220, 220, 220), anchor="mm")
                return

            # 3. Standard Data Cells
            for i, (cell, w) in enumerate(zip(row_data, COL_WS)):
                txt_color = (255, 255, 255)
                val = str(cell).upper().strip()
                
                if is_header:
                    txt_color = (114, 137, 218) # Discord Blurple
                else:
                    # Highlight "TT CUP" (Mustard Yellow)
                    if i == 0 and "TT CUP" in val:
                        draw.rectangle([current_x+2, y+2, current_x+w-2, y+ROW_H-2], fill=(180, 150, 20))
                        txt_color = (0, 0, 0)
                    
                    # BET Column (6) Highlights
                    if i == 6: 
                        if "OVER" in val:
                            draw.rectangle([current_x+4, y+4, current_x+w-4, y+ROW_H-4], fill=(20, 60, 30), outline=(0, 255, 0))
                            txt_color = (0, 255, 0)
                        elif "UNDER" in val:
                            draw.rectangle([current_x+4, y+4, current_x+w-4, y+ROW_H-4], fill=(60, 20, 20), outline=(255, 50, 50))
                            txt_color = (255, 80, 80)
                        elif "SPLIT" in val:
                            txt_color = (180, 180, 180)

                # Draw text with slight padding
                draw.text((current_x + 8, y + 8), val[:25], fill=txt_color)
                current_x += w

        # Draw Table
        draw_row(Y_START, headers, is_header=True)
        curr_y = Y_START + ROW_H

        for row in data_rows:
            # Determine if row is empty (League column check)
            is_empty = not row[0].strip() if len(row) > 0 else True
            
            draw_row(curr_y, [] if is_empty else row, is_sep=is_empty)
            curr_y += ROW_H
            
            # Stop if we hit the bottom of the background
            if curr_y + ROW_H > height:
                break

        img.save('output.png')
        print("SUCCESS: Image rendered as output.png")
        return True
    except Exception as e:
        print(f"ERROR IN GRAPHIC CREATION: {e}")
        return False

def send_to_discord():
    print("--- STEP 3: SENDING TO DISCORD ---")
    webhook = os.environ.get('DISCORD_WEBHOOK')
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK secret missing.")
        return

    with open('output.png', 'rb') as f:
        r = requests.post(webhook, files={'file': f})
    
    if r.status_code in [200, 204]:
        print("SUCCESS: Post sent to Discord!")
    else:
        print(f"DISCORD ERROR {r.status_code}: {r.text}")

if __name__ == "__main__":
    data = get_data()
    if create_graphic(data):
        send_to_discord()
