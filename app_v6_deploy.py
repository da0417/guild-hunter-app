# app_v6_deploy.py
import base64
import json
import re
import time
from datetime import datetime
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
# 基本設定
# ============================================================
st.set_page_config(page_title="AI 智慧派工系統", layout="wide", page_icon="🏢")

st.markdown(
    """
<style>
.ticket-card { border-left: 5px solid #00AAFF; background:#262730; padding:10px; border-radius:5px; margin-bottom:10px; }
.project-card { border-left:5px solid #FF4B4B; background:#1E1E1E; padding:15px; border-radius:10px; margin-bottom:15px; border:1px solid #444; }
.urgent-tag { color:#FF4B4B; font-weight:bold; border:1px solid #FF4B4B; padding:2px 6px; border-radius:4px; font-size:12px; }
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 常數
# ============================================================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
SHEET_NAME = "guild_system_db"

QUEST_SHEET = "quests"
EMP_SHEET = "employees"

TYPE_ENG = ["消防工程", "機電工程", "住戶宅修"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

QUEST_COLS = [
    "id",
    "title",
    "description",
    "rank",
    "points",
    "status",
    "hunter_id",
    "created_at",
    "partner_id",
]

# ============================================================
# 工具
# ============================================================
def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# Google Sheet
# ============================================================
@st.cache_resource
def connect_db():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], SCOPE
    )
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME)


@st.cache_data(ttl=2)
def get_data(sheet_name: str) -> pd.DataFrame:
    try:
        ws = connect_db().worksheet(sheet_name)
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()


def invalidate_cache():
    get_data.clear()  # type: ignore


# ============================================================
# ✅ 核心：欄位映射（修正「主管發包後同仁看不到」）
# ============================================================
def ensure_quests_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    rename_map = {
        "category": "rank",
        "類別": "rank",
        "type": "rank",
        "budget": "points",
        "金額": "points",
        "amount": "points",
        "desc": "description",
        "說明": "description",
        "內容": "description",
        "partner_list": "partner_id",
        "隊友": "partner_id",
    }

    for old, new in rename_map.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    for c in QUEST_COLS:
        if c not in df.columns:
            df[c] = ""

    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)

    for c in ["id", "rank", "status", "hunter_id", "partner_id", "title", "description"]:
        df[c] = df[c].astype(str)

    return df[QUEST_COLS]


# ============================================================
# DB 寫入
# ============================================================
def add_quest(title: str, desc: str, rank: str, points: int):
    ws = connect_db().worksheet(QUEST_SHEET)
    ws.append_row(
        [
            int(time.time()),
            title,
            desc,
            rank,
            points,
            "Open",
            "",
            now_str(),
            "",
        ]
    )
    invalidate_cache()


def update_quest(
    qid: str,
    status: str,
    hunter: Optional[str] = None,
    partners: Optional[List[str]] = None,
):
    ws = connect_db().worksheet(QUEST_SHEET)
    ids = ws.col_values(1)
    row = ids.index(str(qid)) + 1

    ws.update_cell(row, 6, status)
    if hunter is not None:
        ws.update_cell(row, 7, hunter)
    if partners is not None:
        ws.update_cell(row, 9, ",".join(partners))

    invalidate_cache()


# ============================================================
# 業績 / 狀態
# ============================================================
def calc_my_total(df: pd.DataFrame, me: str) -> int:
    total = 0
    for _, r in df[df["status"] == "Done"].iterrows():
        team = [r["hunter_id"]] + [p for p in r["partner_id"].split(",") if p]
        if me in team:
            share = r["points"] // len(team)
            rem = r["points"] % len(team)
            total += share + rem if me == r["hunter_id"] else share
    return total


def is_busy(df: pd.DataFrame, me: str) -> bool:
    for _, r in df[df["status"] == "Active"].iterrows():
        team = [r["hunter_id"]] + [p for p in r["partner_id"].split(",") if p]
        if me in team:
            return True
    return False


# ============================================================
# 同仁畫面
# ============================================================
def hunter_view():
    me = st.session_state["user_name"]
    df = ensure_quests_schema(get_data(QUEST_SHEET))

    st.title(f"🚀 工作台：{me}")
    c1, c2 = st.columns([2, 1])

    with c1:
        st.metric("💰 本月實拿業績", f"${calc_my_total(df, me):,}")

    with c2:
        if is_busy(df, me):
            st.error("🚫 任務進行中")
        else:
            st.success("✅ 狀態閒置")

    st.divider()
    tab_eng, tab_maint, tab_my = st.tabs(["🏗️ 工程標案", "🔧 維修派單", "📂 我的任務"])

    # 工程
    with tab_eng:
        for _, r in df[(df["status"] == "Open") & (df["rank"].isin(TYPE_ENG))].iterrows():
            st.markdown(
                f"""
<div class="project-card">
<h3>{r['title']}</h3>
<p>類別：{r['rank']}｜金額：${r['points']:,}</p>
<p>{r['description']}</p>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("⚡ 投標", key=f"be_{r['id']}"):
                update_quest(r["id"], "Active", me, [])
                st.rerun()

    # 維修
    with tab_maint:
        for _, r in df[(df["status"] == "Open") & (df["rank"].isin(TYPE_MAINT))].iterrows():
            st.markdown(
                f"""
<div class="ticket-card">
<strong>{r['title']}</strong>
<span style="float:right">${r['points']:,}</span>
<div>{r['description']}</div>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("✋ 我來處理", key=f"bm_{r['id']}"):
                update_quest(r["id"], "Active", me, [])
                st.rerun()

    # 我的任務（✅ 顯示金額）
    with tab_my:
        my_df = df[
            df.apply(
                lambda r: me == r["hunter_id"] or me in r["partner_id"].split(","), axis=1
            )
            & df["status"].isin(["Active", "Pending"])
        ]

        if my_df.empty:
            st.info("目前無任務")
        else:
            for _, r in my_df.iterrows():
                with st.expander(f"{r['title']}（{r['status']}）"):
                    st.markdown(f"**金額：${r['points']:,}（完工依此金額收費）**")
                    st.write(f"說明：{r['description']}")
                    if r["status"] == "Active" and r["hunter_id"] == me:
                        if st.button("📩 完工回報", key=f"done_{r['id']}"):
                            update_quest(r["id"], "Pending")
                            st.rerun()
                    if r["status"] == "Pending":
                        st.warning("等待主管驗收中")


# ============================================================
# 入口
# ============================================================
def main():
    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "工程師A"  # demo
    hunter_view()


main()
