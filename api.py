"""
Project FORESIGHT — Planning Dashboard (D5)
==============================================
Interactive Streamlit dashboard for the NorthBay Living ops team.

Run locally:
    streamlit run app/app.py

Deploy free on Streamlit Community Cloud:
    1. Push this repo to GitHub.
    2. Go to https://streamlit.io/cloud -> "New app" -> point at app/app.py.
    3. Make sure data/processed/*.csv are committed (or regenerate on
       startup — see the "Data availability" note below).
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

st.set_page_config(
    page_title="FORESIGHT — NorthBay Living Planning Dashboard",
    page_icon="📦",
    layout="wide",
)

DATA_DIR = ROOT / "data" / "processed"


@st.cache_data
def load_data():
    """Load pre-computed features and risk scores. If they don't exist yet
    (fresh clone), run the pipeline end-to-end once."""
    features_path = DATA_DIR / "features.csv"
    risk_path = DATA_DIR / "risk_scores.csv"

    if not features_path.exists() or not risk_path.exists():
        return None, None

    features = pd.read_csv(features_path, parse_dates=["week_start"])
    risk = pd.read_csv(risk_path)
    return features, risk


def empty_state():
    st.warning(
        "⚠️ No processed data found yet.\n\n"
        "Run the pipeline first from the project root:\n\n"
        "```bash\n"
        "python src/generate_data.py\n"
        "python src/pipeline.py\n"
        "python src/forecast.py\n"
        "python src/risk.py\n"
        "```\n"
        "Then reload this dashboard."
    )


def main():
    st.title("📦 FORESIGHT — Demand & Inventory Planning Dashboard")
    st.caption("NorthBay Living · Prepared by the Data Science & Analytics engagement team")

    features, risk = load_data()

    if features is None or risk is None:
        empty_state()
        return

    # ---------------- Sidebar filters ----------------
    st.sidebar.header("Filters")
    categories = sorted(risk["category"].unique())
    selected_categories = st.sidebar.multiselect(
        "Category", options=categories, default=categories
    )

    quadrants = sorted(risk["quadrant"].unique())
    selected_quadrants = st.sidebar.multiselect(
        "Risk quadrant", options=quadrants, default=quadrants
    )

    sku_search = st.sidebar.text_input("Search SKU ID", "")

    filtered_risk = risk[
        risk["category"].isin(selected_categories)
        & risk["quadrant"].isin(selected_quadrants)
    ]
    if sku_search:
        filtered_risk = filtered_risk[
            filtered_risk["sku_id"].str.contains(sku_search, case=False, na=False)
        ]

    if filtered_risk.empty:
        st.info("No SKUs match the current filters. Try widening your selection.")
        return

    # ---------------- Top KPIs ----------------
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("SKUs shown", f"{filtered_risk['sku_id'].nunique():,}")
    col2.metric(
        "Reorder now",
        f"{(filtered_risk['quadrant'] == 'Reorder now').sum():,}",
        help="High stockout risk — raise a replenishment order.",
    )
    col3.metric(
        "Markdown / clear",
        f"{(filtered_risk['quadrant'] == 'Markdown / clear').sum():,}",
        help="Overstocked — promote or discount.",
    )
    col4.metric(
        "Total Rs. at stake",
        f"₹{filtered_risk['rupee_value_at_stake'].sum():,.0f}",
    )

    st.divider()

    # ---------------- Decisioning grid ----------------
    st.subheader("Stockout vs. Overstock Decisioning Grid")
    scatter_df = filtered_risk.copy()
    scatter_df["bubble_size"] = (
        scatter_df["rupee_value_at_stake"].clip(lower=1) ** 0.5
    )
    st.scatter_chart(
        scatter_df,
        x="projected_coverage_weeks",
        y="weeks_of_stock_on_hand",
        color="quadrant",
        size="bubble_size",
    )
    st.caption(
        "X-axis: weeks of coverage before stockout (lower = more urgent). "
        "Y-axis: weeks of stock on hand (higher = more overstocked). "
        "Bubble size ~ rupee value at stake."
    )

    st.divider()

    # ---------------- Prioritised action list ----------------
    st.subheader("Prioritised Reorder / Markdown List")
    tab1, tab2, tab3 = st.tabs(["🔴 Reorder now", "🟡 Markdown / clear", "🟠 Watch / volatile"])

    with tab1:
        reorder = filtered_risk[filtered_risk["quadrant"] == "Reorder now"].sort_values(
            "rupee_value_at_stake", ascending=False
        )
        st.dataframe(
            reorder[
                ["sku_id", "category", "subcategory", "forecast_weekly_demand",
                 "on_hand_units", "projected_coverage_weeks", "sales_at_risk_rs"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        if reorder.empty:
            st.info("No SKUs currently need reordering.")

    with tab2:
        markdown = filtered_risk[filtered_risk["quadrant"] == "Markdown / clear"].sort_values(
            "rupee_value_at_stake", ascending=False
        )
        st.dataframe(
            markdown[
                ["sku_id", "category", "subcategory", "forecast_weekly_demand",
                 "on_hand_units", "weeks_of_stock_on_hand", "capital_locked_rs"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        if markdown.empty:
            st.info("No SKUs currently flagged for markdown.")

    with tab3:
        watch = filtered_risk[filtered_risk["quadrant"] == "Watch / volatile"].sort_values(
            "rupee_value_at_stake", ascending=False
        )
        st.dataframe(watch, use_container_width=True, hide_index=True)
        if watch.empty:
            st.info("No SKUs currently flagged as volatile.")

    st.divider()

    # ---------------- Forecast vs actual for a chosen SKU ----------------
    st.subheader("Forecast vs. Actual — Single SKU Drill-down")
    sku_options = sorted(filtered_risk["sku_id"].unique())
    chosen_sku = st.selectbox("Choose a SKU", sku_options)

    sku_history = features[features["sku_id"] == chosen_sku].sort_values("week_start")
    if not sku_history.empty:
        chart_df = sku_history.set_index("week_start")[["units_sold", "roll_mean_4"]]
        chart_df.columns = ["Actual units sold", "4-week rolling average"]
        st.line_chart(chart_df)

        sku_row = filtered_risk[filtered_risk["sku_id"] == chosen_sku]
        if not sku_row.empty:
            r = sku_row.iloc[0]
            st.write(
                f"**Quadrant:** {r['quadrant']} — {r['recommended_action']} "
                f"(₹{r['rupee_value_at_stake']:,.0f} at stake)"
            )
    else:
        st.info("No history available for this SKU yet.")
    st.divider()
    st.caption(
        "Data is simulated for the Zidio Data Science internship engagement "
        "(Project FORESIGHT). Not real NorthBay Living data."
    )


if __name__ == "__main__":
    main()