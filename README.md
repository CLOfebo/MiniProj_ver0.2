# AI Analytics Dashboard

Local MVP based on the shared workflow:

1. Upload CSV to a FastAPI backend.
2. Load the data into pandas.
3. Generate profile stats, null counts, preview rows, and suggested questions.
4. Ask simple natural-language questions like `sales by region`.
5. Return structured ECharts chart data plus an insight sentence.
6. Render interactive Apache ECharts visualizations and a result table in the frontend.

## Visualization

The frontend uses Apache ECharts from a CDN and supports:

- bar, line, pie, and scatter charts
- chart type switching in the UI
- zoom and pan on chart types that support it
- restore and save-as-image through the ECharts toolbox

## Run

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The current AI layer is a local intent parser and insight generator so the project runs without API keys. A real LLM step can be added later between `/query` and the pandas execution layer.
