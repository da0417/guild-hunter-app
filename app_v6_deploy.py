# app_v6_deploy.py
import base64
import json
import re
import time
from datetime import datetime
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import gspread
from oauth2client.service_account import ServiceAccountCredentials

try:
    import requests
except ImportError:
    st.error("請在 requirements.txt 加入 requests")
    raise

# ============================================================
# 0) SessionState 防呆（一定要在 set_page_config 前）
# ============================================================
try:
    _ = st.session_state
except Exception:
    st.error("SessionState 異常，請重新整理頁面")
    st.stop()

# ============================================================
# 1) Streamlit 設定
# ============================================================
st.set_page_config(page_title="AI 智慧派工系統", layout="wide", page_icon="🏢")

st.markdown(
    """
<style>
    .ticket-card { border-left: 5px solid #00AAFF !important; background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .project-card { border-left: 5px solid #FF4B4B !important; background-color: #1E1E1E; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #444; }
    .urgent-tag { color: #FF4B4B; font-weight: bold; border: 1px solid #FF4B4B; padding: 2px 5px; border-radius: 4px; font-size: 12px; margin-left: 5px; }
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 2) 常數 / 類別
# ============================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "guild_system_db"

TYPE_ENG = ["消防工程", "機電工程", "住戶宅修"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

ADMIN_ACCESS_KEY_SECRET_NAME = "ADMIN_ACCESS_KEY"  # 建議放 st.secrets；若沒設則用預設值相容
QUEST_SHEET = "quests"
EMP_SHEET = "employees"

# ✅ quests 欄位（你要新增「估價單號 quote_no」）
# Google Sheet 請調整成：
# A:id | B:title | C:quote_no | D:description | E:rank | F:points | G:status | H:hunter_id | I:created_at | J:partner_id
QUEST_COLS = ["id", "title", "quote_no", "description", "rank", "points", "status", "hunter_id", "created_at", "partner_id"]


# ============================================================
# 3) 小工具
# ============================================================

REFRESH_TTL_SECONDS = 15         # 「只在 cache 過期才顯示」的判斷基準（建議 >= get_data ttl）
POLL_INTERVAL_MS = 15000         # 多人在線偵測新任務的輪詢頻率（15 秒）
ENABLE_AUTO_POLL = True          # 若你覺得太頻繁可改 False

# (選配) 多人在線 → 自動輪詢需要 st_autorefresh
try:
    from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False


def _now_ts() -> float:
    return time.time()


def _get_last_refresh_ts(key: str) -> float:
    return float(st.session_state.get(key, 0.0))


def _set_last_refresh_ts(key: str) -> None:
    st.session_state[key] = _now_ts()


@st.cache_data(ttl=5)
def _latest_quest_signature() -> str:
    """
    用於判斷「是否有新任務」的簽章
    - 盡量用 created_at / id 這種會遞增的欄位
    - 避免用整份 df hash（太重）
    """
    df = get_data(QUEST_SHEET)
    if df.empty:
        return "EMPTY"

    # 盡量取最大 created_at，其次用 id
    if "created_at" in df.columns:
        max_created = str(df["created_at"].astype(str).max())
    else:
        max_created = ""

    max_id = str(df["id"].astype(str).max()) if "id" in df.columns else ""
    return f"{max_created}|{max_id}"


def _has_new_quests(sig_key: str) -> bool:
    latest = _latest_quest_signature()
    last_seen = str(st.session_state.get(sig_key, ""))
    if not last_seen:
        # 第一次進來，先記住，不顯示紅點
        st.session_state[sig_key] = latest
        return False
    return latest != last_seen


def _mark_seen(sig_key: str) -> None:
    st.session_state[sig_key] = _latest_quest_signature()


def _inject_refresh_button_css() -> None:
    st.markdown(
        """
        <style>
        .rect-refresh-btn button {
            width: 100%;
            height: 46px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 700;
            background: linear-gradient(90deg, #2c7be5, #1f5fbf);
            color: white;
            border: none;
        }
        .rect-refresh-btn button:hover {
            background: linear-gradient(90deg, #1f5fbf, #174a96);
        }
        .refresh-badge {
            display:inline-block;
            margin-left:8px;
            width:10px; height:10px;
            border-radius:999px;
            background:#ff3b30;
            box-shadow: 0 0 10px rgba(255,59,48,0.9);
            animation: pulse 1.2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.35); opacity: 0.65; }
            100% { transform: scale(1); opacity: 1; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_refresh_widget(
    *,
    label: str,
    refresh_ts_key: str,
    sig_key: str,
    tab_state_key: str,
    pick_tab_fn,  # callable: () -> str
) -> None:
    """
    需求涵蓋：
    1) 更新時 loading / 閃爍動畫 / loading 條
    2) 只在 cache 過期才顯示「需要更新」
    3) 更新後自動跳到有新任務的 tab（靠 tab_state_key + pick_tab_fn）
    4) 多人同時在線 → 顯示「有新任務」紅點（輪詢 + signature）
    """
    _inject_refresh_button_css()

    # (4) 多人在線：若可用 autorefresh 就定時 rerun 以便更新紅點狀態
    if ENABLE_AUTO_POLL and HAS_AUTOREFRESH:
        st_autorefresh(interval=POLL_INTERVAL_MS, key=f"auto_poll_{sig_key}")

    last_refresh = _get_last_refresh_ts(refresh_ts_key)
    stale = (_now_ts() - last_refresh) >= REFRESH_TTL_SECONDS if last_refresh > 0 else True
    has_new = _has_new_quests(sig_key)

    # (2) 只在 cache 過期才顯示：但若「有新任務」也要顯示（不然你看不到紅點）
    should_show = stale or has_new

    # 左上角區塊
    col_btn, col_sp = st.columns([2, 10])

    with col_btn:
        if not should_show:
            # 不顯示按鈕時，用一行小字提示已同步（可刪）
            st.caption("✅ 已是最新")
            return

        badge = '<span class="refresh-badge"></span>' if has_new else ""
        st.markdown('<div class="rect-refresh-btn">', unsafe_allow_html=True)

        # Streamlit 的 button 不能直接塞 HTML badge，因此用 label + badge 顯示在旁邊：用 markdown 補一行
        clicked = st.button(label, use_container_width=True)
        if has_new:
            st.markdown(f"<div style='margin-top:-8px; text-align:center;'>{badge}</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        if clicked:
            # (1) loading / 閃爍 / loading 條
            with st.spinner("同步中…"):
                p = st.progress(0)
                for i in range(1, 6):
                    time.sleep(0.08)
                    p.progress(i * 20)

                invalidate_cache()
                # 更新後把「新任務」視為已讀
                _mark_seen(sig_key)
                _set_last_refresh_ts(refresh_ts_key)

                # (3) 更新後自動跳到有新任務的 tab
                st.session_state[tab_state_key] = pick_tab_fn()

            st.toast("✅ 已同步最新任務")
            st.rerun()


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_quote_no(x: Any) -> str:
    s = str(x or "").strip()
    s = s.replace(" ", "").replace("－", "-").replace("—", "-")
    return s


def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    for c in QUEST_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[QUEST_COLS]

def render_refresh_button(label: str = "🔄 更新任務") -> None:
    st.markdown(
        """
        <style>
        .rect-refresh-btn button {
            width: 100%;
            height: 44px;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            background: linear-gradient(90deg, #2c7be5, #1f5fbf);
            color: white;
            border: none;
        }
        .rect-refresh-btn button:hover {
            background: linear-gradient(90deg, #1f5fbf, #174a96);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_btn, col_sp = st.columns([2, 10])
    with col_btn:
        st.markdown('<div class="rect-refresh-btn">', unsafe_allow_html=True)
        if st.button(label):
            invalidate_cache()
            st.toast("✅ 已同步最新任務")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# 4) Google Sheet 存取層（集中化、快取、批次更新）
# ============================================================
@st.cache_resource
def connect_db() -> Optional[gspread.Spreadsheet]:
    try:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME)
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {e}")
        return None


@st.cache_data(ttl=2)
def get_data(worksheet_name: str) -> pd.DataFrame:
    sheet = connect_db()
    if not sheet:
        return pd.DataFrame()
    try:
        ws = sheet.worksheet(worksheet_name)
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)

        for c in ["id", "password", "partner_id", "hunter_id", "rank", "status", "title", "name", "quote_no"]:
            if c in df.columns:
                df[c] = df[c].astype(str)

        if "points" in df.columns:
            df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

        return df
    except Exception:
        return pd.DataFrame()


def invalidate_cache() -> None:
    get_data.clear()  # type: ignore
    quest_id_to_row_map.clear()  # type: ignore


@st.cache_data(ttl=10)
def quest_id_to_row_map() -> Dict[str, int]:
    """
    A欄 id -> row index
    假設第1列為標題列，資料從第2列開始。
    """
    sheet = connect_db()
    if not sheet:
        return {}
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        values = ws.col_values(1)  # A 欄（含標題列）
        mapping: Dict[str, int] = {}
        for idx, v in enumerate(values, start=1):
            v = str(v).strip()
            if idx == 1:
                continue
            if v:
                mapping[v] = idx
        return mapping
    except Exception:
        return {}


def add_quest_to_sheet(title: str, quote_no: str, desc: str, category: str, points: int) -> bool:
    """
    ✅ 寫入 quests（含 quote_no）
    A:id | B:title | C:quote_no | D:description | E:rank | F:points | G:status | H:hunter_id | I:created_at | J:partner_id
    """
    sheet = connect_db()
    if not sheet:
        return False
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        q_id = str(int(time.time()))
        quote_no = _normalize_quote_no(quote_no)

        ws.append_row(
            [q_id, title, quote_no, desc, category, int(points), "Open", "", _now_str(), ""],
            value_input_option="USER_ENTERED",
        )
        invalidate_cache()
        return True
    except Exception as e:
        st.error(f"❌ 新增任務失敗: {e}")
        return False


def update_quest_status(
    quest_id: str,
    new_status: str,
    hunter_id: Optional[str] = None,
    partner_list: Optional[List[str]] = None,
) -> bool:
    """
    ✅ 依新欄位位置更新：
    G=status, H=hunter_id, J=partner_id
    """
    sheet = connect_db()
    if not sheet:
        return False
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        mapping = quest_id_to_row_map()
        row_num = mapping.get(str(quest_id))
        if not row_num:
            return False

        updates = [{"range": f"G{row_num}", "values": [[new_status]]}]  # status

        if hunter_id is not None:
            updates.append({"range": f"H{row_num}", "values": [[hunter_id]]})  # hunter_id

        if partner_list is not None:
            partner_str = ",".join([p for p in partner_list if p])
            updates.append({"range": f"J{row_num}", "values": [[partner_str]]})  # partner_id
        elif new_status == "Open":
            updates.append({"range": f"J{row_num}", "values": [[""]]})

        ws.batch_update(updates, value_input_option="USER_ENTERED")

        invalidate_cache()
        return True
    except Exception:
        return False


# ============================================================
# 5) 密碼驗證（相容舊明碼；支援 PBKDF2）
# ============================================================
def _hash_password_pbkdf2(password: str, salt_b64: str, rounds: int = 120_000) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return base64.b64encode(dk).decode("utf-8")


def verify_password(input_pwd: str, stored: str) -> bool:
    """
    stored 支援：
    - 明碼： "1234"
    - pbkdf2： "pbkdf2$<rounds>$<salt_b64>$<hash_b64>"
    """
    if not isinstance(stored, str):
        return False

    if stored.startswith("pbkdf2$"):
        try:
            _, rounds, salt_b64, hash_b64 = stored.split("$", 3)
            calc = _hash_password_pbkdf2(input_pwd, salt_b64, rounds=int(rounds))
            return compare_digest(calc, hash_b64)
        except Exception:
            return False

    return compare_digest(str(input_pwd), str(stored))


def admin_access_key_ok(input_key: str) -> bool:
    expected = st.secrets.get(ADMIN_ACCESS_KEY_SECRET_NAME, "Boss@9988")
    return compare_digest(str(input_key), str(expected))


def get_auth_dict() -> Dict[str, str]:
    df = get_data(EMP_SHEET)
    if df.empty or "name" not in df.columns or "password" not in df.columns:
        return {}
    return dict(zip(df["name"].astype(str), df["password"].astype(str)))


# ============================================================
# 6) AI 影像解析（新增：估價單號 quote_no）
# ============================================================
def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
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


def normalize_category(cat: str, budget: int) -> str:
    cat = str(cat).strip()
    if cat in ALL_TYPES:
        return cat
    if budget == 0:
        return "場勘報價"
    return TYPE_ENG[0]


def analyze_quote_image(image_file) -> Optional[Dict[str, Any]]:
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

        # ✅ 加入 quote_no 要求
        prompt = f"""
請分析圖片（估價單/報價單或報修APP截圖），提取資訊並只輸出「單一 JSON 物件」，不得輸出任何額外文字。
欄位：
- quote_no: 估價單號（例如 A1412290028-1；找不到就輸出空字串 ""）
- community: 社區名稱（去除編號/代碼前綴）
- project: 工程名稱或報修摘要
- description: 詳細說明
- budget: 總金額（整數；若無則 0）
- category: 僅能從下列清單擇一（不得自創）：[{categories_str}]
- is_urgent: true/false
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
        data = extract_first_json_object(raw_text)
        if not data:
            return None

        comm = str(data.get("community", "")).strip()
        proj = str(data.get("project", "")).strip()

        if comm:
            comm = re.sub(r"^[A-Za-z0-9]+\s*", "", comm).strip()

        budget = _safe_int(data.get("budget", 0), 0)
        cat = normalize_category(data.get("category", ""), budget)
        quote_no = _normalize_quote_no(data.get("quote_no", ""))

        if comm and proj:
            title = f"【{comm}】{proj}"
        else:
            title = proj or comm

        return {
            "quote_no": quote_no,
            "community": comm,
            "project": proj,
            "description": str(data.get("description", "")).strip(),
            "budget": budget,
            "category": cat,
            "is_urgent": bool(data.get("is_urgent", False)),
            "title": title,
        }
    except Exception:
        return None


# ============================================================
# 7) 業績計算 / 忙碌鎖定
# ============================================================
def calc_my_total(df_quests: pd.DataFrame, me: str) -> int:
    if df_quests.empty:
        return 0

    df = ensure_quests_schema(df_quests)
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

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


def my_team_label(me: str) -> str:
    if me in TEAM_ENG_1:
        return "🏗️ 工程 1 組"
    if me in TEAM_ENG_2:
        return "🏗️ 工程 2 組"
    if me in TEAM_MAINT_1:
        return "🔧 維養 1 組"
    return "未分組"


# ============================================================
# 8) UI：登入 / 側欄
# ============================================================
def login_screen() -> None:
    st.title("🏢 工程/叫修 發包管理系統")
    st.caption("v9.4 類別精準版（新增：估價單號）")

    c1, c2 = st.columns(2)

    with c1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管入口")
            key = st.text_input("Access Key", type="password")
            if st.button("🚀 進入指揮台"):
                if admin_access_key_ok(key):
                    st.session_state["user_role"] = "Admin"
                    st.session_state["user_name"] = "Admin"
                    st.rerun()
                else:
                    st.error("密碼錯誤")

    with c2:
        with st.container(border=True):
            st.subheader("👷 同仁入口")
            auth = get_auth_dict()
            if not auth:
                st.warning("employees 表缺少 name/password 或尚無資料")
                return

            name = st.selectbox("姓名", list(auth.keys()))
            pwd = st.text_input("密碼", type="password")

            if st.button("⚡ 上工"):
                stored = auth.get(name, "")
                if verify_password(pwd, stored):
                    st.session_state["user_role"] = "Hunter"
                    st.session_state["user_name"] = name
                    st.rerun()
                else:
                    st.error("密碼錯誤")


def sidebar() -> None:
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
# 9) Admin View（需求 1：案件名稱下方增加「估價單號」）
# ============================================================
def admin_view() -> None:
    # --- 更新後要跳哪個 tab（依最新資料判斷） ---
    def pick_admin_tab() -> str:
        dfq = ensure_quests_schema(get_data(QUEST_SHEET))
        pending = dfq[dfq["status"] == "Pending"]
        if not pending.empty:
            return "🔍 驗收審核"
        return "📷 AI 快速派單"

    # ✅ 共用更新元件（Admin）
    render_refresh_widget(
        label="🔄 更新發包",
        refresh_ts_key="admin_last_refresh_ts",
        sig_key="admin_last_seen_sig",
        tab_state_key="admin_active_tab",
        pick_tab_fn=pick_admin_tab,
    )

    st.title("👨‍💼 發包/派單指揮台")

    # ✅ 可控 tab：用 radio 取代 st.tabs
    tab_state_key = "admin_active_tab"
    tabs = ["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"]
    default_tab = st.session_state.get(tab_state_key, tabs[0])

    active_tab = st.radio(
        "admin_tab",
        tabs,
        index=tabs.index(default_tab) if default_tab in tabs else 0,
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state[tab_state_key] = active_tab

    # ----------------------------
    # 📷 AI 快速派單
    # ----------------------------
    if active_tab == "📷 AI 快速派單":
        st.subheader("發布新任務")
        uploaded_file = st.file_uploader("📤 上傳 (報價單 / 報修截圖)", type=["png", "jpg", "jpeg"])

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
                        st.session_state["draft_budget"] = _safe_int(ai.get("budget", 0), 0)
                        st.session_state["draft_type"] = normalize_category(
                            ai.get("category", ""), st.session_state["draft_budget"]
                        )
                        st.toast("✅ 辨識成功！", icon="🤖")
                    else:
                        st.error("AI 辨識失敗（JSON 解析或 API 回覆異常）")

        with st.form("new_task"):
            c_a, c_b = st.columns([2, 1])
            with c_a:
                title = st.text_input("案件名稱", value=st.session_state["draft_title"])
                quote_no = st.text_input("估價單號", value=st.session_state["draft_quote_no"])
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

    # ----------------------------
    # 🔍 驗收審核
    # ----------------------------
    elif active_tab == "🔍 驗收審核":
        st.subheader("待驗收清單")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        if df.empty:
            st.info("無待審案件")
            return

        df_p = df[df["status"] == "Pending"]
        if df_p.empty:
            st.info("無待審案件")
            return

        for _, r in df_p.iterrows():
            with st.expander(f"待審: {r['title']} ({r['hunter_id']})"):
                qn = str(r.get("quote_no", "")).strip()
                if qn:
                    st.write(f"估價單號: {qn}")
                st.write(f"金額: ${_safe_int(r['points'],0):,}")
                c1, c2 = st.columns(2)
                if c1.button("✅ 通過", key=f"ok_{r['id']}"):
                    update_quest_status(str(r["id"]), "Done")
                    st.rerun()
                if c2.button("❌ 退回", key=f"no_{r['id']}"):
                    update_quest_status(str(r["id"]), "Active")
                    st.rerun()

    # ----------------------------
    # 📊 數據總表
    # ----------------------------
    else:
        st.subheader("📊 數據總表")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        st.dataframe(df, use_container_width=True)



# ============================================================
# 10) Hunter View（保留原功能；我的任務顯示金額+估價單號）
# ============================================================
def hunter_view() -> None:
    me = st.session_state["user_name"]

    # ✅ 讓工作台立刻看到主管新發包：強制刷新快取
    render_refresh_button("🔄 更新任務")

    # ✅ 第一次進入工作台也先清一次（避免剛登入就吃到舊快取）
    st.session_state.setdefault("_hunter_loaded_once", False)
    if not st.session_state["_hunter_loaded_once"]:
        st.session_state["_hunter_loaded_once"] = True
        invalidate_cache()

    df = ensure_quests_schema(get_data(QUEST_SHEET))

    my_total = calc_my_total(df, me)
    busy = is_me_busy(df, me)
    # ============================================================
    # ✅ 超振奮版：進度條 + 等級徽章 + 全寬橫幅 + 達標 streak + 單次動畫
    # 放在：my_total / busy 計算後、st.title(...) 前
    # ============================================================
    TARGET = 250_000
    total = int(my_total)

    # --- streak：每次達標時 +1；未達標時歸零 ---
    st.session_state.setdefault("streak", 0)
    st.session_state.setdefault("prev_hit", False)
    hit = total >= TARGET
    if hit and not st.session_state["prev_hit"]:
        st.session_state["streak"] += 1
    elif not hit:
        st.session_state["streak"] = 0
    st.session_state["prev_hit"] = hit

    # --- 等級徽章（可自行調整門檻） ---
    tiers = [
        ("🟦 新手", 0, "尚未達標"),
        ("🟩 進階", 100_000, "節奏上來了"),
        ("🟨 菁英", 250_000, "達標！"),
        ("🟧 傳奇", 400_000, "超標強者"),
        ("🟥 神話", 600_000, "封神等級"),
    ]
    tier_name, tier_min, tier_desc = tiers[0]
    for name, mn, desc in tiers:
        if total >= mn:
            tier_name, tier_min, tier_desc = name, mn, desc

    # --- 進度條（0~100） ---
    progress = min(1.0, total / TARGET) if TARGET > 0 else 1.0
    progress_pct = int(round(progress * 100))

    # --- 達標只噴一次動畫（避免每次 rerun 都噴） ---
    st.session_state.setdefault("target_fx_fired", False)
    if hit and not st.session_state["target_fx_fired"]:
        st.session_state["target_fx_fired"] = True
        st.balloons()  # 也可改成 st.snow()
    if not hit:
        st.session_state["target_fx_fired"] = False

    # --- UI：全寬橫幅 + 閃爍/掃光動畫 + 徽章 + streak ---
    st.markdown(
        """
    <style>
    @keyframes bannerGlow {
      0% { filter: drop-shadow(0 0 0 rgba(0,0,0,0)); transform: translateY(0); }
      50% { filter: drop-shadow(0 0 24px rgba(0,255,180,.35)); transform: translateY(-2px); }
      100% { filter: drop-shadow(0 0 0 rgba(0,0,0,0)); transform: translateY(0); }
    }
    @keyframes sweep {
      0% { background-position: -200% 0; }
      100% { background-position: 200% 0; }
    }
    .kpi-hero{
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 18px;
      padding: 16px 18px;
      margin: 8px 0 16px 0;
      background: rgba(255,255,255,.04);
    }
    .kpi-hero.hit{
      background: linear-gradient(90deg, rgba(0,255,180,.14), rgba(255,210,77,.10), rgba(0,255,180,.14));
      background-size: 200% 100%;
      animation: sweep 3.0s linear infinite, bannerGlow 2.0s ease-in-out infinite;
    }
    .kpi-row{
      display:flex; gap:14px; align-items:flex-start; justify-content:space-between; flex-wrap:wrap;
    }
    .kpi-left{ min-width: 320px; flex: 2; }
    .kpi-right{ min-width: 240px; flex: 1; text-align:right; }
    .kpi-title{
      font-size: 22px; font-weight: 900; letter-spacing:.4px;
    }
    .kpi-sub{
      margin-top: 6px; color: rgba(255,255,255,.75); font-size: 13px;
    }
    .pill{
      display:inline-flex; align-items:center; gap:8px;
      padding: 8px 10px; border-radius: 999px;
      border: 1px solid rgba(255,255,255,.14);
      background: rgba(0,0,0,.25);
      font-weight: 800;
    }
    .pill small{
      font-weight: 700; color: rgba(255,255,255,.7);
    }
    .streak{
      margin-top: 10px;
      display:inline-flex; align-items:center; gap:10px;
      padding: 8px 10px; border-radius: 12px;
      border: 1px dashed rgba(255,255,255,.18);
      background: rgba(255,255,255,.03);
    }
    .streak b{ font-size: 16px; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    hero_class = "kpi-hero hit" if hit else "kpi-hero"
    title_text = "🏆 本月達標成就解鎖" if hit else "🎯 本月目標進度"
    streak_text = f"🔥 連續達標 Streak：<b>{st.session_state['streak']}</b>" if hit else "📌 達標後將開始累積 streak"

    st.markdown(
        f"""
    <div class="{hero_class}">
      <div class="kpi-row">
        <div class="kpi-left">
          <div class="kpi-title">{title_text}</div>
          <div class="kpi-sub">
            實拿業績：<b>${total:,}</b> ／ 目標：<b>${TARGET:,}</b>（{progress_pct}%）
          </div>
        </div>
        <div class="kpi-right">
          <span class="pill">🏅 等級：{tier_name} <small>｜{tier_desc}</small></span>
          <div class="streak">{streak_text}</div>
        </div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # Streamlit 原生進度條（穩定）
    st.progress(progress)

    # 額外：未達標提示（可關掉）
    if not hit:
        gap = max(0, TARGET - total)
        st.info(f"距離達標還差：${gap:,}（達標後會啟動榮耀橫幅 + 動畫 + streak）")
    else:
        st.success("達標狀態已啟動：橫幅掃光 + 榮耀徽章 + streak 計數")


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


    tab_state_key = "hunter_active_tab"
    tabs = ["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"]
    default_tab = st.session_state.get(tab_state_key, tabs[0]

    active_tab = st.radio(
        "hunter_tab",
        tabs,
        index=tabs.index(default_tab) if default_tab in tabs else 0,
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state[tab_state_key] = active_tab

    if active_tab == "🏗️ 工程標案":
        ...  # 原本 tab_eng 的內容
    elif active_tab == "🔧 維修派單":
        ...  # 原本 tab_maint 的內容
    else:
        ...  # 原本 tab_my 的內容
    )

    
<div class="project-card">
  <h3>📄 {row['title']}</h3>
  {qn_line}
  <p style="color:#aaa;">類別: {row['rank']} | 預算: <span style="color:#0f0; font-size:1.2em;">${_safe_int(row['points'],0):,}</span></p>
  <p>{row['description']}</p>
</div>
""",
                    unsafe_allow_html=True,
                )

                c1, c2 = st.columns([3, 1])
                with c1:
                    partners = st.multiselect(
                        "🤝 找隊友",
                        [u for u in all_users if u != me],
                        max_selections=3,
                        key=f"pe_{row['id']}",
                        disabled=busy,
                    )
                with c2:
                    st.write("")
                    if st.button("⚡ 投標", key=f"be_{row['id']}", use_container_width=True, disabled=busy):
                        ok = update_quest_status(str(row["id"]), "Active", me, partners)
                        if ok:
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("投標失敗（資料列定位或寫入異常）")

   
<div class="ticket-card">
  <div style="display:flex; justify-content:space-between;">
    <strong>🔧 {row['title']} {urgent_html}</strong>
    <span style="color:#00AAFF; font-weight:bold;">${_safe_int(row['points'],0):,}</span>
  </div>
  {qn_line}
  <div style="font-size:0.9em; color:#ccc;">{row['description']}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

                col_fast, _ = st.columns([1, 4])
                with col_fast:
                    if st.button("✋ 我來處理", key=f"bm_{row['id']}", disabled=busy):
                        ok = update_quest_status(str(row["id"]), "Active", me, [])
                        if ok:
                            st.toast(f"已接下：{row['title']}")
                            st.rerun()
                        else:
                            st.error("接單失敗（資料列定位或寫入異常）")

   

                   


# ============================================================
# 11) main
# ============================================================
def main() -> None:
    if "user_role" not in st.session_state:
        login_screen()
        return

    sidebar()

    if st.session_state["user_role"] == "Admin":
        admin_view()
    else:
        hunter_view()


main()
