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
    pairwise: "codon-composition-length-pairwise-overview-payload",
    pairwiseTaxonomyGutter: "codon-composition-length-pairwise-taxonomy-gutter-payload",
    browse: "codon-composition-length-browse-payload",
    inspect: "codon-composition-length-inspect-payload",
  };
  const CODON_COLORS = [
    "#0f5964",
    "#d06e37",
    "#7b5ea7",
    "#2f8f5b",
    "#b04f6f",
    "#9a7b2f",
  ];
  const DEFAULT_VISIBLE_COLUMNS = 16;
  const DEFAULT_BROWSE_WINDOW_SIZE = 12;
  const BROWSE_PANEL_HEIGHT = 250;
  const BROWSE_ROW_GAP = 16;
  const BROWSE_ROW_BUFFER = 2;

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
    const events = Array.isArray(params.batch) && params.batch.length > 0 ? params.batch : [params];
    const payload = events.find((entry) => entry && entry.dataZoomId === "codon-length-x-slider");
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

  function formatShare(value) {
    return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-";
  }

  function supportLine(label, observationCount, speciesCount, totalObservationCount) {
    const total = Math.max(0, totalObservationCount || 0);
    const share = total > 0 ? ` (${formatShare((observationCount || 0) / total)} of panel total)` : "";
    return `${label}: ${observationCount} observations${share}, ${speciesCount} species`;
  }

  function tooltipHtml(payload, cell) {
    const taxon = payload.taxa[cell.rowIndex] || {};
    if (payload.mode === "shift") {
      return [
        `<strong>${taxon.taxonName || "Taxon"}</strong>`,
        `${cell.previousBin.label} -> ${cell.nextBin.label}`,
        `${payload.metricLabel}: ${cell.shift.toFixed(3)}`,
        supportLine(
          "Previous support",
          cell.previousSupport.observationCount,
          cell.previousSupport.speciesCount,
          taxon.observationCount,
        ),
        supportLine(
          "Next support",
          cell.nextSupport.observationCount,
          cell.nextSupport.speciesCount,
          taxon.observationCount,
        ),
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
        supportLine("Support", cell.observationCount, cell.speciesCount, taxon.observationCount),
      ].join("<br>");
    }
    return [
      `<strong>${taxon.taxonName || "Taxon"}</strong>`,
      cell.binLabel,
      `Dominant codon: ${cell.dominantCodon}`,
      `Dominance margin: ${cell.dominanceMargin.toFixed(3)}`,
      supportLine("Support", cell.observationCount, cell.speciesCount, taxon.observationCount),
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
      left: 0,
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
      const isAvailable = Boolean(payload && payload.available);
      const isActive = mode === activeMode;
      button.hidden = !isAvailable;
      button.disabled = !isAvailable;
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
    const pairwiseContainer = document.getElementById("codon-composition-length-pairwise-chart");
    if (!container || typeof window.echarts === "undefined") return;

    const pairwisePayload = parsePayload(PAYLOAD_IDS.pairwise) || {};
    const payloads = {
      preference: parsePayload(PAYLOAD_IDS.preference) || {},
      dominance: parsePayload(PAYLOAD_IDS.dominance) || {},
      shift: parsePayload(PAYLOAD_IDS.shift) || {},
      similarity: pairwisePayload,
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

    if (pairwiseContainer && pairwisePayload?.available && window.HomorepeatPairwiseOverview) {
      const pairwiseTaxonomyGutterPayload = parsePayload(PAYLOAD_IDS.pairwiseTaxonomyGutter) || null;
      window.HomorepeatPairwiseOverview.renderPairwiseOverview({
        container: pairwiseContainer,
        payload: pairwisePayload,
        taxonomyGutterPayload: pairwiseTaxonomyGutterPayload,
        distanceScaleStorageKey: "codon-length-pairwise-distance-scale",
      });
      pairwiseContainer.hidden = true;
    }

    function render() {
      const isPairwise = currentMode === "similarity";
      if (isPairwise) {
        container.hidden = true;
        if (pairwiseContainer) pairwiseContainer.hidden = false;
        if (emptyMessage) emptyMessage.hidden = true;
        syncButtons(buttons, currentMode, payloads);
        syncDescriptions(descriptions, currentMode);
        return;
      }
      if (pairwiseContainer) pairwiseContainer.hidden = true;
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
      if (currentMode === "similarity") return;
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
        if (nextMode !== "similarity") {
          currentRowZoomState = normalizeZoomState(
            nextPayload.visibleTaxaCount || 0,
            defaultZoomState(nextPayload.visibleTaxaCount || 0),
          );
          currentColumnZoomState = normalizeColumnZoomState(
            xLabels(nextPayload).length,
            defaultColumnZoomState(xLabels(nextPayload).length),
          );
        }
        render();
      });
    });

    window.addEventListener("resize", () => chart.resize());
    render();
  }

  function browseSeries(payload, panel) {
    const codons = payload.visibleCodons || [];
    const totalObservations = Math.max(0, panel.observationCount || 0);
    const supportSeries = {
      name: "Support",
      type: "line",
      smooth: false,
      showSymbol: false,
      connectNulls: false,
      silent: true,
      tooltip: { show: false },
      emphasis: { disabled: true },
      z: 3,
      lineStyle: {
        color: "#17242c",
        width: 2,
        opacity: 0.22,
      },
      areaStyle: {
        color: "#17242c",
        opacity: 0.05,
      },
      data: panel.bins.map((bin) => {
        if (!bin.occupied || totalObservations <= 0) return null;
        return (bin.observationCount || 0) / totalObservations;
      }),
    };
    if (codons.length === 2) {
      return [
        supportSeries,
        ...codons.map((codon, codonIndex) => ({
          name: codon,
          type: "line",
          smooth: false,
          showSymbol: true,
          symbolSize: 4,
          connectNulls: false,
          z: 2,
          areaStyle: { opacity: codonIndex === 0 ? 0.22 : 0 },
          lineStyle: { width: 2 },
          itemStyle: { color: CODON_COLORS[codonIndex % CODON_COLORS.length] },
          data: panel.bins.map((bin) => {
            const shareRow = (bin.codonShares || []).find((row) => row.codon === codon);
            return bin.occupied && shareRow ? shareRow.share : null;
          }),
        })),
      ];
    }
    return [
      ...codons.map((codon, codonIndex) => ({
        name: codon,
        type: "bar",
        stack: "composition",
        barWidth: "72%",
        z: 2,
        itemStyle: {
          color: CODON_COLORS[codonIndex % CODON_COLORS.length],
        },
        data: panel.bins.map((bin) => {
          const shareRow = (bin.codonShares || []).find((row) => row.codon === codon);
          return bin.occupied && shareRow ? shareRow.share : null;
        }),
      })),
      supportSeries,
    ];
  }

  function browseTooltip(panel, dataIndex) {
    const bin = panel.bins[dataIndex];
    if (!bin) return "";
    const lines = [
      `<strong>${panel.taxonName}</strong>`,
      bin.bin.label,
    ];
    if (!bin.occupied) {
      lines.push("No occupied observations in this bin");
      return lines.join("<br>");
    }
    lines.push(supportLine("Support", bin.observationCount, bin.speciesCount, panel.observationCount));
    lines.push(...(bin.codonShares || []).map((row) => `${row.codon}: ${formatShare(row.share)}`));
    return lines.join("<br>");
  }

  function browseChartOption(payload, panel) {
    const labels = (payload.visibleBins || []).map((bin) => bin.label);
    const isTwoCodon = (payload.visibleCodons || []).length === 2;
    return {
      animation: false,
      color: CODON_COLORS,
      grid: {
        left: 48,
        right: 18,
        top: isTwoCodon ? 34 : 42,
        bottom: 52,
      },
      legend: {
        show: true,
        top: 10,
        type: "scroll",
        data: payload.visibleCodons || [],
        textStyle: { color: "#63727a" },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        formatter(params) {
          const firstParam = Array.isArray(params) ? params[0] : params;
          return browseTooltip(panel, firstParam?.dataIndex ?? 0);
        },
      },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: {
          color: "#63727a",
          interval: labelInterval(labels.length),
          hideOverlap: true,
          width: 48,
          overflow: "truncate",
        },
        axisTick: { alignWithLabel: true },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 1,
        axisLabel: {
          color: "#63727a",
          formatter: (value) => `${Math.round(value * 100)}%`,
        },
        splitLine: {
          lineStyle: { color: "rgba(23, 36, 44, 0.08)" },
        },
      },
      series: browseSeries(payload, panel),
    };
  }

  function buildBrowsePanel(payload, panel) {
    const panelNode = document.createElement("article");
    panelNode.className = "codon-length-browse-panel";

    const header = document.createElement("div");
    header.className = "codon-length-browse-panel__header";

    const title = document.createElement("p");
    title.className = "codon-length-browse-panel__title";
    title.textContent = panel.taxonName;

    const meta = document.createElement("p");
    meta.className = "codon-length-browse-panel__meta";
    meta.textContent = `${panel.observationCount} observations`;

    const chartNode = document.createElement("div");
    chartNode.className = "codon-length-browse-chart";

    header.append(title, meta);
    panelNode.append(header, chartNode);

    return { panelNode, chartNode, panel };
  }

  function browseColumnCount(container) {
    const width = container.clientWidth || 0;
    if (width <= 720) return 1;
    if (width <= 1100) return 2;
    return 3;
  }

  function mountBrowse() {
    const container = document.getElementById("codon-composition-length-browse");
    if (!container || typeof window.echarts === "undefined") return;

    const payload = parsePayload(PAYLOAD_IDS.browse) || {};
    const emptyMessage = document.querySelector("[data-codon-length-browse-empty]");
    const toolbar = document.querySelector("[data-codon-length-browse-toolbar]");
    const rangeNode = document.querySelector("[data-codon-length-browse-range]");
    const spacer = container.querySelector("[data-codon-length-browse-spacer]");
    if (!payload.available || !Array.isArray(payload.panels) || payload.panels.length === 0) {
      container.hidden = true;
      if (toolbar) toolbar.hidden = true;
      return;
    }

    container.hidden = false;
    if (emptyMessage) emptyMessage.hidden = true;
    if (toolbar) toolbar.hidden = false;

    let columnCount = browseColumnCount(container);
    let rowHeight = BROWSE_PANEL_HEIGHT + BROWSE_ROW_GAP;
    let mountedRows = new Map();
    let rafHandle = null;

    function totalRows() {
      return Math.ceil(payload.panels.length / columnCount);
    }

    function updateSpacerHeight() {
      if (spacer) {
        spacer.style.height = `${Math.max(1, totalRows() * rowHeight)}px`;
      }
    }

    function disposeRow(rowIndex) {
      const rowEntry = mountedRows.get(rowIndex);
      if (!rowEntry) return;
      rowEntry.charts.forEach((chart) => chart.dispose());
      rowEntry.rowNode.remove();
      mountedRows.delete(rowIndex);
    }

    function buildBrowseRow(rowIndex) {
      const rowNode = document.createElement("div");
      rowNode.className = "codon-length-browse-row";
      rowNode.style.top = `${rowIndex * rowHeight}px`;
      rowNode.style.height = `${BROWSE_PANEL_HEIGHT}px`;

      const startIndex = rowIndex * columnCount;
      const panels = payload.panels.slice(startIndex, startIndex + columnCount);
      const entries = panels.map((panel) => buildBrowsePanel(payload, panel));
      rowNode.append(...entries.map((entry) => entry.panelNode));
      spacer.append(rowNode);

      const charts = entries.map((entry) => {
        const chart = window.echarts.init(entry.chartNode);
        chart.setOption(browseChartOption(payload, entry.panel), { notMerge: true });
        return chart;
      });
      window.requestAnimationFrame(() => {
        charts.forEach((chart) => chart.resize());
      });
      mountedRows.set(rowIndex, { rowNode, charts });
    }

    function syncToolbar(firstPanelIndex, lastPanelIndex) {
      if (!rangeNode) return;
      rangeNode.textContent = `Showing taxa ${firstPanelIndex + 1}-${lastPanelIndex + 1} of ${payload.panels.length}`;
    }

    function renderVirtualWindow() {
      rafHandle = null;
      updateSpacerHeight();
      const viewportHeight = container.clientHeight || 1;
      const scrollTop = container.scrollTop || 0;
      const firstVisibleRow = Math.max(0, Math.floor(scrollTop / rowHeight) - BROWSE_ROW_BUFFER);
      const lastVisibleRow = Math.min(
        Math.max(0, totalRows() - 1),
        Math.ceil((scrollTop + viewportHeight) / rowHeight) + BROWSE_ROW_BUFFER,
      );
      mountedRows.forEach((_rowEntry, rowIndex) => {
        if (rowIndex < firstVisibleRow || rowIndex > lastVisibleRow) {
          disposeRow(rowIndex);
        }
      });
      for (let rowIndex = firstVisibleRow; rowIndex <= lastVisibleRow; rowIndex += 1) {
        if (!mountedRows.has(rowIndex)) {
          buildBrowseRow(rowIndex);
        }
      }
      const firstPanelIndex = Math.min(payload.panels.length - 1, firstVisibleRow * columnCount);
      const lastPanelIndex = Math.min(payload.panels.length - 1, ((lastVisibleRow + 1) * columnCount) - 1);
      syncToolbar(firstPanelIndex, lastPanelIndex);
    }

    function scheduleRenderVirtualWindow() {
      if (rafHandle !== null) return;
      rafHandle = window.requestAnimationFrame(renderVirtualWindow);
    }

    if (spacer) spacer.replaceChildren();
    updateSpacerHeight();
    container.addEventListener("scroll", scheduleRenderVirtualWindow, { passive: true });
    window.addEventListener("resize", () => {
      const nextColumnCount = browseColumnCount(container);
      if (nextColumnCount !== columnCount) {
        mountedRows.forEach((_rowEntry, rowIndex) => disposeRow(rowIndex));
        columnCount = nextColumnCount;
        updateSpacerHeight();
        renderVirtualWindow();
        return;
      }
      mountedRows.forEach((rowEntry) => {
        rowEntry.charts.forEach((chart) => chart.resize());
      });
    });
    renderVirtualWindow();
  }

  function inspectChartOption(payload) {
    const codons = payload.visibleCodons || [];
    const binRows = payload.binRows || [];
    const labels = binRows.map((row) => row.binLabel);
    const isTwoCodon = codons.length === 2;
    const compRows = payload.comparisonBinRows || [];
    const hasComparison = compRows.length > 0;
    const compLabel = payload.comparisonScopeLabel || "Parent";
    const compRowByBinStart = new Map(compRows.map((r) => [r.binStart, r]));

    function inspectTooltip(dataIndex) {
      const row = binRows[dataIndex];
      if (!row) return "";
      const lines = [
        `<strong>${payload.scopeLabel}</strong>`,
        row.binLabel,
        supportLine("Support", row.observationCount, row.speciesCount, payload.observationCount),
        `Dominant codon: ${row.dominantCodon}`,
        `Dominance margin: ${row.dominanceMargin.toFixed(3)}`,
      ];
      if (row.delta !== null && row.delta !== undefined) {
        lines.push(`Shift from previous: ${row.delta.toFixed(3)}`);
      }
      lines.push(...(row.codonShares || []).map((cs) => `${cs.codon}: ${formatShare(cs.share)}`));
      if (hasComparison) {
        const compRow = compRowByBinStart.get(row.binStart);
        if (compRow) {
          lines.push(`<hr><strong>${compLabel}</strong>`);
          lines.push(supportLine("Support", compRow.observationCount, compRow.speciesCount, payload.comparisonObservationCount));
          lines.push(...(compRow.codonShares || []).map((cs) => `${cs.codon}: ${formatShare(cs.share)}`));
        }
      }
      return lines.join("<br>");
    }

    function makeSeries() {
      if (isTwoCodon) {
        const focused = codons.map((codon, i) => ({
          name: codon,
          type: "line",
          smooth: false,
          showSymbol: true,
          symbolSize: 5,
          connectNulls: false,
          areaStyle: { opacity: i === 0 ? 0.22 : 0 },
          lineStyle: { width: 2.5 },
          itemStyle: { color: CODON_COLORS[i % CODON_COLORS.length] },
          data: binRows.map((row) => {
            const cs = (row.codonShares || []).find((s) => s.codon === codon);
            return cs ? cs.share : null;
          }),
        }));
        if (!hasComparison) return focused;
        const comparison = codons.map((codon, i) => ({
          name: `${codon} (${compLabel})`,
          type: "line",
          smooth: false,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1.5, type: "dashed", color: CODON_COLORS[i % CODON_COLORS.length] },
          itemStyle: { color: CODON_COLORS[i % CODON_COLORS.length] },
          tooltip: { show: false },
          data: binRows.map((row) => {
            const compRow = compRowByBinStart.get(row.binStart);
            const cs = compRow && (compRow.codonShares || []).find((s) => s.codon === codon);
            return cs ? cs.share : null;
          }),
        }));
        return [...focused, ...comparison];
      }
      const focused = codons.map((codon, i) => ({
        name: codon,
        type: "bar",
        stack: "composition",
        barWidth: hasComparison ? "42%" : "72%",
        itemStyle: { color: CODON_COLORS[i % CODON_COLORS.length] },
        data: binRows.map((row) => {
          const cs = (row.codonShares || []).find((s) => s.codon === codon);
          return cs ? cs.share : null;
        }),
      }));
      if (!hasComparison) return focused;
      const comparison = codons.map((codon, i) => ({
        name: `${codon} (${compLabel})`,
        type: "bar",
        stack: "composition-parent",
        barWidth: "42%",
        itemStyle: { color: CODON_COLORS[i % CODON_COLORS.length], opacity: 0.4 },
        data: binRows.map((row) => {
          const compRow = compRowByBinStart.get(row.binStart);
          const cs = compRow && (compRow.codonShares || []).find((s) => s.codon === codon);
          return cs ? cs.share : null;
        }),
      }));
      return [...focused, ...comparison];
    }

    return {
      animation: false,
      color: CODON_COLORS,
      grid: {
        left: 60,
        right: 24,
        top: isTwoCodon ? 42 : 50,
        bottom: 52,
      },
      legend: {
        show: true,
        top: 10,
        type: "scroll",
        data: codons,
        textStyle: { color: "#63727a" },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        formatter(params) {
          const firstParam = Array.isArray(params) ? params[0] : params;
          return inspectTooltip(firstParam?.dataIndex ?? 0);
        },
      },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: {
          color: "#63727a",
          interval: labelInterval(labels.length),
          hideOverlap: true,
          width: 52,
          overflow: "truncate",
        },
        axisTick: { alignWithLabel: true },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 1,
        axisLabel: {
          color: "#63727a",
          formatter: (value) => `${Math.round(value * 100)}%`,
        },
        splitLine: {
          lineStyle: { color: "rgba(23, 36, 44, 0.08)" },
        },
      },
      series: makeSeries(),
    };
  }

  function mountInspect() {
    const container = document.getElementById("codon-composition-length-inspect-chart");
    if (!container || typeof window.echarts === "undefined") return;

    const payload = parsePayload(PAYLOAD_IDS.inspect) || {};
    if (!payload.available || !Array.isArray(payload.binRows) || payload.binRows.length === 0) {
      container.hidden = true;
      return;
    }

    container.hidden = false;
    container.style.height = "300px";
    const chart = window.echarts.init(container);
    chart.setOption(inspectChartOption(payload), { notMerge: true });
    window.addEventListener("resize", () => chart.resize());
  }

  document.addEventListener("DOMContentLoaded", () => {
    mountOverview();
    mountBrowse();
    mountInspect();
  });
})();
