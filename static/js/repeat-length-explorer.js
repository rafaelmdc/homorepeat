(() => {
  const BOX_FILL = "#dcebef";
  const BOX_BORDER = "#0f5964";
  const MEDIAN_COLOR = "#d06e37";
  const CHART_MODE_FOCUSED = "focused";
  const CHART_MODE_FULL_RANGE = "full-range";
  const GRID_COLOR = "rgba(23, 36, 44, 0.1)";
  const MAX_VISIBLE_ROWS_WITH_TAXON_LABELS = 24;
  const PENDING_SCROLL_KEY = "repeat-length-explorer:pending-scroll";
  const PENDING_SCROLL_MAX_AGE_MS = 15000;
  const TEXT_COLOR = "#17242c";
  const MUTED_TEXT_COLOR = "#63727a";
  const DEFAULT_VISIBLE_ROWS = 12;
  const DEFAULT_SUMMARY_PAGE_SIZE = 25;
  const MAX_CHART_HEIGHT = 980;
  const MIN_CHART_HEIGHT = 380;
  const ROW_HEIGHT = 38;
  const CHART_PADDING = 120;

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

  function clamp(number, minimum, maximum) {
    return Math.min(Math.max(number, minimum), maximum);
  }

  function positiveInteger(value, fallbackValue) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      return fallbackValue;
    }
    return parsed;
  }

  function numericValue(value, fallbackValue) {
    if (Array.isArray(value)) {
      return numericValue(value[0], fallbackValue);
    }
    return typeof value === "number" && Number.isFinite(value) ? value : fallbackValue;
  }

  function formatLengthValue(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "-";
    }

    const rounded = Math.round(value * 1000) / 1000;
    return Number.isInteger(rounded) ? String(rounded) : String(rounded);
  }

  function truncateTaxonName(taxonName) {
    if (taxonName.length <= 28) {
      return taxonName;
    }
    return `${taxonName.slice(0, 25)}...`;
  }

  function rowCategoryValue(row) {
    return String(row.taxonId);
  }

  function rowForAxisValue(rows, axisValue) {
    return rows.find((row) => rowCategoryValue(row) === String(axisValue)) || null;
  }

  function chartHeightForRowCount(rowCount) {
    if (rowCount <= 0) {
      return MIN_CHART_HEIGHT;
    }
    return clamp((rowCount * ROW_HEIGHT) + CHART_PADDING, MIN_CHART_HEIGHT, MAX_CHART_HEIGHT);
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

  function shouldShowObservationCounts(visibleRowCount) {
    return visibleRowCount <= DEFAULT_VISIBLE_ROWS;
  }

  function shouldShowTaxonLabels(visibleRowCount) {
    return visibleRowCount <= MAX_VISIBLE_ROWS_WITH_TAXON_LABELS;
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
      // Ignore sessionStorage failures and fall back to default browser behavior.
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
        // Ignore cleanup failures.
      }
    }
  }

  function focusedDisplayMin(row) {
    const iqr = Math.max(0, row.q3 - row.q1);
    return Math.max(row.min, row.q1 - (1.5 * iqr));
  }

  function focusedDisplayMax(row) {
    const iqr = Math.max(0, row.q3 - row.q1);
    return Math.min(row.max, row.q3 + (1.5 * iqr));
  }

  function deriveChartRows(rows, mode) {
    return rows.map((row) => {
      if (mode !== CHART_MODE_FOCUSED) {
        return {
          ...row,
          displayMin: row.min,
          displayMax: row.max,
          maxOverflow: false,
        };
      }

      const displayMin = focusedDisplayMin(row);
      const displayMax = focusedDisplayMax(row);
      return {
        ...row,
        displayMin,
        displayMax,
        maxOverflow: row.max > displayMax,
      };
    });
  }

  function lengthBounds(rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
      return [0, 1];
    }

    const visibleMin = Math.min(...rows.map((row) => row.displayMin));
    const visibleMax = Math.max(...rows.map((row) => row.displayMax));
    const span = visibleMax - visibleMin;
    const padding = span > 0 ? Math.max(1, Math.round(span * 0.08)) : 1;
    return [Math.max(0, visibleMin - padding), visibleMax + padding];
  }

  function buildEmptyOption(payload) {
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
        min: 0,
        max: 1,
        show: false,
      },
      yAxis: {
        type: "category",
        data: [],
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
            fill: TEXT_COLOR,
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
            fill: MUTED_TEXT_COLOR,
            textAlign: "center",
          },
        },
      ],
    };
  }

  function buildTooltip(row, { focusedMode = false } = {}) {
    const lines = [
      `<strong>${row.taxonName}</strong>`,
      `Observations: ${row.observationCount}`,
      `Min-Max: ${formatLengthValue(row.min)}-${formatLengthValue(row.max)}`,
      `Median: ${formatLengthValue(row.median)}`,
      `IQR: ${formatLengthValue(row.q1)}-${formatLengthValue(row.q3)}`,
    ];
    if (focusedMode && row.maxOverflow) {
      lines.push(`Focused view clips max whisker at ${formatLengthValue(row.displayMax)}`);
    }
    return lines.join("<br>");
  }

  function markerPoint(row, rowIndex, xValue) {
    return {
      value: [xValue, rowIndex],
      rowIndex,
    };
  }

  function overflowMarkerData(rows) {
    const markers = [];
    rows.forEach((row, rowIndex) => {
      if (row.maxOverflow) {
        markers.push(markerPoint(row, rowIndex, row.displayMax));
      }
    });
    return markers;
  }

  function averageMedian(rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
      return null;
    }

    const sum = rows.reduce((total, row) => total + row.median, 0);
    return sum / rows.length;
  }

  function buildChartOption(payload, mode, zoomState) {
    if (!Array.isArray(payload.rows) || payload.rows.length === 0) {
      return buildEmptyOption(payload);
    }

    const rows = deriveChartRows(payload.rows, mode);
    const categories = rows.map((row) => rowCategoryValue(row));
    const boxplotData = rows.map((row) => [row.displayMin, row.q1, row.median, row.q3, row.displayMax]);
    const [xMin, xMax] = lengthBounds(rows);
    const visibleRowWindow = Math.min(rows.length, DEFAULT_VISIBLE_ROWS);
    const needsZoom = rows.length > visibleRowWindow;
    const normalizedZoomState = normalizeZoomState(rows.length, zoomState);
    const visibleRowCount = visibleRowCountForZoom(rows.length, normalizedZoomState);
    const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
    const showObservationCounts = shouldShowObservationCounts(
      visibleRowCount,
    );
    const overflowMarkers = mode === CHART_MODE_FOCUSED ? overflowMarkerData(rows) : [];
    const avgMedian = averageMedian(rows);

    return {
      animationDuration: 250,
      animationDurationUpdate: 150,
      grid: {
        left: 188,
        right: needsZoom ? 56 : 20,
        top: 16,
        bottom: 56,
        containLabel: false,
      },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: "rgba(255, 253, 249, 0.98)",
        borderColor: "rgba(23, 36, 44, 0.12)",
        borderWidth: 1,
        textStyle: {
          color: TEXT_COLOR,
          fontSize: 13,
        },
        formatter(params) {
          return buildTooltip(rows[params.dataIndex], {
            focusedMode: mode === CHART_MODE_FOCUSED,
          });
        },
      },
      xAxis: {
        type: "value",
        min: xMin,
        max: xMax,
        name: "Repeat length",
        nameGap: 22,
        nameLocation: "middle",
        nameTextStyle: {
          color: MUTED_TEXT_COLOR,
          fontWeight: 700,
          fontSize: 12,
        },
        axisLabel: {
          color: MUTED_TEXT_COLOR,
        },
        splitLine: {
          lineStyle: {
            color: GRID_COLOR,
          },
        },
      },
      yAxis: {
        type: "category",
        data: categories,
        triggerEvent: true,
        axisTick: {
          show: false,
        },
        axisLine: {
          show: false,
        },
        axisLabel: {
          show: showTaxonLabels,
          interval: showTaxonLabels ? 0 : "auto",
          color: TEXT_COLOR,
          fontWeight: 700,
          lineHeight: 17,
          margin: 16,
          rich: {
            taxon: {
              color: TEXT_COLOR,
              fontWeight: 700,
            },
            count: {
              color: MUTED_TEXT_COLOR,
              fontSize: 12,
              fontWeight: 600,
            },
          },
          formatter(value) {
            const row = rowForAxisValue(rows, value);
            if (!row) {
              return "";
            }
            if (!showObservationCounts) {
              return `{taxon|${truncateTaxonName(row.taxonName)}}`;
            }
            return `{taxon|${truncateTaxonName(row.taxonName)}}\n{count|n=${row.observationCount}}`;
          },
        },
      },
      dataZoom: needsZoom
        ? [
            {
              type: "inside",
              yAxisIndex: 0,
              zoomOnMouseWheel: false,
              moveOnMouseMove: true,
              moveOnMouseWheel: true,
              startValue: normalizedZoomState.startValue,
              endValue: normalizedZoomState.endValue,
            },
            {
              type: "slider",
              yAxisIndex: 0,
              filterMode: "empty",
              right: 8,
              width: 14,
              top: 24,
              bottom: 64,
              brushSelect: false,
              startValue: normalizedZoomState.startValue,
              endValue: normalizedZoomState.endValue,
              fillerColor: "rgba(15, 89, 100, 0.16)",
              borderColor: "rgba(23, 36, 44, 0.08)",
              handleStyle: {
                color: BOX_BORDER,
                borderColor: BOX_BORDER,
              },
              moveHandleStyle: {
                color: BOX_BORDER,
              },
              textStyle: {
                color: MUTED_TEXT_COLOR,
              },
            },
          ]
        : [],
      series: [
        {
          name: "Repeat length distribution",
          type: "boxplot",
          cursor: "pointer",
          data: boxplotData,
          itemStyle: {
            color: BOX_FILL,
            borderColor: BOX_BORDER,
            borderWidth: 2,
          },
          emphasis: {
            itemStyle: {
              color: "#eef6f7",
              borderColor: BOX_BORDER,
              borderWidth: 2,
            },
          },
          tooltip: {
            show: true,
          },
        },
        {
          name: "Median marker",
          type: "scatter",
          cursor: "pointer",
          data: rows.map((row, index) => markerPoint(row, index, row.median)),
          symbol: "circle",
          symbolSize: 7,
          itemStyle: {
            color: MEDIAN_COLOR,
          },
          z: 4,
          tooltip: {
            show: false,
          },
          markLine: avgMedian === null
            ? undefined
            : {
                silent: true,
                symbol: "none",
                lineStyle: {
                  color: MEDIAN_COLOR,
                  type: "dashed",
                  width: 2,
                  opacity: 0.7,
                },
                label: {
                  show: true,
                  formatter: `Avg median ${formatLengthValue(avgMedian)}`,
                  color: MEDIAN_COLOR,
                  fontWeight: 700,
                  padding: [0, 0, 8, 0],
                },
                data: [
                  {
                    xAxis: avgMedian,
                  },
                ],
              },
        },
        ...(
          overflowMarkers.length > 0
            ? [
                {
                  name: "Clipped max marker",
                  type: "scatter",
                  cursor: "pointer",
                  data: overflowMarkers,
                  symbol: "triangle",
                  symbolRotate: 90,
                  symbolSize: 12,
                  itemStyle: {
                    color: MEDIAN_COLOR,
                  },
                  z: 6,
                  tooltip: {
                    show: true,
                    formatter(params) {
                      const row = rows[params.data.rowIndex];
                      return buildTooltip(row, { focusedMode: true });
                    },
                  },
                },
              ]
            : []
        ),
      ],
    };
  }

  function openBranchExplorer(rows, rowIndex) {
    const row = rows[rowIndex];
    if (!row || !row.branchExplorerUrl) {
      return;
    }
    savePendingScrollPosition();
    window.location.assign(row.branchExplorerUrl);
  }

  function rowIndexForAxisValue(rows, axisValue) {
    return rows.findIndex((row) => rowCategoryValue(row) === String(axisValue));
  }

  function rowIndexForChartParams(params) {
    if (params.data && typeof params.data.rowIndex === "number") {
      return params.data.rowIndex;
    }
    if (typeof params.dataIndex === "number") {
      return params.dataIndex;
    }
    return -1;
  }

  function installDrilldown(chart, payload) {
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    if (rows.length === 0) {
      return;
    }

    chart.off("click");
    chart.on("click", (params) => {
      const rowIndex = rowIndexForChartParams(params);
      if (rowIndex >= 0) {
        openBranchExplorer(rows, rowIndex);
        return;
      }

      if (params.componentType === "yAxis") {
        const rowIndex = rowIndexForAxisValue(rows, params.value);
        if (rowIndex >= 0) {
          openBranchExplorer(rows, rowIndex);
        }
      }
    });
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

  function mountLengthChart() {
    const container = document.getElementById("repeat-length-chart");
    const payload = parsePayload("repeat-length-chart-payload");
    if (!container || !payload || typeof window.echarts === "undefined") {
      return;
    }

    const modeButtons = Array.from(document.querySelectorAll("[data-chart-mode-button]"));
    container.style.height = `${chartHeightForRowCount(payload.visibleTaxaCount || 0)}px`;

    const chart = window.echarts.init(container, null, { renderer: "svg" });
    let currentMode = CHART_MODE_FOCUSED;
    let currentZoomState = normalizeZoomState(payload.visibleTaxaCount || 0, null);

    function syncModeButtons() {
      modeButtons.forEach((button) => {
        const isActive = button.dataset.chartMode === currentMode;
        button.classList.toggle("btn-brand", isActive);
        button.classList.toggle("btn-outline-secondary", !isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderChart() {
      chart.setOption(buildChartOption(payload, currentMode, currentZoomState), { notMerge: true });
      installDrilldown(chart, payload);
    }

    chart.off("datazoom");
    chart.on("datazoom", () => {
      const nextZoomState = zoomStateFromChart(chart, payload.visibleTaxaCount || 0);
      const previousVisibleRowCount = visibleRowCountForZoom(payload.visibleTaxaCount || 0, currentZoomState);
      const nextVisibleRowCount = visibleRowCountForZoom(payload.visibleTaxaCount || 0, nextZoomState);
      currentZoomState = nextZoomState;
      if (shouldShowObservationCounts(previousVisibleRowCount) !== shouldShowObservationCounts(nextVisibleRowCount)) {
        renderChart();
      }
    });

    modeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const requestedMode = button.dataset.chartMode;
        if (requestedMode !== CHART_MODE_FOCUSED && requestedMode !== CHART_MODE_FULL_RANGE) {
          return;
        }
        if (requestedMode === currentMode) {
          return;
        }
        currentMode = requestedMode;
        syncModeButtons();
        renderChart();
      });
    });

    syncModeButtons();
    renderChart();

    window.addEventListener("resize", () => {
      chart.resize();
    });
  }

  function summaryPageStatus(pageNumber, pageCount, totalRows, pageSize) {
    const startRow = ((pageNumber - 1) * pageSize) + 1;
    const endRow = Math.min(pageNumber * pageSize, totalRows);
    return `Rows ${startRow}-${endRow} of ${totalRows} visible taxa. Page ${pageNumber} of ${pageCount}.`;
  }

  function mountSummaryTablePagination() {
    const section = document.querySelector("[data-summary-section]");
    if (!section) {
      return;
    }

    const tableBody = section.querySelector("[data-summary-table-body]");
    const pagination = section.querySelector("[data-summary-pagination]");
    const previousButton = section.querySelector("[data-summary-pagination-previous]");
    const nextButton = section.querySelector("[data-summary-pagination-next]");
    const status = section.querySelector("[data-summary-pagination-status]");
    if (!tableBody || !pagination || !previousButton || !nextButton || !status) {
      return;
    }

    const rows = Array.from(tableBody.querySelectorAll("[data-summary-row]"));
    if (rows.length === 0) {
      return;
    }

    const pageSize = positiveInteger(section.dataset.summaryPageSize, DEFAULT_SUMMARY_PAGE_SIZE);
    const pageCount = Math.ceil(rows.length / pageSize);
    if (pageCount <= 1) {
      return;
    }

    function renderPage(pageNumber) {
      const currentPage = clamp(pageNumber, 1, pageCount);
      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = startIndex + pageSize;

      rows.forEach((row, index) => {
        row.hidden = index < startIndex || index >= endIndex;
      });

      previousButton.disabled = currentPage === 1;
      nextButton.disabled = currentPage === pageCount;
      status.textContent = summaryPageStatus(currentPage, pageCount, rows.length, pageSize);
      pagination.hidden = false;
      pagination.dataset.currentPage = String(currentPage);
    }

    previousButton.addEventListener("click", () => {
      renderPage(positiveInteger(pagination.dataset.currentPage, 1) - 1);
    });

    nextButton.addEventListener("click", () => {
      renderPage(positiveInteger(pagination.dataset.currentPage, 1) + 1);
    });

    renderPage(1);
  }

  function installScrollPreservingLinks() {
    document.querySelectorAll("[data-preserve-scroll-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0) {
          return;
        }
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }
        savePendingScrollPosition();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    mountLengthChart();
    mountSummaryTablePagination();
    installScrollPreservingLinks();
    restorePendingScrollPosition();
  });
})();
