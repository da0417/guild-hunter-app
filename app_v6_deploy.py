import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime

# ==========================================
# 1. 雲端資料庫層 (改為讀取 st.secrets)
# ==========================================
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'guild_system_db'

@st.cache_resource
def connect_db():
    """連線到 Google Sheets (使用雲端 Secrets)"""
    try:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME)
        return sheet
    except Exception as e:
        st.error(f"❌ 無法連線到 Google Sheet: {e}")
        st.stop()

def get_data(worksheet_name):
    sheet = connect_db()
    ws = sheet.worksheet(worksheet_name)
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if 'password' in df.columns:
        df['password'] = df['password'].astype(str)
    return df

def add_quest_to_sheet(title, desc, rank, points):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    q_id = int(time.time()) 
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 寫入順序: id, title, desc, rank, points, status, hunter_id, created_at, partner_id
    ws.append_row([q_id, title, desc, rank, points, "Open", "", created_at, ""])

def update_quest_status(quest_id, new_status, hunter_id=None, partner_id=None):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    try:
        cell = ws.find(str(quest_id))
        row_num = cell.row
    except:
        st.error("找不到該任務 ID")
        return False
    
    ws.update_cell(row_num, 6, new_status)
    if hunter_id is not None:
        ws.update_cell(row_num, 7, hunter_id)
    if partner_id is not None:
        ws.update_cell(row_num, 9, partner_id)
    elif new_status == 'Open':
        ws.update_cell(row_num, 9, "")
        
    return True

# ==========================================
# 2. 業務邏輯與介面
# ==========================================
RANK_POINTS = {"S (屠龍級)": 100, "A (打虎級)": 50, "B (獵狼級)": 20, "C (抓兔級)": 10}

st.set_page_config(page_title="☁️ 雲端公會獵人 (Online)", layout="wide", page_icon="🌍")

if 'user_role' not in st.session_state:
    st.title("🌍 雲端賞金獵人公會 (24h Online)")
    st.caption("🟢 系統狀態：已部署至 Streamlit Cloud")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("我是公會長")
        pwd = st.text_input("輸入管理員密碼", type="password")
        if st.button("👑 Admin 登入"):
            # 👇 您可以在這裡修改管理員密碼
            if pwd == "Boss@9988": 
                st.session_state['user_role'] = 'Admin'
                st.rerun()
            else:
                st.error("密碼錯誤")

    with col2:
        st.subheader("我是獵人")
        if 'auth_dict' not in st.session_state:
            try:
                df_emps = get_data('employees')
                if not df_emps.empty and 'password' in df_emps.columns:
                    st.session_state['auth_dict'] = dict(zip(df_emps['name'], df_emps['password']))
                else:
                    st.session_state['auth_dict'] = {}
            except:
                st.session_state['auth_dict'] = {}

        if st.session_state['auth_dict']:
            hunter_name = st.selectbox("選擇身份", list(st.session_state['auth_dict'].keys()))
            hunter_pwd = st.text_input("輸入獵人密碼", type="password", key="h_pwd")
            if st.button("⚔️ 獵人登入"):
                stored_pwd = str(st.session_state['auth_dict'].get(hunter_name))
                if hunter_pwd == stored_pwd:
                    st.session_state['user_role'] = 'Hunter'
                    st.session_state['user_name'] = hunter_name
                    st.success("登入成功！")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("密碼錯誤！")
        else:
            st.warning("無法連線資料庫，請檢查 Secrets 設定。")

else:
    with st.sidebar:
        st.title(f"身份: {st.session_state['user_role']}")
        if st.session_state['user_role'] == 'Hunter':
            st.write(f"ID: **{st.session_state['user_name']}**")
        if st.button("🚪 登出"):
            for key in ['user_role', 'auth_dict']:
                if key in st.session_state: del st.session_state[key]
            st.rerun()

    if st.session_state['user_role'] == 'Admin':
        st.title("👑 公會長指揮中心")
        tab1, tab2, tab3 = st.tabs(["📜 發布", "⚖️ 驗收", "📊 數據"])
        with tab1:
            with st.form("new_quest"):
                title = st.text_input("標題")
                desc = st.text_area("詳情")
                rank = st.selectbox("難度", list(RANK_POINTS.keys()))
                if st.form_submit_button("🚀 發布"):
                    add_quest_to_sheet(title, desc, rank, RANK_POINTS[rank])
                    st.success("已發布")
        with tab2:
            st.subheader("待驗收")
            df = get_data('quests')
            if not df.empty:
                df['id'] = df['id'].astype(str)
                df_pending = df[df['status'] == 'Pending']
                if not df_pending.empty:
                    for i, row in df_pending.iterrows():
                        with st.expander(f"{row['title']} (獵人: {row['hunter_id']})"):
                            if 'partner_id' in row and row['partner_id']:
                                st.info(f"🤝 協力獵人: {row['partner_id']}")
                            c1, c2 = st.columns(2)
                            if c1.button("✅", key=f"ok_{row['id']}"):
                                update_quest_status(row['id'], 'Done')
                                st.rerun()
                            if c2.button("❌", key=f"no_{row['id']}"):
                                update_quest_status(row['id'], 'Active')
                                st.rerun()
                else: st.info("無待驗收")
        with tab3:
            st.dataframe(get_data('quests'))

    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        
        # --- 👇 積分計算邏輯 ---
        df = get_data('quests')
        my_score = 0
        if not df.empty:
            df['id'] = df['id'].astype(str)
            # 確保 points 是數字
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            
            # 1. 篩選出已完成 (Done) 的任務
            df_done = df[df['status'] == 'Done']
            
            # 2. 篩選出「我是主獵人」或「我是隊友」的任務
            # 使用 .get 來避免舊資料沒有 partner_id 欄位時報錯
            mask = (df_done['hunter_id'] == me) | (df_done.get('partner_id', pd.Series()) == me)
            
            # 3. 加總分數
            my_score = df_done.loc[mask, 'points'].sum()

        # --- 顯示積分板 ---
        st.title(f"⚔️ 獵人儀表板: {me}")
        col_score, col_hint = st.columns([1, 3])
        with col_score:
            st.metric(label="🏆 累積積分", value=int(my_score))
        with col_hint:
            st.info("💡 只有經公會長驗收通過 (Done) 的任務才會列入計算！")
        st.divider()

        tab1, tab2 = st.tabs(["🔥 搶單", "🎒 我的"])
        with tab1:
            df_open = df[df['status'] == 'Open']
            if not df_open.empty:
                for i, row in df_open.iterrows():
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 2])
