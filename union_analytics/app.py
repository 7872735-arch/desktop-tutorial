import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import numpy as np

st.set_page_config(
    page_title="工會對話記錄分析系統",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    .stProgress > div > div { border-radius: 8px; }
    [data-testid="stMetricValue"] { font-size: 1.8em; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)

COLUMNS_CONFIG = {
    "month": "月份 (YYYY-MM)",
    "raise_date": "提出日期 (YYYY-MM-DD)",
    "issue_id": "議題編號",
    "category": "議題類別",
    "description": "議題描述",
    "factory_response": "廠方回應",
    "status": "解決狀態（已解決 / 未解決）",
    "resolution_date": "解決日期（未解決留空）",
}

CATEGORY_COLORS = {
    "工資薪酬": "#e74c3c",
    "工時休假": "#e67e22",
    "安全衛生": "#f1c40f",
    "福利待遇": "#2ecc71",
    "工作環境": "#3498db",
    "勞動合同": "#9b59b6",
    "管理溝通": "#1abc9c",
    "其他": "#95a5a6",
}


# ─── helpers ────────────────────────────────────────────────────────────────

def create_template() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "month": "2025-01", "raise_date": "2025-01-15",
            "issue_id": "ISS-2025-001", "category": "工資薪酬",
            "description": "要求調整加班費計算方式，按實際工時計算",
            "factory_response": "管理層同意重新審核加班費政策",
            "status": "已解決", "resolution_date": "2025-01-28",
        },
        {
            "month": "2025-01", "raise_date": "2025-01-15",
            "issue_id": "ISS-2025-002", "category": "安全衛生",
            "description": "生產線粉塵過多，需要改善通風設施",
            "factory_response": "已申請採購新型通風設備，預計下月安裝",
            "status": "未解決", "resolution_date": "",
        },
    ])


def load_file(uploaded_file) -> pd.DataFrame | None:
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            return pd.read_csv(uploaded_file, encoding="utf-8-sig")
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(uploaded_file)
        st.error(f"❌ 不支持的格式：{uploaded_file.name}")
        return None
    except Exception as exc:
        st.error(f"❌ 讀取 {uploaded_file.name} 失敗：{exc}")
        return None


def clean_data(df: pd.DataFrame) -> pd.DataFrame | None:
    missing = [c for c in COLUMNS_CONFIG if c not in df.columns]
    if missing:
        friendly = [COLUMNS_CONFIG[c] for c in missing]
        st.error("❌ 缺少欄位：" + "、".join(friendly))
        return None

    df = df.copy()
    df["raise_date"] = pd.to_datetime(df["raise_date"], errors="coerce")
    df["resolution_date"] = pd.to_datetime(df["resolution_date"], errors="coerce")
    df["is_resolved"] = df["status"].str.strip().isin(
        ["已解決", "解決", "resolved", "done", "完成"]
    )
    df["days_to_resolve"] = np.where(
        df["is_resolved"] & df["resolution_date"].notna() & df["raise_date"].notna(),
        (df["resolution_date"] - df["raise_date"]).dt.days,
        np.nan,
    )
    df["month"] = df["month"].astype(str)
    return df


# ─── chart builders ──────────────────────────────────────────────────────────

def monthly_trend_chart(df: pd.DataFrame):
    monthly = (
        df.groupby("month")
        .agg(total=("issue_id", "count"), resolved=("is_resolved", "sum"))
        .reset_index()
        .sort_values("month")
    )
    monthly["rate"] = monthly["resolved"] / monthly["total"] * 100

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=monthly["month"], y=monthly["total"], name="總議題數",
               marker_color="#3498db", opacity=0.6),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=monthly["month"], y=monthly["resolved"], name="已解決",
               marker_color="#2ecc71", opacity=0.85),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["month"], y=monthly["rate"], name="解決率 %",
            mode="lines+markers",
            line=dict(color="#e74c3c", width=3),
            marker=dict(size=8),
        ),
        secondary_y=True,
    )
    fig.update_layout(
        title="月度議題追蹤趨勢", barmode="overlay", height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="議題數量", secondary_y=False)
    fig.update_yaxes(title_text="解決率 (%)", range=[0, 115], secondary_y=True)
    return fig


def top5_chart(df: pd.DataFrame):
    cat_stats = (
        df.groupby("category")
        .agg(total=("issue_id", "count"), resolved=("is_resolved", "sum"))
        .reset_index()
    )
    cat_stats["unresolved"] = cat_stats["total"] - cat_stats["resolved"]
    cat_stats["rate"] = cat_stats["resolved"] / cat_stats["total"] * 100
    cat_stats = cat_stats.sort_values("total", ascending=False).head(5)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=cat_stats["category"], x=cat_stats["resolved"],
        name="已解決", orientation="h", marker_color="#2ecc71",
    ))
    fig.add_trace(go.Bar(
        y=cat_stats["category"], x=cat_stats["unresolved"],
        name="未解決", orientation="h", marker_color="#e74c3c",
    ))
    fig.update_layout(
        title="最常見 Top 5 訴求類別", barmode="stack", height=380,
        xaxis_title="議題數量",
        legend=dict(orientation="h"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig, cat_stats


def resolution_time_chart(df: pd.DataFrame):
    sub = df[df["is_resolved"] & df["days_to_resolve"].notna()].copy()
    if sub.empty:
        return None
    fig = px.histogram(
        sub, x="days_to_resolve", color="category",
        nbins=20, title="解決時間分佈（天數）",
        labels={"days_to_resolve": "解決天數"},
        color_discrete_map=CATEGORY_COLORS,
    )
    fig.update_layout(
        height=350, bargap=0.1,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ─── HTML report ─────────────────────────────────────────────────────────────

def generate_html_report(df: pd.DataFrame, metrics: dict, cat_stats: pd.DataFrame) -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    rate_color = (
        "#27ae60" if metrics["rate"] >= 80
        else "#e67e22" if metrics["rate"] >= 60
        else "#e74c3c"
    )
    avg_str = f"{metrics['avg_days']:.1f}" if not np.isnan(metrics["avg_days"]) else "N/A"

    cat_rows = "".join(
        f"<tr><td>{r['category']}</td><td>{int(r['total'])}</td>"
        f"<td>{int(r['resolved'])}</td><td>{int(r['unresolved'])}</td>"
        f"<td style='color:{'#27ae60' if r['rate']>=80 else '#e74c3c'}'>{r['rate']:.1f}%</td></tr>"
        for _, r in cat_stats.iterrows()
    )

    unresolved_rows = "".join(
        f"<tr><td>{r['month']}</td><td>{r['issue_id']}</td><td>{r['category']}</td>"
        f"<td>{str(r['description'])[:80]}</td><td>{str(r['raise_date'])[:10]}</td></tr>"
        for _, r in df[~df["is_resolved"]].head(30).iterrows()
    )

    monthly = (
        df.groupby("month")
        .agg(total=("issue_id", "count"), resolved=("is_resolved", "sum"))
        .reset_index().sort_values("month")
    )
    monthly["rate"] = monthly["resolved"] / monthly["total"] * 100
    monthly_rows = "".join(
        f"<tr><td>{r['month']}</td><td>{int(r['total'])}</td><td>{int(r['resolved'])}</td>"
        f"<td>{int(r['total']-r['resolved'])}</td><td>{r['rate']:.1f}%</td></tr>"
        for _, r in monthly.iterrows()
    )

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<title>工會對話記錄年度報表</title>
<style>
  body{{font-family:'Microsoft JhengHei',Arial,sans-serif;margin:40px;color:#333;background:#f5f6fa}}
  .header{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:white;padding:30px;border-radius:12px;text-align:center;margin-bottom:30px}}
  .header h1{{margin:0;font-size:1.8em}}
  .header p{{margin:8px 0 0;opacity:.85}}
  .badge{{background:#27ae60;color:white;padding:3px 12px;border-radius:20px;font-size:.8em}}
  .metrics{{display:flex;gap:20px;margin-bottom:30px}}
  .mc{{flex:1;background:white;border-radius:10px;padding:20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
  .mc .val{{font-size:2em;font-weight:700;margin-bottom:4px}}
  .mc .lbl{{color:#7f8c8d;font-size:.9em}}
  .card{{background:white;border-radius:10px;padding:24px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
  .card h2{{margin:0 0 16px;color:#2c3e50;border-left:5px solid #3498db;padding-left:12px;font-size:1.1em}}
  table{{width:100%;border-collapse:collapse}}
  th{{background:#2c3e50;color:white;padding:10px 14px;text-align:left;font-size:.9em}}
  td{{padding:9px 14px;border-bottom:1px solid #ecf0f1;font-size:.9em}}
  tr:nth-child(even){{background:#f8f9fa}}
  .footer{{text-align:center;color:#95a5a6;font-size:.82em;margin-top:40px}}
</style>
</head>
<body>
<div class="header">
  <h1>🏭 工會對話記錄年度進度報表</h1>
  <p>生成日期：{today} &nbsp;|&nbsp; <span class="badge">✓ 驗廠專用報表</span></p>
</div>

<div class="metrics">
  <div class="mc"><div class="val">{metrics['total']}</div><div class="lbl">📋 全年總議題數</div></div>
  <div class="mc"><div class="val" style="color:#27ae60">{metrics['resolved']}</div><div class="lbl">✅ 已解決</div></div>
  <div class="mc"><div class="val" style="color:{rate_color}">{metrics['rate']:.1f}%</div><div class="lbl">📈 整體解決率</div></div>
  <div class="mc"><div class="val" style="color:#e67e22">{avg_str}</div><div class="lbl">⏱️ 平均解決天數</div></div>
</div>

<div class="card">
  <h2>月度議題統計</h2>
  <table><thead><tr><th>月份</th><th>總計</th><th>已解決</th><th>未解決</th><th>解決率</th></tr></thead>
  <tbody>{monthly_rows}</tbody></table>
</div>

<div class="card">
  <h2>最常見訴求類別分析</h2>
  <table><thead><tr><th>議題類別</th><th>總計</th><th>已解決</th><th>未解決</th><th>解決率</th></tr></thead>
  <tbody>{cat_rows}</tbody></table>
</div>

<div class="card">
  <h2>未解決議題清單（最多顯示 30 項）</h2>
  <table><thead><tr><th>月份</th><th>議題編號</th><th>類別</th><th>議題描述</th><th>提出日期</th></tr></thead>
  <tbody>{unresolved_rows}</tbody></table>
</div>

<div class="footer">本報表由工會對話記錄分析系統自動生成，用於展示系統化議題追蹤管理能力</div>
</body></html>"""


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#1a1a2e,#0f3460);padding:24px;
                    border-radius:12px;color:white;text-align:center;margin-bottom:20px">
          <h1 style="margin:0;font-size:1.7em">🏭 工會對話記錄分析系統</h1>
          <p style="margin:8px 0 0;opacity:.85">系統化追蹤工人訴求 · 向驗廠官展示管理成效</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 📂 上傳記錄文件")
        uploaded_files = st.file_uploader(
            "支持 CSV / Excel，可同時上傳多個月份",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
        )
        st.divider()
        st.markdown("### 📋 下載填寫模板")
        tpl_csv = create_template().to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "⬇️ 下載 CSV 模板", data=tpl_csv,
            file_name="工會對話記錄模板.csv", mime="text/csv",
            use_container_width=True,
        )
        st.divider()
        st.markdown("### 📌 必填欄位")
        for k, v in COLUMNS_CONFIG.items():
            st.markdown(f"- `{k}` — {v}")

    # ── welcome ───────────────────────────────────────────────────────────────
    if not uploaded_files:
        st.info("👈 請從左側上傳月度對話記錄文件開始分析")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**📁 支持格式**\n- CSV（推薦，UTF-8 BOM）\n- Excel（.xlsx / .xls）\n- 可同時上傳多個月份")
        with c2:
            st.markdown("**📊 分析功能**\n- 全年議題統計與解決率\n- 最常見 Top 5 訴求\n- 平均解決時間\n- 月度趨勢圖表")
        with c3:
            st.markdown("**📤 輸出功能**\n- 可視化進度報表\n- 可下載 HTML 驗廠報告\n- 未解決議題清單\n- 按類別/月份篩選")
        return

    # ── load & combine ────────────────────────────────────────────────────────
    frames = []
    for f in uploaded_files:
        raw = load_file(f)
        if raw is None:
            continue
        clean = clean_data(raw)
        if clean is None:
            continue
        frames.append(clean)
        st.success(f"✅ {f.name} — {len(clean)} 筆議題已載入")

    if not frames:
        st.error("沒有可用數據，請檢查文件格式是否符合模板")
        return

    df = pd.concat(frames, ignore_index=True)
    total = len(df)
    resolved = int(df["is_resolved"].sum())
    unresolved_count = total - resolved
    rate = resolved / total * 100 if total else 0
    avg_days = df["days_to_resolve"].dropna().mean()
    avg_days_str = f"{avg_days:.1f} 天" if not np.isnan(avg_days) else "N/A"
    metrics = {"total": total, "resolved": resolved, "unresolved": unresolved_count,
               "rate": rate, "avg_days": avg_days}

    # ── 1. key metrics ────────────────────────────────────────────────────────
    st.markdown("### 📊 全年總覽")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 全年總議題數", f"{total} 項")
    c2.metric("✅ 已解決", f"{resolved} 項", f"+{rate:.1f}% 解決率")
    c3.metric("⏳ 未解決", f"{unresolved_count} 項")
    c4.metric("⏱️ 平均解決時間", avg_days_str)
    st.progress(rate / 100, text=f"整體解決率 {rate:.1f}%")

    # ── 2. monthly trend ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 月度議題趨勢")
    st.plotly_chart(monthly_trend_chart(df), use_container_width=True)

    # ── 3. top5 + resolution time ─────────────────────────────────────────────
    st.markdown("---")
    left, right = st.columns([3, 2])
    with left:
        st.markdown("### 🏆 最常見 Top 5 訴求類別")
        fig_cat, cat_stats = top5_chart(df)
        st.plotly_chart(fig_cat, use_container_width=True)
    with right:
        st.markdown("### ⏱️ 解決時間分佈")
        fig_t = resolution_time_chart(df)
        if fig_t:
            st.plotly_chart(fig_t, use_container_width=True)
        else:
            st.info("尚無已解決議題的時間數據")

    # ── 4. unresolved this month ──────────────────────────────────────────────
    st.markdown("---")
    latest_month = df["month"].max()
    pending = df[(df["month"] == latest_month) & (~df["is_resolved"])]
    st.markdown(f"### ⚠️ 本月未解決議題（{latest_month}）")
    if pending.empty:
        st.success(f"🎉 {latest_month} 所有議題均已解決！")
    else:
        st.warning(f"共 {len(pending)} 項議題尚待處理")
        show_cols = [c for c in ["issue_id", "category", "description", "raise_date", "factory_response"] if c in pending.columns]
        rename_map = {"issue_id": "議題編號", "category": "類別", "description": "議題描述",
                      "raise_date": "提出日期", "factory_response": "廠方回應"}
        st.dataframe(pending[show_cols].rename(columns=rename_map), use_container_width=True, hide_index=True)

    # ── 5. full data viewer ───────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📋 查看 & 篩選完整議題記錄", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        sel_month = fc1.selectbox("月份", ["全部"] + sorted(df["month"].unique().tolist()))
        sel_cat = fc2.selectbox("類別", ["全部"] + sorted(df["category"].unique().tolist()))
        sel_status = fc3.selectbox("狀態", ["全部", "已解決", "未解決"])

        fdf = df.copy()
        if sel_month != "全部":
            fdf = fdf[fdf["month"] == sel_month]
        if sel_cat != "全部":
            fdf = fdf[fdf["category"] == sel_cat]
        if sel_status == "已解決":
            fdf = fdf[fdf["is_resolved"]]
        elif sel_status == "未解決":
            fdf = fdf[~fdf["is_resolved"]]

        view_cols = [c for c in ["month", "issue_id", "category", "description", "status",
                                  "raise_date", "resolution_date", "days_to_resolve"] if c in fdf.columns]
        st.dataframe(fdf[view_cols], use_container_width=True, hide_index=True)
        st.caption(f"顯示 {len(fdf)} / {len(df)} 筆記錄")

    # ── 6. download ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📤 下載驗廠報表")
    dl1, dl2 = st.columns(2)
    with dl1:
        html_rpt = generate_html_report(df, metrics, cat_stats)
        st.download_button(
            "⬇️ 下載 HTML 進度報表（驗廠用）",
            data=html_rpt.encode("utf-8"),
            file_name=f"工會對話記錄報表_{datetime.now().strftime('%Y%m%d')}.html",
            mime="text/html",
            use_container_width=True,
            type="primary",
        )
    with dl2:
        csv_export = df.drop(columns=["is_resolved"], errors="ignore").to_csv(
            index=False, encoding="utf-8-sig"
        )
        st.download_button(
            "⬇️ 下載整合後 CSV 數據",
            data=csv_export.encode("utf-8-sig"),
            file_name=f"工會議題整合數據_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
