import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import json
import base64
import re
from typing import Optional, Dict, List, Tuple
import logging

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    st.error("❌ 請在 requirements.txt 加入: `requests`")
    st.stop()

# ==========================================
# 🎨 系統設定與常數
# ==========================================
st.set_page_config(
    page_title="AI 智慧派工系統",
    layout="wide",
    page_icon="🏢",
    initial_sidebar_state="expanded"
)

# Google Sheets 設定
SCOPE = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
SHEET_NAME = 'guild_system_db'

# 工作類別定義
TYPE_ENG = ["消防工程", "機電工程", "室內裝修", "軟體開發"]
TYPE_MAINT = ["場勘報價", "點交總檢", "緊急搶修", "定期保養", "設備巡檢", "耗材更換"]
ALL_TYPES = TYPE_ENG + TYPE_MAINT

# 團隊配置
TEAMS = {
    "工程1組": ["譚學峰", "邱顯杰"],
    "工程2組": ["古孟平", "李名傑"],
    "維養1組": ["陳緯民", "李宇傑"]
}

# 狀態常數
STATUS = {
    'OPEN': 'Open',
    'ACTIVE': 'Active',
    'PENDING': 'Pending',
    'DONE': 'Done'
}

# ==========================================
# 🎨 樣式設定
# ==========================================
def apply_custom_styles():
    """套用自訂 CSS 樣式"""
    st.markdown("""
    <style>
        /* 卡片樣式 */
        .ticket-card {
            border-left: 5px solid #00AAFF !important;
            background: linear-gradient(135deg, #262730 0%, #1a1a24 100%);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            transition: transform 0.2s;
        }
        .ticket-card:hover {
            transform: translateX(5px);
        }
        
        .project-card {
            border-left: 5px solid #FF4B4B !important;
            background: linear-gradient(135deg, #1E1E1E 0%, #2a2a2a 100%);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            border: 1px solid #444;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        
        .urgent-tag {
            color: #FF4B4B;
            font-weight: bold;
            border: 2px solid #FF4B4B;
            padding: 3px 8px;
            border-radius: 5px;
            font-size: 11px;
            margin-left: 8px;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        
        /* 狀態標籤 */
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-open { background-color: #4CAF50; color: white; }
        .status-active { background-color: #FF9800; color: white; }
        .status-pending { background-color: #2196F3; color: white; }
        .status-done { background-color: #9E9E9E; color: white; }
        
        /* 改善表單外觀 */
        .stTextInput > div > div > input {
            border-radius: 8px;
        }
        
        /* 側邊欄美化 */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
        }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 🔐 資料庫連線與快取管理
# ==========================================
@st.cache_resource(ttl=300)
def connect_db() -> Optional[gspread.Spreadsheet]:
    """
    連線至 Google Sheets 資料庫
    
    Returns:
        Google Sheets 物件或 None (失敗時)
    """
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("❌ 缺少 Google Cloud 認證設定")
            return None
            
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME)
        logger.info("✅ 資料庫連線成功")
        return sheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ 找不到工作表: {SHEET_NAME}")
        return None
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {str(e)}")
        logger.error(f"Database connection error: {e}")
        return None

@st.cache_data(ttl=60)
def get_data(worksheet_name: str) -> pd.DataFrame:
    """
    從指定工作表讀取資料
    
    Args:
        worksheet_name: 工作表名稱
        
    Returns:
        DataFrame 物件
    """
    try:
        sheet = connect_db()
        if not sheet:
            return pd.DataFrame()
            
        ws = sheet.worksheet(worksheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # 資料型別轉換
        if 'password' in df.columns:
            df['password'] = df['password'].astype(str)
        if 'partner_id' in df.columns:
            df['partner_id'] = df['partner_id'].astype(str)
        if 'id' in df.columns:
            df['id'] = df['id'].astype(str)
        if 'points' in df.columns:
            df['points'] = pd.to_numeric(df['points'], errors='coerce').fillna(0)
            
        logger.info(f"✅ 成功讀取 {worksheet_name}: {len(df)} 筆資料")
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.warning(f"⚠️ 工作表 '{worksheet_name}' 不存在")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ 讀取資料失敗: {str(e)}")
        logger.error(f"Error reading {worksheet_name}: {e}")
        return pd.DataFrame()

def clear_cache():
    """清除所有快取資料"""
    st.cache_data.clear()
    st.cache_resource.clear()

# ==========================================
# 📝 資料操作函式
# ==========================================
def add_quest_to_sheet(title: str, desc: str, category: str, points: int) -> bool:
    """
    新增任務至資料表
    
    Args:
        title: 任務標題
        desc: 任務描述
        category: 任務類別
        points: 任務點數/金額
        
    Returns:
        成功回傳 True，失敗回傳 False
    """
    try:
        # 輸入驗證
        if not title or not title.strip():
            st.error("❌ 任務標題不可為空")
            return False
        
        if category not in ALL_TYPES:
            st.error(f"❌ 無效的類別: {category}")
            return False
            
        if points < 0:
            st.error("❌ 金額不可為負數")
            return False
        
        sheet = connect_db()
        if not sheet:
            return False
            
        ws = sheet.worksheet('quests')
        q_id = int(time.time())
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        ws.append_row([
            q_id,
            title.strip(),
            desc.strip(),
            category,
            points,
            STATUS['OPEN'],
            "",  # hunter_id
            created_at,
            ""   # partner_id
        ])
        
        clear_cache()
        logger.info(f"✅ 新增任務成功: {title}")
        return True
    except Exception as e:
        st.error(f"❌ 新增任務失敗: {str(e)}")
        logger.error(f"Error adding quest: {e}")
        return False

def update_quest_status(
    quest_id: str,
    new_status: str,
    hunter_id: Optional[str] = None,
    partner_list: Optional[List[str]] = None
) -> bool:
    """
    更新任務狀態
    
    Args:
        quest_id: 任務 ID
        new_status: 新狀態
        hunter_id: 主要負責人
        partner_list: 協作夥伴清單
        
    Returns:
        成功回傳 True，失敗回傳 False
    """
    try:
        if new_status not in STATUS.values():
            st.error(f"❌ 無效的狀態: {new_status}")
            return False
            
        sheet = connect_db()
        if not sheet:
            return False
            
        ws = sheet.worksheet('quests')
        
        try:
            cell = ws.find(str(quest_id))
            row_num = cell.row
        except gspread.exceptions.CellNotFound:
            st.error(f"❌ 找不到任務 ID: {quest_id}")
            return False
        
        # 批次更新（效能優化）
        updates = []
        updates.append(gspread.Cell(row_num, 6, new_status))
        
        if hunter_id is not None:
            updates.append(gspread.Cell(row_num, 7, hunter_id))
            
        if partner_list is not None:
            partner_str = ",".join(partner_list) if isinstance(partner_list, list) else partner_list
            updates.append(gspread.Cell(row_num, 9, partner_str))
        elif new_status == STATUS['OPEN']:
            updates.append(gspread.Cell(row_num, 9, ""))
        
        ws.update_cells(updates)
        clear_cache()
        logger.info(f"✅ 更新任務狀態: {quest_id} -> {new_status}")
        return True
    except Exception as e:
        st.error(f"❌ 更新任務失敗: {str(e)}")
        logger.error(f"Error updating quest: {e}")
        return False

# ==========================================
# 🤖 AI 影像辨識
# ==========================================
def analyze_quote_image(image_file) -> Optional[Dict]:
    """
    使用 Gemini AI 分析圖片內容
    
    Args:
        image_file: 上傳的圖片檔案
        
    Returns:
        辨識結果字典或 None
    """
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = image_file.type

        categories_str = ", ".join(ALL_TYPES)

        payload = {
            "contents": [{
                "parts": [
                    {"text": f"""
請分析此圖片（報價單或報修 APP 截圖），並以 JSON 格式回傳以下資訊：

1. **community**: 社區名稱（去除前綴編號）
2. **project**: 工程名稱或報修摘要
3. **description**: 詳細說明（包含項目、數量、單價等細節）
4. **budget**: 總金額（純數字，若無明確金額則填 0）
5. **category**: 必須從以下清單選擇最相近的類別：
   [{categories_str}]
   
   分類建議：
   - 換燈泡、更換配件 → 耗材更換
   - 漏水、停電、緊急維修 → 緊急搶修
   - 定期檢查、保養 → 定期保養
   - 大型工程、裝修 → 對應工程類別
   
6. **is_urgent**: 是否為緊急案件（true/false）

**重要**: 請直接回傳 JSON 格式，不要包含任何其他文字或說明。
                    """},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_img
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 1024,
            }
        }
        
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        
        if response.status_code != 200:
            st.error(f"❌ AI 服務錯誤: HTTP {response.status_code}")
            logger.error(f"API Error: {response.text}")
            return None
            
        result = response.json()
        
        try:
            raw_text = result['candidates'][0]['content']['parts'][0]['text']
            clean_json = raw_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            # 處理社區名稱（去除編號）
            comm = data.get('community', '')
            proj = data.get('project', '')
            
            if comm:
                comm = re.sub(r'^[A-Za-z0-9]+\s*', '', comm)
            
            # 組合標題
            if comm and proj:
                data['title'] = f"【{comm}】{proj}"
            else:
                data['title'] = proj if proj else comm
            
            # 驗證類別
            if data.get('category') not in ALL_TYPES:
                # 回退機制：根據金額判斷
                budget = data.get('budget', 0)
                data['category'] = TYPE_MAINT[0] if budget == 0 else TYPE_ENG[0]
                logger.warning(f"AI 類別錯誤，已自動修正為: {data['category']}")
            
            logger.info("✅ AI 辨識成功")
            return data
            
        except (KeyError, json.JSONDecodeError, IndexError) as e:
            st.error("❌ AI 回應格式錯誤")
            logger.error(f"Parse error: {e}")
            return None
            
    except requests.exceptions.Timeout:
        st.error("❌ AI 服務逾時，請稍後再試")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"❌ 網路連線錯誤: {str(e)}")
        return None
    except Exception as e:
        st.error(f"❌ 未知錯誤: {str(e)}")
        logger.error(f"Unexpected error in AI analysis: {e}")
        return None

# ==========================================
# 📊 資料分析函式
# ==========================================
def calculate_user_performance(username: str, df: pd.DataFrame) -> int:
    """
    計算使用者業績總額
    
    Args:
        username: 使用者名稱
        df: 任務資料框
        
    Returns:
        業績總額
    """
    if df.empty or 'status' not in df.columns:
        return 0
    
    total = 0
    df_done = df[df['status'] == STATUS['DONE']]
    
    for _, row in df_done.iterrows():
        partners = str(row['partner_id']).split(',') if row['partner_id'] else []
        partners = [p.strip() for p in partners if p.strip()]
        team = [row['hunter_id']] + partners
        
        if username in team:
            team_size = len(team)
            share = row['points'] // team_size
            remainder = row['points'] % team_size
            
            # 主要負責人獲得餘數
            if username == row['hunter_id']:
                total += share + remainder
            else:
                total += share
    
    return int(total)

def check_user_busy_status(username: str, df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
    """
    檢查使用者是否有進行中的任務
    
    Args:
        username: 使用者名稱
        df: 任務資料框
        
    Returns:
        (是否忙碌, 任務標題)
    """
    if df.empty or 'status' not in df.columns:
        return False, None
    
    active_df = df[df['status'] == STATUS['ACTIVE']]
    
    for _, row in active_df.iterrows():
        partners = str(row['partner_id']).split(',') if row['partner_id'] else []
        partners = [p.strip() for p in partners if p.strip()]
        
        if username == row['hunter_id'] or username in partners:
            return True, row['title']
    
    return False, None

def get_user_team(username: str) -> str:
    """取得使用者所屬團隊"""
    for team_name, members in TEAMS.items():
        if username in members:
            icon = "🏗️" if "工程" in team_name else "🔧"
            return f"{icon} {team_name}"
    return "未分組"

# ==========================================
# 🖥️ UI 元件
# ==========================================
def render_status_badge(status: str) -> str:
    """渲染狀態標籤"""
    status_map = {
        STATUS['OPEN']: ('開放中', 'status-open'),
        STATUS['ACTIVE']: ('進行中', 'status-active'),
        STATUS['PENDING']: ('待審核', 'status-pending'),
        STATUS['DONE']: ('已完成', 'status-done')
    }
    label, css_class = status_map.get(status, (status, ''))
    return f'<span class="status-badge {css_class}">{label}</span>'

def render_project_card(row: pd.Series, card_type: str = "project"):
    """渲染專案卡片"""
    urgent_tag = '<span class="urgent-tag">🔥 緊急</span>' if row['rank'] == '緊急搶修' else ''
    
    card_class = "project-card" if card_type == "project" else "ticket-card"
    icon = "📄" if card_type == "project" else "🔧"
    
    st.markdown(f"""
    <div class="{card_class}">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h3>{icon} {row['title']} {urgent_tag}</h3>
            <span style="color:#0f0; font-size:1.3em; font-weight:bold;">${row['points']:,}</span>
        </div>
        <p style="color:#aaa; margin:8px 0;">
            類別: <strong>{row['rank']}</strong> | 
            狀態: {render_status_badge(row['status'])}
        </p>
        <p style="color:#ccc; margin-top:10px;">{row['description']}</p>
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 🔐 登入介面
# ==========================================
def render_login_page():
    """渲染登入頁面"""
    st.title("🏢 營繕發包管理系統")
    st.caption("v10.0 企業級優化版 | Powered by AI")
    
    col1, col2 = st.columns(2)
    
    with col1:
        with st.container(border=True):
            st.subheader("👨‍💼 主管入口")
            st.caption("管理所有派工與審核")
            
            admin_pwd = st.text_input("Access Key", type="password", key="admin_pwd")
            
            if st.button("🚀 進入指揮台", use_container_width=True):
                if admin_pwd == "Boss@9988":
                    st.session_state['user_role'] = 'Admin'
                    st.success("✅ 登入成功！")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
    
    with col2:
        with st.container(border=True):
            st.subheader("👷 同仁入口")
            st.caption("查看與接取任務")
            
            # 載入員工資料
            if 'auth_dict' not in st.session_state:
                with st.spinner("載入員工資料..."):
                    df_emps = get_data('employees')
                    if not df_emps.empty and 'password' in df_emps.columns:
                        st.session_state['auth_dict'] = dict(zip(
                            df_emps['name'],
                            df_emps['password']
                        ))
                    else:
                        st.session_state['auth_dict'] = {}

            if st.session_state['auth_dict']:
                hunter_name = st.selectbox(
                    "選擇姓名",
                    list(st.session_state['auth_dict'].keys())
                )
                hunter_pwd = st.text_input("密碼", type="password", key="hunter_pwd")
                
                if st.button("⚡ 上工", use_container_width=True):
                    if hunter_pwd == str(st.session_state['auth_dict'].get(hunter_name)):
                        st.session_state['user_role'] = 'Hunter'
                        st.session_state['user_name'] = hunter_name
                        st.success(f"✅ 歡迎回來，{hunter_name}！")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ 密碼錯誤")
            else:
                st.warning("⚠️ 無法載入員工資料")

# ==========================================
# 👨‍💼 管理員介面
# ==========================================
def render_admin_dashboard():
    """渲染管理員儀表板"""
    st.title("👨‍💼 發包/派單指揮台")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📷 AI 快速派單",
        "🔍 驗收審核",
        "📊 數據總表",
        "⚙️ 系統設定"
    ])
    
    # ===== Tab 1: AI 派單 =====
    with tab1:
    st.subheader("📤 發布新任務")
    
    uploaded_file = st.file_uploader(
        "上傳報價單或報修截圖",
        type=['png', 'jpg', 'jpeg'],
        help="支援 JPG, PNG 格式"
    )
    
    # 初始化草稿
    if 'draft_title' not in st.session_state:
        st.session_state['draft_title'] = ""
    if 'draft_desc' not in st.session_state:
        st.session_state['draft_desc'] = ""
    if 'draft_budget' not in st.session_state:
        st.session_state['draft_budget'] = 0
    if 'draft_type' not in st.session_state:
        st.session_state['draft_type'] = TYPE_ENG[0]
    
    if uploaded_file is not None:
        col_img, col_btn = st.columns([2, 1])
        
        with col_img:
            st.image(uploaded_file, caption="預覽", use_container_width=True)
        
        with col_btn:
            st.write("")
            st.write("")
            if st.button("✨ 啟動 AI 辨識", use_container_width=True):
                with st.spinner("🤖 AI 正在分析..."):
                    ai_data = analyze_quote_image(uploaded_file)
                    
                    if ai_data:
                        st.session_state['draft_title'] = ai_data.get('title', '')
                        st.session_state['draft_desc'] = ai_data.get('description', '')
                        st.session_state['draft_budget'] = int(ai_data.get('budget', 0))
                        
                        cat = ai_data.get('category', '')
                        if cat in ALL_TYPES:
                            st.session_state['draft_type'] = cat
                        else:
                            st.session_state['draft_type'] = TYPE_MAINT[0] if ai_data.get('budget', 0) == 0 else TYPE_ENG[0]
                        
                        if ai_data.get('is_urgent'):
                            st.toast("🚨 緊急案件！", icon="🔥")
                        else:
                            st.toast("✅ 辨識成功！", icon="🤖")
                        
                        st.rerun()
    
    st.divider()
    
    # 任務表單
    with st.form("new_task_form"):
        col_a, col_b = st.columns([2, 1])
        
        with col_a:
            title = st.text_input(
                "案件名稱 *",
                value=st.session_state['draft_title'],
                placeholder="例: 【XX社區】消防設備檢修"
            )
        
        with col_b:
            try:
                idx = ALL_TYPES.index(st.session_state['draft_type'])
            except ValueError:
                idx = 0
            
            # ✅ 修復：完整的 selectbox 語法
            category = st.selectbox(
                "類別",
                ALL_TYPES,
                index=idx
            )
        
        budget = st.number_input(
            "金額 ($)",
            min_value=0,
            step=1000,
            value=st.session_state['draft_budget']
        )
        
        desc = st.text_area(
            "詳細說明",
            value=st.session_state['draft_desc'],
            height=150,
            placeholder="請詳細描述工程內容、數量、材料等"
        )
        
        submit_col1, submit_col2 = st.columns([1, 4])
        with submit_col1:
            submitted = st.form_submit_button(
                "🚀 確認發布",
                use_container_width=True,
                type="primary"
            )
        
        if submitted:
            if not title or not title.strip():
                st.error("❌ 請輸入案件名稱")
            else:
                if add_quest_to_sheet(title, desc, category, budget):
                    st.success(f"✅ 已發布: {title}")
                    # 清空草稿
                    st.session_state['draft_title'] = ""
                    st.session_state['draft_desc'] = ""
                    st.session_state['draft_budget'] = 0
                    time.sleep(1)
                    st.rerun()

