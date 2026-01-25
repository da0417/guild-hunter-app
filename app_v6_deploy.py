with t3:
    st.subheader("📊 數據總表（除錯 + 可選工作表）")

    sheet = connect_db()
    if not sheet:
        st.error("資料庫未連線")
    else:
        # 列出所有工作表名稱
        ws_titles = [ws.title for ws in sheet.worksheets()]
        st.write("目前資料庫工作表：", ws_titles)

        # 選擇工作表（預設 quests）
        if QUEST_SHEET in ws_titles:
            default_idx = ws_titles.index(QUEST_SHEET)
        else:
            default_idx = 0

        pick = st.selectbox("選擇要查看的工作表", ws_titles, index=default_idx)

        ws = sheet.worksheet(pick)
        raw = ws.get_all_values()
        st.caption(f"raw 行數（含表頭）：{len(raw)}")

        df = pd.DataFrame(ws.get_all_records())

        # quests 才套 schema
        if pick == QUEST_SHEET and not df.empty:
            df = ensure_quests_schema(df)

        if df.empty:
            st.warning("get_all_records() 讀到空資料（通常是表頭不在第 1 列，或表頭有空欄）")
            preview_n = min(10, len(raw))
            st.write("raw 預覽（前幾行）：")
            st.dataframe(pd.DataFrame(raw[:preview_n]))
        else:
            st.caption(f"DataFrame：{df.shape[0]} 筆 × {df.shape[1]} 欄")
            st.dataframe(df, use_container_width=True)
