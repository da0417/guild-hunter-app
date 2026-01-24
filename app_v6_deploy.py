import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import json
import base64
# 這裡 import requests，如果 requirements.txt 有加，這裡就安全
try:
    import requests
except ImportError:
    st.error("請在 requirements.txt 加入 requests")

# ==========================================
# 1. 系統初始化
# ==========================================
st.set_page_config(page_title="AI 智慧派工系統", layout="wide", page_icon="🏢")

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'guild_system_db'

# CSS 樣式：區分工程與維修，增加急件標籤
st.markdown("""
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .urgent-tag { color: #FF4B4B; font-weight: bold; border: 1px solid #FF4B4B; padding: 2px 5px; border-radius: 4px; font-size: 12px; margin-left: 5px; }
    .metric-card { background-color: #333; padding: 10px; border-radius: 5px; text-align: center; }
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

# --- 🔥 AI 核心：Gemini 2.0 Flash (自動拆分標題版) ---
def analyze_quote_image(image_file):
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    # 使用我們剛剛確認過，您權限裡有的模型
    model_name = "gemini-2.5-flash" 
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = image_file.type

        # Prompt: 要求 AI 拆分社區名與工程名
        payload = {
            "contents": [{
                "parts": [
                    {"text": """
                    請分析這張圖片（報價單或簽呈），提取以下資訊並輸出為純 JSON 格式 (不要 Markdown)：
                    1. community: 客戶名稱、社區名稱或大樓名稱（通常在單據抬頭或客戶欄）。
                    2. project: 具體的工程名稱或施工項目。
                    3. description: 詳細施工內容摘要。
                    4. budget: 總金額（純數字，去除幣別符號）。
                    5. category: 從 ['土木工程', '機電工程', '室內裝修', '軟體開發', '定期保養', '緊急搶修', '設備巡檢', '耗材更換'] 選一個最接近的。
                    6. is_urgent: 是否緊急 (true/false)。
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
                data = json.loads(clean_json)
                
                # 自動組合標題：【社區】工程名
                comm = data.get('community', '')
                proj = data.get('project', '')
                if comm and proj:
                    final_title = f"【{comm}】{proj}"
                else:
                    final_title = proj if proj else comm
                data['title'] = final_title
                return data
            except: return None
        else:
            st.error(f"API 連線失敗 ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"系統錯誤: {e}")
        return None

# ==========================================
# 2. 介面邏輯 (雙軌制)
# ==========================================
TYPE_ENG = ["土木工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["定期保養", "緊急搶修", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

# 登入介面
if 'user_role' not in st.session_state:
    st.title("🏢 營繕發包管理系統")
    st.caption("v8.0 完整版")
    
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
    # 側邊欄與登出
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

    # --- Admin 介面 ---
    if st.session_state['user_role'] == 'Admin':
        st.title("👨‍💼 發包/派單指揮台")
        t1, t2, t3 = st.tabs(["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"])
        
        with t1:
            st.subheader("發布新任務")
            uploaded_file = st.file_uploader("📤 上傳報價單 (AI 自動辨識)", type=['png', 'jpg', 'jpeg'])
            
            # 初始化暫存
            if 'draft_title' not in st.session_state: st.session_state['draft_title'] = ""
            if 'draft_desc' not in st.session_state: st.session_state['draft_desc'] = ""
            if 'draft_budget' not in st.session_state: st.session_state['draft_budget'] = 0
            if 'draft_type' not in st.session_state: st.session_state['draft_type'] = TYPE_ENG[0]
            
            if uploaded_file is not None:
                if st.button("✨ 啟動 AI 辨識"):
                    with st.spinner("🤖 AI 正在閱讀..."):
                        ai_data = analyze_quote_image(uploaded_file)
                        if ai_data:
                            st.session_state['draft_title'] = ai_data.get('title', '')
                            st.session_state['draft_desc'] = ai_data.get('description', '')
                            st.session_state['draft_budget'] = int(ai_data.get('budget', 0))
                            st.session_state['draft_type'] = ai_data.get('category', TYPE_ENG[0])
                            if ai_data.get('is_urgent'): st.toast("🚨 偵測到緊急案件！", icon="🔥")
                            else: st.toast("✅ 辨識成功！", icon="🤖")

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
            st.subheader("待驗收清單")
            df = get_data('quests')
            if not df.empty and 'status' in df.columns:
                df['id'] = df['id'].astype(str)
                df_p = df[df['status'] == 'Pending']
                if not df_p.empty:
                    for i, r in df_p.iterrows():
                        with st.expander(f"待審: {r['title']} ({r['hunter_id']})"):
                            st.write(f"金額: ${r['points']:,}")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 通過", key=f"ok_{r['id']}"):
                                update_quest_status(r['id'], 'Done')
                                st.rerun()
                            if c2.button("❌ 退回", key=f"no_{r['id']}"):
                                update_quest_status(r['id'], 'Active')
                                st.rerun()
                else: st.info("無待審案件")
        with t3: st.dataframe(get_data('quests'))

    # --- Hunter 介面 (雙軌制邏輯恢復) ---
    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        df = get_data('quests')
        
        # 營收計算
        my_total = 0
        if not df.empty and 'status' in df.columns:
            df['id'] = df['id'].astype(str)
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            df_done = df[df['status'] == 'Done']
            for i, r in df_done.iterrows():
                ps = str(r['partner_id']).split(',') if r['partner_id'] else []
                ps = [p for p in ps if p]
                team = [r['hunter_id']] + ps
                if me in team:
                    share = r['points'] // len(team)
                    rem = r['points'] % len(team)
                    my_total += (share + rem) if me == r['hunter_id'] else share

        st.title(f"🚀 工程師工作台: {me}")
        st.metric("💰 本月實拿業績", f"${int(my_total):,}")
        st.divider()

        # 分頁：工程標案 vs 維修派單 vs 我的任務
        tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])
        
        # 1. 工程標案 (大卡片)
        with tab_eng:
            if not df.empty and 'status' in df.columns:
                df_eng = df[(df['status'] == 'Open') & (df['rank'].isin(TYPE_ENG))]
                if not df_eng.empty:
                    st.caption("🔥 工程競標區 (需聯合承攬)")
                    for i, row in df_eng.iterrows():
                        st.markdown(f"""
                        <div class="project-card">
                            <h3>📄 {row['title']}</h3>
                            <p style="color:#aaa;">類別: {row['rank']} | 預算: <span style="color:#0f0; font-size:1.2em;">${row['points']:,}</span></p>
                            <p>{row['description']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            all_users = list(st.session_state['auth_dict'].keys())
                            partners = st.multiselect("🤝 找隊友", [u for u in all_users if u != me], max_selections=3, key=f"pe_{row['id']}")
                        with c2:
                            st.write("")
                            if st.button("⚡ 投標", key=f"be_{row['id']}", use_container_width=True):
                                update_quest_status(row['id'], 'Active', me, partners)
                                st.balloons()
                                st.rerun()
                else: st.info("目前無工程標案")

        # 2. 維修派單 (列表式)
        with tab_maint:
            if not df.empty and 'status' in df.columns:
                df_maint = df[(df['status'] == 'Open') & (df['rank'].isin(TYPE_MAINT))]
                if not df_maint.empty:
                    st.caption("⚡ 快速搶修區 (先搶先贏)")
                    for i, row in df_maint.iterrows():
                        urgent_html = '<span class="urgent-tag">🔥URGENT</span>' if row['rank'] == '緊急搶修' else ''
                        with st.container():
                            st.markdown(f"""
                            <div class="ticket-card">
                                <div style="display:flex; justify-content:space-between;">
                                    <strong>🔧 {row['title']} {urgent_html}</strong>
                                    <span style="color:#00AAFF; font-weight:bold;">${row['points']:,}</span>
                                </div>
                                <div style="font-size:0.9em; color:#ccc;">{row['description']}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            col_fast, col_null = st.columns([1, 4])
                            with col_fast:
                                if st.button("✋ 我來處理", key=f"bm_{row['id']}"):
                                    update_quest_status(row['id'], 'Active', me, [])
                                    st.toast(f"已接下：{row['title']}")
                                    st.rerun()
                else: st.info("目前無維修單")
        
        # 3. 我的任務
        with tab_my:
            if not df.empty and 'status' in df.columns:
                def check_me(r):
                    ps = str(r['partner_id']).split(',')
                    return r['hunter_id'] == me or me in ps
                
                df_my = df[df.apply(check_me, axis=1)]
                df_my = df_my[df_my['status'].isin(['Active', 'Pending'])]
                
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        with st.expander(f"進行中: {row['title']} ({row['status']})"):
                            st.markdown(f"**類別**: {row['rank']} | **金額**: ${row['points']:,}")
                            st.write(f"說明: {row['description']}")
                            if row['status'] == 'Active' and row['hunter_id'] == me:
                                if st.button("📩 完工回報", key=f"sub_{row['id']}"):
                                    update_quest_status(row['id'], 'Pending')
                                    st.rerun()
                            elif row['status'] == 'Pending':
                                st.warning("主管審核中...")
                else: st.info("無進行中任務")
