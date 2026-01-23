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
        # 強制將 partner_id 轉為字串，避免多人時被當成數字
        if 'partner_id' in df.columns:
            df['partner_id'] = df['partner_id'].astype(str)
        return df
    except:
        return pd.DataFrame()

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
    except:
        st.error("找不到該案件 ID")
        return False
    
    ws.update_cell(row_num, 6, new_status)
    
    if hunter_id is not None: 
        ws.update_cell(row_num, 7, hunter_id)
        
    # 👇 修改重點：將多人名單結合成字串存入 (例如: "Alex,Betty,Charlie")
    if partner_list is not None:
        if isinstance(partner_list, list):
            partner_str = ",".join(partner_list)
        else:
            partner_str = partner_list # 相容舊資料
        ws.update_cell(row_num, 9, partner_str)
        
    elif new_status == 'Open': 
        ws.update_cell(row_num, 9, "")
        
    return True

# ==========================================
# 2. 工程標案業務邏輯
# ==========================================
PROJECT_TYPES = ["消防工程", "機電工程", "場勘報價", "室內裝修", "點移交總檢", "人力派遣", "其他"]

st.set_page_config(page_title="工程標案管理系統", layout="wide", page_icon="🏗️")

if 'user_role' not in st.session_state:
    st.title("🏗️ 工程標案管理系統")
    st.caption("🔴 內部招標專用平台 (聯合承攬版)")
    
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
            st.subheader("🚜 投標工程師")
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
                st.warning("⚠️ 連線中...")

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
            if not df.empty and 'status' in df.columns:
                df['id'] = df['id'].astype(str)
                df_p = df[df['status'] == 'Pending']
                if not df_p.empty:
                    for i, row in df_p.iterrows():
                        with st.expander(f"📋 {row['title']} (得標: {row['hunter_id']})"):
                            st.write(f"金額: ${row['points']:,}")
                            # 顯示所有團隊成員
                            if row['partner_id']:
                                st.info(f"🤝 聯合承攬團隊: {row['partner_id']}")
                            
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 驗收撥款", key=f"ok_{row['id']}"):
                                update_quest_status(row['id'], 'Done')
                                st.rerun()
                            if c2.button("❌ 退回修正", key=f"no_{row['id']}"):
                                update_quest_status(row['id'], 'Active')
                                st.rerun()
                else: st.info("無待驗收案件")
            else: st.info("無資料")

        with tab3:
            st.dataframe(get_data('quests'))

    elif st.session_state['user_role'] == 'Hunter':
        me = st.session_state['user_name']
        
        df = get_data('quests')
        my_revenue = 0
        
        # --- 👇 核心算法升級：均分預算邏輯 ---
        if not df.empty and 'status' in df.columns:
            df['id'] = df['id'].astype(str)
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            
            # 只看已完成 (Done) 的案子
            df_done = df[df['status'] == 'Done']
            
            for i, row in df_done.iterrows():
                total_budget = row['points']
                main_hunter = row['hunter_id']
                # 解析隊友字串 "A,B,C" -> ['A', 'B', 'C']
                partners = str(row['partner_id']).split(',') if row['partner_id'] else []
                # 過濾空字串 (避免最後有逗號)
                partners = [p for p in partners if p]
                
                # 團隊全體成員
                team_members = [main_hunter] + partners
                team_size = len(team_members)
                
                # 1. 檢查我是否在這個團隊裡
                if me in team_members:
                    # 2. 計算均分
                    base_share = total_budget // team_size  # 整除 (每人拿多少)
                    remainder = total_budget % team_size    # 餘數 (除不盡剩多少)
                    
                    # 3. 分錢邏輯
                    if me == main_hunter:
                        # 主標者拿：基本份額 + 餘數
                        my_revenue += (base_share + remainder)
                    else:
                        # 隊友拿：基本份額
                        my_revenue += base_share

        st.title(f"🚜 得標平台: {me}")
        col_m1, col_m2 = st.columns(2)
        with col_m1: st.metric("💰 實拿分潤總額", f"${int(my_revenue):,}")
        with col_m2: st.caption("計算方式：團隊均分，除不盡餘數歸主標者")
        st.divider()
        
        tab1, tab2 = st.tabs(["📢 招標公告", "🏗️ 我的工程"])
        
        with tab1:
            st.subheader("可投標案件")
            if not df.empty and 'status' in df.columns:
                df_open = df[df['status'] == 'Open']
                if not df_open.empty:
                    for i, row in df_open.iterrows():
                        with st.container(border=True):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.subheader(f"📄 {row['title']}")
                                st.caption(f"類別: {row['rank']}")
                            with c2: st.metric("總預算", f"${row['points']:,}")
                            st.markdown(f"**說明**: {row['description']}")
                            
                            # 👇 升級：多選選單 (Multiselect)
                            all_users = list(st.session_state['auth_dict'].keys())
                            partners_options = [u for u in all_users if u != me]
                            
                            # 限制最多選 3 人 (加上自己 = 4人)
                            selected_partners = st.multiselect(
                                "選擇聯合承攬夥伴 (最多3人)", 
                                partners_options,
                                max_selections=3,
                                key=f"p_{row['id']}"
                            )
                            
                            if st.button("⚡️ 投標接案", key=f"claim_{row['id']}"):
                                update_quest_status(row['id'], 'Active', me, selected_partners)
                                st.success("成功得標！")
                                time.sleep(1)
                                st.rerun()
                else: st.info("🚧 目前無公開招標案件")
            else: st.info("🚧 資料庫準備中")
        
        with tab2:
            st.subheader("進行中工程")
            if not df.empty and 'status' in df.columns:
                # 這裡的邏輯稍微複雜一點：要在「字串」裡找自己
                # 因為 partner_id 現在可能是 "Alex,Betty"
                # 我們用 apply 寫一個簡單的過濾器
                def is_in_project(row):
                    p_list = str(row['partner_id']).split(',')
                    return (row['hunter_id'] == me) or (me in p_list)

                # 篩選出跟我有關的案子
                df_relevant = df[df.apply(is_in_project, axis=1)]
                df_my = df_relevant[df_relevant['status'].isin(['Active', 'Pending'])]
                
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        with st.expander(f"🚧 {row['title']} ({row['status']})", expanded=True):
                            st.write(f"總預算: ${row['points']:,}")
                            
                            # 解析團隊
                            p_list = [p for p in str(row['partner_id']).split(',') if p]
                            team_str = ", ".join(p_list) if p_list else "無"
                            
                            st.write(f"👑 主標: {row['hunter_id']}")
                            st.write(f"🤝 夥伴: {team_str}")

                            if row['status'] == 'Active' and row['hunter_id'] == me:
                                if st.button("📩 完工申報", key=f"sub_{row['id']}"):
                                    update_quest_status(row['id'], 'Pending')
                                    st.rerun()
                            elif row['status'] == 'Pending':
                                st.warning("等待驗收中...")
                else: st.info("無進行中工程")
            else: st.info("無進行中工程")
