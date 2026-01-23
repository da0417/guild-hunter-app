import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import json
import requests
import base64

# ==========================================
# 1. 系統初始化與連線
# ==========================================
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'guild_system_db'

@st.cache_resource
def connect_db():
    try:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME)
        return sheet
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {e}")
        st.stop()

def get_data(worksheet_name):
    try:
        sheet = connect_db()
        ws = sheet.worksheet(worksheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if 'password' in df.columns: df['password'] = df['password'].astype(str)
        if 'partner_id' in df.columns: df['partner_id'] = df['partner_id'].astype(str)
        return df
    except: return pd.DataFrame()

def add_quest_to_sheet(title, desc, category, points):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    q_id = int(time.time()) 
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([q_id, title, desc, category, points, "Open", "", created_at, ""])

def update_quest_status(quest_id, new_status, hunter_id=None, partner_list=None):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    try:
        cell = ws.find(str(quest_id))
        row_num = cell.row
    except: return False
    
    ws.update_cell(row_num, 6, new_status)
    if hunter_id is not None: ws.update_cell(row_num, 7, hunter_id)
    if partner_list is not None:
        partner_str = ",".join(partner_list) if isinstance(partner_list, list) else partner_list
        ws.update_cell(row_num, 9, partner_str)
    elif new_status == 'Open': ws.update_cell(row_num, 9, "")
    return True

# --- 🔥 AI 核心：HTTP 直連模式 ---
def analyze_quote_image(image_file):
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    # 預設嘗試使用 1.5 Flash
    model_name = "gemini-1.5-flash" 
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = image_file.type

        payload = {
            "contents": [{
                "parts": [
                    {"text": """
                    請分析這張圖片（報價單或簽呈），提取以下資訊並輸出為純 JSON 格式 (不要 Markdown)：
                    1. title: 案件簡短名稱。
                    2. description: 詳細施工內容摘要。
                    3. budget: 總金額（純數字）。
                    4. category: 從 ['土木工程', '機電工程', '室內裝修', '軟體開發', '定期保養', '緊急搶修', '設備巡檢', '耗材更換'] 選一個最接近的。
                    5. is_urgent: 是否緊急 (true/false)。
                    """},
                    { "inline_data": { "mime_type": mime_type, "data": b64_img } }
                ]
            }]
        }
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            result = response.json()
            try:
                raw_text = result['candidates'][0]['content']['parts'][0]['text']
                clean_json = raw_text.replace("```json", "").replace("```", "").strip()
                return json.loads(clean_json)
            except: return None
        else:
            st.error(f"API 連線失敗 ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"系統錯誤: {e}")
        return None

# ==========================================
# 2. 介面設定
# ==========================================
TYPE_ENG = ["土木工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["定期保養", "緊急搶修", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

st.set_
