(() => {
  function parsePayload(scriptId) {
    const payloadNode = document.getElementById(scriptId);
    if (!payloadNode) {
      return null;
    }

    try {
      return JSON.parse(payloadNode.textContent);
    } catch (error) {
      return null;
    }
  }

  function buildShellOption(payload) {
    const hasRows = Array.isArray(payload.rows) && payload.rows.length > 0;
    const rangeLabel = hasRows ? `${payload.x_min} to ${payload.x_max}` : "No visible taxa";
    const summaryLabel = hasRows
      ? `${payload.visibleTaxaCount} taxa ready for chart rendering`
      : "Adjust the filters to populate the chart";

    return {
      animation: false,
      grid: {
        left: 16,
        right: 16,
        top: 16,
        bottom: 16,
      },
      xAxis: {
        type: "value",
        min: payload.x_min,
        max: payload.x_max,
        show: false,
      },
      yAxis: {
        type: "category",
        data: hasRows ? payload.rows.map((row) => row.taxonName) : [],
        show: false,
      },
      series: [],
      tooltip: {
        show: false,
      },
      graphic: [
        {
          type: "text",
          left: "center",
          top: "42%",
          style: {
            text: summaryLabel,
            fontSize: 20,
            fontWeight: 700,
            fill: "#17242c",
            textAlign: "center",
          },
        },
        {
          type: "text",
          left: "center",
          top: "54%",
          style: {
            text: `Length span: ${rangeLabel}`,
            fontSize: 14,
            fontWeight: 500,
            fill: "#63727a",
            textAlign: "center",
          },
        },
      ],
    };
  }

  function mountLengthChart() {
    const container = document.getElementById("repeat-length-chart");
    const payload = parsePayload("repeat-length-chart-payload");
    if (!container || !payload || typeof window.echarts === "undefined") {
      return;
    }

    const chart = window.echarts.init(container, null, { renderer: "svg" });
    chart.setOption(buildShellOption(payload));

    window.addEventListener("resize", () => {
      chart.resize();
    });
  }

  document.addEventListener("DOMContentLoaded", mountLengthChart);
})();
