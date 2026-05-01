const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

const els = {
    uploadForm: document.getElementById("uploadForm"),
    fileInput: document.getElementById("fileInput"),
    fileName: document.getElementById("fileName"),
    uploadButton: document.getElementById("uploadButton"),
    queryForm: document.getElementById("queryForm"),
    questionInput: document.getElementById("questionInput"),
    queryButton: document.getElementById("queryButton"),
    questionChips: document.getElementById("questionChips"),
    metricGrid: document.getElementById("metricGrid"),
    profileInsights: document.getElementById("profileInsights"),
    columnList: document.getElementById("columnList"),
    datasetStatus: document.getElementById("datasetStatus"),
    chartTitle: document.getElementById("chartTitle"),
    chartSubtitle: document.getElementById("chartSubtitle"),
    chartModeControls: document.getElementById("chartModeControls"),
    chart: document.getElementById("chart"),
    resultInsight: document.getElementById("resultInsight"),
    resultTable: document.getElementById("resultTable"),
    previewTable: document.getElementById("previewTable"),
    toast: document.getElementById("toast")
};

let chartInstance = null;
let statusLabel = "No dataset";
let activeChartMode = "auto";
let currentResult = null;

document.addEventListener("DOMContentLoaded", () => {
    chartInstance = window.echarts ? echarts.init(els.chart) : null;
    wireEvents();
    loadProfile();
});

function wireEvents() {
    els.fileInput.addEventListener("change", () => {
        const file = els.fileInput.files[0];
        els.fileName.textContent = file ? file.name : "Choose CSV file";
    });

    els.uploadForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = els.fileInput.files[0];
        if (!file) {
            showToast("Choose a CSV file first.", true);
            return;
        }
        await uploadFile(file);
    });

    els.queryForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const question = els.questionInput.value.trim();
        if (!question) {
            showToast("Ask a question about the dataset.", true);
            return;
        }
        await runQuery(question);
    });

    els.chartModeControls.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
            activeChartMode = button.dataset.chartMode;
            els.chartModeControls.querySelectorAll("button").forEach((item) => {
                item.classList.toggle("active", item === button);
            });
            if (currentResult) {
                renderChart(currentResult);
            }
        });
    });

    window.addEventListener("resize", () => {
        if (chartInstance) chartInstance.resize();
    });
}

async function uploadFile(file) {
    setBusy(true, "Uploading...");
    try {
        const response = await fetch(`${API_BASE}/upload?filename=${encodeURIComponent(file.name)}`, {
            method: "POST",
            headers: {
                "Content-Type": file.type || "text/csv",
                "X-Filename": file.name
            },
            body: file
        });
        const data = await readJson(response);
        renderProfile(data.profile);
        renderResult(data.result);
        showToast("Dataset uploaded.");
    } catch (error) {
        showToast(error.message || "Upload failed.", true);
    } finally {
        setBusy(false);
    }
}

async function loadProfile() {
    try {
        const response = await fetch(`${API_BASE}/profile`);
        if (response.status === 404) return;
        const profile = await readJson(response);
        renderProfile(profile);
    } catch {
        statusLabel = "API offline";
        els.datasetStatus.textContent = statusLabel;
    }
}

async function runQuery(question) {
    setBusy(true, "Thinking...");
    try {
        const response = await fetch(`${API_BASE}/query`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({question})
        });
        const data = await readJson(response);
        renderResult(data);
        showToast("Chart updated.");
    } catch (error) {
        showToast(error.message || "Query failed.", true);
    } finally {
        setBusy(false);
    }
}

async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.detail || "Request failed.");
    }
    return data;
}

function renderProfile(profile) {
    statusLabel = `${profile.rows.toLocaleString()} rows`;
    els.datasetStatus.textContent = statusLabel;
    els.metricGrid.innerHTML = [
        metricCard("Rows", profile.rows.toLocaleString()),
        metricCard("Columns", profile.columnCount.toLocaleString()),
        metricCard("Missing", profile.missingCells.toLocaleString()),
        metricCard("Duplicates", profile.duplicateRows.toLocaleString())
    ].join("");

    els.profileInsights.innerHTML = profile.insights
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("");

    els.columnList.innerHTML = profile.columns
        .map((column) => `
            <div class="column-item">
                <div>
                    <strong>${escapeHtml(column.name)}</strong>
                    <span>${escapeHtml(column.dtype)}</span>
                </div>
                <small>${escapeHtml(column.type)} / ${column.unique} unique / ${column.missingPct}% missing</small>
            </div>
        `)
        .join("");

    els.questionChips.innerHTML = profile.suggestedQuestions
        .map((question) => `<button type="button" data-question="${escapeHtml(question)}">${escapeHtml(question)}</button>`)
        .join("");

    els.questionChips.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
            els.questionInput.value = button.dataset.question;
            runQuery(button.dataset.question);
        });
    });

    renderTable(els.previewTable, profile.preview);
}

function renderResult(result) {
    currentResult = result;
    const chart = result.chart;
    els.chartTitle.textContent = chart.title || "Chart";
    els.chartSubtitle.textContent = summarizeIntent(result.intent);
    els.resultInsight.textContent = result.insight || "";
    renderTable(els.resultTable, result.table || []);
    renderChart(result);
}

function renderChart(result) {
    if (chartInstance) {
        chartInstance.setOption(buildEChartsOption(result), true);
    } else {
        renderNoChartFallback();
    }
}

function buildEChartsOption(result) {
    const sourceOption = cloneOption(result.chart || {});
    const mode = activeChartMode === "auto" ? result.intent?.chartType : activeChartMode;
    const option = coerceChartType(sourceOption, mode);

    option.color = ["#0f766e", "#2563eb", "#b45309", "#7c3aed", "#dc2626", "#0891b2", "#4d7c0f"];
    option.backgroundColor = "transparent";
    option.animationDuration = 650;
    option.title = {
        text: sourceOption.title || "Chart",
        left: 8,
        top: 4,
        textStyle: {
            color: "#17211f",
            fontSize: 15,
            fontWeight: 700
        }
    };
    option.legend = {
        type: "scroll",
        top: 28,
        right: 8,
        textStyle: {color: "#61706c"}
    };
    option.toolbox = {
        right: 8,
        top: 0,
        feature: {
            restore: {},
            saveAsImage: {title: "Save"}
        }
    };

    const seriesType = option.series?.[0]?.type;
    if (seriesType === "bar" || seriesType === "line") {
        option.dataZoom = [
            {type: "inside", throttle: 50},
            {type: "slider", height: 22, bottom: 8}
        ];
        option.grid = {...(option.grid || {}), bottom: 84};
    }
    if (seriesType === "scatter") {
        option.dataZoom = [{type: "inside", xAxisIndex: 0}, {type: "inside", yAxisIndex: 0}];
    }

    return option;
}

function coerceChartType(option, mode) {
    const series = option.series?.[0];
    if (!series || !mode) return option;

    if (mode === "pie" && option.xAxis?.data && Array.isArray(series.data)) {
        const labels = option.xAxis.data;
        return {
            ...option,
            tooltip: {trigger: "item"},
            xAxis: undefined,
            yAxis: undefined,
            grid: undefined,
            series: [{
                name: series.name || "value",
                type: "pie",
                radius: ["42%", "70%"],
                center: ["50%", "54%"],
                data: labels.map((label, index) => ({
                    name: label,
                    value: series.data[index]
                })),
                label: {formatter: "{b}: {d}%"}
            }]
        };
    }

    if ((mode === "bar" || mode === "line") && series.type === "pie" && Array.isArray(series.data)) {
        const labels = series.data.map((item) => item.name);
        const values = series.data.map((item) => item.value);
        return {
            ...option,
            tooltip: {trigger: "axis"},
            grid: {left: 48, right: 24, top: 48, bottom: 72},
            xAxis: {type: "category", data: labels, axisLabel: {rotate: 30}},
            yAxis: {type: "value"},
            series: [{
                name: series.name || "value",
                type: mode,
                smooth: mode === "line",
                areaStyle: mode === "line" ? {opacity: 0.08} : undefined,
                data: values
            }]
        };
    }

    if ((mode === "bar" || mode === "line") && (series.type === "bar" || series.type === "line")) {
        return {
            ...option,
            series: [{
                ...series,
                type: mode,
                smooth: mode === "line",
                areaStyle: mode === "line" ? {opacity: 0.08} : undefined
            }]
        };
    }

    if (mode === "scatter" && series.type === "scatter") {
        return option;
    }

    return option;
}

function cloneOption(option) {
    return JSON.parse(JSON.stringify(option));
}

function summarizeIntent(intent = {}) {
    if (!intent.metric && !intent.dimension) return "Auto-selected chart";
    const parts = [];
    if (intent.aggregate) parts.push(intent.aggregate);
    if (intent.metric) parts.push(intent.metric);
    if (intent.dimension) parts.push(`by ${intent.dimension}`);
    return parts.join(" ");
}

function renderTable(tableElement, rows) {
    if (!rows || rows.length === 0) {
        tableElement.innerHTML = `<tbody><tr><td class="empty-cell">No rows</td></tr></tbody>`;
        return;
    }

    const headers = Object.keys(rows[0]);
    const headerHtml = headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("");
    const bodyHtml = rows
        .map((row) => `
            <tr>
                ${headers.map((header) => `<td>${escapeHtml(formatValue(row[header]))}</td>`).join("")}
            </tr>
        `)
        .join("");

    tableElement.innerHTML = `<thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody>`;
}

function metricCard(label, value) {
    return `
        <div class="metric-card">
            <span>${label}</span>
            <strong>${value}</strong>
        </div>
    `;
}

function setBusy(isBusy, label = "Working...") {
    els.uploadButton.disabled = isBusy;
    els.queryButton.disabled = isBusy;
    if (isBusy) {
        els.datasetStatus.textContent = label;
    } else {
        els.datasetStatus.textContent = statusLabel;
    }
}

function showToast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.className = `toast ${isError ? "error" : "show"}`;
    if (isError) els.toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        els.toast.className = "toast";
    }, 2600);
}

function renderNoChartFallback() {
    els.chart.innerHTML = `<div class="chart-fallback">Chart library unavailable.</div>`;
}

function formatValue(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(2);
    return String(value);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
