(() => {
  const GRID_COLOR = "rgba(23, 36, 44, 0.1)";
  const TEXT_COLOR = "#17242c";
  const MUTED_TEXT_COLOR = "#63727a";
  const PENDING_SCROLL_KEY = "repeat-codon-composition-explorer:pending-scroll";
  const PENDING_SCROLL_MAX_AGE_MS = 15000;
  const PALETTE = [
    "#0f5964",
    "#d06e37",
    "#9db7a5",
    "#6a8caf",
    "#d9a441",
    "#6e7f80",
  ];

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

  function formatShare(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "-";
    }
    return value.toFixed(3).replace(/\.?0+$/, "");
  }

  function chartHeight(rowCount, minimumHeight) {
    return Math.max(minimumHeight, (rowCount * 40) + 140);
  }

  function savePendingScrollPosition() {
    try {
      window.sessionStorage.setItem(
        PENDING_SCROLL_KEY,
        JSON.stringify({
          path: window.location.pathname,
          scrollY: window.scrollY,
          savedAt: Date.now(),
        }),
      );
    } catch (error) {
    }
  }

  function restorePendingScrollPosition() {
    try {
      const rawValue = window.sessionStorage.getItem(PENDING_SCROLL_KEY);
      if (!rawValue) {
        return;
      }

      window.sessionStorage.removeItem(PENDING_SCROLL_KEY);
      const pendingState = JSON.parse(rawValue);
      if (!pendingState || pendingState.path !== window.location.pathname) {
        return;
      }
      if ((Date.now() - pendingState.savedAt) > PENDING_SCROLL_MAX_AGE_MS) {
        return;
      }
      if (typeof pendingState.scrollY !== "number" || !Number.isFinite(pendingState.scrollY)) {
        return;
      }

      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          window.scrollTo({
            top: pendingState.scrollY,
            left: 0,
            behavior: "auto",
          });
        });
      });
    } catch (error) {
      try {
        window.sessionStorage.removeItem(PENDING_SCROLL_KEY);
      } catch (storageError) {
      }
    }
  }

  function buildEmptyOption(message, detail) {
    return {
      animation: false,
      grid: {
        left: 16,
        right: 16,
        top: 16,
        bottom: 16,
      },
      xAxis: {
        show: false,
      },
      yAxis: {
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
            text: message,
            fontSize: 20,
            fontWeight: 700,
            fill: TEXT_COLOR,
            textAlign: "center",
          },
        },
        {
          type: "text",
          left: "center",
          top: "54%",
          style: {
            text: detail,
            fontSize: 14,
            fontWeight: 500,
            fill: MUTED_TEXT_COLOR,
            textAlign: "center",
          },
        },
      ],
    };
  }

  function renderOverview() {
    const payload = parsePayload("codon-composition-overview-payload");
    const container = document.getElementById("codon-composition-overview");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    const chart = window.echarts.init(container);
    container.style.height = `${chartHeight(payload.visibleTaxaCount || 0, 320)}px`;

    if (!Array.isArray(payload.cells) || payload.cells.length === 0) {
      chart.setOption(
        buildEmptyOption(
          "No visible codon composition cells",
          "Adjust the filters or choose a residue to populate the overview.",
        ),
      );
      return;
    }

    chart.setOption({
      animation: false,
      grid: {
        left: 160,
        right: 56,
        top: 32,
        bottom: 48,
      },
      tooltip: {
        trigger: "item",
        formatter(params) {
          const cell = payload.cells[params.dataIndex];
          return [
            `<strong>${cell.taxonName}</strong>`,
            `Codon: ${cell.codon}`,
            `Share: ${formatShare(cell.value)}`,
            `Calls: ${cell.observationCount}`,
          ].join("<br>");
        },
      },
      xAxis: {
        type: "category",
        data: payload.codons.map((row) => row.codon),
        axisLabel: {
          color: TEXT_COLOR,
        },
        axisLine: {
          lineStyle: {
            color: GRID_COLOR,
          },
        },
      },
      yAxis: {
        type: "category",
        data: payload.taxa.map((row) => row.taxonName),
        axisLabel: {
          color: TEXT_COLOR,
        },
        axisLine: {
          lineStyle: {
            color: GRID_COLOR,
          },
        },
      },
      visualMap: {
        min: payload.valueMin,
        max: payload.valueMax,
        calculable: false,
        orient: "vertical",
        right: 0,
        top: "middle",
        text: ["High", "Low"],
        textStyle: {
          color: MUTED_TEXT_COLOR,
        },
        inRange: {
          color: ["#f2efe6", "#cddfd8", "#0f5964"],
        },
      },
      series: [
        {
          type: "heatmap",
          data: payload.seriesData,
          label: {
            show: true,
            formatter(params) {
              return formatShare(params.data[2]);
            },
            color: TEXT_COLOR,
            fontSize: 11,
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: "rgba(0, 0, 0, 0.18)",
            },
          },
        },
      ],
    });

    window.addEventListener("resize", () => chart.resize());
  }

  function renderBrowseChart() {
    const payload = parsePayload("codon-composition-chart-payload");
    const container = document.getElementById("codon-composition-chart");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    const chart = window.echarts.init(container);
    container.style.height = `${chartHeight(payload.visibleTaxaCount || 0, 380)}px`;

    if (!Array.isArray(payload.rows) || payload.rows.length === 0 || !Array.isArray(payload.visibleCodons) || payload.visibleCodons.length === 0) {
      chart.setOption(
        buildEmptyOption(
          "No visible codon composition rows",
          "Adjust the filters or choose a residue to populate the browse chart.",
        ),
      );
      return;
    }

    const taxonNames = payload.rows.map((row) => row.taxonName);
    const series = payload.visibleCodons.map((codon, codonIndex) => ({
      name: codon,
      type: "bar",
      stack: "codon-composition",
      barMaxWidth: 22,
      itemStyle: {
        color: PALETTE[codonIndex % PALETTE.length],
      },
      data: payload.rows.map((row) => ({
        value: row.codonShares[codonIndex] || 0,
        taxonName: row.taxonName,
        codon,
        branchExplorerUrl: row.branchExplorerUrl || "",
      })),
    }));

    chart.setOption({
      animation: false,
      grid: {
        left: 180,
        right: 24,
        top: 72,
        bottom: 48,
      },
      legend: {
        top: 16,
        textStyle: {
          color: TEXT_COLOR,
        },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "shadow",
        },
        formatter(params) {
          if (!Array.isArray(params) || params.length === 0) {
            return "";
          }
          const lines = [`<strong>${params[0].data.taxonName}</strong>`];
          params.forEach((entry) => {
            lines.push(`${entry.seriesName}: ${formatShare(entry.data.value)}`);
          });
          return lines.join("<br>");
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 1,
        axisLabel: {
          color: TEXT_COLOR,
          formatter: (value) => formatShare(value),
        },
        splitLine: {
          lineStyle: {
            color: GRID_COLOR,
          },
        },
      },
      yAxis: {
        type: "category",
        data: taxonNames,
        axisLabel: {
          color: TEXT_COLOR,
        },
      },
      series,
    });

    chart.on("click", (params) => {
      if (params && params.data && params.data.branchExplorerUrl) {
        window.location.href = params.data.branchExplorerUrl;
      }
    });

    window.addEventListener("resize", () => chart.resize());
  }

  function renderInspectChart() {
    const payload = parsePayload("codon-composition-inspect-payload");
    const container = document.getElementById("codon-composition-inspect-chart");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    const chart = window.echarts.init(container);
    container.style.height = "320px";

    if (!Array.isArray(payload.codonShares) || payload.codonShares.length === 0) {
      chart.setOption(
        buildEmptyOption(
          "No inspect composition available",
          "Choose a residue-scoped branch with imported codon-usage rows.",
        ),
      );
      return;
    }

    chart.setOption({
      animation: false,
      grid: {
        left: 64,
        right: 24,
        top: 32,
        bottom: 48,
      },
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "shadow",
        },
        formatter(params) {
          if (!Array.isArray(params) || params.length === 0) {
            return "";
          }
          const entry = params[0];
          return [
            `<strong>${payload.scopeLabel}</strong>`,
            `Codon: ${entry.axisValue}`,
            `Share: ${formatShare(entry.data)}`,
            `Calls: ${payload.observationCount}`,
          ].join("<br>");
        },
      },
      xAxis: {
        type: "category",
        data: payload.visibleCodons,
        axisLabel: {
          color: TEXT_COLOR,
        },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: Math.max(1, payload.maxShare),
        axisLabel: {
          color: TEXT_COLOR,
          formatter: (value) => formatShare(value),
        },
        splitLine: {
          lineStyle: {
            color: GRID_COLOR,
          },
        },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 36,
          itemStyle: {
            color: "#0f5964",
          },
          data: payload.codonShares.map((row) => row.share),
        },
      ],
    });

    window.addEventListener("resize", () => chart.resize());
  }

  function bindScrollPreservingLinks() {
    document.querySelectorAll("[data-preserve-scroll-link]").forEach((link) => {
      link.addEventListener("click", () => {
        savePendingScrollPosition();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    restorePendingScrollPosition();
    bindScrollPreservingLinks();
    renderOverview();
    renderBrowseChart();
    renderInspectChart();
  });
})();
