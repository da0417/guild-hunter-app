# ===============================
# app_v6_deploy.py
# 穩定基準版（可直接跑）
# ===============================

import streamlit as st
from datetime import datetime

# -------------------------------
# 🛡️ SessionState 防呆（一定要最前）
# -------------------------------
try:
    _ = st.session_state
except Exception:
    st.error("SessionState 異常，請重新整理頁面")
    st.stop()

# -------------------------------
# Page Config（一定要完整）
# -------------------------------
st.set_page_config(
    page_title="發包 / 派單系統",
    layout="wide",
    page_icon="🏗️"
)

# -------------------------------
# 初始化 SessionState
# -------------------------------
if "user_role" not in st.session_state:
    st.session_state["user_role"] = None
if "user_name" not in st.session_state:
    st.session_state["user_name"] = None
if "tasks" not in st.session_state:
    st.session_state["tasks"] = []  # 暫存任務（之後可換成 Google Sheet）

# ===============================
# Login Screen
# ===============================
def login_screen():
    st.title("🔐 登入系統")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("👨‍💼 主管入口")
        pwd = st.text_input("Access Key", type="password")
        if st.button("🚀 進入指揮台"):
            if pwd == "Boss@9988":
                st.session_state["user_role"] = "Admin"
                st.session_state["user_name"] = "Admin"
                st.rerun()
            else:
                st.error("Access Key 錯誤")

    with col2:
        st.subheader("👷 同仁入口")
        name = st.text_input("姓名")
        if st.button("⚡ 上工"):
            if name.strip():
                st.session_state["user_role"] = "Hunter"
                st.session_state["user_name"] = name.strip()
                st.rerun()
            else:
                st.error("請輸入姓名")

# ===============================
# Admin View
# ===============================
def admin_view():
    st.title("👨‍💼 發包 / 派單指揮台")

    tabs = st.tabs(["📤 發布任務", "📊 任務總表"])

    # -------- 發布任務 --------
    with tabs[0]:
        st.subheader("發布新任務")

        title = st.text_input("案件名稱")
        quote_no = st.text_input("估價單號")
        amount = st.number_input("金額 ($)", min_value=0, step=1000)
        desc = st.text_area("詳細說明")

        if st.button("🚀 確認發布"):
            if not title:
                st.error("案件名稱必填")
            else:
                st.session_state["tasks"].append({
                    "title": title,
                    "quote_no": quote_no,
                    "amount": amount,
                    "desc": desc,
                    "status": "Open",
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                st.success("任務已發布")

    # -------- 任務總表 --------
    with tabs[1]:
        st.subheader("📊 任務總表")
        if not st.session_state["tasks"]:
            st.info("目前尚無任務")
        else:
            for i, t in enumerate(st.session_state["tasks"], start=1):
                st.markdown(f"""
                **#{i}｜{t['title']}**  
                - 估價單號：{t['quote_no'] or "—"}  
                - 金額：${t['amount']:,}  
                - 狀態：{t['status']}  
                - 建立時間：{t['created_at']}
                ---
                """)

# ===============================
# Hunter View
# ===============================
def hunter_view():
    st.title(f"🚀 工作台：{st.session_state['user_name']}")

    open_tasks = [t for t in st.session_state["tasks"] if t["status"] == "Open"]

    if not open_tasks:
        st.info("目前沒有可接任務")
        return

    for t in open_tasks:
        with st.expander(f"📄 {t['title']}"):
            st.write(f"估價單號：{t['quote_no'] or '—'}")
            st.write(f"金額：${t['amount']:,}")
            st.write(f"說明：{t['desc']}")
            if st.button(f"✋ 接下任務｜{t['title']}"):
                t["status"] = "Active"
                st.success("任務已接下")
                st.rerun()

# ===============================
# Main
# ===============================
def main():
    if not st.session_state["user_role"]:
        login_screen()
    elif st.session_state["user_role"] == "Admin":
        admin_view()
    elif st.session_state["user_role"] == "Hunter":
        hunter_view()

    st.sidebar.divider()
    if st.sidebar.button("🚪 登出"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

main()
