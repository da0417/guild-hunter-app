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

def add_quest_to_sheet(title, desc, rank, points):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    q_id = int(time.time()) 
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([q_id, title, desc, rank, points, "Open", "", created_at, ""])

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

# ==========================================
# 2. 介面設定與邏輯
# ==========================================
PROJECT_TYPES = ["消防工程", "機電工程", "給排水工程", "室內裝修", "點交總檢", "人力派遣", "其他"]

st.set_page_config(page_title="工程戰情中心", layout="wide", page_icon="⚡")

# 自訂 CSS 來增強競爭感
st.markdown("""
<style>
    .big-font { font-size:24px !important; font-weight: bold; color: #FF4B4B; }
    .metric-card { background-color: #262730; padding: 15px; border-radius: 10px; border: 1px solid #4e4f57; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #00FF00; }
</style>
""", unsafe_allow_html=True)

if 'user_role' not in st.session_state:
    st.title("⚡ 工程發包戰情中心")
    st.caption("🔴 Live Trading Floor")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 發包主管入口")
            pwd = st.text_input("Access Key", type="password")
            if st.button("🚀 進入指揮台"):
                if pwd == "Boss@9988": 
                    st.session_state['user_role'] = 'Admin'
                    st.rerun()
                else: st.error("Access Denied")
    with c2:
        with st.container(border=True):
            st.subheader("👷 工程競標入口")
            if 'auth_dict' not in st.session_state:
                df_emps = get_data('employees')
                if not df_emps.empty and 'password' in df_emps.columns:
                    st.session_state['auth_dict'] = dict(zip(df_emps['name'], df_emps['password']))
                else: st.session_state['auth_dict'] = {}

            if st.session_state['auth_dict']:
                h_name = st.selectbox("廠商代號", list(st.session_state['auth_dict'].keys()))
                h_pwd = st.text_input("Security Code", type="password")
                if st.button("⚡ 進入市場"):
                    if h_pwd == str(st.session_state['auth_dict'].get(h_name)):
                        st.session_state['user_role'] = 'Hunter'
                        st.session_state['user_name'] = h_name
                        st.rerun()
                    else: st.error("Invalid Credentials")

else:
    # 頂部導航條
    with st.sidebar:
        st.header(f"👤 {st.session_state['user_role']}")
        if st.session_state['user_role'] == 'Hunter':
            st.success(f"已連線: {st.session_state['user_name']}")
        if st.button("🚪 安全登出"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

    # --- Admin ---
    if st.session_state['user_role'] == 'Admin':
        st.title("👨‍💼 發包指揮台")
        t1, t2, t3 = st.tabs(["📝 發布標案", "🔍 驗收撥款", "📊 戰情總覽"])
        
        with t1:
            with st.form("new_p"):
                st.subheader("建立新標案")
                c_a, c_b = st.columns([2, 1])
                with c_a: title = st.text_input("標案名稱")
                with c_b: p_type = st.selectbox("類別", PROJECT_TYPES)
                budget = st.number_input("預算金額 ($)", min_value=0, step=10000, help="輸入整數金額")
                desc = st.text_area("規格需求")
                if st.form_submit_button("🚀 發布至市場"):
                    add_quest_to_sheet(title, desc, p_type, budget)
                    st.toast('標案已上線！廠商將收到通知', icon='📣')
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
                        with st.expander(f"💰 {r['title']} (得標: {r['hunter_id']})"):
                            st.write(f"金額: **${r['points']:,}**")
                            if r['partner_id']: st.info(f"團隊: {r['partner_id']}")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 批准撥款", key=f"ok_{r['id']}"):
                                update_quest_status(r['id'], 'Done')
                                st.balloons()
                                st.rerun()
                            if c2.button("❌ 退回修正", key=f"no_{r['id']}"):
                                update_quest_status(r['id'], 'Active')
                                st.rerun()
                else: st.info("目前無待審核項目")
        with t3: st.dataframe(get_data('quests'))

    # --- Hunter (Competitive UI) ---
    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        df = get_data('quests')
        
        # 計算營收
        my_rev, pending_rev = 0, 0
        if not df.empty and 'status' in df.columns:
            df['id'] = df['id'].astype(str)
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            
            # 1. 已驗收 (實拿)
            df_done = df[df['status'] == 'Done']
            for i, r in df_done.iterrows():
                ps = str(r['partner_id']).split(',') if r['partner_id'] else []
                ps = [p for p in ps if p]
                team = [r['hunter_id']] + ps
                if me in team:
                    share = r['points'] // len(team)
                    rem = r['points'] % len(team)
                    my_rev += (share + rem) if me == r['hunter_id'] else share
            
            # 2. 進行中 (預估)
            df_active = df[df['status'].isin(['Active', 'Pending'])]
            for i, r in df_active.iterrows():
                # 簡單邏輯：只要參與就先算進預估值
                ps = str(r['partner_id']).split(',') if r['partner_id'] else []
                if me == r['hunter_id'] or me in ps:
                    team_len = 1 + len([p for p in ps if p])
                    pending_rev += (r['points'] // team_len)

        # Dashboard 區塊
        st.title(f"🚀 {me} 的戰情室")
        
        # 股市大盤風格 Metric
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("💰 已落袋營收", f"${int(my_rev):,}", delta="已入帳")
        with m2:
            st.metric("⏳ 進行中/預估", f"${int(pending_rev):,}", delta="潛在收益", delta_color="off")
        with m3:
            # 隨機顯示一個市場熱度 (增加氛圍)
            market_heat = random.choice(["🔥 交易熱絡", "📈 指數上升", "⚡ 競爭激烈"])
            st.metric("📊 市場狀態", market_heat)
        
        st.divider()

        tab1, tab2 = st.tabs(["🔥 搶標大廳 (Market)", "🏗️ 我的工程 (My Ops)"])
        
        with tab1:
            if not df.empty and 'status' in df.columns:
                df_open = df[df['status'] == 'Open']
                if not df_open.empty:
                    # 依金額排序，讓大案子排前面
                    df_open = df_open.sort_values(by='points', ascending=False)
                    
                    for i, row in df_open.iterrows():
                        # 卡片樣式設計
                        with st.container(border=True):
                            # 標題列：左邊標題，右邊金額
                            c_head1, c_head2 = st.columns([3, 2])
                            with c_head1:
                                # 熱門標籤邏輯
                                tags = f"**[{row['rank']}]**"
                                if row['points'] >= 100000:
                                    tags += " :red[🔥 鉅額]"
                                elif row['points'] >= 20000:
                                    tags += " :orange[⚡ 熱門]"
                                elif row['points'] <= 5000:
                                    tags += " :orange[🌱 小資]"    
                                st.markdown(f"### {row['title']}")
                                st.markdown(tags)
                            with c_head2:
                                st.markdown(f"<div style='text-align: right; font-size: 24px; color: #4CAF50; font-weight: bold;'>${row['points']:,}</div>", unsafe_allow_html=True)
                            
                            st.caption(f"發布時間: {row['created_at']}")
                            with st.expander("查看詳細規格"):
                                st.write(row['description'])
                            
                            # 投標區
                            c_act1, c_act2 = st.columns([3, 1])
                            with c_act1:
                                all_users = list(st.session_state['auth_dict'].keys())
                                p_opts = [u for u in all_users if u != me]
                                partners = st.multiselect("🤝 聯合承攬 (邀請隊友)", p_opts, max_selections=3, key=f"p_{row['id']}")
                            with c_act2:
                                st.write("") # Spacer
                                st.write("")
                                if st.button("⚡ 立即搶標", key=f"btn_{row['id']}", use_container_width=True):
                                    update_quest_status(row['id'], 'Active', me, partners)
                                    st.toast(f"恭喜得標！預算 ${row['points']:,} 已鎖定！", icon='🎉')
                                    st.balloons()
                                    time.sleep(1.5)
                                    st.rerun()
                else: st.info("💤 目前市場平靜，等待新標案發布...")
            else: st.info("等待資料庫連線...")

        with tab2:
            if not df.empty and 'status' in df.columns:
                def check_me(r):
                    ps = str(r['partner_id']).split(',')
                    return r['hunter_id'] == me or me in ps
                
                df_my = df[df.apply(check_me, axis=1)]
                df_my = df_my[df_my['status'].isin(['Active', 'Pending'])]
                
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        status_color = "orange" if row['status'] == 'Active' else "blue"
                        status_txt = "施工中" if row['status'] == 'Active' else "驗收審核中"
                        
                        with st.container(border=True):
                            st.markdown(f"#### :{status_color}[{status_txt}] {row['title']}")
                            st.progress(50 if row['status'] == 'Active' else 90)
                            
                            c1, c2 = st.columns(2)
                            with c1: st.write(f"💰 總預算: **${row['points']:,}**")
                            with c2: 
                                role = "👑 主標" if row['hunter_id'] == me else "🤝 隊友"
                                st.write(f"身份: **{role}**")
                            
                            if row['status'] == 'Active' and row['hunter_id'] == me:
                                if st.button("✅ 申報完工 (送審)", key=f"sub_{row['id']}"):
                                    update_quest_status(row['id'], 'Pending')
                                    st.toast("已送出驗收申請！")
                                    st.rerun()
                else: st.info("尚無進行中的工程")
