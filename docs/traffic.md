---
layout: default
title: Repository Traffic
---

# Repository Traffic

This page shows GitHub traffic metrics captured by the daily workflow. It includes rolling totals from GitHub plus your archived daily history so the numbers stay useful beyond GitHub's 14-day window.

<style>
  .traffic-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin: 1.5rem 0;
  }

  .traffic-card {
    padding: 1rem;
    border: 1px solid #d0d7de;
    border-radius: 12px;
    background: #ffffff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  }

  .traffic-label {
    font-size: 0.9rem;
    color: #57606a;
    margin-bottom: 0.35rem;
  }

  .traffic-value {
    font-size: 1.9rem;
    font-weight: 700;
    line-height: 1.1;
  }

  .traffic-delta {
    margin-top: 0.45rem;
    font-size: 0.95rem;
    color: #57606a;
  }

  .traffic-panel {
    margin: 1.5rem 0;
    padding: 1rem;
    border: 1px solid #d0d7de;
    border-radius: 12px;
    background: #ffffff;
  }

  .traffic-panel h2,
  .traffic-panel h3 {
    margin-top: 0;
  }

  .traffic-meta {
    color: #57606a;
    font-size: 0.95rem;
  }

  .traffic-empty {
    padding: 1rem;
    border-radius: 10px;
    background: #f6f8fa;
    color: #57606a;
  }

  .traffic-list {
    margin: 0;
    padding-left: 1.2rem;
  }

  .traffic-list li + li {
    margin-top: 0.45rem;
  }
</style>

<div class="traffic-meta" id="traffic-meta">Loading latest traffic snapshot...</div>

<div class="traffic-grid" id="summary-cards"></div>

<div class="traffic-grid" id="delta-cards"></div>

<div class="traffic-panel">
  <h2>Daily Views</h2>
  <canvas id="views-chart" height="110"></canvas>
</div>

<div class="traffic-panel">
  <h2>Daily Clones</h2>
  <canvas id="clones-chart" height="110"></canvas>
</div>

<div class="traffic-grid">
  <div class="traffic-panel">
    <h3>Top Referrers</h3>
    <div id="referrers-panel" class="traffic-empty">No referrer data yet.</div>
  </div>
  <div class="traffic-panel">
    <h3>Popular Content</h3>
    <div id="paths-panel" class="traffic-empty">No popular content data yet.</div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  const latestUrl = "{{ '/data/traffic/latest.json' | relative_url }}";
  const dailyUrl = "{{ '/data/traffic/daily.json' | relative_url }}";

  const formatNumber = (value) => new Intl.NumberFormat().format(value || 0);
  const formatDelta = (value, noun) => {
    const sign = value > 0 ? "+" : "";
    return `${sign}${value || 0} ${noun} vs previous day`;
  };

  function renderCards(targetId, cards) {
    const target = document.getElementById(targetId);
    target.innerHTML = cards.map((card) => `
      <div class="traffic-card">
        <div class="traffic-label">${card.label}</div>
        <div class="traffic-value">${formatNumber(card.value)}</div>
        ${card.delta ? `<div class="traffic-delta">${card.delta}</div>` : ""}
      </div>
    `).join("");
  }

  function renderList(targetId, items, formatter) {
    const target = document.getElementById(targetId);
    if (!items || !items.length) {
      target.className = "traffic-empty";
      target.textContent = "No data yet.";
      return;
    }

    target.className = "";
    target.innerHTML = `<ol class="traffic-list">${items.map(formatter).join("")}</ol>`;
  }

  function renderChart(canvasId, labels, firstSeries, secondSeries, firstLabel, secondLabel, firstColor, secondColor) {
    const canvas = document.getElementById(canvasId);

    new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: firstLabel,
            data: firstSeries,
            borderColor: firstColor,
            backgroundColor: firstColor,
            tension: 0.25
          },
          {
            label: secondLabel,
            data: secondSeries,
            borderColor: secondColor,
            backgroundColor: secondColor,
            tension: 0.25
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        scales: {
          y: {
            beginAtZero: true
          }
        }
      }
    });
  }

  async function loadTraffic() {
    const [latest, daily] = await Promise.all([
      fetch(latestUrl).then((response) => response.json()),
      fetch(dailyUrl).then((response) => response.json())
    ]);

    const generatedAt = latest.generated_at
      ? new Date(latest.generated_at).toLocaleString()
      : "not captured yet";

    document.getElementById("traffic-meta").textContent =
      `Repository: ${latest.repo || "unknown"} | Updated: ${generatedAt}`;

    renderCards("summary-cards", [
      { label: "Views (14-day total)", value: latest.summary?.views },
      { label: "Unique Visitors", value: latest.summary?.visitors },
      { label: "Clones (14-day total)", value: latest.summary?.clones },
      { label: "Unique Cloners", value: latest.summary?.cloners }
    ]);

    renderCards("delta-cards", [
      {
        label: "Today Views",
        value: latest.current_day?.views,
        delta: formatDelta(latest.delta_since_previous_day?.views, "views")
      },
      {
        label: "Today Visitors",
        value: latest.current_day?.visitors,
        delta: formatDelta(latest.delta_since_previous_day?.visitors, "visitors")
      },
      {
        label: "Today Clones",
        value: latest.current_day?.clones,
        delta: formatDelta(latest.delta_since_previous_day?.clones, "clones")
      },
      {
        label: "Today Cloners",
        value: latest.current_day?.cloners,
        delta: formatDelta(latest.delta_since_previous_day?.cloners, "cloners")
      }
    ]);

    const rows = daily.daily || [];
    if (rows.length) {
      const labels = rows.map((row) => row.date);
      renderChart(
        "views-chart",
        labels,
        rows.map((row) => row.views),
        rows.map((row) => row.visitors),
        "Views",
        "Unique visitors",
        "#0969da",
        "#2da44e"
      );
      renderChart(
        "clones-chart",
        labels,
        rows.map((row) => row.clones),
        rows.map((row) => row.cloners),
        "Clones",
        "Unique cloners",
        "#8250df",
        "#bf8700"
      );
    }

    renderList(
      "referrers-panel",
      latest.referrers,
      (item) => `<li><strong>${item.referrer}</strong>: ${formatNumber(item.count)} views from ${formatNumber(item.uniques)} unique visitors</li>`
    );

    renderList(
      "paths-panel",
      latest.popular_paths,
      (item) => `<li><strong><a href="https://github.com/${latest.repo}${item.path}">${item.title}</a></strong>: ${formatNumber(item.count)} views from ${formatNumber(item.uniques)} unique visitors</li>`
    );
  }

  loadTraffic().catch((error) => {
    document.getElementById("traffic-meta").textContent = `Failed to load traffic data: ${error.message}`;
  });
</script>
