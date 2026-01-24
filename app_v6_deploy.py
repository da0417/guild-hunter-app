# --- 🔥 AI 核心：HTTP 直連模式 (Gemini 2.0 拆分優化版) ---
def analyze_quote_image(image_file):
    # 在這裡才 import，避免程式一開始就崩潰
    try:
        import requests
    except ImportError:
        st.error("❌ 系統缺少 'requests' 套件，請更新 requirements.txt")
        return None

    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 尚未設定 GEMINI_API_KEY")
        return None

    api_key = st.secrets["GEMINI_API_KEY"]
    
    # 使用您權限內可用的最強模型
    model_name = "gemini-2.0-flash" 
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    try:
        img_bytes = image_file.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        mime_type = image_file.type

        # 👇👇👇 修改了這裡的 Prompt，要求 AI 把名字拆開 👇👇👇
        payload = {
            "contents": [{
                "parts": [
                    {"text": """
                    請分析這張圖片（報價單或簽呈），提取以下資訊並輸出為純 JSON 格式 (不要 Markdown)：
                    1. community: 客戶名稱、社區名稱或大樓名稱（通常在單據抬頭或客戶欄，例如：宏傳上琉ABC棟、竹國霖）。
                    2. project: 具體的工程名稱或施工項目（例如：揚水液面控制器預防性更新）。
                    3. description: 詳細施工內容摘要（包含規格、數量等）。
                    4. budget: 總金額（純數字，去除幣別符號）。
                    5. category: 從 ['土木工程', '機電工程', '室內裝修', '軟體開發', '定期保養', '緊急搶修', '設備巡檢', '耗材更換'] 選一個最接近的。
                    6. is_urgent: 是否緊急 (true/false)。
                    """},
                    { "inline_data": { "mime_type": mime_type, "data": b64_img } }
                ]
            }]
        }
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            result = response.json()
            try:
                raw_text = result['candidates'][0]['content']['parts'][0]['text']
                clean_json = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)
                
                # 👇👇👇 這裡自動將兩個欄位組合成標準標題 👇👇👇
                comm = data.get('community', '')
                proj = data.get('project', '')
                
                # 如果有抓到社區名，就加上括號；否則只顯示工程名
                if comm and proj:
                    final_title = f"【{comm}】{proj}"
                else:
                    final_title = proj if proj else comm
                
                # 將組合好的標題塞回 title 欄位，讓主程式讀取
                data['title'] = final_title
                
                return data
            except: return None
        else:
            st.error(f"API 連線失敗 ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"系統錯誤: {e}")
        return None
