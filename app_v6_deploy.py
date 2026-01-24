import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import json
import base64

# 注意：我們不在此處 import requests，改在函數內引用，避免啟動卡死

# ==========================================
# 1. 系統初始化
# ==========================================
st.set_page_config(page_title="AI 智慧派工系統", layout="wide", page_icon="🤖")

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'guild_system_db'

# CSS 樣式
st.markdown("""
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .urgent-tag { color: #FF4B4B; font-weight: bold; border: 1px solid #FF4B4B; padding: 2px 5px; border-radius: 4px; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

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
        return None # 避免直接 stop，讓介面能顯示

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

# --- 🔥 AI 核心：HTTP 直連模式 (Gemini 2.0 版) ---
def analyze_quote_image(image_file):
    # 在這裡才 import，避免程式一開始就崩潰
    try:
        import requests
    except ImportError:
        st.error("❌ 系統缺少 'requests' 套件，請更新 requirements.txt")
        return None

    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    
    # 👇👇👇 關鍵修改：使用您清單裡有的 2.0 模型 👇👇👇
    model_name = "gemini-2.5-flash" 
    
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
# 2. 介面與 AI 偵探
# ==========================================
TYPE_ENG = ["土木工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["定期保養", "緊急搶修", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

with st.sidebar:
    st.divider()
    st.subheader("🕵️‍♂️ AI 偵探")
    if st.button("🔍 查詢可用模型"):
        try:
            import requests # 安全引用
            if "GEMINI_API_KEY" in st.secrets:
                k = st.secrets["GEMINI_API_KEY"]
                resp = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={k}")
                if resp.status_code == 200:
                    data = resp.json()
                    valid_models = [m['name'] for m in data.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
                    st.success("API 支援模型：")
                    st.code(valid_models)
                else:
                    st.error(f"查詢失敗: {resp.text}")
            else:
                st.error("無 API Key")
        except Exception as e:
            st.error(f"錯誤: {e}")

if 'user_role' not in st.session_state:
    st.title("🤖 AI 智慧營繕派工系統")
    st.caption("🚀 安全啟動模式")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管入口")
            pwd = st.text_input("Access Key", type="password")
            if st.button("🚀 進入"):
                if pwd == "Boss@9988": 
                    st.session_state['user_role'] = 'Admin'
                    st.rerun()
                else: st.error("錯誤")
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
                    else: st.error("錯誤")

else:
    with st.sidebar:
        me = st.session_state.get('user_name', 'Admin')
        st.header(f"👤 {me}")
        if st.button("🚪 登出"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

    if st.session_state['user_role'] == 'Admin':
        st.title("👨‍💼 指揮台")
        t1, t2, t3 = st.tabs(["📷 AI 派單", "🔍 驗收", "📊 數據"])
        
        with t1:
            st.subheader("發布任務")
            uploaded_file = st.file_uploader("📤 上傳報價單", type=['png', 'jpg', 'jpeg'])
            
            if 'draft_title' not in st.session_state: st.session_state['draft_title'] = ""
            if 'draft_desc' not in st.session_state: st.session_state['draft_desc'] = ""
            if 'draft_budget' not in st.session_state: st.session_state['draft_budget'] = 0
            if 'draft_type' not in st.session_state: st.session_state['draft_type'] = TYPE_ENG[0]
            
            if uploaded_file is not None:
                if st.button("✨ 啟動 AI"):
                    with st.spinner("🤖 分析中..."):
                        ai_data = analyze_quote_image(uploaded_file)
                        if ai_data:
                            st.session_state['draft_title'] = ai_data.get('title', '')
                            st.session_state['draft_desc'] = ai_data.get('description', '')
                            st.session_state['draft_budget'] = int(ai_data.get('budget', 0))
                            st.session_state['draft_type'] = ai_data.get('category', TYPE_ENG[0])
                            st.toast("✅ 成功！", icon="🤖")

            with st.form("new_task"):
                c_a, c_b = st.columns([2, 1])
                with c_a: title = st.text_input("案件名稱", value=st.session_state['draft_title'])
                with c_b: 
                    try: idx = ALL_TYPES.index(st.session_state['draft_type'])
                    except: idx = 0
                    p_type = st.selectbox("類別", ALL_TYPES, index=idx)
                
                budget = st.number_input("金額 ($)", min_value=0, step=1000, value=st.session_state['draft_budget'])
                desc = st.text_area("說明", value=st.session_state['draft_desc'], height=150)
                
                if st.form_submit_button("🚀 發布"):
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
         st.info("獵人介面載入中...")
