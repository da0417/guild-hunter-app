# app.py
import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from typing import Any, Dict, List, Optional, Tuple

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
# 0) Streamlit 設定
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
# 1) 常數 / 類別
# ============================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "guild_system_db"

TYPE_ENG = ["消防工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

ADMIN_ACCESS_KEY_SECRET_NAME = "ADMIN_ACCESS_KEY"  # 建議放在 st.secrets，避免寫死

QUEST_SHEET = "quests"
EMP_SHEET = "employees"

# quests 欄位（與你的 sheet 欄位對齊）
# id,title,description,rank,points,status,hunter_id,created_at,partner_id
QUEST_COLS = ["id", "title", "description", "rank", "points", "status", "hunter_id", "created_at", "partner_id"]


@dataclass(frozen=True)
class Quest:
    id: str
    title: str
    description: str
    rank: str
    points: int
    status: str
    hunter_id: str
    created_at: str
    partner_id: str


# ============================================================
# 2) 安全：密碼雜湊（相容舊資料：明碼仍可登入）
# ============================================================
def _hash_password_pbkdf2(password: str, salt_b64: str, rounds: int = 120_000) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return base64.b64encode(dk).decode("utf-8")


def verify_password(input_pwd: str, stored: str) -> bool:
    """
    stored 支援兩種格式：
    1) 舊版：明碼 "1234"
    2) 新版： "pbkdf2$<rounds>$<salt_b64>$<hash_b64>"
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

    # 舊版相容：明碼比對
    return compare_digest(input_pwd, stored)


# ============================================================
# 3) Google Sheet 存取層（集中化、快取、批次更新）
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


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@st.cache_data(ttl=10)  # 10秒內重複讀取同一張表直接用快取，減少 API 次數
def get_data(worksheet_name: str) -> pd.DataFrame:
    sheet = connect_db()
    if not sheet:
        return pd.DataFrame()

    try:
        ws = sheet.worksheet(worksheet_name)
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)

        # 資料型態統一（避免後續 split / 比對出錯）
        for c in ["id", "password", "partner_id", "hunter_id", "rank", "status", "title"]:
            if c in df.columns:
                df[c] = df[c].astype(str)

        if "points" in df.columns:
            df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

        return df
    except Exception:
        return pd.DataFrame()


def invalidate_cache() -> None:
    # Streamlit cache_data 清除：確保寫入後能立即刷新
    get_data.clear()  # type: ignore


def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    # 補欄位，避免某些 row 少欄時 UI 崩掉
    for c in QUEST_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[QUEST_COLS]


def add_quest_to_sheet(title: str, desc: str, category: str, points: int) -> bool:
    sheet = connect_db()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        q_id = str(int(time.time()))
        ws.append_row(
            [q_id, title, desc, category, int(points), "Open", "", _now_str(), ""],
            value_input_option="USER_ENTERED",
        )
        invalidate_cache()
        return True
    except Exception as e:
        st.error(f"❌ 新增任務失敗: {e}")
        return False


@st.cache_data(ttl=10)
def quest_id_to_row_map() -> Dict[str, int]:
    """
    建立 quest_id -> row_num 的映射，避免 worksheet.find() 每次都掃描整張表（慢且耗 API）。
    假設 quests 第一列是標題列，資料從第2列開始，且第一欄是 id。
    """
    sheet = connect_db()
    if not sheet:
        return {}

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        values = ws.col_values(1)  # A欄 id（含標題列）
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


def update_quest_status(quest_id: str, new_status: str, hunter_id: Optional[str] = None, partner_list: Optional[List[str]] = None) -> bool:
    sheet = connect_db()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        mapping = quest_id_to_row_map()
        row_num = mapping.get(str(quest_id))
        if not row_num:
            return False

        # 批次更新：一次送出，避免連續 update_cell 造成慢與 API quota 風險
        updates = []
        # 欄位位置：依你的 append_row 順序：1 id,2 title,3 desc,4 rank,5 points,6 status,7 hunter_id,8 created_at,9 partner_id
        updates.append({"range": f"F{row_num}", "values": [[new_status]]})

        if hunter_id is not None:
            updates.append({"range": f"G{row_num}", "values": [[hunter_id]]})

        if partner_list is not None:
            partner_str = ",".join([p for p in partner_list if p])
            updates.append({"range": f"I{row_num}", "values": [[partner_str]]})
        elif new_status == "Open":
            updates.append({"range": f"I{row_num}", "values": [[""]]})

        ws.batch_update(updates, value_input_option="USER_ENTERED")

        # 清快取：確保 UI 即時看到狀態變更
        invalidate_cache()
        quest_id_to_row_map.clear()  # type: ignore
        return True
    except Exception:
        return False


# ============================================================
# 4) AI 影像解析（強化：JSON 清理、類別硬限制、fallback 規則）
# ============================================================
def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    從模型回覆中抽出第一個 JSON 物件（避免 ```json ... ``` 或多餘文字導致 json.loads 失敗）
    """
    if not text:
        return None

    t = text.strip()
    t = t.replace("```json", "").replace("```", "").strip()

    # 嘗試直接 loads
    try:
        return json.loads(t)
    except Exception:
        pass

    # 嘗試抓第一個 { ... } 區塊
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

    # fallback：明確規則（可驗證）
    # 0元 → 維養類（先用「場勘報價」當缺省）
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

        prompt = f"""
請分析圖片（報價單或報修APP截圖），提取資訊並只輸出「單一 JSON 物件」，不得輸出任何額外文字。
欄位：
- community: 社區名稱（去除編號/代碼前綴）
- project: 工程名稱或報修摘要
- description: 詳細說明
- budget: 總金額（整數；若無則 0）
- category: 僅能從下列清單擇一（不得自創）：
  [{categories_str}]
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

        resp = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=25)
        if resp.status_code != 200:
            return None

        result = resp.json()
        raw_text = result["candidates"][0]["content"]["parts"][0]["text"]
        data = extract_first_json_object(raw_text)
        if not data:
            return None

        comm = str(data.get("community", "")).strip()
        proj = str(data.get("project", "")).strip()

        # 去除社區前綴編號（明確規則）
        if comm:
            comm = re.sub(r"^[A-Za-z0-9]+\s*", "", comm).strip()

        budget = _safe_int(data.get("budget", 0), 0)
        cat = normalize_category(data.get("category", ""), budget)

        # title 組合（固定規則）
        if comm and proj:
            title = f"【{comm}】{proj}"
        else:
            title = proj or comm

        return {
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
# 5) 認證 / 授權
# ============================================================
def get_auth_dict() -> Dict[str, str]:
    df = get_data(EMP_SHEET)
    if df.empty or "name" not in df.columns or "password" not in df.columns:
        return {}
    return dict(zip(df["name"].astype(str), df["password"].astype(str)))


def admin_access_key_ok(input_key: str) -> bool:
    # 原本寫死 "Boss@9988" 風險高：改用 secrets（若沒設仍相容舊值）
    expected = st.secrets.get(ADMIN_ACCESS_KEY_SECRET_NAME, "Boss@9988")
    return compare_digest(str(input_key), str(expected))


# ============================================================
# 6) 業績計算（封裝，避免散落在 UI）
# ============================================================
def calc_my_total(df_quests: pd.DataFrame, me: str) -> int:
    if df_quests.empty:
        return 0

    df = ensure_quests_schema(df_quests)
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

    my_total = 0
    done = df[df["status"] == "Done"]
    for _, r in done.iterrows():
        partners = [p for p in str(r["partner_id"]).split(",") if p]
        team = [str(r["hunter_id"])] + partners
        if me not in team:
            continue

        pts = int(r["points"])
        share = pts // len(team)
        rem = pts % len(team)
        # 明確規則：主接單者拿餘數
        my_total += (share + rem) if me == str(r["hunter_id"]) else share

    return my_total


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
# 7) UI
# ============================================================
def login_screen() -> None:
    st.title("🏢 工程/叫修 發包管理系統")
    st.caption("v10.0 安全/效能/可維護性強化版")

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
                    st.error("Access Key 錯誤")

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


def admin_view() -> None:
    st.title("👨‍💼 發包/派單指揮台")
    t1, t2, t3 = st.tabs(["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"])

    with t1:
        st.subheader("發布新任務")
        uploaded_file = st.file_uploader("📤 上傳 (報價單 / 報修截圖)", type=["png", "jpg", "jpeg"])

        st.session_state.setdefault("draft_title", "")
        st.session_state.setdefault("draft_desc", "")
        st.session_state.setdefault("draft_budget", 0)
        st.session_state.setdefault("draft_type", TYPE_ENG[0])

        if uploaded_file is not None:
            if st.button("✨ 啟動 AI 辨識"):
                with st.spinner("🤖 AI 正在閱讀並歸類..."):
                    ai = analyze_quote_image(uploaded_file)
                    if ai:
                        st.session_state["draft_title"] = ai.get("title", "")
                        st.session_state["draft_desc"] = ai.get("description", "")
                        st.session_state["draft_budget"] = _safe_int(ai.get("budget", 0), 0)
                        st.session_state["draft_type"] = normalize_category(ai.get("category", ""), st.session_state["draft_budget"])

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
            with c_b:
                idx = ALL_TYPES.index(st.session_state["draft_type"]) if st.session_state["draft_type"] in ALL_TYPES else 0
                p_type = st.selectbox("類別", ALL_TYPES, index=idx)

            budget = st.number_input("金額 ($)", min_value=0, step=1000, value=int(st.session_state["draft_budget"]))
            desc = st.text_area("詳細說明", value=st.session_state["draft_desc"], height=150)

            if st.form_submit_button("🚀 確認發布"):
                ok = add_quest_to_sheet(title.strip(), desc.strip(), p_type, int(budget))
                if ok:
                    st.success(f"已發布: {title}")
                    st.session_state["draft_title"] = ""
                    st.session_state["draft_desc"] = ""
                    st.session_state["draft_budget"] = 0
                    st.session_state["draft_type"] = TYPE_ENG[0]
                    time.sleep(0.5)
                    st.rerun()

    with t2:
        st.subheader("待驗收清單")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        if df.empty:
            st.info("無資料")
            return

        df_p = df[df["status"] == "Pending"]
        if df_p.empty:
            st.info("無待審案件")
            return

        for _, r in df_p.iterrows():
            with st.expander(f"待審: {r['title']} ({r['hunter_id']})"):
                st.write(f"金額: ${_safe_int(r['points'],0):,}")
                c1, c2 = st.columns(2)
                if c1.button("✅ 通過", key=f"ok_{r['id']}"):
                    update_quest_status(str(r["id"]), "Done")
                    st.rerun()
                if c2.button("❌ 退回", key=f"no_{r['id']}"):
                    update_quest_status(str(r["id"]), "Active")
                    st.rerun()

    with t3:
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        st.dataframe(df, use_container_width=True)


def hunter_view() -> None:
    me = st.session_state["user_name"]
    df = ensure_quests_schema(get_data(QUEST_SHEET))

    my_total = calc_my_total(df, me)
    busy = is_me_busy(df, me)

    st.title(f"🚀 工作台: {me}")
    c_m1, c_m2 = st.columns([2, 1])
    with c_m1:
        st.metric("💰 本月實拿業績", f"${int(my_total):,}")
    # app.py
import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from typing import Any, Dict, List, Optional, Tuple

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
# 0) Streamlit 設定
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
# 1) 常數 / 類別
# ============================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "guild_system_db"

TYPE_ENG = ["消防工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

ADMIN_ACCESS_KEY_SECRET_NAME = "ADMIN_ACCESS_KEY"  # 建議放在 st.secrets，避免寫死

QUEST_SHEET = "quests"
EMP_SHEET = "employees"

# quests 欄位（與你的 sheet 欄位對齊）
# id,title,description,rank,points,status,hunter_id,created_at,partner_id
QUEST_COLS = ["id", "title", "description", "rank", "points", "status", "hunter_id", "created_at", "partner_id"]


@dataclass(frozen=True)
class Quest:
    id: str
    title: str
    description: str
    rank: str
    points: int
    status: str
    hunter_id: str
    created_at: str
    partner_id: str


# ============================================================
# 2) 安全：密碼雜湊（相容舊資料：明碼仍可登入）
# ============================================================
def _hash_password_pbkdf2(password: str, salt_b64: str, rounds: int = 120_000) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return base64.b64encode(dk).decode("utf-8")


def verify_password(input_pwd: str, stored: str) -> bool:
    """
    stored 支援兩種格式：
    1) 舊版：明碼 "1234"
    2) 新版： "pbkdf2$<rounds>$<salt_b64>$<hash_b64>"
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

    # 舊版相容：明碼比對
    return compare_digest(input_pwd, stored)


# ============================================================
# 3) Google Sheet 存取層（集中化、快取、批次更新）
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


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@st.cache_data(ttl=10)  # 10秒內重複讀取同一張表直接用快取，減少 API 次數
def get_data(worksheet_name: str) -> pd.DataFrame:
    sheet = connect_db()
    if not sheet:
        return pd.DataFrame()

    try:
        ws = sheet.worksheet(worksheet_name)
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)

        # 資料型態統一（避免後續 split / 比對出錯）
        for c in ["id", "password", "partner_id", "hunter_id", "rank", "status", "title"]:
            if c in df.columns:
                df[c] = df[c].astype(str)

        if "points" in df.columns:
            df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

        return df
    except Exception:
        return pd.DataFrame()


def invalidate_cache() -> None:
    # Streamlit cache_data 清除：確保寫入後能立即刷新
    get_data.clear()  # type: ignore


def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    # 補欄位，避免某些 row 少欄時 UI 崩掉
    for c in QUEST_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[QUEST_COLS]


def add_quest_to_sheet(title: str, desc: str, category: str, points: int) -> bool:
    sheet = connect_db()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        q_id = str(int(time.time()))
        ws.append_row(
            [q_id, title, desc, category, int(points), "Open", "", _now_str(), ""],
            value_input_option="USER_ENTERED",
        )
        invalidate_cache()
        return True
    except Exception as e:
        st.error(f"❌ 新增任務失敗: {e}")
        return False


@st.cache_data(ttl=10)
def quest_id_to_row_map() -> Dict[str, int]:
    """
    建立 quest_id -> row_num 的映射，避免 worksheet.find() 每次都掃描整張表（慢且耗 API）。
    假設 quests 第一列是標題列，資料從第2列開始，且第一欄是 id。
    """
    sheet = connect_db()
    if not sheet:
        return {}

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        values = ws.col_values(1)  # A欄 id（含標題列）
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


def update_quest_status(quest_id: str, new_status: str, hunter_id: Optional[str] = None, partner_list: Optional[List[str]] = None) -> bool:
    sheet = connect_db()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        mapping = quest_id_to_row_map()
        row_num = mapping.get(str(quest_id))
        if not row_num:
            return False

        # 批次更新：一次送出，避免連續 update_cell 造成慢與 API quota 風險
        updates = []
        # 欄位位置：依你的 append_row 順序：1 id,2 title,3 desc,4 rank,5 points,6 status,7 hunter_id,8 created_at,9 partner_id
        updates.append({"range": f"F{row_num}", "values": [[new_status]]})

        if hunter_id is not None:
            updates.append({"range": f"G{row_num}", "values": [[hunter_id]]})

        if partner_list is not None:
            partner_str = ",".join([p for p in partner_list if p])
            updates.append({"range": f"I{row_num}", "values": [[partner_str]]})
        elif new_status == "Open":
            updates.append({"range": f"I{row_num}", "values": [[""]]})

        ws.batch_update(updates, value_input_option="USER_ENTERED")

        # 清快取：確保 UI 即時看到狀態變更
        invalidate_cache()
        quest_id_to_row_map.clear()  # type: ignore
        return True
    except Exception:
        return False


# ============================================================
# 4) AI 影像解析（強化：JSON 清理、類別硬限制、fallback 規則）
# ============================================================
def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    從模型回覆中抽出第一個 JSON 物件（避免 ```json ... ``` 或多餘文字導致 json.loads 失敗）
    """
    if not text:
        return None

    t = text.strip()
    t = t.replace("```json", "").replace("```", "").strip()

    # 嘗試直接 loads
    try:
        return json.loads(t)
    except Exception:
        pass

    # 嘗試抓第一個 { ... } 區塊
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

    # fallback：明確規則（可驗證）
    # 0元 → 維養類（先用「場勘報價」當缺省）
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

        prompt = f"""
請分析圖片（報價單或報修APP截圖），提取資訊並只輸出「單一 JSON 物件」，不得輸出任何額外文字。
欄位：
- community: 社區名稱（去除編號/代碼前綴）
- project: 工程名稱或報修摘要
- description: 詳細說明
- budget: 總金額（整數；若無則 0）
- category: 僅能從下列清單擇一（不得自創）：
  [{categories_str}]
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

        resp = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=25)
        if resp.status_code != 200:
            return None

        result = resp.json()
        raw_text = result["candidates"][0]["content"]["parts"][0]["text"]
        data = extract_first_json_object(raw_text)
        if not data:
            return None

        comm = str(data.get("community", "")).strip()
        proj = str(data.get("project", "")).strip()

        # 去除社區前綴編號（明確規則）
        if comm:
            comm = re.sub(r"^[A-Za-z0-9]+\s*", "", comm).strip()

        budget = _safe_int(data.get("budget", 0), 0)
        cat = normalize_category(data.get("category", ""), budget)

        # title 組合（固定規則）
        if comm and proj:
            title = f"【{comm}】{proj}"
        else:
            title = proj or comm

        return {
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
# 5) 認證 / 授權
# ============================================================
def get_auth_dict() -> Dict[str, str]:
    df = get_data(EMP_SHEET)
    if df.empty or "name" not in df.columns or "password" not in df.columns:
        return {}
    return dict(zip(df["name"].astype(str), df["password"].astype(str)))


def admin_access_key_ok(input_key: str) -> bool:
    # 原本寫死 "Boss@9988" 風險高：改用 secrets（若沒設仍相容舊值）
    expected = st.secrets.get(ADMIN_ACCESS_KEY_SECRET_NAME, "Boss@9988")
    return compare_digest(str(input_key), str(expected))


# ============================================================
# 6) 業績計算（封裝，避免散落在 UI）
# ============================================================
def calc_my_total(df_quests: pd.DataFrame, me: str) -> int:
    if df_quests.empty:
        return 0

    df = ensure_quests_schema(df_quests)
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

    my_total = 0
    done = df[df["status"] == "Done"]
    for _, r in done.iterrows():
        partners = [p for p in str(r["partner_id"]).split(",") if p]
        team = [str(r["hunter_id"])] + partners
        if me not in team:
            continue

        pts = int(r["points"])
        share = pts // len(team)
        rem = pts % len(team)
        # 明確規則：主接單者拿餘數
        my_total += (share + rem) if me == str(r["hunter_id"]) else share

    return my_total


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
# 7) UI
# ============================================================
def login_screen() -> None:
    st.title("🏢 工程/叫修 發包管理系統")
    st.caption("v10.0 安全/效能/可維護性強化版")

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
                    st.error("Access Key 錯誤")

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


def admin_view() -> None:
    st.title("👨‍💼 發包/派單指揮台")
    t1, t2, t3 = st.tabs(["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"])

    with t1:
        st.subheader("發布新任務")
        uploaded_file = st.file_uploader("📤 上傳 (報價單 / 報修截圖)", type=["png", "jpg", "jpeg"])

        st.session_state.setdefault("draft_title", "")
        st.session_state.setdefault("draft_desc", "")
        st.session_state.setdefault("draft_budget", 0)
        st.session_state.setdefault("draft_type", TYPE_ENG[0])

        if uploaded_file is not None:
            if st.button("✨ 啟動 AI 辨識"):
                with st.spinner("🤖 AI 正在閱讀並歸類..."):
                    ai = analyze_quote_image(uploaded_file)
                    if ai:
                        st.session_state["draft_title"] = ai.get("title", "")
                        st.session_state["draft_desc"] = ai.get("description", "")
                        st.session_state["draft_budget"] = _safe_int(ai.get("budget", 0), 0)
                        st.session_state["draft_type"] = normalize_category(ai.get("category", ""), st.session_state["draft_budget"])

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
            with c_b:
                idx = ALL_TYPES.index(st.session_state["draft_type"]) if st.session_state["draft_type"] in ALL_TYPES else 0
                p_type = st.selectbox("類別", ALL_TYPES, index=idx)

            budget = st.number_input("金額 ($)", min_value=0, step=1000, value=int(st.session_state["draft_budget"]))
            desc = st.text_area("詳細說明", value=st.session_state["draft_desc"], height=150)

            if st.form_submit_button("🚀 確認發布"):
                ok = add_quest_to_sheet(title.strip(), desc.strip(), p_type, int(budget))
                if ok:
                    st.success(f"已發布: {title}")
                    st.session_state["draft_title"] = ""
                    st.session_state["draft_desc"] = ""
                    st.session_state["draft_budget"] = 0
                    st.session_state["draft_type"] = TYPE_ENG[0]
                    time.sleep(0.5)
                    st.rerun()

    with t2:
        st.subheader("待驗收清單")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        if df.empty:
            st.info("無資料")
            return

        df_p = df[df["status"] == "Pending"]
        if df_p.empty:
            st.info("無待審案件")
            return

        for _, r in df_p.iterrows():
            with st.expander(f"待審: {r['title']} ({r['hunter_id']})"):
                st.write(f"金額: ${_safe_int(r['points'],0):,}")
                c1, c2 = st.columns(2)
                if c1.button("✅ 通過", key=f"ok_{r['id']}"):
                    update_quest_status(str(r["id"]), "Done")
                    st.rerun()
                if c2.button("❌ 退回", key=f"no_{r['id']}"):
                    update_quest_status(str(r["id"]), "Active")
                    st.rerun()

    with t3:
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        st.dataframe(df, use_container_width=True)


def hunter_view() -> None:
    me = st.session_state["user_name"]
    df = ensure_quests_schema(get_data(QUEST_SHEET))

    my_total = calc_my_total(df, me)
    busy = is_me_busy(df, me)

    st.title(f"🚀 工作台: {me}")
    c_m1, c_m2 = st.columns([2, 1])
    with c_m1:
        st.metric("💰 本月實拿業績", f"${int(my_total):,}")
    with c_m2:
        if is_busy:
            status_box.error("🚫 任務進行中")
        else:
            status_box.success("✅ 狀態閒置")

    st.divider()
    tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])

    with tab_eng:
        df_eng = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_ENG))]
        if df_eng.empty:
            st.info("無標案")
        else:
            st.caption("🔥 工程競標區")
            auth = get_auth_dict()
            all_users = list(auth.keys())

            for _, row in df_eng.iterrows():
                st.markdown(
                    f"""
<div class="project-card">
  <h3>📄 {row['title']}</h3>
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
                        if update_quest_status(str(row["id"]), "Active", me, partners):
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
                st.markdown(
                    f"""
<div class="ticket-card">
  <div style="display:flex; justify-content:space-between;">
    <strong>🔧 {row['title']} {urgent_html}</strong>
    <span style="color:#00AAFF; font-weight:bold;">${_safe_int(row['points'],0):,}</span>
  </div>
  <div style="font-size:0.9em; color:#ccc;">{row['description']}</div>
</div>
""",
                    unsafe_allow_html=True,
                )
                col_fast, _ = st.columns([1, 4])
                with col_fast:
                    if st.button("✋ 我來處理", key=f"bm_{row['id']}", disabled=busy):
                        if update_quest_status(str(row["id"]), "Active", me, []):
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
                with st.expander(f"進行中: {row['title']} ({row['status']})"):
                    st.write(f"說明: {row['description']}")
                    if row["status"] == "Active" and str(row["hunter_id"]) == me:
                        if st.button("📩 完工回報 (解除鎖定)", key=f"sub_{row['id']}"):
                            update_quest_status(str(row["id"]), "Pending")
                            st.rerun()
                    elif row["status"] == "Pending":
                        st.warning("✅ 已回報，等待主管審核中")


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

st.divider()
    tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])

    with tab_eng:
        df_eng = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_ENG))]
        if df_eng.empty:
            st.info("無標案")
        else:
            st.caption("🔥 工程競標區")
            auth = get_auth_dict()
            all_users = list(auth.keys())

            for _, row in df_eng.iterrows():
                st.markdown(
                    f"""
<div class="project-card">
  <h3>📄 {row['title']}</h3>
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
                        if update_quest_status(str(row["id"]), "Active", me, partners):
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
                st.markdown(
                    f"""
<div class="ticket-card">
  <div style="display:flex; justify-content:space-between;">
    <strong>🔧 {row['title']} {urgent_html}</strong>
    <span style="color:#00AAFF; font-weight:bold;">${_safe_int(row['points'],0):,}</span>
  </div>
  <div style="font-size:0.9em; color:#ccc;">{row['description']}</div>
</div>
""",
                    unsafe_allow_html=True,
                )
                col_fast, _ = st.columns([1, 4])
                with col_fast:
                    if st.button("✋ 我來處理", key=f"bm_{row['id']}", disabled=busy):
                        if update_quest_status(str(row["id"]), "Active", me, []):
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
                with st.expander(f"進行中: {row['title']} ({row['status']})"):
                    st.write(f"說明: {row['description']}")
                    if row["status"] == "Active" and str(row["hunter_id"]) == me:
                        if st.button("📩 完工回報 (解除鎖定)", key=f"sub_{row['id']}"):
                            update_quest_status(str(row["id"]), "Pending")
                            st.rerun()
                    elif row["status"] == "Pending":
                        st.warning("✅ 已回報，等待主管審核中")


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
