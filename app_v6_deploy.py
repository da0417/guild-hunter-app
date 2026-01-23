import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime

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
        if 'password' in df.columns:
            df['password'] = df['password'].astype(str)
        return df
    except:
        return pd.DataFrame() # 如果讀取失敗，回傳空表格

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
        st.error("找不到該案件 ID")
        return False
    
    ws.update_cell(row_num, 6, new_status)
    if hunter_id is not None: ws.update_cell(row_num, 7, hunter_id)
    if partner_id is not None: ws.update_cell(row_num, 9, partner_id)
    elif new_status == 'Open': ws.update_cell(row_num, 9, "")
    return True

# ==========================================
# 2. 工程標案業務邏輯
# ==========================================
PROJECT_TYPES = ["土木工程", "機電工程", "室內裝修", "軟體開發", "人力派遣", "其他"]

st.set_page_config(page_title="工程標案管理系統", layout="wide", page_icon="🏗️")

if 'user_role' not in st.session_state:
    st.title("🏗️ 工程標案管理系統")
    st.caption("🔴 內部招標專用平台")
    
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.subheader("👷‍♂️ 發包主管 (Admin)")
            pwd = st.text_input("輸入管理密碼", type="password")
            if st.button("登入管理後台"):
                if pwd == "Boss@9988": 
                    st.session_state['user_role'] = 'Admin'
                    st.rerun()
                else: st.error("密碼錯誤")

    with col2:
        with st.container(border=True):
            st.subheader("🚜 投標廠商/工程師")
            # --- 防呆讀取員工名單 ---
            if 'auth_dict' not in st.session_state:
                df_emps = get_data('employees')
                if not df_emps.empty and 'password' in df_emps.columns:
                    st.session_state['auth_dict'] = dict(zip(df_emps['name'], df_emps['password']))
                else:
                    st.session_state['auth_dict'] = {}

            if st.session_state['auth_dict']:
                hunter_name = st.selectbox("選擇廠商/人員", list(st.session_state['auth_dict'].keys()))
                hunter_pwd = st.text_input("輸入密碼", type="password", key="h_pwd")
                if st.button("登入標案系統"):
                    stored_pwd = str(st.session_state['auth_dict'].get(hunter_name))
                    if hunter_pwd == stored_pwd:
                        st.session_state['user_role'] = 'Hunter'
                        st.session_state['user_name'] = hunter_name
                        st.rerun()
                    else: st.error("密碼錯誤")
            else:
                st.warning("⚠️ 無法讀取人員名單，請確認 Google Sheet 設定。")

else:
    with st.sidebar:
        st.write(f"當前身份: **{st.session_state['user_role']}**")
        if st.session_state['user_role'] == 'Hunter':
            st.write(f"使用者: **{st.session_state['user_name']}**")
        st.divider()
        if st.button("🚪 登出系統"):
            for key in ['user_role', 'auth_dict']:
                if key in st.session_state: del st.session_state[key]
            st.rerun()

    # --- 管理者介面 ---
    if st.session_state['user_role'] == 'Admin':
        st.title("👷‍♂️ 發包管理中心")
        tab1, tab2, tab3 = st.tabs(["📝 新增標案", "🔍 驗收工程", "📊 案件總表"])
        
        with tab1:
            st.subheader("發布新的招標案件")
            with st.form("new_project"):
                title = st.text_input("標案名稱")
                col_a, col_b = st.columns(2)
                with col_a: p_type = st.selectbox("工程類別", PROJECT_TYPES)
                with col_b: budget = st.number_input("預算金額 ($)", min_value=0, step=10000)
                desc = st.text_area("工程需求/規格說明")
                
                if st.form_submit_button("🚀 發布招標"):
                    add_quest_to_sheet(title, desc, p_type, budget)
                    st.success(f"標案「{title}」已發布！")
                    time.sleep(1)
                    st.rerun()
        
        with tab2:
            st.subheader("待驗收工程")
            df = get_data('quests')
            # --- 防呆檢查 ---
            if not df.empty and 'status' in df.columns:
                df['id'] = df['id'].astype(str)
                df_p = df[df['status'] == 'Pending']
                if not df_p.empty:
                    for i, row in df_p.iterrows():
                        with st.expander(f"📋 {row['title']} (得標: {row['hunter_id']})"):
                            st.write(f"金額: ${row['points']:,}")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 驗收通過", key=f"ok_{row['id']}"):
                                update_quest_status(row['id'], 'Done')
                                st.rerun()
                            if c2.button("❌ 退回", key=f"no_{row['id']}"):
                                update_quest_status(row['id'], 'Active')
                                st.rerun()
                else: st.info("目前無待驗收案件")
            else: st.info("目前無資料")

        with tab3:
            st.dataframe(get_data('quests'))

    # --- 廠商/工程師介面 ---
    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        
        df = get_data('quests')
        total_revenue = 0
        
        # --- 安全計算營收 ---
        if not df.empty and 'status' in df.columns:
            df['id'] = df['id'].astype(str)
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            df_done = df[df['status'] == 'Done']
            mask = (df_done['hunter_id'] == me) | (df_done.get('partner_id', pd.Series()) == me)
            total_revenue = df_done.loc[mask, 'points'].sum()

        st.title(f"🚜 廠商工作台: {me}")
        col_m1, col_m2 = st.columns(2)
        with col_m1: st.metric("💰 累計得標金額", f"${int(total_revenue):,}")
        with col_m2: st.caption("此金額為已驗收通過之案件總和")
        st.divider()
        
        tab1, tab2 = st.tabs(["📢 招標公告", "🏗️ 我的工程"])
        
        # --- 招標區 (已修復 Crash 問題) ---
        with tab1:
            st.subheader("可投標案件")
            # 👇 這裡加了防呆：先確認表格是不是空的，有沒有 status 欄位
            if not df.empty and 'status' in df.columns:
                df_open = df[df['status'] == 'Open']
                if not df_open.empty:
                    for i, row in df_open.iterrows():
                        with st.container(border=True):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.subheader(f"📄 {row['title']}")
                                st.caption(f"類別: {row['rank']}")
                            with c2: st.metric("預算", f"${row['points']:,}")
                            st.markdown(f"**說明**: {row['description']}")
                            
                            all_users = list(st.session_state['auth_dict'].keys())
                            partners = [u for u in all_users if u != me]
                            partner = st.selectbox("聯合承攬 (選填)", ["無"] + partners, key=f"p_{row['id']}")
                            
                            if st.button("⚡️ 投標接案", key=f"claim_{row['id']}"):
                                final_partner = partner if partner != "無" else ""
                                update_quest_status(row['id'], 'Active', me, final_partner)
                                st.success("成功得標！")
                                time.sleep(1)
                                st.rerun()
                else:
                    st.info("🚧 目前無公開招標案件")
            else:
                # 👇 這就是您要的：如果資料庫壞了或空的，顯示這行
                st.info("🚧 目前無公開招標案件 (或資料庫尚未建立)")
        
        with tab2:
            st.subheader("進行中工程")
            if not df.empty and 'status' in df.columns:
                mask_my = (df['hunter_id'] == me) | (df.get('partner_id', pd.Series()) == me)
                df_my = df[mask_my & (df['status'].isin(['Active', 'Pending']))]
                
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        with st.expander(f"🚧 {row['title']} ({row['status']})", expanded=True):
                            st.write(f"預算: ${row['points']:,}")
                            st.caption(f"身份: {'主承攬' if row['hunter_id'] == me else '協力'}")
                            if row['status'] == 'Active' and row['hunter_id'] == me:
                                if st.button("📩 完工申報", key=f"sub_{row['id']}"):
                                    update_quest_status(row['id'], 'Pending')
                                    st.rerun()
                            elif row['status'] == 'Pending':
                                st.warning("等待驗收中...")
                else: st.info("無進行中工程")
            else: st.info("無進行中工程")
