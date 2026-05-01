from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import math
import re
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DATASET: dict[str, Any] = {}

app = FastAPI(title="AI Analytics Dashboard API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload")
async def upload_csv(request: Request) -> dict[str, Any]:
    raw_csv = await request.body()
    if not raw_csv:
        raise HTTPException(status_code=400, detail="Upload a non-empty CSV file.")

    filename = (
        request.headers.get("x-filename")
        or request.query_params.get("filename")
        or "uploaded.csv"
    )

    try:
        df = pd.read_csv(BytesIO(raw_csv))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read CSV: {exc}") from exc

    if df.empty or df.shape[1] == 0:
        raise HTTPException(status_code=400, detail="The CSV has no usable data.")

    df.columns = normalize_columns(df.columns)
    DATASET.clear()
    DATASET.update(
        {
            "df": df,
            "filename": filename,
            "uploaded_at": datetime.now(timezone.utc),
        }
    )

    profile = build_profile(df, filename)
    return clean_json(
        {
            "message": "CSV uploaded",
            "profile": profile,
            "result": build_default_chart(df),
        }
    )


@app.get("/profile")
def profile() -> dict[str, Any]:
    df = current_dataframe()
    return clean_json(build_profile(df, DATASET["filename"]))


@app.post("/query")
def query_dataset(payload: QueryRequest) -> dict[str, Any]:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question about the dataset.")

    df = current_dataframe()
    result = interpret_query(df, question)
    return clean_json({"question": question, **result})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/{asset_name}")
def static_asset(asset_name: str) -> FileResponse:
    allowed = {"script.js", "style.css", "sample_sales.csv"}
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(BASE_DIR / asset_name)


def current_dataframe() -> pd.DataFrame:
    if "df" not in DATASET:
        raise HTTPException(status_code=404, detail="No dataset uploaded yet.")
    return DATASET["df"]


def normalize_columns(columns: Any) -> list[str]:
    seen: dict[str, int] = {}
    normalized = []
    for index, column in enumerate(columns):
        name = str(column).strip() or f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        normalized.append(name)
    return normalized


def build_profile(df: pd.DataFrame, filename: str) -> dict[str, Any]:
    column_groups = classify_columns(df)
    numeric_cols = column_groups["numeric"]
    date_cols = column_groups["date"]

    columns = []
    for column in df.columns:
        series = df[column]
        if column in numeric_cols:
            kind = "number"
        elif column in date_cols:
            kind = "date"
        else:
            kind = "category"

        columns.append(
            {
                "name": column,
                "type": kind,
                "dtype": str(series.dtype),
                "missing": int(series.isna().sum()),
                "missingPct": pct(series.isna().sum(), len(series)),
                "unique": int(series.nunique(dropna=True)),
                "sample": [clean_json(value) for value in series.dropna().head(3).tolist()],
            }
        )

    numeric_summary = []
    for column in numeric_cols:
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        if series.empty:
            continue
        numeric_summary.append(
            {
                "column": column,
                "min": round_number(series.min()),
                "max": round_number(series.max()),
                "mean": round_number(series.mean()),
                "median": round_number(series.median()),
                "std": round_number(series.std()),
            }
        )

    return {
        "filename": filename,
        "uploadedAt": clean_json(DATASET.get("uploaded_at")),
        "rows": int(len(df)),
        "columnCount": int(df.shape[1]),
        "missingCells": int(df.isna().sum().sum()),
        "duplicateRows": int(df.duplicated().sum()),
        "columns": columns,
        "numericSummary": numeric_summary,
        "preview": dataframe_preview(df),
        "suggestedQuestions": suggested_questions(df),
        "insights": profile_insights(df, column_groups),
    }


def classify_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    numeric = df.select_dtypes(include="number").columns.tolist()
    date = []

    for column in df.columns:
        if column in numeric:
            continue
        parsed = pd.to_datetime(df[column], errors="coerce")
        parse_rate = parsed.notna().mean() if len(parsed) else 0
        if parse_rate >= 0.7 and parsed.nunique(dropna=True) > 1:
            date.append(column)

    category = [column for column in df.columns if column not in numeric and column not in date]
    return {"numeric": numeric, "date": date, "category": category}


def dataframe_preview(df: pd.DataFrame) -> list[dict[str, Any]]:
    preview = df.head(8).where(pd.notnull(df.head(8)), None)
    return clean_json(preview.to_dict(orient="records"))


def profile_insights(df: pd.DataFrame, column_groups: dict[str, list[str]]) -> list[str]:
    insights = [
        f"Loaded {len(df):,} rows across {df.shape[1]:,} columns.",
    ]

    if column_groups["numeric"]:
        joined = ", ".join(column_groups["numeric"][:3])
        insights.append(f"Numeric measures detected: {joined}.")

    if column_groups["date"]:
        insights.append(f"Date fields detected: {', '.join(column_groups['date'][:2])}.")

    missing_cells = int(df.isna().sum().sum())
    if missing_cells:
        insights.append(f"{missing_cells:,} missing cells are present and may affect analysis.")
    else:
        insights.append("No missing cells were found in the uploaded preview.")

    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows:
        insights.append(f"{duplicate_rows:,} duplicate rows were detected.")

    return insights


def suggested_questions(df: pd.DataFrame) -> list[str]:
    groups = classify_columns(df)
    numeric = groups["numeric"]
    category = groups["category"]
    date = groups["date"]

    questions = []
    if numeric and category:
        questions.append(f"sum of {numeric[0]} by {category[0]}")
        questions.append(f"average {numeric[0]} by {category[0]}")
    if numeric and date:
        questions.append(f"{numeric[0]} over time")
    if len(numeric) >= 2:
        questions.append(f"relationship between {numeric[0]} and {numeric[1]}")
    if category:
        questions.append(f"count by {category[0]}")

    return questions[:5]


def interpret_query(df: pd.DataFrame, question: str) -> dict[str, Any]:
    groups = classify_columns(df)
    numeric = groups["numeric"]
    category = groups["category"]
    date = groups["date"]

    aggregate = infer_aggregate(question)
    mentioned_numeric = mentioned_columns(question, numeric)
    mentioned_category = mentioned_columns(question, category)
    mentioned_date = mentioned_columns(question, date)
    metric = mentioned_numeric[0] if mentioned_numeric else (numeric[0] if numeric else None)
    limit = infer_limit(question)
    wants_pie = contains_any(question, ["pie", "share", "percent", "percentage", "proportion", "breakdown"])

    wants_scatter = contains_any(question, ["relationship", "correlation", "compare", " vs ", " versus "])
    if wants_scatter and len(mentioned_numeric) >= 2:
        return scatter_chart(df, mentioned_numeric[0], mentioned_numeric[1], question)
    if wants_scatter and len(numeric) >= 2:
        return scatter_chart(df, numeric[0], numeric[1], question)

    wants_time = contains_any(question, ["over time", "trend", "date", "month", "year", "daily", "weekly"])
    if metric and (mentioned_date or (wants_time and date)):
        return time_chart(df, metric, mentioned_date[0] if mentioned_date else date[0], aggregate)

    dimension = (
        pick_column_after_anchor(question, category + date)
        or (mentioned_category[0] if mentioned_category else None)
        or (mentioned_date[0] if mentioned_date else None)
    )

    wants_count = aggregate == "count" or (not metric and category)
    if dimension:
        if dimension in date and metric:
            return time_chart(df, metric, dimension, aggregate)
        return aggregate_chart(
            df=df,
            metric=None if wants_count else metric,
            dimension=dimension,
            aggregate=aggregate,
            limit=limit,
            chart_type="pie" if wants_pie else "bar",
        )

    if metric:
        return histogram_chart(df, metric)

    return build_default_chart(df)


def build_default_chart(df: pd.DataFrame) -> dict[str, Any]:
    groups = classify_columns(df)
    if groups["numeric"] and groups["category"]:
        return aggregate_chart(df, groups["numeric"][0], groups["category"][0], "sum", 12)
    if groups["numeric"] and groups["date"]:
        return time_chart(df, groups["numeric"][0], groups["date"][0], "sum")
    if len(groups["numeric"]) >= 2:
        return scatter_chart(df, groups["numeric"][0], groups["numeric"][1], "relationship")
    if groups["category"]:
        return aggregate_chart(df, None, groups["category"][0], "count", 12)
    if groups["numeric"]:
        return histogram_chart(df, groups["numeric"][0])

    raise HTTPException(status_code=400, detail="No chartable columns were found.")


def aggregate_chart(
    df: pd.DataFrame,
    metric: str | None,
    dimension: str,
    aggregate: str,
    limit: int,
    chart_type: str = "bar",
) -> dict[str, Any]:
    work = df[[dimension] + ([metric] if metric else [])].copy()
    work[dimension] = work[dimension].fillna("Missing").astype(str)

    if metric:
        work[metric] = pd.to_numeric(work[metric], errors="coerce")
        grouped = work.groupby(dimension, dropna=False)[metric].agg(aggregate).dropna()
        measure_name = f"{aggregate} {metric}"
    else:
        grouped = work.groupby(dimension, dropna=False).size()
        measure_name = "count"

    if grouped.empty:
        raise HTTPException(status_code=400, detail="No data matched that question.")

    grouped = grouped.sort_values(ascending=False).head(limit)
    labels = [str(value) for value in grouped.index.tolist()]
    values = [round_number(value) for value in grouped.tolist()]

    table = [{dimension: label, measure_name: value} for label, value in zip(labels, values)]
    title = f"{measure_name} by {dimension}"

    chart = {
        "title": title,
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 48, "right": 24, "top": 48, "bottom": 72},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"name": measure_name, "type": "bar", "data": values}],
    }

    if chart_type == "pie":
        chart = {
            "title": title,
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "name": measure_name,
                    "type": "pie",
                    "radius": ["42%", "70%"],
                    "center": ["50%", "54%"],
                    "data": [
                        {"name": label, "value": value}
                        for label, value in zip(labels, values)
                    ],
                    "label": {"formatter": "{b}: {d}%"},
                }
            ],
        }

    return {
        "intent": {
            "chartType": chart_type,
            "metric": metric,
            "dimension": dimension,
            "aggregate": aggregate if metric else "count",
        },
        "chart": chart,
        "table": table,
        "insight": aggregate_insight(labels, values, measure_name),
    }


def time_chart(df: pd.DataFrame, metric: str, date_column: str, aggregate: str) -> dict[str, Any]:
    dates = pd.to_datetime(df[date_column], errors="coerce")
    values = pd.to_numeric(df[metric], errors="coerce")
    work = pd.DataFrame({"date": dates, "value": values}).dropna()

    if work.empty:
        raise HTTPException(status_code=400, detail="No date and numeric data matched that question.")

    if work["date"].nunique() > 40:
        work["bucket"] = work["date"].dt.to_period("M").dt.to_timestamp()
    else:
        work["bucket"] = work["date"].dt.normalize()

    grouped = work.groupby("bucket")["value"].agg(aggregate).sort_index().tail(36)
    labels = [value.strftime("%Y-%m-%d") for value in grouped.index.tolist()]
    series_values = [round_number(value) for value in grouped.tolist()]
    measure_name = f"{aggregate} {metric}"

    return {
        "intent": {
            "chartType": "line",
            "metric": metric,
            "dimension": date_column,
            "aggregate": aggregate,
        },
        "chart": {
            "title": f"{measure_name} over {date_column}",
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 24, "top": 48, "bottom": 72},
            "xAxis": {"type": "category", "data": labels},
            "yAxis": {"type": "value"},
            "series": [{"name": measure_name, "type": "line", "smooth": True, "data": series_values}],
        },
        "table": [{date_column: label, measure_name: value} for label, value in zip(labels, series_values)],
        "insight": time_insight(labels, series_values, measure_name),
    }


def scatter_chart(df: pd.DataFrame, x_column: str, y_column: str, question: str) -> dict[str, Any]:
    work = df[[x_column, y_column]].apply(pd.to_numeric, errors="coerce").dropna().head(300)
    if work.empty:
        raise HTTPException(status_code=400, detail="No numeric data matched that comparison.")

    points = [[round_number(row[x_column]), round_number(row[y_column])] for _, row in work.iterrows()]
    correlation = work[x_column].corr(work[y_column]) if len(work) > 1 else None
    insight = scatter_insight(x_column, y_column, correlation)

    return {
        "intent": {
            "chartType": "scatter",
            "metric": y_column,
            "dimension": x_column,
            "aggregate": "none",
            "question": question,
        },
        "chart": {
            "title": f"{y_column} vs {x_column}",
            "tooltip": {"trigger": "item"},
            "grid": {"left": 56, "right": 24, "top": 48, "bottom": 56},
            "xAxis": {"type": "value", "name": x_column},
            "yAxis": {"type": "value", "name": y_column},
            "series": [{"name": f"{y_column} vs {x_column}", "type": "scatter", "data": points}],
        },
        "table": [{x_column: point[0], y_column: point[1]} for point in points[:25]],
        "insight": insight,
    }


def histogram_chart(df: pd.DataFrame, metric: str) -> dict[str, Any]:
    values = pd.to_numeric(df[metric], errors="coerce").dropna()
    if values.empty:
        raise HTTPException(status_code=400, detail="No numeric data matched that question.")

    bins = min(10, max(3, int(values.nunique())))
    grouped = pd.cut(values, bins=bins).value_counts(sort=False)
    labels = [str(label) for label in grouped.index.tolist()]
    counts = [int(value) for value in grouped.tolist()]

    return {
        "intent": {
            "chartType": "bar",
            "metric": metric,
            "dimension": "range",
            "aggregate": "count",
        },
        "chart": {
            "title": f"Distribution of {metric}",
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 24, "top": 48, "bottom": 88},
            "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 30}},
            "yAxis": {"type": "value"},
            "series": [{"name": "rows", "type": "bar", "data": counts}],
        },
        "table": [{"range": label, "rows": count} for label, count in zip(labels, counts)],
        "insight": aggregate_insight(labels, counts, "rows"),
    }


def infer_aggregate(question: str) -> str:
    normalized = normalize_text(question)
    if contains_any(normalized, ["average", "avg", "mean"]):
        return "mean"
    if contains_any(normalized, ["max", "highest", "largest", "most"]):
        return "max"
    if contains_any(normalized, ["min", "lowest", "smallest", "least"]):
        return "min"
    if contains_any(normalized, ["count", "number of", "how many", "rows"]):
        return "count"
    return "sum"


def infer_limit(question: str) -> int:
    match = re.search(r"\btop\s+(\d{1,2})\b", question.lower())
    if not match:
        return 12
    return max(3, min(25, int(match.group(1))))


def mentioned_columns(question: str, columns: list[str]) -> list[str]:
    normalized_question = f" {normalize_text(question)} "
    matches = []
    for column in columns:
        normalized_column = normalize_text(column)
        if not normalized_column:
            continue
        tokens = normalized_column.split()
        if f" {normalized_column} " in normalized_question or all(
            f" {token} " in normalized_question for token in tokens
        ):
            matches.append(column)
    return matches


def pick_column_after_anchor(question: str, columns: list[str]) -> str | None:
    normalized_question = normalize_text(question)
    anchors = ["by", "per", "across", "for each"]
    for column in columns:
        normalized_column = normalize_text(column)
        for anchor in anchors:
            if f"{anchor} {normalized_column}" in normalized_question:
                return column
    return None


def contains_any(text: str, needles: list[str]) -> bool:
    haystack = text.lower()
    return any(needle in haystack for needle in needles)


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def aggregate_insight(labels: list[str], values: list[float], measure_name: str) -> str:
    if not labels or not values:
        return "No insight could be generated for this result."

    top_label = labels[0]
    top_value = values[0]
    total = sum(value for value in values if isinstance(value, (int, float)))
    if total and measure_name.startswith(("sum", "count", "rows")):
        share = top_value / total * 100
        return f"{top_label} leads with {top_value:,}, representing {share:.1f}% of the displayed total."
    return f"{top_label} has the highest displayed {measure_name} at {top_value:,}."


def time_insight(labels: list[str], values: list[float], measure_name: str) -> str:
    if len(values) < 2:
        return f"{measure_name} has one available time period."

    first = values[0]
    last = values[-1]
    change = last - first
    direction = "increased" if change >= 0 else "decreased"
    peak_index = values.index(max(values))
    return (
        f"{measure_name} {direction} by {abs(round_number(change)):,} from first to last period. "
        f"The peak is {values[peak_index]:,} on {labels[peak_index]}."
    )


def scatter_insight(x_column: str, y_column: str, correlation: float | None) -> str:
    if correlation is None or not math.isfinite(correlation):
        return f"{x_column} and {y_column} do not have enough paired values for correlation."

    strength = "weak"
    if abs(correlation) >= 0.7:
        strength = "strong"
    elif abs(correlation) >= 0.4:
        strength = "moderate"

    direction = "positive" if correlation >= 0 else "negative"
    return (
        f"{x_column} and {y_column} show a {strength} {direction} relationship "
        f"(correlation {correlation:.2f})."
    )


def pct(value: int | float, total: int | float) -> float:
    if not total:
        return 0
    return round_number(value / total * 100)


def round_number(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(number):
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, tuple):
        return [clean_json(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return clean_json(value.item())
        except ValueError:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA:
        return None
    return value
