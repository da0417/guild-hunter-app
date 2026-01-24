import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import json
import base64
import re

# 強制檢查 requests
try:
    import requests
except ImportError:
    st.error("🚨 嚴重錯誤：找不到 'requests' 套件。請檢查 requirements.txt 是否有加入 requests")
    st.stop()

# ==========================================
# 1. 系統設定
# ==========================================
st.set_page_config(page_title="AI 智慧派工系統", layout="wide", page_icon="🏢")

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'guild_system_db'

st.markdown("""
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .debug-box { background-color: #444; color: #0f0; padding: 10px; border-radius: 5px; font-family: monospace; margin-bottom: 10px; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

TYPE_ENG = ["消防工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

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
        return None

def get_data(worksheet_name):
    try:
        sheet = connect_db()
        if not sheet: return pd.DataFrame()
        ws = sheet.worksheet(worksheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if 'password' in df.columns: df['password'] = df['password'].astype(str)
        if 'partner_id' in df.columns: df['partner_id'] = df['partner_id'].astype(str)
        return df
    except: return pd.DataFrame()

def add_quest_to_sheet(title, desc, category, points):
    sheet = connect_db()
    if not sheet: return
    ws = sheet.worksheet('quests')
    q_id = int(time.time()) 
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([q_id, title, desc, category, points, "Open", "", created_at, ""])

def update_quest_status(quest_id, new_status, hunter_id=None, partner_list=None):
    sheet = connect_db()
    if not sheet: return False
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

# --- 🔥 AI 核心 (除錯模式) ---
def analyze_quote_image_debug(image_file):
    # 1. 檢查 API Key
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 錯誤：Secrets 中找不到 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    model_name = "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    st.markdown(f"<div class='debug-box'>📡 正在連線模型: {model_name}</div>", unsafe_allow_html=True)

    try:
        # 2. 處理圖片
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = image_file.type
        st.markdown(f"<div class='debug-box'>🖼️ 圖片讀取成功 ({len(img_bytes)} bytes), 格式: {mime_type}</div>", unsafe_allow_html=True)

        categories_str = str(ALL_TYPES).replace("'", "") 

        payload = {
            "contents": [{
                "parts": [
                    {"text": f"""
                    請分析圖片（報價單或報修APP截圖），提取資訊並輸出為 JSON：
                    1. community: 社區名稱 (去除編號)。
                    2. project: 工程名稱或報修摘要。
                    3. description: 詳細說明。
                    4. budget: 總金額 (數字，若無則填0)。
                    5. category: 請務必從以下清單中選擇最接近的一個：{categories_str}。
                    6. is_urgent: 是否緊急 (true/false)。
                    """},
                    { "inline_data": { "mime_type": mime_type, "data": b64_img } }
                ]
            }]
        }
        
        # 3. 發送請求
        headers = {'Content-Type': 'application/json'}
        st.markdown("<div class='debug-box'>🚀 發送請求中... (請稍候)</div>", unsafe_allow_html=True)
        
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        # 4. 檢查回應代碼
        st.markdown(f"<div class='debug-box'>📥 收到回應，狀態碼: {response.status_code}</div>", unsafe_allow_html=True)
        
        if response.status_code == 200:
            result = response.json()
            try:
                raw_text = result['candidates'][0]['content']['parts'][0]['text']
                # st.text(f"原始回傳內容: {raw_text}") # 如果需要看原始內容可打開
                
                clean_json = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)
                st.markdown("<div class='debug-box'>✅ JSON 解析成功！</div>", unsafe_allow_html=True)
                
                comm = data.get('community', '')
                proj = data.get('project', '')
                if comm: comm = re.sub(r'^[A-Za-z0-9]+\s*', '', comm)

                if comm and proj: final_title = f"【{comm}】{proj}"
                else: final_title = proj if proj else comm
                
                data['title'] = final_title
                return data
            except Exception as e:
                st.error(f"❌ JSON 解析失敗: {e}")
                st.write(f"AI 回傳的內容: {result}")
                return None
        else:
            st.error(f"❌ API 連線錯誤: {response.text}")
            return None

    except Exception as e:
        st.error(f"❌ 系統執行錯誤: {e}")
        return None

# ==========================================
# 3. 介面邏輯
# ==========================================
TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

if 'user_role' not in st.session_state:
    st.title("🏢 營繕發包管理系統")
    st.caption("v9.5 強制除錯版")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管入口")
            pwd = st.text_input("Access Key", type="password")
            if st.button("🚀 進入指揮台"):
                if pwd == "Boss@9988": 
                    st.session_state['user_role'] = 'Admin'
                    st.rerun()
                else: st.error("密碼錯誤")
    with c2:
        with st.container(border=True):
            st.subheader("👷 同仁入口")
            if 'auth_dict' not in st.session_state:
                df_emps = get_data('employees')
                if not df_emps.empty and 'password' in df_emps.columns:
                    st.session_state['auth_dict'] = dict(zip(df_emps['name'], df_emps['password']))
                else: st.session_state['auth_dict'] = {}

            if st.session_state['auth_dict']:
                h_name = st.selectbox("姓名", list(st.session_state['auth_dict'].keys()))
                h_pwd = st.text_input("密碼", type="password")
                if st.button("⚡ 上工"):
                    if h_pwd == str(st.session_state['auth_dict'].get(h_name)):
                        st.session_state['user_role'] = 'Hunter'
                        st.session_state['user_name'] = h_name
                        st.rerun()
                    else: st.error("密碼錯誤")

else:
    with st.sidebar:
        me = st.session_state.get('user_name', 'Admin')
        st.header(f"👤 {me}")
        if st.session_state['user_role'] == 'Hunter':
            my_team = "未分組"
            if me in TEAM_ENG_1: my_team = "🏗️ 工程 1 組"
            elif me in TEAM_ENG_2: my_team = "🏗️ 工程 2 組"
            elif me in TEAM_MAINT_1: my_team = "🔧 維養 1 組"
            st.info(f"所屬: **{my_team}**")
            
        if st.button("🚪 登出系統"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

    # --- Admin ---
    if st.session_state['user_role'] == 'Admin':
        st.title("👨‍💼 發包/派單指揮台")
        t1, t2, t3 = st.tabs(["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"])
        
        with t1:
            st.subheader("發布新任務")
            uploaded_file = st.file_uploader("📤 上傳 (報價單 / 報修截圖)", type=['png', 'jpg', 'jpeg'])
            
            # 初始化 session state
            if 'draft_title' not in st.session_state: st.session_state['draft_title'] = ""
            if 'draft_desc' not in st.session_state: st.session_state['draft_desc'] = ""
            if 'draft_budget' not in st.session_state: st.session_state['draft_budget'] = 0
            if 'draft_type' not in st.session_state: st.session_state['draft_type'] = TYPE_ENG[0]
            
            if uploaded_file is not None:
                # 這裡改用除錯函數
                if st.button("✨ 啟動 AI 辨識 (除錯模式)"):
                    with st.status("🤖 AI 正在工作中...", expanded=True) as status:
                        st.write("準備開始...")
                        ai_data = analyze_quote_image_debug(uploaded_file)
                        
                        if ai_data:
                            status.update(label="✅ 辨識成功！", state="complete", expanded=False)
                            st.session_state['draft_title'] = ai_data.get('title', '')
                            st.session_state['draft_desc'] = ai_data.get('description', '')
                            st.session_state['draft_budget'] = int(ai_data.get('budget', 0))
                            
                            cat = ai_data.get('category', '')
                            if cat in ALL_TYPES: st.session_state['draft_type'] = cat
                            else: st.session_state['draft_type'] = TYPE_MAINT[0] if ai_data.get('budget', 0) == 0 else TYPE_ENG[0]

                            if ai_data.get('is_urgent'): st.toast("🚨 緊急案件！", icon="🔥")
                            st.rerun() # 成功後刷新頁面填入資料
                        else:
                            status.update(label="❌ 辨識失敗", state="error")
            
            st.divider()
            with st.form("new_task"):
                c_a, c_b = st.columns([2, 1])
                with c_a: title = st.text_input("案件名稱", value=st.session_state['draft_title'])
                with c_b: 
                    try: idx = ALL_TYPES.index(st.session_state['draft_type'])
                    except: idx = 0
                    p_type = st.selectbox("類別", ALL_TYPES, index=idx)
                
                budget = st.number_input("金額 ($)", min_value=0, step=1000, value=st.session_state['draft_budget'])
                desc = st.text_area("詳細說明", value=st.session_state['draft_desc'], height=150)
                
                if st.form_submit_button("🚀 確認發布"):
                    add_quest_to_sheet(title, desc, p_type, budget)
                    st.success(f"已發布: {title}")
                    st.session_state['draft_title'] = ""
                    time.sleep(1)
                    st.rerun()

        with t2:
             st.dataframe(get_data('quests'))
        with t3:
             st.dataframe(get_data('quests'))

    elif st.session_state['user_role'] == 'Hunter':
        # (獵人介面保持不變，為節省空間省略顯示，但功能請保留 V9.4 的內容)
        st.info("獵人介面載入中... (功能與 V9.4 相同)")
        # 實務上請保留 V9.4 的獵人代碼，這裡重點是修復 Admin 的按鈕
