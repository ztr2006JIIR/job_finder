from pathlib import Path
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from src.analyzer import count_skill_frequency, count_top_cities, get_statistics
from src.ai_recommender import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AIRecommendationError,
    prepare_job_candidates,
    recommend_jobs_with_ai,
    recommendations_to_dataframe,
)
from src.cleaner import clean_salary_column
from src.crawler_51job import CITY_CODES, crawl_51job
from src.data_loader import load_jobs
from src.exporter import export_to_excel

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_CSV = BASE_DIR / "data" / "sample_jobs.csv"
LIVE_CSV = BASE_DIR / "data" / "live_51job_jobs.csv"


def load_live_jobs():
    """加载实时抓取结果。"""
    if not LIVE_CSV.exists():
        return pd.DataFrame()
    return load_jobs(LIVE_CSV)


def save_live_jobs(df):
    """保存实时抓取结果，方便页面重启后继续使用。"""
    LIVE_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(LIVE_CSV, index=False, encoding="utf-8-sig")


def merge_jobs(old_df, new_df):
    """合并新旧岗位，按链接优先去重。"""
    frames = [df for df in [old_df, new_df] if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    if "url" in merged.columns:
        merged = merged.drop_duplicates(subset=["url"], keep="last")
    else:
        keys = [col for col in ["title", "company", "city", "salary"] if col in merged.columns]
        if keys:
            merged = merged.drop_duplicates(subset=keys, keep="last")
    return merged.reset_index(drop=True)


def filter_live_jobs_by_query(df, keyword, city):
    """只展示当前抓取条件对应的实时数据。"""
    if df is None or df.empty:
        return pd.DataFrame()

    filtered_df = df.copy()
    if "search_keyword" in filtered_df.columns and keyword:
        filtered_df = filtered_df[filtered_df["search_keyword"].fillna("") == keyword]
    if "search_city" in filtered_df.columns and city and city != "全国":
        filtered_df = filtered_df[filtered_df["search_city"].fillna("") == city]
    return filtered_df.reset_index(drop=True)


def schedule_auto_refresh(enabled, interval_seconds):
    """在自动抓取模式下等待一段时间后刷新页面。"""
    if enabled:
        st.caption(f"自动抓取已开启，约 {interval_seconds} 秒后刷新。")
        time.sleep(interval_seconds)
        st.rerun()


def get_ai_config():
    """读取本地 AI API 配置。"""
    try:
        api_key = st.secrets.get("OPENAI_API_KEY", "")
        base_url = st.secrets.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
        model = st.secrets.get("OPENAI_MODEL", DEFAULT_MODEL)
    except Exception:
        api_key = ""
        base_url = DEFAULT_BASE_URL
        model = DEFAULT_MODEL
    return api_key, base_url, model


def render_ai_recommendation_section(filtered):
    """展示 AI 岗位推荐区域。"""
    st.markdown("---")
    st.subheader("AI 岗位推荐")

    if filtered is None or filtered.empty:
        st.info("当前没有可推荐的岗位，请先上传、抓取或筛选岗位数据。")
        return

    api_key, base_url, model = get_ai_config()
    if not api_key:
        st.warning("缺少 AI API 配置，请在 .streamlit/secrets.toml 中配置 OPENAI_API_KEY。")

    with st.form("ai_recommendation_form"):
        col_left, col_right = st.columns(2)
        with col_left:
            background = st.text_area(
                "个人背景",
                placeholder="请填写求职者的学历、经历、行业背景等信息。",
                height=100,
            )
            skills = st.text_input("已掌握技能", placeholder="请填写求职者已掌握的技能。")
            target_role = st.text_input("目标岗位", placeholder="请填写求职者希望寻找的岗位方向。")
        with col_right:
            preferred_city = st.text_input("期望城市", placeholder="请填写求职者期望工作的城市。")
            expected_salary = st.text_input("期望薪资", placeholder="请填写求职者期望的薪资范围。")
            other_requirements = st.text_area(
                "其他要求",
                placeholder="请填写工作时间、公司类型、岗位性质等其他偏好。",
                height=100,
            )

        submitted = st.form_submit_button("开始 AI 推荐")

    if submitted:
        user_profile = {
            "个人背景": background,
            "已掌握技能": skills,
            "目标岗位": target_role,
            "期望城市": preferred_city,
            "期望薪资": expected_salary,
            "其他要求": other_requirements,
        }
        jobs = prepare_job_candidates(filtered, limit=20)
        with st.spinner("AI 正在分析岗位匹配度..."):
            try:
                result = recommend_jobs_with_ai(
                    api_key=api_key,
                    user_profile=user_profile,
                    jobs=jobs,
                    base_url=base_url,
                    model=model,
                )
                st.session_state["ai_recommendation_result"] = result
            except AIRecommendationError as error:
                st.error(str(error))
            except Exception as error:
                st.error(f"AI 推荐失败：{error}")

    result = st.session_state.get("ai_recommendation_result")
    if not result:
        return

    if result.get("parse_error"):
        st.warning(result["parse_error"])
        st.text_area("AI 原始回答", value=result.get("raw_text", ""), height=220)
        return

    recommendation_df = recommendations_to_dataframe(result)
    if recommendation_df.empty:
        st.info("AI 没有返回可展示的岗位推荐。")
    else:
        st.dataframe(
            recommendation_df,
            use_container_width=True,
            column_config={
                "岗位链接": st.column_config.LinkColumn("岗位链接"),
                "匹配分": st.column_config.ProgressColumn("匹配分", min_value=0, max_value=100),
            },
        )

    if result.get("overall_advice"):
        st.markdown("**整体求职建议**")
        st.write(result["overall_advice"])


def main():
    """Streamlit 主程序：展示招聘分析平台界面。"""
    st.set_page_config(page_title="Job Analyzer", layout="wide")
    st.title("招聘信息分析平台 MVP")
    st.write("上传招聘 CSV 数据后，可查看岗位表格、筛选城市、搜索关键词，并导出结果。")

    source_mode = st.radio(
        "选择数据来源",
        ["使用示例数据", "上传 CSV", "实时抓取前程无忧"],
        index=2,
        horizontal=True,
    )
    df = load_jobs(SAMPLE_CSV)
    auto_refresh = False
    refresh_interval = 30

    if source_mode == "上传 CSV":
        uploaded_file = st.file_uploader("上传 jobs.csv 文件", type=["csv"])
        if uploaded_file is not None:
            df = load_jobs(uploaded_file)
        else:
            st.info("当前未上传文件，已加载示例数据。")
    elif source_mode == "实时抓取前程无忧":
        col_keyword, col_city, col_pages, col_interval = st.columns([2, 1, 1, 1])
        with col_keyword:
            crawl_keyword = st.text_input("岗位关键词", value=st.session_state.get("crawl_keyword", ""))
        with col_city:
            crawl_city = st.selectbox("城市", options=list(CITY_CODES.keys()), index=0)
        with col_pages:
            crawl_pages = st.number_input("每次抓取页数", min_value=1, max_value=5, value=1, step=1)
        with col_interval:
            refresh_interval = st.selectbox("自动间隔", options=[10, 30, 60], index=1, format_func=lambda value: f"{value} 秒")

        col_manual, col_auto, col_clear = st.columns([1, 1, 1])
        with col_manual:
            manual_crawl = st.button("立即抓取")
        with col_auto:
            auto_refresh = st.toggle("自动抓取", value=st.session_state.get("auto_refresh_51job", True))
        with col_clear:
            clear_live_data = st.button("清空实时数据")

        st.session_state["crawl_keyword"] = crawl_keyword
        st.session_state["auto_refresh_51job"] = auto_refresh

        if clear_live_data:
            if LIVE_CSV.exists():
                LIVE_CSV.unlink()
            st.session_state.pop("last_crawl_at", None)
            st.success("实时数据已清空。")

        live_df = load_live_jobs()
        df = filter_live_jobs_by_query(live_df, crawl_keyword.strip(), crawl_city)
        now = time.time()
        last_crawl_at = st.session_state.get("last_crawl_at", 0)
        keyword_ready = bool(crawl_keyword.strip())
        should_auto_crawl = keyword_ready and auto_refresh and now - last_crawl_at >= refresh_interval
        should_crawl = keyword_ready and (manual_crawl or should_auto_crawl)

        if should_crawl:
            with st.spinner("正在抓取前程无忧公开搜索结果..."):
                try:
                    result = crawl_51job(crawl_keyword, crawl_city, pages=crawl_pages)
                    new_jobs = result.jobs.copy()
                    if not new_jobs.empty:
                        new_jobs["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        new_jobs["search_keyword"] = crawl_keyword.strip()
                        new_jobs["search_city"] = crawl_city
                    before_count = len(filter_live_jobs_by_query(live_df, crawl_keyword.strip(), crawl_city))
                    live_df = merge_jobs(live_df, new_jobs)
                    df = filter_live_jobs_by_query(live_df, crawl_keyword.strip(), crawl_city)
                    after_count = len(df)
                    if not live_df.empty:
                        save_live_jobs(live_df)
                    st.session_state["last_crawl_at"] = time.time()
                    if result.jobs.empty:
                        st.warning(result.message or "没有抓取到岗位数据。")
                    elif result.message:
                        st.success(f"{result.message} 新增 {after_count - before_count} 条，当前累计 {after_count} 条。")
                except Exception as error:
                    st.error(f"抓取失败：{error}")
                    st.session_state["last_crawl_at"] = time.time()
        elif manual_crawl and not keyword_ready:
            st.warning("请先输入岗位关键词，再开始抓取。")
        else:
            if df.empty:
                st.info("请输入岗位关键词；自动抓取开启后会按当前关键词和城市更新数据。")
            else:
                st.info(f"已加载实时数据 {len(df)} 条。")

    if df is None or df.empty:
        st.warning("没有可用的招聘数据，请上传有效的 jobs.csv。")
        schedule_auto_refresh(auto_refresh, refresh_interval)
        return

    df = clean_salary_column(df)

    with st.sidebar:
        st.header("筛选条件")
        keyword = st.text_input("岗位关键词搜索", value="")
        cities = sorted(df["city"].dropna().unique())
        selected_cities = st.multiselect("选择城市", options=cities, default=cities)
        st.markdown("---")
        st.write("数据说明：薪资已清洗为平均月薪。面议岗位不参与平均薪资计算。")

    filtered = df.copy()
    if keyword:
        mask = df["title"].str.contains(keyword, case=False, na=False) | df["description"].str.contains(keyword, case=False, na=False) | df["tags"].str.contains(keyword, case=False, na=False)
        filtered = filtered[mask]
    if selected_cities:
        filtered = filtered[filtered["city"].isin(selected_cities)]

    stats = get_statistics(filtered)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("岗位总数", stats["total_jobs"])
    col2.metric("平均薪资（月薪, RMB)", f"{stats['average_salary']:.0f}" if stats["average_salary"] else "无数据")
    col3.metric("有效薪资岗位", stats["salary_count"])
    col4.metric("当前筛选行数", len(filtered))

    st.subheader("城市岗位数量 Top 10")
    top_cities = count_top_cities(filtered)
    st.table(top_cities)

    st.subheader("技能词频 Top 20")
    top_skills = count_skill_frequency(filtered)
    st.table(top_skills)

    st.subheader("筛选后岗位表格")
    st.dataframe(filtered.drop(columns=["salary_min", "salary_max"], errors="ignore"), use_container_width=True)

    render_ai_recommendation_section(filtered)

    excel_bytes = export_to_excel(filtered)
    st.download_button(
        label="导出筛选结果为 Excel",
        data=excel_bytes,
        file_name="job_analyzer_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    schedule_auto_refresh(auto_refresh, refresh_interval)


if __name__ == "__main__":
    main()
