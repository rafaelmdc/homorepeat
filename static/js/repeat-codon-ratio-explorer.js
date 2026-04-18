(() => {
  const GRID_COLOR = "rgba(23, 36, 44, 0.1)";
  const TEXT_COLOR = "#17242c";
  const MUTED_TEXT_COLOR = "#63727a";
  const DEFAULT_VISIBLE_ROWS = 12;
  const MAX_CHART_HEIGHT = 980;
  const MAX_VISIBLE_ROWS_WITH_TAXON_LABELS = 24;
  const PENDING_SCROLL_KEY = "repeat-codon-composition-explorer:pending-scroll";
  const PENDING_SCROLL_MAX_AGE_MS = 15000;
  const ROW_HEIGHT = 38;
  const CHART_PADDING = 120;
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

  function taxonomyGutterApi() {
    return typeof window.HomorepeatTaxonomyGutter !== "undefined"
      ? window.HomorepeatTaxonomyGutter
      : null;
  }

  function hasTaxonomyGutterPayload(payload) {
    const api = taxonomyGutterApi();
    return Boolean(api && api.hasPayload(payload));
  }

  function taxonomyGutterReservedWidth(payload, options = {}) {
    const api = taxonomyGutterApi();
    if (!api || !api.hasPayload(payload)) {
      return 0;
    }
    return api.reservedWidth(payload, options);
  }

  function formatShare(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "-";
    }
    return value.toFixed(3).replace(/\.?0+$/, "");
  }

  function clamp(number, minimum, maximum) {
    return Math.min(Math.max(number, minimum), maximum);
  }

  function numericValue(value, fallbackValue) {
    if (Array.isArray(value)) {
      return numericValue(value[0], fallbackValue);
    }
    return typeof value === "number" && Number.isFinite(value) ? value : fallbackValue;
  }

  function chartHeightForRowCount(rowCount, minimumHeight) {
    if (rowCount <= 0) {
      return minimumHeight;
    }
    return clamp((rowCount * ROW_HEIGHT) + CHART_PADDING, minimumHeight, MAX_CHART_HEIGHT);
  }

  function defaultZoomState(rowCount) {
    return {
      startValue: 0,
      endValue: Math.max(0, Math.min(rowCount - 1, DEFAULT_VISIBLE_ROWS - 1)),
    };
  }

  function normalizeZoomState(rowCount, zoomState) {
    if (rowCount <= DEFAULT_VISIBLE_ROWS) {
      return null;
    }

    const fallback = defaultZoomState(rowCount);
    const startValue = clamp(
      Math.round(numericValue(zoomState ? zoomState.startValue : undefined, fallback.startValue)),
      0,
      rowCount - 1,
    );
    const endValue = clamp(
      Math.round(numericValue(zoomState ? zoomState.endValue : undefined, fallback.endValue)),
      startValue,
      rowCount - 1,
    );
    return {
      startValue,
      endValue,
    };
  }

  function visibleRowCountForZoom(rowCount, zoomState) {
    if (rowCount <= 0) {
      return 0;
    }
    if (!zoomState) {
      return rowCount;
    }
    return (zoomState.endValue - zoomState.startValue) + 1;
  }

  function shouldShowTaxonLabels(visibleRowCount) {
    return visibleRowCount <= MAX_VISIBLE_ROWS_WITH_TAXON_LABELS;
  }

  function buildYAxisZoom(rowCount, zoomState, { right = 8, top = 24, bottom = 64, width = 14 } = {}) {
    if (!zoomState) {
      return [];
    }

    return [
      {
        type: "inside",
        yAxisIndex: 0,
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
        startValue: zoomState.startValue,
        endValue: zoomState.endValue,
      },
      {
        type: "slider",
        yAxisIndex: 0,
        filterMode: "empty",
        right,
        width,
        top,
        bottom,
        brushSelect: false,
        startValue: zoomState.startValue,
        endValue: zoomState.endValue,
        fillerColor: "rgba(15, 89, 100, 0.16)",
        borderColor: "rgba(23, 36, 44, 0.08)",
        handleStyle: {
          color: "#0f5964",
          borderColor: "#0f5964",
        },
        moveHandleStyle: {
          color: "#0f5964",
        },
        textStyle: {
          color: MUTED_TEXT_COLOR,
        },
      },
    ];
  }

  function zoomStateFromChart(chart, rowCount) {
    const dataZoom = chart.getOption().dataZoom;
    if (!Array.isArray(dataZoom) || dataZoom.length === 0) {
      return null;
    }

    return normalizeZoomState(rowCount, {
      startValue: numericValue(dataZoom[0].startValue, 0),
      endValue: numericValue(dataZoom[0].endValue, Math.max(0, rowCount - 1)),
    });
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
    const taxonomyGutterPayload = parsePayload("codon-composition-overview-taxonomy-gutter-payload");
    const container = document.getElementById("codon-composition-overview");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    const rowCount = payload.visibleTaxaCount || 0;
    container.style.height = `${chartHeightForRowCount(rowCount, 320)}px`;
    const chart = window.echarts.init(container);
    const taxonomyGutter = hasTaxonomyGutterPayload(taxonomyGutterPayload)
      ? taxonomyGutterApi().attach(chart, { payload: taxonomyGutterPayload })
      : null;
    let currentZoomState = normalizeZoomState(rowCount, null);
    let pendingGutterOptions = null;
    let gutterSyncPending = false;
    const taxonAxisValues = payload.taxa.map((row) => String(row.taxonId));
    const taxonLabelByAxisValue = new Map(
      (payload.taxa || []).map((row) => [String(row.taxonId), row.taxonName]),
    );

    if (!Array.isArray(payload.cells) || payload.cells.length === 0) {
      chart.setOption(
        buildEmptyOption(
          "No visible codon composition cells",
          "Adjust the filters or choose a residue to populate the overview.",
        ),
      );
      return;
    }

    const heatmapData = payload.cells.map((cell) => ({
      value: [cell.codon, String(cell.taxonId), cell.value],
      taxonId: String(cell.taxonId),
      taxonName: cell.taxonName,
      codon: cell.codon,
      observationCount: cell.observationCount,
      share: cell.value,
    }));

    function scheduleGutterRender(options) {
      if (!taxonomyGutter) {
        return;
      }
      pendingGutterOptions = options;
      gutterSyncPending = true;
    }

    chart.off("finished");
    chart.on("finished", () => {
      if (!taxonomyGutter || !gutterSyncPending || !pendingGutterOptions) {
        return;
      }
      const nextOptions = pendingGutterOptions;
      pendingGutterOptions = null;
      gutterSyncPending = false;
      taxonomyGutter.render(nextOptions);
    });

    function renderChart() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
      const gutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: showTaxonLabels,
        visibleLeafCount: visibleRowCount,
      });
      chart.setOption({
        animation: false,
        grid: {
          left: gutterWidth > 0 ? gutterWidth + 20 : 160,
          right: currentZoomState ? 104 : 56,
          top: 32,
          bottom: 48,
        },
        tooltip: {
          trigger: "item",
          formatter(params) {
            const cell = params.data || {};
            return [
              `<strong>${cell.taxonName}</strong>`,
              `Codon: ${cell.codon}`,
              `Share: ${formatShare(cell.share)}`,
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
          inverse: true,
          data: taxonAxisValues,
          axisLabel: {
            show: !taxonomyGutter && shouldShowTaxonLabels(visibleRowCount),
            interval: 0,
            color: TEXT_COLOR,
            formatter: (value) => taxonLabelByAxisValue.get(String(value)) || String(value),
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
        dataZoom: buildYAxisZoom(rowCount, currentZoomState, {
          right: 44,
          top: 28,
          bottom: 56,
          width: 12,
        }),
        series: [
          {
            type: "heatmap",
            data: heatmapData,
            encode: {
              x: 0,
              y: 1,
              value: 2,
            },
            label: {
              show: true,
              formatter(params) {
                return formatShare(
                  params.data && typeof params.data.share === "number"
                    ? params.data.share
                    : undefined,
                );
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
      }, { notMerge: true });
      scheduleGutterRender({
        showLabels: showTaxonLabels,
        visibleLeafCount: visibleRowCount,
        zoomState: currentZoomState,
      });
    }

    chart.off("datazoom");
    chart.on("datazoom", () => {
      const nextZoomState = zoomStateFromChart(chart, rowCount);
      const previousVisibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const nextVisibleRowCount = visibleRowCountForZoom(rowCount, nextZoomState);
      const previousShowTaxonLabels = shouldShowTaxonLabels(previousVisibleRowCount);
      const nextShowTaxonLabels = shouldShowTaxonLabels(nextVisibleRowCount);
      const previousGutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: previousShowTaxonLabels,
        visibleLeafCount: previousVisibleRowCount,
      });
      const nextGutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: nextShowTaxonLabels,
        visibleLeafCount: nextVisibleRowCount,
      });
      currentZoomState = nextZoomState;
      if (previousGutterWidth !== nextGutterWidth) {
        renderChart();
        return;
      }
      scheduleGutterRender({
        showLabels: nextShowTaxonLabels,
        visibleLeafCount: nextVisibleRowCount,
        zoomState: nextZoomState,
      });
    });

    renderChart();

    window.addEventListener("resize", () => {
      chart.resize();
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      scheduleGutterRender({
        showLabels: shouldShowTaxonLabels(visibleRowCount),
        visibleLeafCount: visibleRowCount,
        zoomState: currentZoomState,
      });
    });
  }

  function renderBrowseChart() {
    const payload = parsePayload("codon-composition-chart-payload");
    const taxonomyGutterPayload = parsePayload("codon-composition-chart-taxonomy-gutter-payload");
    const container = document.getElementById("codon-composition-chart");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    const rowCount = payload.visibleTaxaCount || 0;
    container.style.height = `${chartHeightForRowCount(rowCount, 380)}px`;
    const chart = window.echarts.init(container);
    const taxonomyGutter = hasTaxonomyGutterPayload(taxonomyGutterPayload)
      ? taxonomyGutterApi().attach(chart, { payload: taxonomyGutterPayload })
      : null;
    let currentZoomState = normalizeZoomState(rowCount, null);
    let pendingGutterOptions = null;
    let gutterSyncPending = false;
    const taxonLabelByAxisValue = new Map(
      (payload.rows || []).map((row) => [String(row.taxonId), row.taxonName]),
    );

    if (!Array.isArray(payload.rows) || payload.rows.length === 0 || !Array.isArray(payload.visibleCodons) || payload.visibleCodons.length === 0) {
      chart.setOption(
        buildEmptyOption(
          "No visible codon composition rows",
          "Adjust the filters or choose a residue to populate the browse chart.",
        ),
      );
      return;
    }

    const taxonAxisValues = payload.rows.map((row) => String(row.taxonId));
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

    function scheduleGutterRender(options) {
      if (!taxonomyGutter) {
        return;
      }
      pendingGutterOptions = options;
      gutterSyncPending = true;
    }

    chart.off("finished");
    chart.on("finished", () => {
      if (!taxonomyGutter || !gutterSyncPending || !pendingGutterOptions) {
        return;
      }
      const nextOptions = pendingGutterOptions;
      pendingGutterOptions = null;
      gutterSyncPending = false;
      taxonomyGutter.render(nextOptions);
    });

    function renderChart() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
      const gutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: showTaxonLabels,
        visibleLeafCount: visibleRowCount,
      });
      chart.setOption({
        animation: false,
        grid: {
          left: gutterWidth > 0 ? gutterWidth + 20 : 180,
          right: currentZoomState ? 56 : 24,
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
          inverse: true,
          data: taxonAxisValues,
          axisLabel: {
            show: !taxonomyGutter && shouldShowTaxonLabels(visibleRowCount),
            interval: 0,
            color: TEXT_COLOR,
            formatter: (value) => taxonLabelByAxisValue.get(String(value)) || String(value),
          },
        },
        dataZoom: buildYAxisZoom(rowCount, currentZoomState, {
          right: 8,
          top: 72,
          bottom: 48,
        }),
        series,
      }, { notMerge: true });
      scheduleGutterRender({
        showLabels: showTaxonLabels,
        visibleLeafCount: visibleRowCount,
        zoomState: currentZoomState,
      });
    }

    chart.off("datazoom");
    chart.on("datazoom", () => {
      const nextZoomState = zoomStateFromChart(chart, rowCount);
      const previousVisibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const nextVisibleRowCount = visibleRowCountForZoom(rowCount, nextZoomState);
      const previousShowTaxonLabels = shouldShowTaxonLabels(previousVisibleRowCount);
      const nextShowTaxonLabels = shouldShowTaxonLabels(nextVisibleRowCount);
      const previousGutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: previousShowTaxonLabels,
        visibleLeafCount: previousVisibleRowCount,
      });
      const nextGutterWidth = taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: nextShowTaxonLabels,
        visibleLeafCount: nextVisibleRowCount,
      });
      currentZoomState = nextZoomState;
      if (previousGutterWidth !== nextGutterWidth) {
        renderChart();
        return;
      }
      scheduleGutterRender({
        showLabels: nextShowTaxonLabels,
        visibleLeafCount: nextVisibleRowCount,
        zoomState: nextZoomState,
      });
    });

    renderChart();

    chart.on("click", (params) => {
      if (params && params.data && params.data.branchExplorerUrl) {
        window.location.href = params.data.branchExplorerUrl;
      }
    });

    window.addEventListener("resize", () => {
      chart.resize();
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      scheduleGutterRender({
        showLabels: shouldShowTaxonLabels(visibleRowCount),
        visibleLeafCount: visibleRowCount,
        zoomState: currentZoomState,
      });
    });
  }

  function renderInspectChart() {
    const payload = parsePayload("codon-composition-inspect-payload");
    const container = document.getElementById("codon-composition-inspect-chart");
    if (!payload || !container || typeof window.echarts === "undefined") {
      return;
    }

    container.style.height = "320px";
    const chart = window.echarts.init(container);

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
