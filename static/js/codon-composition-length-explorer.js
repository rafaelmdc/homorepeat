(() => {
  const chartShell = window.HomorepeatStatsChartShell;
  if (!chartShell) return;

  const parsePayload = chartShell.parsePayload;
  const chartHeightForRowCount = chartShell.chartHeightForRowCount;
  const defaultZoomState = chartShell.defaultZoomState;
  const normalizeZoomState = chartShell.normalizeZoomState;
  const buildXAxisZoom = chartShell.buildXAxisZoom;
  const buildYAxisZoom = chartShell.buildYAxisZoom;
  const installWheelHandler = chartShell.installWheelHandler;
  const resolveZoomState = chartShell.resolveZoomState;

  const PAYLOAD_IDS = {
    preference: "codon-composition-length-preference-overview-payload",
    dominance: "codon-composition-length-dominance-overview-payload",
    shift: "codon-composition-length-shift-overview-payload",
  };
  const CODON_COLORS = [
    "#0f5964",
    "#d06e37",
    "#7b5ea7",
    "#2f8f5b",
    "#b04f6f",
    "#9a7b2f",
  ];
  const DEFAULT_VISIBLE_COLUMNS = 64;

  function supportOpacity(cell, payload) {
    const maxObservationCount = Math.max(1, payload.maxObservationCount || 1);
    const observationCount = Math.max(0, cell.observationCount || 0);
    return Math.max(0.62, Math.min(1, 0.62 + 0.38 * Math.sqrt(observationCount / maxObservationCount)));
  }

  function modePayload(payloads, mode) {
    return payloads[mode] || null;
  }

  function activePayload(payloads, requestedMode) {
    const requested = modePayload(payloads, requestedMode);
    if (requested && requested.available) return requested;
    return payloads.preference.available
      ? payloads.preference
      : (payloads.dominance.available ? payloads.dominance : payloads.shift);
  }

  function xLabels(payload) {
    if (payload.mode === "shift") {
      return (payload.transitions || []).map((transition) => transition.label);
    }
    return (payload.visibleBins || []).map((bin) => bin.label);
  }

  function yLabels(payload) {
    return (payload.taxa || []).map((taxon) => taxon.taxonName);
  }

  function cellXIndex(cell, payload) {
    return payload.mode === "shift" ? cell.transitionIndex : cell.binIndex;
  }

  function defaultColumnZoomState(columnCount) {
    if (columnCount <= DEFAULT_VISIBLE_COLUMNS) return null;
    return {
      startValue: 0,
      endValue: DEFAULT_VISIBLE_COLUMNS - 1,
    };
  }

  function normalizeColumnZoomState(columnCount, zoomState) {
    if (columnCount <= DEFAULT_VISIBLE_COLUMNS) return null;
    const fallback = defaultColumnZoomState(columnCount);
    const startValue = Math.max(0, Math.min(columnCount - 1, Math.round(
      typeof zoomState?.startValue === "number" ? zoomState.startValue : fallback.startValue,
    )));
    const endValue = Math.max(startValue, Math.min(columnCount - 1, Math.round(
      typeof zoomState?.endValue === "number" ? zoomState.endValue : fallback.endValue,
    )));
    return { startValue, endValue };
  }

  function columnZoomStateFromParams(params, columnCount) {
    if (!params) return null;
    const payload = Array.isArray(params.batch) && params.batch.length > 0 ? params.batch[0] : params;
    if (!payload || payload.dataZoomId !== "codon-length-x-slider") return null;
    if (payload.startValue != null || payload.endValue != null) {
      return normalizeColumnZoomState(columnCount, {
        startValue: payload.startValue,
        endValue: payload.endValue,
      });
    }
    return null;
  }

  function labelInterval(columnCount) {
    if (columnCount <= 32) return 0;
    if (columnCount <= 96) return 4;
    if (columnCount <= 180) return 9;
    return 19;
  }

  function seriesData(payload) {
    return (payload.cells || []).map((cell) => {
      const item = {
        value: [cellXIndex(cell, payload), cell.rowIndex, cell.value],
        cell,
        itemStyle: {
          opacity: supportOpacity(
            payload.mode === "shift" ? cell.nextSupport : cell,
            payload,
          ),
        },
      };
      if (payload.mode === "dominance") {
        item.itemStyle.color = CODON_COLORS[Math.max(0, cell.dominantCodonIndex) % CODON_COLORS.length];
        item.itemStyle.opacity = Math.max(item.itemStyle.opacity * Math.max(0.35, cell.dominanceMargin || 0), 0.28);
      }
      return item;
    });
  }

  function formatShares(rows) {
    return (rows || [])
      .map((row) => `${row.codon}: ${(row.share * 100).toFixed(1)}%`)
      .join("<br>");
  }

  function tooltipHtml(payload, cell) {
    const taxon = payload.taxa[cell.rowIndex] || {};
    if (payload.mode === "shift") {
      return [
        `<strong>${taxon.taxonName || "Taxon"}</strong>`,
        `${cell.previousBin.label} -> ${cell.nextBin.label}`,
        `${payload.metricLabel}: ${cell.shift.toFixed(3)}`,
        `Previous support: ${cell.previousSupport.observationCount} observations, ${cell.previousSupport.speciesCount} species`,
        `Next support: ${cell.nextSupport.observationCount} observations, ${cell.nextSupport.speciesCount} species`,
        "<hr>",
        `<strong>${cell.previousBin.label}</strong><br>${formatShares(cell.previousCodonShares)}`,
        `<strong>${cell.nextBin.label}</strong><br>${formatShares(cell.nextCodonShares)}`,
      ].join("<br>");
    }
    if (payload.mode === "preference") {
      return [
        `<strong>${taxon.taxonName || "Taxon"}</strong>`,
        cell.binLabel,
        `${payload.metricLabel}: ${cell.preference.toFixed(3)}`,
        `${cell.codonA}: ${(cell.codonAShare * 100).toFixed(1)}%`,
        `${cell.codonB}: ${(cell.codonBShare * 100).toFixed(1)}%`,
        `Support: ${cell.observationCount} observations, ${cell.speciesCount} species`,
      ].join("<br>");
    }
    return [
      `<strong>${taxon.taxonName || "Taxon"}</strong>`,
      cell.binLabel,
      `Dominant codon: ${cell.dominantCodon}`,
      `Dominance margin: ${cell.dominanceMargin.toFixed(3)}`,
      `Support: ${cell.observationCount} observations, ${cell.speciesCount} species`,
      "<hr>",
      formatShares(cell.codonShares),
    ].join("<br>");
  }

  function visualMap(payload) {
    if (payload.mode === "dominance") return [];
    return [
      {
        min: payload.valueMin,
        max: payload.valueMax,
        dimension: 2,
        calculable: true,
        orient: "vertical",
        right: 16,
        top: 42,
        bottom: 72,
        inRange: {
          color: payload.mode === "preference"
            ? ["#0f5964", "#f2efe6", "#d06e37"]
            : ["#f2efe6", "#d06e37"],
        },
        textStyle: { color: "#63727a" },
      },
    ];
  }

  function chartOption(payload, rowZoomState, columnZoomState) {
    const labels = xLabels(payload);
    const xZoom = buildXAxisZoom(labels.length, columnZoomState, {
      insideId: "codon-length-x-inside",
      sliderId: "codon-length-x-slider",
      left: 172,
      right: payload.mode === "dominance" ? 28 : 96,
      bottom: 24,
      height: 18,
    });
    return {
      animation: false,
      grid: {
        left: 172,
        right: payload.mode === "dominance" ? 28 : 96,
        top: 36,
        bottom: columnZoomState ? 112 : 76,
        containLabel: false,
      },
      tooltip: {
        confine: true,
        formatter: (params) => tooltipHtml(payload, params.data.cell),
      },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: {
          color: "#63727a",
          rotate: 0,
          interval: labelInterval(labels.length),
          hideOverlap: true,
          width: 52,
          overflow: "truncate",
        },
        axisTick: { alignWithLabel: true },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: yLabels(payload),
        axisLabel: {
          color: "#17242c",
          width: 156,
          overflow: "truncate",
        },
      },
      dataZoom: [
        ...buildYAxisZoom(payload.visibleTaxaCount || 0, rowZoomState, {
        right: payload.mode === "dominance" ? 8 : 72,
        top: 36,
          bottom: columnZoomState ? 112 : 76,
        }),
        ...xZoom,
      ],
      visualMap: visualMap(payload),
      series: [
        {
          type: "heatmap",
          data: seriesData(payload),
          emphasis: {
            itemStyle: {
              borderColor: "#17242c",
              borderWidth: 1,
            },
          },
        },
      ],
    };
  }

  function syncButtons(buttons, activeMode, payloads) {
    buttons.forEach((button) => {
      const mode = button.dataset.overviewMode;
      const payload = modePayload(payloads, mode);
      const isActive = mode === activeMode;
      button.disabled = !payload || !payload.available;
      button.classList.toggle("btn-brand", isActive);
      button.classList.toggle("btn-outline-secondary", !isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function syncDescriptions(descriptions, activeMode) {
    descriptions.forEach((description) => {
      description.hidden = description.dataset.overviewMode !== activeMode;
    });
  }

  function mountOverview() {
    const container = document.getElementById("codon-composition-length-overview-chart");
    if (!container || typeof window.echarts === "undefined") return;

    const payloads = {
      preference: parsePayload(PAYLOAD_IDS.preference) || {},
      dominance: parsePayload(PAYLOAD_IDS.dominance) || {},
      shift: parsePayload(PAYLOAD_IDS.shift) || {},
    };
    let payload = activePayload(payloads, container.dataset.defaultOverviewMode || "preference");
    const emptyMessage = document.querySelector("[data-codon-length-overview-empty]");
    const buttons = Array.from(document.querySelectorAll("[data-codon-length-overview-mode-button]"));
    const descriptions = Array.from(document.querySelectorAll("[data-codon-length-overview-description]"));

    if (!payload || !payload.available) {
      container.hidden = true;
      syncButtons(buttons, "", payloads);
      return;
    }

    let currentMode = payload.mode;
    let currentRowZoomState = normalizeZoomState(
      payload.visibleTaxaCount || 0,
      defaultZoomState(payload.visibleTaxaCount || 0),
    );
    let currentColumnZoomState = normalizeColumnZoomState(
      xLabels(payload).length,
      defaultColumnZoomState(xLabels(payload).length),
    );
    container.style.height = `${chartHeightForRowCount(payload.visibleTaxaCount || 0, { minimumHeight: 360 })}px`;
    const chart = window.echarts.init(container);
    installWheelHandler(chart, payload.visibleTaxaCount || 0, () => currentRowZoomState);

    function render() {
      payload = modePayload(payloads, currentMode);
      currentRowZoomState = normalizeZoomState(payload.visibleTaxaCount || 0, currentRowZoomState);
      currentColumnZoomState = normalizeColumnZoomState(xLabels(payload).length, currentColumnZoomState);
      container.hidden = false;
      if (emptyMessage) emptyMessage.hidden = true;
      syncButtons(buttons, currentMode, payloads);
      syncDescriptions(descriptions, currentMode);
      container.style.height = `${chartHeightForRowCount(payload.visibleTaxaCount || 0, { minimumHeight: 360 })}px`;
      chart.setOption(chartOption(payload, currentRowZoomState, currentColumnZoomState), { notMerge: true });
      chart.resize();
    }

    chart.on("datazoom", (params) => {
      currentRowZoomState = resolveZoomState(chart, payload.visibleTaxaCount || 0, params);
      currentColumnZoomState = columnZoomStateFromParams(params, xLabels(payload).length)
        || currentColumnZoomState;
    });

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const nextMode = button.dataset.overviewMode;
        const nextPayload = modePayload(payloads, nextMode);
        if (!nextPayload || !nextPayload.available || nextMode === currentMode) return;
        currentMode = nextMode;
        currentRowZoomState = normalizeZoomState(
          nextPayload.visibleTaxaCount || 0,
          defaultZoomState(nextPayload.visibleTaxaCount || 0),
        );
        currentColumnZoomState = normalizeColumnZoomState(
          xLabels(nextPayload).length,
          defaultColumnZoomState(xLabels(nextPayload).length),
        );
        render();
      });
    });

    window.addEventListener("resize", () => chart.resize());
    render();
  }

  document.addEventListener("DOMContentLoaded", mountOverview);
})();
