# app_v6_deploy.py
# Streamlit + Google Sheet 派工系統（含：AI 辨識估價單號 quote_no、自動帶入表單、我的任務顯示金額）
import base64
import json
import re
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials

try:
    import requests
except ImportError:
    st.error("請在 requirements.txt 加入 requests")
    raise

# ===============================
# 🛡️ SessionState 防呆保護
# ===============================
try:
    _ = st.session_state
except Exception:
    st.error("SessionState 異常，已自動重置，請重新整理頁面。")
    try:
        for k in list(st.session_state.keys()):
            del st.session_state[k]
    except Exception:
        pass
    st.stop()

# ============================================================
# 0) Streamlit 設定
# ============================================================
st.set_page_config(
    page_title="發包 / 派單指揮台",
    layout="wide",
    page_icon="🏢"
)

st.markdown(
    """
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .urgent-tag { color: #FF4B4B; font-weight: bold; border: 1px solid #FF4B4B; padding: 2px 5px; border-radius: 4px; font-size: 12px; margin-left: 5px; }
    .pill { display:inline-block; padding:2px 8px; border:1px solid #555; border-radius:999px; font-size:12px; color:#ddd; margin-right:6px;}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 1) 系統常數
# ============================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "guild_system_db"

QUEST_SHEET = "quests"
EMP_SHEET = "employees"

# quests 表建議欄位順序（表頭第 1 列）
# id | title | quote_no | description | rank | points | status | hunter_id | created_at | partner_id
QUEST_HEADERS = [
    "id",
    "title",
    "quote_no",
    "description",
    "rank",
    "points",
    "status",
    "hunter_id",
    "created_at",
    "partner_id",
]

# quests 欄位位置（1-based）
COL_ID = 1
COL_TITLE = 2
COL_QUOTE_NO = 3
COL_DESC = 4
COL_RANK = 5
COL_POINTS = 6
COL_STATUS = 7
COL_HUNTER = 8
COL_CREATED_AT = 9
COL_PARTNERS = 10

# 類別
TYPE_ENG = ["消防工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

# 分組（可自行調整）
TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

# 主管密碼（優先讀 secrets，沒設就用預設）
ADMIN_KEY_DEFAULT = "Boss@9988"
ADMIN_KEY_SECRET_NAME = "ADMIN_ACCESS_KEY"

# ============================================================
# 2) 小工具
# ============================================================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_int(x, default=0) -> int:
    try:
        return int(float(x))
    except Exception:
        return int(default)


def normalize_quote_no(qn: str) -> str:
    qn = str(qn or "").strip()
    qn = qn.replace(" ", "")
    # 常見字元修正（全形）
    qn = qn.replace("－", "-").replace("—", "-")
    return qn


def normalize_category(cat: str, budget: int) -> str:
    cat = str(cat or "").strip()
    if cat in ALL_TYPES:
        return cat
    return TYPE_MAINT[0] if budget == 0 else TYPE_ENG[0]


def my_team_label(name: str) -> str:
    if name in TEAM_ENG_1:
        return "🏗️ 工程 1 組"
    if name in TEAM_ENG_2:
        return "🏗️ 工程 2 組"
    if name in TEAM_MAINT_1:
        return "🔧 維養 1 組"
    return "未分組"


# ============================================================
# 3) Google Sheet 連線
# ============================================================
@st.cache_resource
def connect_db():
    try:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME)
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {e}")
        return None


@st.cache_data(ttl=3)
def get_data(worksheet_name: str) -> pd.DataFrame:
    try:
        sheet = connect_db()
        if not sheet:
            return pd.DataFrame()
        ws = sheet.worksheet(worksheet_name)
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)
        return df
    except Exception:
        return pd.DataFrame()


def invalidate_cache():
    get_data.clear()  # type: ignore


def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    """容錯：把不同欄名映射到標準欄名，確保同仁端/總表能顯示。"""
    if df.empty:
        return df

    rename_map = {
        # 類別
        "category": "rank",
        "type": "rank",
        "類別": "rank",
        # 金額
        "budget": "points",
        "amount": "points",
        "金額": "points",
        # 說明
        "desc": "description",
        "內容": "description",
        "說明": "description",
        # 估價單號
        "估價單號": "quote_no",
        "quoteNo": "quote_no",
        "quotation_no": "quote_no",
        # 隊友
        "partner_list": "partner_id",
        "partners": "partner_id",
        "隊友": "partner_id",
    }

    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # 補齊缺欄
    for c in QUEST_HEADERS:
        if c not in df.columns:
            df[c] = ""

    # 型態整理
    for c in ["id", "title", "quote_no", "description", "rank", "status", "hunter_id", "partner_id", "created_at"]:
        df[c] = df[c].astype(str)

    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

    return df[QUEST_HEADERS]


def add_quest_to_sheet(title: str, quote_no: str, desc: str, category: str, points: int) -> bool:
    """寫入 quests：id,title,quote_no,description,rank,points,status,hunter_id,created_at,partner_id"""
    sheet = connect_db()
    if not sheet:
        return False
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        q_id = str(int(time.time()))
        created_at = now_str()
        quote_no = normalize_quote_no(quote_no)

        ws.append_row(
            [
                q_id,
                title,
                quote_no,
                desc,
                category,
                int(points),
                "Open",
                "",
                created_at,
                "",
            ],
            value_input_option="USER_ENTERED",
        )
        invalidate_cache()
        return True
    except Exception as e:
        st.error(f"❌ 新增任務失敗: {e}")
        return False


def update_quest_status(quest_id: str, new_status: str, hunter_id=None, partner_list=None) -> bool:
    sheet = connect_db()
    if not sheet:
        return False
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        cell = ws.find(str(quest_id))
        row_num = cell.row

        ws.update_cell(row_num, COL_STATUS, new_status)
        if hunter_id is not None:
            ws.update_cell(row_num, COL_HUNTER, str(hunter_id))

        if partner_list is not None:
            partner_str = ",".join([p for p in partner_list if p]) if isinstance(partner_list, list) else str(partner_list)
            ws.update_cell(row_num, COL_PARTNERS, partner_str)
        elif new_status == "Open":
            ws.update_cell(row_num, COL_PARTNERS, "")

        invalidate_cache()
        return True
    except Exception:
        return False


# ============================================================
# 4) AI 辨識（含 quote_no）
# ============================================================
def extract_first_json(text: str):
    if not text:
        return None
    t = text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def analyze_quote_image(image_file):
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    try:
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode("utf-8")
        mime_type = image_file.type

        categories_str = ", ".join(ALL_TYPES)

        prompt = f"""
請分析圖片（估價單/報價單或報修APP截圖），並且只輸出「單一 JSON 物件」，不得輸出任何額外文字。

請提取欄位：
1. quote_no: 估價單號（例如 A1412290028-1；若找不到則空字串 ""）
2. community: 社區名稱（去除編號/代碼）
3. project: 工程名稱或報修摘要
4. description: 詳細說明
5. budget: 總金額（整數；若無則 0）
6. category: 必須從以下清單中選一個（不得自創）：[{categories_str}]
7. is_urgent: true/false
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": b64_img}},
                    ]
                }
            ]
        }

        resp = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=25,
        )

        if resp.status_code != 200:
            return None

        result = resp.json()
        raw_text = result["candidates"][0]["content"]["parts"][0]["text"]
        data = extract_first_json(raw_text)
        if not data:
            return None

        comm = str(data.get("community", "")).strip()
        proj = str(data.get("project", "")).strip()
        desc = str(data.get("description", "")).strip()

        # 去除社區前綴編號（你原本的規則保留）
        if comm:
            comm = re.sub(r"^[A-Za-z0-9]+\s*", "", comm).strip()

        budget = safe_int(data.get("budget", 0), 0)
        cat = normalize_category(data.get("category", ""), budget)
        qn = normalize_quote_no(data.get("quote_no", ""))

        if comm and proj:
            title = f"【{comm}】{proj}"
        else:
            title = proj or comm

        return {
            "quote_no": qn,
            "community": comm,
            "project": proj,
            "description": desc,
            "budget": budget,
            "category": cat,
            "is_urgent": bool(data.get("is_urgent", False)),
            "title": title,
        }
    except Exception:
        return None


# ============================================================
# 5) 業績/忙碌判斷
# ============================================================
def calc_my_total(df_quests: pd.DataFrame, me: str) -> int:
    if df_quests.empty:
        return 0
    df = ensure_quests_schema(df_quests)
    total = 0
    done = df[df["status"] == "Done"]

    for _, r in done.iterrows():
        partners = [p for p in str(r["partner_id"]).split(",") if p]
        team = [str(r["hunter_id"])] + partners
        if me not in team:
            continue

        pts = int(r["points"])
        share = pts // len(team)
        rem = pts % len(team)
        total += (share + rem) if me == str(r["hunter_id"]) else share

    return total


def is_me_busy(df_quests: pd.DataFrame, me: str) -> bool:
    if df_quests.empty:
        return False
    df = ensure_quests_schema(df_quests)
    active = df[df["status"] == "Active"]
    for _, r in active.iterrows():
        partners = [p for p in str(r["partner_id"]).split(",") if p]
        if me == str(r["hunter_id"]) or me in partners:
            return True
    return False


# ============================================================
# 6) UI：登入
# ============================================================
def admin_access_ok(pwd: str) -> bool:
    expected = st.secrets.get(ADMIN_KEY_SECRET_NAME, ADMIN_KEY_DEFAULT)
    return str(pwd) == str(expected)


def load_auth_dict():
    df = get_data(EMP_SHEET)
    if df.empty:
        return {}
    if "name" not in df.columns or "password" not in df.columns:
        return {}
    return dict(zip(df["name"].astype(str), df["password"].astype(str)))


def login_screen():
    st.title("🏢 工程/叫修 發包管理系統")
    st.caption("v9.6（含：AI 辨識估價單號 → 自動帶入表單）")

    c1, c2 = st.columns(2)

    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管入口")
            pwd = st.text_input("Access Key", type="password")
            if st.button("🚀 進入指揮台"):
                if admin_access_ok(pwd):
                    st.session_state.update({"user_role": "Admin", "user_name": "Admin"})
                    st.rerun()
                else:
                    st.error("密碼錯誤")

    with c2:
        with st.container(border=True):
            st.subheader("👷 同仁入口")
            auth = load_auth_dict()
            if not auth:
                st.warning("employees 表缺少 name/password 或尚無資料")
                return

            name = st.selectbox("姓名", list(auth.keys()))
            pwd = st.text_input("密碼", type="password")
            if st.button("⚡ 上工"):
                if str(pwd) == str(auth.get(name)):
                    st.session_state["user_role"] = "Hunter"
                    st.session_state["user_name"] = name
                    st.rerun()
                else:
                    st.error("密碼錯誤")


def sidebar():
    with st.sidebar:
        me = st.session_state.get("user_name", "Admin")
        st.header(f"👤 {me}")

        if st.session_state.get("user_role") == "Hunter":
            st.info(f"所屬: **{my_team_label(me)}**")

        if st.button("🚪 登出系統"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


# ============================================================
# 7) Admin View
# ============================================================
def admin_view():
    st.title("🧑‍💼 發包/派單指揮台")
    t1, t2, t3 = st.tabs(["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"])

    # ------- t1: 發布新任務 -------
    with t1:
        st.subheader("發布新任務")
        uploaded_file = st.file_uploader("📤 上傳 (估價單 / 報價單 / 報修截圖)", type=["png", "jpg", "jpeg"])

        st.session_state.setdefault("draft_title", "")
        st.session_state.setdefault("draft_quote_no", "")
        st.session_state.setdefault("draft_desc", "")
        st.session_state.setdefault("draft_budget", 0)
        st.session_state.setdefault("draft_type", TYPE_ENG[0])

        if uploaded_file is not None:
            if st.button("✨ 啟動 AI 辨識"):
                with st.spinner("🤖 AI 正在閱讀並歸類..."):
                    ai = analyze_quote_image(uploaded_file)
                    if ai:
                        st.session_state["draft_title"] = ai.get("title", "")
                        st.session_state["draft_quote_no"] = ai.get("quote_no", "")
                        st.session_state["draft_desc"] = ai.get("description", "")
                        st.session_state["draft_budget"] = safe_int(ai.get("budget", 0), 0)

                        cat = ai.get("category", "")
                        st.session_state["draft_type"] = cat if cat in ALL_TYPES else normalize_category(cat, st.session_state["draft_budget"])

                        if ai.get("is_urgent"):
                            st.toast("🚨 緊急案件！", icon="🔥")
                        else:
                            st.toast("✅ 辨識成功！", icon="🤖")
                    else:
                        st.error("AI 辨識失敗（JSON 解析或 API 回覆異常）")

        with st.form("new_task"):
            c_a, c_b = st.columns([2, 1])

            with c_a:
                title = st.text_input("案件名稱", value=st.session_state["draft_title"])
                quote_no = st.text_input("估價單號", value=st.session_state["draft_quote_no"], placeholder="例如：A1412290028-1")

            with c_b:
                idx = ALL_TYPES.index(st.session_state["draft_type"]) if st.session_state["draft_type"] in ALL_TYPES else 0
                p_type = st.selectbox("類別", ALL_TYPES, index=idx)

            budget = st.number_input("金額 ($)", min_value=0, step=1000, value=int(st.session_state["draft_budget"]))
            desc = st.text_area("詳細說明", value=st.session_state["draft_desc"], height=150)

            if st.form_submit_button("🚀 確認發布"):
                ok = add_quest_to_sheet(title.strip(), quote_no.strip(), desc.strip(), p_type, int(budget))
                if ok:
                    st.success(f"已發布: {title}")
                    st.session_state["draft_title"] = ""
                    st.session_state["draft_quote_no"] = ""
                    st.session_state["draft_desc"] = ""
                    st.session_state["draft_budget"] = 0
                    st.session_state["draft_type"] = TYPE_ENG[0]
                    time.sleep(0.3)
                    st.rerun()

    # ------- t2: 驗收審核 -------
    with t2:
        st.subheader("待驗收清單")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        if df.empty:
            st.info("無待審案件")
        else:
            df_p = df[df["status"] == "Pending"]
            if df_p.empty:
                st.info("無待審案件")
            else:
                for _, r in df_p.iterrows():
                    qn = r.get("quote_no", "")
                    qn_badge = f"<span class='pill'>估價單號：{qn}</span>" if qn and qn != "nan" else ""
                    with st.expander(f"待審: {r['title']} ({r['hunter_id']})"):
                        st.markdown(qn_badge, unsafe_allow_html=True)
                        st.write(f"金額: ${int(r['points']):,}")
                        st.write(f"說明: {r['description']}")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ 通過", key=f"ok_{r['id']}"):
                            update_quest_status(r["id"], "Done")
                            st.rerun()
                        if c2.button("❌ 退回", key=f"no_{r['id']}"):
                            update_quest_status(r["id"], "Active")
                            st.rerun()

    # ------- t3: 數據總表 -------
    with t3:
        st.subheader("📊 數據總表")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        if df.empty:
            st.warning("quests 讀不到資料（請確認工作表名稱為 quests 且表頭在第 1 列）")
        else:
            st.dataframe(df, use_container_width=True)


# ============================================================
# 8) Hunter View（含：我的任務顯示金額 + 估價單號）
# ============================================================
def hunter_view():
    me = st.session_state["user_name"]
    df = ensure_quests_schema(get_data(QUEST_SHEET))

    my_total = calc_my_total(df, me)
    busy = is_me_busy(df, me)

    st.title(f"🚀 工作台: {me}")
    c_m1, c_m2 = st.columns([2, 1])

    with c_m1:
        st.metric("💰 本月實拿業績", f"${int(my_total):,}")

    with c_m2:
        if busy:
            st.error("🚫 任務進行中")
        else:
            st.success("✅ 狀態閒置")

    st.divider()

    tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])

    with tab_eng:
        df_eng = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_ENG))]
        if df_eng.empty:
            st.info("無標案")
        else:
            st.caption("🔥 工程競標區")
            for _, row in df_eng.iterrows():
                qn = row.get("quote_no", "")
                qn_line = f"<span class='pill'>估價單號：{qn}</span>" if qn and qn != "nan" else ""
                st.markdown(
                    f"""
<div class="project-card">
  <h3>📄 {row['title']}</h3>
  <p style="color:#aaa;">{qn_line} <span class='pill'>類別：{row['rank']}</span> <span class='pill'>金額：${int(row['points']):,}</span></p>
  <p>{row['description']}</p>
</div>
""",
                    unsafe_allow_html=True,
                )

                # 忙碌時禁止接單
                if st.button("⚡ 投標", key=f"be_{row['id']}", use_container_width=True, disabled=busy):
                    ok = update_quest_status(row["id"], "Active", me, [])
                    if ok:
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("投標失敗（資料列定位或寫入異常）")

    with tab_maint:
        df_maint = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_MAINT))]
        if df_maint.empty:
            st.info("無維修單")
        else:
            st.caption("⚡ 快速搶修區")
            for _, row in df_maint.iterrows():
                urgent_html = '<span class="urgent-tag">🔥URGENT</span>' if row["rank"] == "緊急搶修" else ""
                qn = row.get("quote_no", "")
                qn_line = f"<span class='pill'>估價單號：{qn}</span>" if qn and qn != "nan" else ""
                st.markdown(
                    f"""
<div class="ticket-card">
  <div style="display:flex; justify-content:space-between;">
    <strong>🔧 {row['title']} {urgent_html}</strong>
    <span style="color:#00AAFF; font-weight:bold;">${int(row['points']):,}</span>
  </div>
  <div style="margin:6px 0;">{qn_line} <span class='pill'>類別：{row['rank']}</span></div>
  <div style="font-size:0.9em; color:#ccc;">{row['description']}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

                if st.button("✋ 我來處理", key=f"bm_{row['id']}", disabled=busy):
                    ok = update_quest_status(row["id"], "Active", me, [])
                    if ok:
                        st.toast(f"已接下：{row['title']}")
                        st.rerun()
                    else:
                        st.error("接單失敗（資料列定位或寫入異常）")

    with tab_my:
        def is_mine(r: pd.Series) -> bool:
            partners = [p for p in str(r["partner_id"]).split(",") if p]
            return str(r["hunter_id"]) == me or me in partners

        df_my = df[df.apply(is_mine, axis=1)]
        df_my = df_my[df_my["status"].isin(["Active", "Pending"])]

        if df_my.empty:
            st.info("目前無任務")
        else:
            for _, row in df_my.iterrows():
                amount = int(row.get("points", 0))
                qn = row.get("quote_no", "")
                with st.expander(f"進行中: {row['title']} ({row['status']})"):
                    if qn and qn != "nan":
                        st.markdown(f"**估價單號：{qn}**")
                    st.markdown(f"**金額：${amount:,}（完工依此金額收費）**")
                    st.write(f"說明：{row['description']}")

                    if row["status"] == "Active" and str(row["hunter_id"]) == me:
                        if st.button("📩 完工回報 (解除鎖定)", key=f"sub_{row['id']}"):
                            update_quest_status(row["id"], "Pending")
                            st.rerun()
                    elif row["status"] == "Pending":
                        st.warning("✅ 已回報，等待主管審核中")


# ============================================================
# 9) Main
# ============================================================
def main():
    if "user_role" not in st.session_state:
        login_screen()
        return

    sidebar()

    if st.session_state["user_role"] == "Admin":
        admin_view()
    else:
        hunter_view()


main()
