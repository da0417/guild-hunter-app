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
        # 👇 關鍵修改：不再讀取 .json 檔案，而是讀取雲端設定
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
    ws.append_row([q_id, title, desc, rank, points, "Open", "", created_at])

# 👇 修改後的函數：多了一個 partner_id 參數 (預設為 None)
def update_quest_status(quest_id, new_status, hunter_id=None, partner_id=None):
    sheet = connect_db()
    ws = sheet.worksheet('quests')
    try:
        cell = ws.find(str(quest_id))
        row_num = cell.row
    except:
        st.error("找不到該任務 ID")
        return False
    
    # 更新狀態 (第 6 欄)
    ws.update_cell(row_num, 6, new_status)
    
    # 如果有主獵人，寫入第 7 欄
    if hunter_id is not None:
        ws.update_cell(row_num, 7, hunter_id)
        
    # 👇 新增：如果有隊友，寫入第 9 欄 (因為 created_at 在第 8 欄)
    if partner_id is not None:
        ws.update_cell(row_num, 9, partner_id)
    # 如果是「放棄任務」或「重置」，也要把隊友欄清空
    elif new_status == 'Open': 
        ws.update_cell(row_num, 9, "")
        
    return True

# ==========================================
# 2. 業務邏輯與介面 (完全不變)
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
            if pwd == "24Nr5Vbr582KLFZ":
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
    # --- 登入後介面 ---
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
            df_open = df[df['status'] == 'Open']
            if not df_open.empty:
                for i, row in df_open.iterrows():
                    with st.container(border=True):
                        col_info, col_action = st.columns([3, 2])
                        
                        with col_info:
                            st.markdown(f"**{row['title']}**")
                            st.caption(f"等級: {row['rank']} | 賞金: {row['points']}")

                        with col_action:
                            # 👇 讓獵人可以選擇隊友 (排除自己)
                            # 先取得所有獵人名單
                            all_hunters = list(st.session_state['auth_dict'].keys())
                            # 排除掉「我」自己
                            teammates = [h for h in all_hunters if h != me]
                            
                            # 製作選單：預設是「無 (獨狼)」
                            partner = st.selectbox("選擇隊友 (選填)", ["無"] + teammates, key=f"p_{row['id']}")
                            
                            if st.button("⚡️ 搶單", key=f"claim_{row['id']}"):
                                # 判斷是否有隊友
                                final_partner = partner if partner != "無" else ""
                                
                                # 呼叫更新函數
                                if update_quest_status(row['id'], 'Active', me, final_partner):
                                    msg = "搶單成功！"
                                    if final_partner:
                                        msg += f" (隊友: {final_partner})"
                                    st.success(msg)
                                    time.sleep(1)
                                    st.rerun()
            else:
                st.warning("目前無懸賞")
        with tab2:
            st.subheader("待驗收")
            df = get_data('quests')
            if not df.empty:
                df['id'] = df['id'].astype(str)
                df_pending = df[df['status'] == 'Pending']
                if not df_pending.empty:
                    for i, row in df_pending.iterrows():
                        with st.expander(f"{row['title']} ({row['hunter_id']})"):
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
        st.title(f"⚔️ {me} 的任務")
        df = get_data('quests')
        if not df.empty:
            df['id'] = df['id'].astype(str)
            tab1, tab2 = st.tabs(["🔥 搶單", "🎒 我的"])
            with tab1:
                df_open = df[df['status'] == 'Open']
                if not df_open.empty:
                    for i, row in df_open.iterrows():
                        with st.container(border=True):
                            st.markdown(f"**{row['title']}** ({row['rank']})")
                            if st.button("⚡️ 搶單", key=f"claim_{row['id']}"):
                                if update_quest_status(row['id'], 'Active', me):
                                    st.success("搶單成功！")
                                    time.sleep(1)
                                    st.rerun()
                else: st.warning("無懸賞")
            with tab2:
                df_my = df[(df['hunter_id'] == me) & (df['status'].isin(['Active', 'Pending']))]
                if not df_my.empty:
                    for i, row in df_my.iterrows():
                        st.write(f"🔹 **{row['title']}** ({row['status']})")
                        if row['status'] == 'Active':
                            if st.button("📩 提交", key=f"sub_{row['id']}"):
                                update_quest_status(row['id'], 'Pending')
                                st.rerun()
