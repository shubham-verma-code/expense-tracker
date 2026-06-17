function money(value) {
  // Keep chart labels using the same money style as the Python pages.
  return "Rs " + Number(value || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function getData(canvas) {
  // Python stores chart data as JSON inside the canvas data-chart attribute.
  try {
    return JSON.parse(canvas.dataset.chart || "[]");
  } catch {
    return [];
  }
}

function setupCanvas(canvas) {
  // Scale canvas for sharp drawing on high-resolution screens.
  const ratio = window.devicePixelRatio || 1;
  // Read the displayed size of the canvas in the browser.
  const rect = canvas.getBoundingClientRect();
  // Internal pixel width is larger on high-DPI screens for crisp lines.
  canvas.width = Math.max(320, Math.floor(rect.width * ratio));
  canvas.height = Math.floor(310 * ratio);
  // ctx is the drawing tool used for all lines, bars, text, and circles.
  const ctx = canvas.getContext("2d");
  // Scaling lets us keep using normal CSS-size coordinates.
  ctx.scale(ratio, ratio);
  return { ctx, width: rect.width, height: 310 };
}

function drawAxes(ctx, width, height) {
  // Simple x/y axis for bar charts.
  ctx.strokeStyle = "#dfe5ee";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(48, 24);
  ctx.lineTo(48, height - 38);
  ctx.lineTo(width - 18, height - 38);
  ctx.stroke();
}

function drawGroupedBars(canvas, keys) {
  // Draw side-by-side bars, used for income vs expense charts.
  const data = getData(canvas);
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  if (!data.length) {
    drawEmpty(ctx, width, height);
    return;
  }
  const max = Math.max(...data.flatMap((item) => keys.map((key) => Number(item[key] || 0))), 1);
  // max is used to convert money values into bar heights.
  const colors = ["#2563eb", "#2dd4bf"];
  const plotW = width - 78;
  const plotH = height - 70;
  // groupW is the horizontal space for one date/month group.
  const groupW = plotW / data.length;
  drawAxes(ctx, width, height);
  data.forEach((item, index) => {
    // Draw all bars for one label, for example income and expense.
    keys.forEach((key, keyIndex) => {
      const value = Number(item[key] || 0);
      // Convert value to a bar size relative to the largest value.
      const barW = Math.max(8, groupW / (keys.length + 1.8));
      const x = 58 + index * groupW + keyIndex * (barW + 4);
      const barH = (value / max) * plotH;
      ctx.fillStyle = colors[keyIndex % colors.length];
      ctx.fillRect(x, height - 38 - barH, barW, barH);
    });
    ctx.fillStyle = "#697386";
    ctx.font = "12px Segoe UI, Arial";
    ctx.save();
    // Rotate labels slightly so longer dates/months fit better.
    ctx.translate(58 + index * groupW, height - 18);
    ctx.rotate(-0.3);
    ctx.fillText(item.label, 0, 0);
    ctx.restore();
  });
  drawLegend(ctx, keys, colors, width);
}

function drawDonut(canvas) {
  // Draw a donut chart, used for category spending.
  const data = getData(canvas);
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const total = data.reduce((sum, item) => sum + Number(item.value || 0), 0);
  // If total is zero, a donut chart cannot be calculated.
  if (!data.length || !total) {
    drawEmpty(ctx, width, height);
    return;
  }
  const colors = ["#2563eb", "#2dd4bf", "#f59e0b", "#ef4444", "#64748b", "#8b5cf6", "#14b8a6"];
  const cx = Math.min(width * 0.38, 190);
  const cy = 150;
  const radius = 102;
  let start = -Math.PI / 2;
  data.forEach((item, index) => {
    // Each slice angle is based on its percentage of the total.
    const slice = (Number(item.value || 0) / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, start, start + slice);
    ctx.closePath();
    ctx.fillStyle = colors[index % colors.length];
    ctx.fill();
    start += slice;
  });
  ctx.globalCompositeOperation = "destination-out";
  // Cut a hole in the middle to turn the pie chart into a donut chart.
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalCompositeOperation = "source-over";
  // Put the total amount in the center of the donut.
  ctx.fillStyle = "#17202a";
  ctx.font = "700 18px Segoe UI, Arial";
  ctx.textAlign = "center";
  ctx.fillText(money(total), cx, cy + 6);
  ctx.textAlign = "left";
  data.forEach((item, index) => {
    // Draw legend rows on the right side of the chart.
    const y = 48 + index * 28;
    ctx.fillStyle = colors[index % colors.length];
    ctx.fillRect(width * 0.63, y - 10, 12, 12);
    ctx.fillStyle = "#17202a";
    ctx.font = "13px Segoe UI, Arial";
    ctx.fillText(`${item.label} - ${money(item.value)}`, width * 0.63 + 20, y);
  });
}

function drawSingleBars(canvas) {
  // Draw horizontal bars, used for payment method reports.
  const data = getData(canvas);
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  if (!data.length) {
    drawEmpty(ctx, width, height);
    return;
  }
  const max = Math.max(...data.map((item) => Number(item.value || 0)), 1);
  // Highest value gets the longest horizontal bar.
  const barH = Math.min(28, (height - 54) / data.length - 8);
  data.forEach((item, index) => {
    // y decides where each row appears vertically.
    const y = 30 + index * (barH + 14);
    const widthPct = (Number(item.value || 0) / max) * (width - 180);
    // Light background bar shows the full available width.
    ctx.fillStyle = "#e8f0ff";
    ctx.fillRect(125, y, width - 170, barH);
    ctx.fillStyle = "#2563eb";
    // Dark bar shows the actual value compared to max.
    ctx.fillRect(125, y, widthPct, barH);
    ctx.fillStyle = "#17202a";
    ctx.font = "13px Segoe UI, Arial";
    ctx.fillText(item.label, 10, y + barH - 8);
    ctx.fillText(money(item.value), 132 + widthPct, y + barH - 8);
  });
}

function drawLegend(ctx, keys, colors, width) {
  // Show which color belongs to each data series.
  keys.forEach((key, index) => {
    const x = width - 180 + index * 90;
    ctx.fillStyle = colors[index];
    ctx.fillRect(x, 18, 12, 12);
    ctx.fillStyle = "#697386";
    ctx.font = "12px Segoe UI, Arial";
    ctx.fillText(key, x + 18, 29);
  });
}

function drawEmpty(ctx, width, height) {
  // Friendly fallback when there is no data for a chart.
  ctx.fillStyle = "#697386";
  ctx.font = "15px Segoe UI, Arial";
  ctx.textAlign = "center";
  ctx.fillText("No data available yet", width / 2, height / 2);
  ctx.textAlign = "left";
}

function renderCharts() {
  // Each page only has some of these canvases, so check before drawing.
  const trend = document.getElementById("trendChart");
  if (trend) drawGroupedBars(trend, ["income", "expense"]);
  const category = document.getElementById("categoryChart");
  if (category) drawDonut(category);
  const monthly = document.getElementById("monthlyChart");
  if (monthly) drawGroupedBars(monthly, ["income", "expense"]);
  const method = document.getElementById("methodChart");
  if (method) drawSingleBars(method);
}

window.addEventListener("load", renderCharts);
window.addEventListener("resize", () => {
  // Re-render after resize so chart proportions stay correct.
  clearTimeout(window.__chartTimer);
  window.__chartTimer = setTimeout(renderCharts, 150);
});
