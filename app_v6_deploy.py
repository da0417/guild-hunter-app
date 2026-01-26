# -*- coding: utf-8 -*-
# app_v6_deploy.py

import uuid
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

TYPE_ENG = ["消防工程", "機電工程", "住戶宅修"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

TEAM_ENG_1 = ["譚學峰", "邱顯杰"]
TEAM_ENG_2 = ["古孟平", "李名傑"]
TEAM_MAINT_1 = ["陳緯民", "李宇傑"]

ADMIN_ACCESS_KEY_SECRET_NAME = "ADMIN_ACCESS_KEY"
QUEST_SHEET = "quests"
EMP_SHEET = "employees"

# quests 欄位（需與你的 Google Sheet 表頭一致）
# 建議表頭：id,title,quote_no,description,rank,points,status,hunter_id,created_at,partner_id
QUEST_COLS = [
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

# ============================================================
# 2) 小工具
# ============================================================
def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_quote_no(s: str) -> str:
    s = str(s or "").strip()
    s = s.replace("：", ":")
    s = re.sub(r"\s+", "", s)
    s = s.replace("估價單號:", "").replace("估價單號", "")
    return s.strip("-_#：: ").strip()


def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    for c in QUEST_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[QUEST_COLS]


# ---- 共用更新元件（loading/過期才顯示/跳tab/多人紅點） ----
REFRESH_TTL_SECONDS = 15
POLL_INTERVAL_MS = 15000
ENABLE_AUTO_POLL = True

try:
    from streamlit_autorefresh import st_autorefresh  # requirements: streamlit-autorefresh

    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False


def _now_ts() -> float:
    return time.time()


def _get_last_refresh_ts(key: str) -> float:
    return float(st.session_state.get(key, 0.0))


def _set_last_refresh_ts(key: str) -> None:
    st.session_state[key] = _now_ts()


def _inject_refresh_button_css() -> None:
    st.markdown(
        """
<style>
.rect-refresh-btn button{
  width:100%;
  height:46px;
  border-radius:8px;
  font-size:16px;
  font-weight:800;
  background:linear-gradient(90deg,#2c7be5,#1f5fbf);
  color:#fff;
  border:none;
}
.rect-refresh-btn button:hover{
  background:linear-gradient(90deg,#1f5fbf,#174a96);
}
.refresh-badge{
  display:inline-block;
  margin-left:8px;
  width:10px; height:10px;
  border-radius:999px;
  background:#ff3b30;
  box-shadow:0 0 10px rgba(255,59,48,.9);
  animation:pulse 1.2s infinite;
}
@keyframes pulse{
  0%{transform:scale(1);opacity:1}
  50%{transform:scale(1.35);opacity:.65}
  100%{transform:scale(1);opacity:1}
}
</style>
""",
        unsafe_allow_html=True,
    )


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


@st.cache_data(ttl=10)
def get_data(worksheet_name: str) -> pd.DataFrame:
    sheet = connect_db()
    if not sheet:
        return pd.DataFrame()
    try:
        ws = sheet.worksheet(worksheet_name)
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)

        for c in [
            "id",
            "password",
            "partner_id",
            "hunter_id",
            "rank",
            "status",
            "title",
            "name",
            "quote_no",
            "created_at",
        ]:
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
    sheet = connect_db()
    if not sheet:
        return {}
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        values = ws.col_values(1)  # A欄 id
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


def get_header_map(ws: gspread.Worksheet) -> Dict[str, int]:
    headers = ws.row_values(1)
    return {str(h).strip(): i + 1 for i, h in enumerate(headers) if str(h).strip()}


@st.cache_data(ttl=5)
def _latest_quest_signature() -> str:
    df = get_data(QUEST_SHEET)
    if df.empty:
        return "EMPTY"
    max_created = str(df["created_at"].astype(str).max()) if "created_at" in df.columns else ""
    max_id = str(df["id"].astype(str).max()) if "id" in df.columns else ""
    return f"{max_created}|{max_id}"


def _has_new_quests(sig_key: str) -> bool:
    latest = _latest_quest_signature()
    last_seen = str(st.session_state.get(sig_key, ""))
    if not last_seen:
        st.session_state[sig_key] = latest
        return False
    return latest != last_seen


def _mark_seen(sig_key: str) -> None:
    st.session_state[sig_key] = _latest_quest_signature()


def render_refresh_widget(
    *,
    label: str,
    refresh_ts_key: str,
    sig_key: str,
    tab_state_key: str,
    pick_tab_fn,
) -> None:
    _inject_refresh_button_css()

    last_refresh = _get_last_refresh_ts(refresh_ts_key)
    stale = (_now_ts() - last_refresh) >= REFRESH_TTL_SECONDS if last_refresh > 0 else True
    has_new = _has_new_quests(sig_key)

    should_show = stale or has_new

    # ✅ 只有在「需要提示更新」時才啟動輪詢，避免一直 rerun 干擾操作
    if should_show and ENABLE_AUTO_POLL and HAS_AUTOREFRESH:
        st_autorefresh(interval=POLL_INTERVAL_MS, key=f"auto_poll_{sig_key}")

    col_btn, _ = st.columns([2, 10])
    with col_btn:
        if not should_show:
            st.caption("✅ 已是最新")
            return

        st.markdown('<div class="rect-refresh-btn">', unsafe_allow_html=True)
        clicked = st.button(label, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if has_new:
            st.markdown(
                "<div style='margin-top:-8px; text-align:center;'><span class='refresh-badge'></span></div>",
                unsafe_allow_html=True,
            )

        if clicked:
            with st.spinner("同步中…"):
                p = st.progress(0)
                for i in range(1, 6):
                    time.sleep(0.08)
                    p.progress(i * 20)

                invalidate_cache()
                _mark_seen(sig_key)
                _set_last_refresh_ts(refresh_ts_key)

                # ✅ 不要強制改 tab；只在 tab 尚未被設定時才用 pick_tab_fn
                if tab_state_key not in st.session_state:
                    st.session_state[tab_state_key] = pick_tab_fn()

            st.toast("✅ 已同步最新任務")
            st.rerun()



def add_quest_to_sheet(title: str, quote_no: str, desc: str, category: str, points: int) -> bool:
    sheet = connect_db()
    if not sheet:
        return False
    try:
        ws = sheet.worksheet(QUEST_SHEET)
        hmap = get_header_map(ws)

        required = [
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
        missing = [k for k in required if k not in hmap]
        if missing:
            st.error(f"quests 表頭缺少欄位：{missing}（請修正 Google Sheet 第一列表頭）")
            return False

        q_id = uuid.uuid4().hex
        quote_no = _normalize_quote_no(quote_no)

        max_col = max(hmap.values())
        row = [""] * max_col

        row[hmap["id"] - 1] = q_id
        row[hmap["title"] - 1] = title
        row[hmap["quote_no"] - 1] = quote_no
        row[hmap["description"] - 1] = desc
        row[hmap["rank"] - 1] = category
        row[hmap["points"] - 1] = int(points)
        row[hmap["status"] - 1] = "Open"
        row[hmap["hunter_id"] - 1] = ""
        row[hmap["created_at"] - 1] = _now_str()
        row[hmap["partner_id"] - 1] = ""

        ws.append_row(row, value_input_option="USER_ENTERED")
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
    sheet = connect_db()
    if not sheet:
        return False

    try:
        ws = sheet.worksheet(QUEST_SHEET)
        mapping = quest_id_to_row_map()
        row_num = mapping.get(str(quest_id))
        if not row_num:
            st.error("❌ 找不到任務列（id 不存在於快取）")
            return False

        # --- 防呆：驗證快取 row 是否真的是該 id ---
        hmap = get_header_map(ws)
        id_col = hmap.get("id", 1)

        def _resolve_row_by_scan() -> Optional[int]:
            ids = ws.col_values(id_col)
            target = str(quest_id).strip()
            for i, v in enumerate(ids, start=1):
                if i == 1:
                    continue
                if str(v).strip() == target:
                    return i
            return None

        try:
            cell_val = ws.cell(row_num, id_col).value
        except Exception:
            cell_val = None

        if str(cell_val).strip() != str(quest_id).strip():
            new_row = _resolve_row_by_scan()
            if not new_row:
                st.error("❌ 任務列定位失敗（Sheet 被人工插列或刪列）")
                return False
            row_num = new_row

        updates = [
            {
                "range": gspread.utils.rowcol_to_a1(row_num, hmap["status"]),
                "values": [[new_status]],
            }
        ]

        if hunter_id is not None:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_num, hmap["hunter_id"]),
                    "values": [[hunter_id]],
                }
            )

        if partner_list is not None:
            partner_str = ",".join([p for p in partner_list if p])
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_num, hmap["partner_id"]),
                    "values": [[partner_str]],
                }
            )
        elif new_status == "Open":
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_num, hmap["partner_id"]),
                    "values": [[""]],
                }
            )

        ws.batch_update(updates, value_input_option="USER_ENTERED")
        invalidate_cache()
        return True

    except Exception as e:
        st.error(f"❌ 更新任務狀態失敗: {type(e).__name__}: {e}")
        return False



# ============================================================
# 4) 密碼驗證（相容舊明碼；支援 PBKDF2）
# ============================================================
def _hash_password_pbkdf2(password: str, salt_b64: str, rounds: int = 120_000) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return base64.b64encode(dk).decode("utf-8")


def verify_password(input_pwd: str, stored: str) -> bool:
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
    expected = st.secrets.get(ADMIN_ACCESS_KEY_SECRET_NAME, None)
    if not expected or not str(expected).strip():
        return False
    return compare_digest(str(input_key), str(expected))


def get_auth_dict() -> Dict[str, str]:
    df = get_data(EMP_SHEET)
    if df.empty or "name" not in df.columns or "password" not in df.columns:
        return {}
    return dict(zip(df["name"].astype(str), df["password"].astype(str)))


# ============================================================
# 5) AI 影像解析（含估價單號）
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
    if "GEMINI_API_KEY" not in st.secrets or not str(st.secrets.get("GEMINI_API_KEY", "")).strip():
        st.error("❌ 尚未設定 GEMINI_API_KEY（請在 .streamlit/secrets.toml 設定）")
        return None

    api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    try:
        img_bytes = image_file.getvalue()
        if not img_bytes:
            st.error("❌ 上傳檔案讀取失敗（空檔）")
            return None

        b64_img = base64.b64encode(img_bytes).decode("utf-8")
        mime_type = getattr(image_file, "type", None) or "image/jpeg"

        categories_str = ", ".join(ALL_TYPES)
        prompt = f"""
請分析圖片（報價單或報修APP截圖），提取資訊並只輸出「單一 JSON 物件」，不得輸出任何額外文字。
欄位：
- quote_no: 估價單號（若無則空字串）
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
            timeout=35,
        )

        if resp.status_code != 200:
            st.error(f"❌ Gemini API 呼叫失敗：HTTP {resp.status_code}")
            # 把回傳內容印出來（通常會包含錯誤原因：API key/billing/模型/權限）
            st.code(resp.text[:5000])
            return None

        result = resp.json()

        # 防呆：若 candidates 結構不符，直接印出回傳
        try:
            raw_text = result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            st.error("❌ Gemini 回傳格式非預期（請看下方原始回應）")
            st.json(result)
            return None

        data = extract_first_json_object(raw_text)
        if not data:
            st.error("❌ AI 回傳不是合法 JSON（請看下方原文）")
            st.code(raw_text[:5000])
            return None

        quote_no = _normalize_quote_no(data.get("quote_no", ""))
        comm = str(data.get("community", "")).strip()
        proj = str(data.get("project", "")).strip()

        if comm:
            comm = re.sub(r"^[A-Za-z0-9]+\s*", "", comm).strip()

        budget = _safe_int(data.get("budget", 0), 0)
        cat = normalize_category(data.get("category", ""), budget)

        title = f"【{comm}】{proj}" if (comm and proj) else (proj or comm)

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

    except requests.exceptions.Timeout:
        st.error("❌ Gemini API 逾時（timeout）。請稍後再試或調高 timeout 秒數。")
        return None
    except Exception as e:
        st.error(f"❌ AI 辨識發生例外：{type(e).__name__}: {e}")
        return None



# ============================================================
# 6) 業績計算 / 忙碌鎖定
# ============================================================
def calc_my_total_month(df_quests: pd.DataFrame, me: str, month_yyyy_mm: str) -> int:
    if df_quests is None or df_quests.empty:
        return 0

    df = ensure_quests_schema(df_quests)
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

    done = df[df["status"] == "Done"].copy()
    done = done[done["created_at"].astype(str).str.startswith(str(month_yyyy_mm))]

    total = 0
    for _, r in done.iterrows():
        partners = [p for p in str(r.get("partner_id", "")).split(",") if p]
        team = [str(r.get("hunter_id", ""))] + partners

        if me not in team:
            continue

        amount = int(r["points"])
        share = amount // len(team)
        rem = amount % len(team)
        total += (share + rem) if me == str(r.get("hunter_id", "")) else share

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
# 7) UI：登入 / 側欄
# ============================================================
def login_screen() -> None:
    st.title("🏢 工程/叫修 發包管理系統")
    st.caption("v10.0（radio tabs + 共用更新元件 + 估價單號）")

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


def admin_view() -> None:
    def pick_admin_tab() -> str:
        dfq = ensure_quests_schema(get_data(QUEST_SHEET))
        pending = dfq[dfq["status"] == "Pending"]
        if not pending.empty:
            return "🔍 驗收審核"
        return "📷 AI 快速派單"

    render_refresh_widget(
        label="🔄 更新發包",
        refresh_ts_key="admin_last_refresh_ts",
        sig_key="admin_last_seen_sig",
        tab_state_key="admin_active_tab",
        pick_tab_fn=pick_admin_tab,
    )

    st.title("👨‍💼 發包/派單指揮台")

    tab_state_key = "admin_active_tab"
    tabs = ["📷 AI 快速派單", "🔍 驗收審核", "📊 數據總表"]


    active_tab = st.radio(
        "admin_tab",
        tabs,
        key=tab_state_key,  # radio 直接讀寫同一個 session_state
        horizontal=True,
        label_visibility="collapsed",
    )

    # ============================================================
    # 📷 AI 快速派單
    # ============================================================
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
                b = uploaded_file.getvalue()
                img_hash = hashlib.sha256(b).hexdigest()
                cache_key = f"ai_result_{img_hash}"

                now = time.time()
                last = st.session_state.get("ai_last_call_ts", 0.0)
                if now - last < 3.0:
                    st.warning("⏳ 請稍候 3 秒再試（避免額度被快速耗盡）")
                else:
                    st.session_state["ai_last_call_ts"] = now

                    if cache_key in st.session_state:
                        ai = st.session_state[cache_key]
                        st.toast("✅ 使用快取結果（同一張圖不重打）", icon="🧠")
                    else:
                        with st.spinner("🤖 AI 正在閱讀並歸類..."):
                            ai = analyze_quote_image(uploaded_file)
                        if ai:
                            st.session_state[cache_key] = ai

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
                    time.sleep(0.25)
                    st.rerun()

    # ============================================================
    # 🔍 驗收審核
    # ============================================================
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
                qn = _normalize_quote_no(r.get("quote_no", ""))
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

    # ============================================================
    # 📊 數據總表 + 估價單/派工單
    # ============================================================
    else:
        st.subheader("📊 數據總表")
        df = ensure_quests_schema(get_data(QUEST_SHEET))
        st.dataframe(df, use_container_width=True)

        st.divider()
        st.subheader("🧾 估價單（待派工 / 競標中）")
        df_open = df[df["status"] == "Open"]
        if df_open.empty:
            st.info("目前沒有待派的估價單")
        else:
            st.dataframe(
                df_open[["id", "title", "quote_no", "rank", "points", "status", "created_at"]],
                use_container_width=True,
            )

        st.subheader("🛠️ 派工單（進行中 / 待驗收）")
        df_work = df[df["status"].isin(["Active", "Pending"])]
        if df_work.empty:
            st.info("目前沒有派工中的任務")
        else:
            st.dataframe(
                df_work[["id", "title", "hunter_id", "partner_id", "rank", "points", "status", "quote_no"]],
                use_container_width=True,
            )




# ============================================================
# 9) Hunter View（radio 控 tab + 共用更新元件）
# ============================================================
def hunter_view() -> None:
    def pick_hunter_tab() -> str:
        dfq = ensure_quests_schema(get_data(QUEST_SHEET))
        eng_open = dfq[(dfq["status"] == "Open") & (dfq["rank"].isin(TYPE_ENG))]
        maint_open = dfq[(dfq["status"] == "Open") & (dfq["rank"].isin(TYPE_MAINT))]
        if not eng_open.empty:
            return "🏗️ 工程標案"
        if not maint_open.empty:
            return "🔧 維修派單"
        return "📂 我的任務"

    render_refresh_widget(
        label="🔄 更新任務",
        refresh_ts_key="hunter_last_refresh_ts",
        sig_key="hunter_last_seen_sig",
        tab_state_key="hunter_active_tab",
        pick_tab_fn=pick_hunter_tab,
    )

    me = st.session_state["user_name"]
    df = ensure_quests_schema(get_data(QUEST_SHEET))

    busy = is_me_busy(df, me)

    month_yyyy_mm = datetime.now().strftime("%Y-%m")
    my_total = calc_my_total_month(df, me, month_yyyy_mm)

    # ============================================================
    # ✅ KPI 橫幅區（這整段必須在 hunter_view 內）
    # ============================================================
    TARGET = 250_000
    total = int(my_total)

    st.session_state.setdefault("streak", 0)
    st.session_state.setdefault("prev_hit", False)
    hit = total >= TARGET
    if hit and not st.session_state["prev_hit"]:
        st.session_state["streak"] += 1
    elif not hit:
        st.session_state["streak"] = 0
    st.session_state["prev_hit"] = hit

    tiers = [
        ("🟦 起步", 0, "尚未達標"),
        ("🟩 進階", 100_000, "節奏上來了"),
        ("🟨 菁英", 250_000, "達標！"),
        ("🟧 傳奇", 400_000, "超標強者"),
        ("🟥 神話", 600_000, "封神等級"),
    ]
    tier_name, tier_min, tier_desc = tiers[0]
    for name, mn, desc in tiers:
        if total >= mn:
            tier_name, tier_min, tier_desc = name, mn, desc

    progress = min(1.0, total / TARGET) if TARGET > 0 else 1.0
    progress_pct = int(round(progress * 100))

    st.session_state.setdefault("target_fx_fired", False)
    if hit and not st.session_state["target_fx_fired"]:
        st.session_state["target_fx_fired"] = True
        st.balloons()
    if not hit:
        st.session_state["target_fx_fired"] = False

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
.kpi-row{ display:flex; gap:14px; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; }
.kpi-left{ min-width: 320px; flex: 2; }
.kpi-right{ min-width: 240px; flex: 1; text-align:right; }
.kpi-title{ font-size: 22px; font-weight: 900; letter-spacing:.4px; }
.kpi-sub{ margin-top: 6px; color: rgba(255,255,255,.75); font-size: 13px; }
.pill{
  display:inline-flex; align-items:center; gap:8px;
  padding: 8px 10px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(0,0,0,.25);
  font-weight: 800;
}
.pill small{ font-weight: 700; color: rgba(255,255,255,.7); }
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

    st.progress(progress)
    if not hit:
        gap = max(0, TARGET - total)
        st.info(f"距離達標還差：${gap:,}")
    else:
        st.success("達標狀態已啟動")


    st.markdown("## 🧱 本月團隊狀態牆（匿名）")

    df_all = ensure_quests_schema(get_data(QUEST_SHEET))
    this_month = datetime.now().strftime("%Y-%m")

    auth = get_auth_dict()
    hunters = list(auth.keys())

    TARGET = 250_000

    progress_levels = {"hit": 0, "rush": 0, "mid": 0, "start": 0}

    for h in hunters:
        total_h = calc_my_total_month(df_all, h, this_month)
        if total_h >= TARGET:
            progress_levels["hit"] += 1
        elif total_h >= TARGET * 0.5:
            progress_levels["rush"] += 1
        elif total_h > 0:
            progress_levels["mid"] += 1
        else:
            progress_levels["start"] += 1

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("🏆 已達標", f"{progress_levels['hit']} 人")
    with c2:
        st.metric("🔥 衝刺中", f"{progress_levels['rush']} 人")
    with c3:
        st.metric("🚧 穩定推進", f"{progress_levels['mid']} 人")
    with c4:
        st.metric("🌱 起步中", f"{progress_levels['start']} 人")

    st.caption("※ 不顯示姓名，僅顯示團隊整體進度分佈")")


    # ============================================================
    # ✅ 原本的工作台內容（你貼的後半段）從這裡開始
    # ============================================================
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

    # ✅ 第一次進來才給預設值；之後切 tab 不會被洗回去
    if tab_state_key not in st.session_state:
        st.session_state[tab_state_key] = pick_hunter_tab()

    active_tab = st.radio(
        "hunter_tab",
        tabs,
        key=tab_state_key,  # ✅ 讓 radio 直接讀寫同一個 session_state
        horizontal=True,
        label_visibility="collapsed",
    )

    # ----------------------------
    # 🏗️ 工程標案
    # ----------------------------
    if active_tab == "🏗️ 工程標案":
        df_eng = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_ENG))]
        if df_eng.empty:
            st.info("無標案")
        else:
            st.caption("🔥 工程競標區")
            auth = get_auth_dict()
            all_users = list(auth.keys())

            for _, row in df_eng.iterrows():
                title_text = str(row.get("title", ""))
                rank_text = str(row.get("rank", ""))
                pts = _safe_int(row.get("points", 0), 0)
                desc_text = str(row.get("description", ""))
                qn = _normalize_quote_no(row.get("quote_no", ""))

                st.markdown(
                    f"""
<div class="project-card">
  <h3>📄 {title_text}</h3>
  <p style="color:#aaa;">
    類別: {rank_text} |
    預算: <span style="color:#0f0; font-size:1.2em;">${pts:,}</span>
    {' | 估價單號: ' + qn if qn else ''}
  </p>
  <p>{desc_text}</p>
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

    # ----------------------------
    # 🔧 維修派單
    # ----------------------------
    elif active_tab == "🔧 維修派單":
        df_maint = df[(df["status"] == "Open") & (df["rank"].isin(TYPE_MAINT))]
        if df_maint.empty:
            st.info("無維修單")
        else:
            st.caption("⚡ 快速搶修區")
            for _, row in df_maint.iterrows():
                title_text = str(row.get("title", ""))
                rank_text = str(row.get("rank", ""))
                pts = _safe_int(row.get("points", 0), 0)
                desc_text = str(row.get("description", ""))
                qn = _normalize_quote_no(row.get("quote_no", ""))

                urgent_html = '<span class="urgent-tag">🔥URGENT</span>' if rank_text == "緊急搶修" else ""
                extra = f" | 估價單號: {qn}" if qn else ""

                st.markdown(
                    f"""
<div class="ticket-card">
  <div style="display:flex; justify-content:space-between;">
    <strong>🔧 {title_text} {urgent_html}</strong>
    <span style="color:#00AAFF; font-weight:bold;">${pts:,}</span>
  </div>
  <div style="font-size:0.9em; color:#ccc;">{desc_text}</div>
  <div style="font-size:0.85em; color:#9aa;">類別: {rank_text}{extra}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

                col_fast, _ = st.columns([1, 4])
                with col_fast:
                    if st.button("✋ 我來處理", key=f"bm_{row['id']}", disabled=busy):
                        ok = update_quest_status(str(row["id"]), "Active", me, [])
                        if ok:
                            st.toast(f"已接下：{title_text}")
                            st.rerun()
                        else:
                            st.error("接單失敗（資料列定位或寫入異常）")

    # ----------------------------
    # 📂 我的任務
    # ----------------------------
    else:
        def is_mine(r: pd.Series) -> bool:
            partners = [p for p in str(r.get("partner_id", "")).split(",") if p]
            return str(r.get("hunter_id", "")) == me or me in partners

        df_my = df[df.apply(is_mine, axis=1)]
        df_my = df_my[df_my["status"].isin(["Active", "Pending"])]

        if df_my.empty:
            st.info("目前無任務")
        else:
            for _, row in df_my.iterrows():
                title_text = str(row.get("title", ""))
                status_text = str(row.get("status", ""))
                desc_text = str(row.get("description", ""))
                pts = _safe_int(row.get("points", 0), 0)
                qn = _normalize_quote_no(row.get("quote_no", ""))

                with st.expander(f"進行中: {title_text} ({status_text})"):
                    st.write(f"估價單號: {qn if qn else '—'}")
                    st.write(f"金額: ${pts:,}（完工依此金額收費）")
                    if desc_text.strip():
                        st.write(desc_text)

                    if status_text == "Active" and str(row.get("hunter_id", "")) == me:
                        if st.button("📩 完工回報 (解除鎖定)", key=f"sub_{row['id']}"):
                            update_quest_status(str(row["id"]), "Pending")
                            st.rerun()
                    elif status_text == "Pending":
                        st.warning("✅ 已回報，等待主管審核中")



# ============================================================
# 10) main
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
