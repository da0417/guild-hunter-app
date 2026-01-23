import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import random

# ==========================================
# 1. 雲端資料庫層
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
    # 寫入順序: id, title, desc, rank(category), points, status, hunter_id, created_at, partner_id
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
    elif new_status == 'Open': 
        ws.update_cell(row_num, 9, "")
        
    return True

# ==========================================
# 2. 系統設定 (工程 vs 維養)
# ==========================================
# 定義兩大類的選項
TYPE_ENG = ["土木工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["定期保養", "緊急搶修", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

# 人員分組設定 (用於顯示歡迎語，不強制限制功能，保持彈性)
TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

st.set_page_config(page_title="工程維養雙軌系統", layout="wide", page_icon="🏢")

# CSS 優化：讓維修單看起來像 Ticket，工程單像合約
st.markdown("""
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .urgent-tag { color: #FF4B4B; font-weight: bold; border: 1px solid #FF4B4B; padding: 2px 5px; border-radius: 4px; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

if 'user_role' not in st.session_state:
    st.title("🏢 營繕發包管理系統")
    st.caption("🔴 工程/維養 雙軌分流版")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管/派單中心")
            pwd = st.text_input("Access Key", type="password")
            if st.button("🚀 進入指揮台"):
                if pwd == "Boss@9988": 
                    st.session_state['user_role'] = 'Admin'
                    st.rerun()
                else: st.error("Access Denied")
    with c2:
        with st.container(border=True):
            st.subheader("👷 同仁登入")
            if 'auth_dict' not in st.session_state:
                df_emps = get_data('employees')
                if not df_emps.empty and 'password' in df_emps.columns:
                    st.session_state['auth_dict'] = dict(zip(df_emps['name'], df_emps['password']))
                else: st.session_state['auth_dict'] = {}

            if st.session_state['auth_dict']:
                h_name = st.selectbox("選擇姓名", list(st.session_state['auth_dict'].keys()))
                h_pwd = st.text_input("密碼", type="password")
                if st.button("⚡ 上工"):
                    if h_pwd == str(st.session_state['auth_dict'].get(h_name)):
                        st.session_state['user_role'] = 'Hunter'
                        st.session_state['user_name'] = h_name
                        st.rerun()
                    else: st.error("密碼錯誤")

else:
    # --- 側邊欄：顯示分組資訊 ---
    with st.sidebar:
        me = st.session_state.get('user_name', 'Admin')
        st.header(f"👤 {me}")
        
        if st.session_state['user_role'] == 'Hunter':
            # 自動識別組別
            my_team = "未分組"
            if me in TEAM_ENG_1: my_team = "🏗️ 工程 1 組"
            elif me in TEAM_ENG_2: my_team = "🏗️ 工程 2 組"
            elif me in TEAM_MAINT_1: my_team = "🔧 維養 1 組"
            
            st.info(f"所屬單位: **{my_team}**")
            
        if st.button("🚪 登出"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

    # --- Admin ---
    if st.session_state['user_role'] == 'Admin':
        st.title("👨‍💼 發包/派單指揮台")
        t1, t2, t3 = st.tabs(["📝 建立案件", "🔍 驗收審核", "📊 數據總表"])
        
        with t1:
            st.subheader("發布新任務")
            with st.form("new_task"):
                # 讓主管選擇這是「工程標案」還是「維修派單」
                task_mode = st.radio("案件模式", ["🏗️ 工程標案 (競標)", "🔧 維修派單 (指派/搶單)"], horizontal=True)
                
                c_a, c_b = st.columns([2, 1])
                with c_a: title = st.text_input("案件名稱")
                with c_b: 
                    # 根據模式給予不同的預設選項
                    if "工程" in task_mode:
                        p_type = st.selectbox("類別", TYPE_ENG)
                    else:
                        p_type = st.selectbox("類別", TYPE_MAINT)
                
                budget = st.number_input("金額/津貼 ($)", min_value=0, step=1000)
                desc = st.text_area("詳細說明")
                
                if st.form_submit_button("🚀 發布"):
                    add_quest_to_sheet(title, desc, p_type, budget)
                    st.success(f"已發布: {title}")
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

    # --- Hunter (Dual Track UI) ---
    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        df = get_data('quests')
        
        # 營收計算 (通用邏輯)
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

        st.title(f"🚀 工作台: {me}")
        st.metric("💰 本月累計業績", f"${int(my_total):,}")
        st.divider()

        # 👇 關鍵修改：將市場分為兩個獨立的 Tab
        tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])
        
        # --- Tab 1: 工程標案區 (適合工程組) ---
        with tab_eng:
            if not df.empty and 'status' in df.columns:
                # 篩選條件：狀態是 Open 且 類型屬於工程類
                df_eng = df[(df['status'] == 'Open') & (df['rank'].isin(TYPE_ENG))]
                
                if not df_eng.empty:
                    st.caption("🔥 競爭激烈的專案市場 (金額較高，需聯合承攬)")
                    for i, row in df_eng.iterrows():
                        # 使用 Project Card 樣式
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
                            partners = st.multiselect("🤝 找隊友 (最多3人)", [u for u in all_users if u != me], max_selections=3, key=f"pe_{row['id']}")
                        with c2:
                            st.write("")
                            if st.button("⚡ 投標", key=f"be_{row['id']}", use_container_width=True):
                                update_quest_status(row['id'], 'Active', me, partners)
                                st.balloons()
                                st.rerun()
                else:
                    st.info("目前無工程標案")

        # --- Tab 2: 維修派單區 (適合維養組) ---
        with tab_maint:
            if not df.empty and 'status' in df.columns:
                # 篩選條件：狀態是 Open 且 類型屬於維養類
                df_maint = df[(df['status'] == 'Open') & (df['rank'].isin(TYPE_MAINT))]
                
                if not df_maint.empty:
                    st.caption("⚡ 快速反應區 (金額固定，強調速度，先搶先贏)")
                    for i, row in df_maint.iterrows():
                        # 特別標示：如果是「緊急搶修」，加上醒目標籤
                        urgent_html = '<span class="urgent-tag">🔥URGENT</span>' if row['rank'] == '緊急搶修' else ''
                        
                        # 使用 Ticket Card 樣式 (更緊湊)
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
                            
                            # 維修單通常是單人作業，或者簡單帶人，這裡簡化流程，直接搶單
                            col_fast, col_null = st.columns([1, 4])
                            with col_fast:
                                if st.button("✋ 我來處理", key=f"bm_{row['id']}"):
                                    # 維修單預設不選隊友，若需要可事後補充
                                    update_quest_status(row['id'], 'Active', me, [])
                                    st.toast(f"已接下維修單：{row['title']}")
                                    st.rerun()
                else:
                    st.info("目前無待處理維修單")
        
        # --- Tab 3: 我的任務 ---
        with tab_my:
            if not df.empty and 'status' in df.columns:
                def check_me(r):
                    ps = str(r['partner_id']).split(',')
                    return r['hunter_id'] == me or me in ps
                
                df_my = df[df.apply(check_me, axis=1)]
                df_my = df_my[df_my['status'].isin(['Active', 'Pending'])]
                
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        # 根據類型顯示不同顏色
                        border_color = "#FF4B4B" if row['rank'] in TYPE_ENG else "#00AAFF"
                        
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
