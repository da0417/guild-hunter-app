def render_team_wall(
    *,
    df_all: pd.DataFrame,
    month_yyyy_mm: str,
    target: int = 250_000,
) -> Dict[str, int]:

    st.markdown("## 🧱 本月團隊狀態牆（匿名）")

    progress_levels = {
        "hit": 0,
        "rush": 0,
        "mid": 0,
        "start": 0,
    }

    auth = get_auth_dict()
    hunters = list(auth.keys()) if auth else []

    if df_all.empty or not hunters:
        st.info("目前尚無團隊進度資料")
        # ✅ 一定要回傳 dict
        return progress_levels

    for h in hunters:
        total = calc_my_total_month(df_all, h, month_yyyy_mm)

        if total >= target:
            progress_levels["hit"] += 1
        elif total >= target * 0.5:
            progress_levels["rush"] += 1
        elif total > 0:
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

    st.caption("※ 不顯示姓名，僅顯示團隊整體進度分佈")

    return progress_levels
