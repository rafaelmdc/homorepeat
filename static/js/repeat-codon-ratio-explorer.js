(() => {
  const GRID_COLOR = "rgba(23, 36, 44, 0.1)";
  const TEXT_COLOR = "#17242c";
  const MUTED_TEXT_COLOR = "#63727a";
  const DEFAULT_VISIBLE_ROWS = 12;
  const MAX_CHART_HEIGHT = 1300;
  const MAX_VISIBLE_ROWS_WITH_TAXON_LABELS = 24;
  const MAX_MATRIX_CELL_LABELS = 16;
  const MAX_MATRIX_COLUMN_LABELS = 18;
  const MAX_BOTTOM_TREE_LEAF_LABELS = 16;
  const MAX_BOTTOM_TREE_BRACE_LABELS = 48;
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

  function taxonomyGutterReservedHeight(payload, options = {}) {
    const api = taxonomyGutterApi();
    if (!api || !api.hasPayload(payload) || typeof api.reservedHeight !== "function") {
      return 0;
    }
    return api.reservedHeight(payload, options);
  }

  function taxonomyGutterPanel(payload, options = {}) {
    const api = taxonomyGutterApi();
    if (!api || !api.hasPayload(payload) || typeof api.buildPanel !== "function") {
      return null;
    }
    return api.buildPanel(payload, options);
  }

  function attachTaxonomyGutter(chart, payload, options = {}) {
    const api = taxonomyGutterApi();
    if (!api || !api.hasPayload(payload) || typeof api.attach !== "function") {
      return null;
    }
    return api.attach(chart, { payload, ...options });
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

  function shouldShowMatrixCellLabels(taxonCount) {
    return taxonCount > 0 && taxonCount <= MAX_MATRIX_CELL_LABELS;
  }

  function shouldShowMatrixColumnLabels(taxonCount) {
    return taxonCount > 0 && taxonCount <= MAX_MATRIX_COLUMN_LABELS;
  }

  function shouldShowBottomTreeLeafLabels(taxonCount) {
    return taxonCount > 0 && taxonCount <= MAX_BOTTOM_TREE_LEAF_LABELS;
  }

  function shouldShowBottomTreeBraceLabels(taxonCount) {
    return taxonCount > 0 && taxonCount <= MAX_BOTTOM_TREE_BRACE_LABELS;
  }

  function resolvedMatrixVisualRange(minimumValue, maximumValue) {
    const safeMinimum = clamp(numericValue(minimumValue, 0), 0, 1);
    const safeMaximum = clamp(numericValue(maximumValue, 1), 0, 1);
    if (safeMaximum <= safeMinimum) {
      const midpoint = safeMaximum;
      return {
        min: clamp(midpoint - 0.02, 0, 1),
        max: clamp(midpoint + 0.02, 0, 1),
      };
    }
    return {
      min: safeMinimum,
      max: safeMaximum,
    };
  }

  function resolvedSignedPreferenceRange(minimumValue, maximumValue) {
    const safeMinimum = numericValue(minimumValue, -1);
    const safeMaximum = numericValue(maximumValue, 1);
    const absoluteBound = Math.max(Math.abs(safeMinimum), Math.abs(safeMaximum), 0.05);
    return {
      min: -absoluteBound,
      max: absoluteBound,
    };
  }

  function buildYAxisZoom(rowCount, zoomState, {
    yAxisIndex = 0,
    right = 8,
    top = 24,
    bottom = 64,
    width = 14,
  } = {}) {
    if (!zoomState) {
      return [];
    }

    return [
      {
        type: "inside",
        yAxisIndex,
        filterMode: "none",
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
        startValue: zoomState.startValue,
        endValue: zoomState.endValue,
      },
      {
        type: "slider",
        yAxisIndex,
        filterMode: "none",
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

  function zoomPercentageToIndex(rowCount, percentage, fallbackIndex, roundingMethod) {
    if (rowCount <= 1) {
      return 0;
    }
    const normalizedPercentage = clamp(
      numericValue(percentage, Number.NaN),
      0,
      100,
    );
    if (!Number.isFinite(normalizedPercentage)) {
      return fallbackIndex;
    }
    return clamp(
      Math[roundingMethod]((normalizedPercentage / 100) * (rowCount - 1)),
      0,
      rowCount - 1,
    );
  }

  function zoomStateFromEventParams(params, rowCount) {
    if (!params) {
      return null;
    }

    const payload = Array.isArray(params.batch) && params.batch.length > 0
      ? params.batch[0]
      : params;
    if (!payload) {
      return null;
    }

    if (payload.startValue != null || payload.endValue != null) {
      return normalizeZoomState(rowCount, {
        startValue: payload.startValue,
        endValue: payload.endValue,
      });
    }

    if (payload.start != null || payload.end != null) {
      return normalizeZoomState(rowCount, {
        startValue: zoomPercentageToIndex(rowCount, payload.start, 0, "floor"),
        endValue: zoomPercentageToIndex(rowCount, payload.end, Math.max(0, rowCount - 1), "ceil"),
      });
    }

    return null;
  }

  function zoomStateFromChart(chart, rowCount) {
    const dataZoom = chart.getOption().dataZoom;
    if (!Array.isArray(dataZoom) || dataZoom.length === 0) {
      return null;
    }

    const zoomComponent = dataZoom.find((entry) => entry && (
      entry.startValue != null
      || entry.endValue != null
      || entry.start != null
      || entry.end != null
    ));
    if (!zoomComponent) {
      return null;
    }

    if (zoomComponent.startValue != null || zoomComponent.endValue != null) {
      return normalizeZoomState(rowCount, {
        startValue: numericValue(zoomComponent.startValue, 0),
        endValue: numericValue(zoomComponent.endValue, Math.max(0, rowCount - 1)),
      });
    }

    if (zoomComponent.start != null || zoomComponent.end != null) {
      return normalizeZoomState(rowCount, {
        startValue: zoomPercentageToIndex(rowCount, zoomComponent.start, 0, "floor"),
        endValue: zoomPercentageToIndex(rowCount, zoomComponent.end, Math.max(0, rowCount - 1), "ceil"),
      });
    }

    return null;
  }

  function resolveZoomState(chart, rowCount, params) {
    return zoomStateFromEventParams(params, rowCount) || zoomStateFromChart(chart, rowCount);
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
    const hasTaxonomyGutter = hasTaxonomyGutterPayload(taxonomyGutterPayload);
    const leftGutterOverlay = hasTaxonomyGutter ? attachTaxonomyGutter(chart, taxonomyGutterPayload) : null;
    const bottomGutterOverlay = hasTaxonomyGutter
      ? attachTaxonomyGutter(chart, taxonomyGutterPayload, { position: "bottom" })
      : null;
    let currentZoomState = normalizeZoomState(rowCount, null);
    const taxonAxisValues = payload.taxa.map((row) => String(row.taxonId));
    const visualRange = resolvedMatrixVisualRange(payload.valueMin, payload.valueMax);
    const signedPreferenceRange = resolvedSignedPreferenceRange(payload.valueMin, payload.valueMax);
    const taxonLabelByAxisValue = new Map(
      (payload.taxa || []).map((row) => [String(row.taxonId), row.taxonName]),
    );

    function overviewGutterWidth(visibleRowCount) {
      if (!hasTaxonomyGutter) {
        return 0;
      }
      return taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: shouldShowTaxonLabels(visibleRowCount),
        visibleLeafCount: visibleRowCount,
      });
    }

    function overviewBottomTreeHeight(visibleRowCount) {
      if (!hasTaxonomyGutter) {
        return 0;
      }
      return taxonomyGutterReservedHeight(taxonomyGutterPayload, {
        showLabels: shouldShowBottomTreeLeafLabels(visibleRowCount),
        showBraceLabels: shouldShowBottomTreeBraceLabels(visibleRowCount),
        visibleLeafCount: visibleRowCount,
      });
    }

    function currentOverviewLayout(visibleRowCount) {
      const showBottomTreeLeafLabels = shouldShowBottomTreeLeafLabels(visibleRowCount);
      const showBottomTreeBraceLabels = shouldShowBottomTreeBraceLabels(visibleRowCount);
      const showMatrixColumnLabels = !showBottomTreeLeafLabels
        && !showBottomTreeBraceLabels
        && shouldShowMatrixColumnLabels(visibleRowCount);
      return {
        top: 32,
        bottom: overviewBottomTreeHeight(visibleRowCount) + (showMatrixColumnLabels ? 92 : 28),
        showMatrixColumnLabels,
        showBottomTreeLeafLabels,
        showBottomTreeBraceLabels,
      };
    }

    function currentVisibleColumnBounds() {
      if (!currentZoomState) {
        return {
          min: 0,
          max: Math.max(0, rowCount - 1),
        };
      }
      return {
        min: currentZoomState.startValue,
        max: currentZoomState.endValue,
      };
    }

    function currentOverviewMargins(gutterWidth) {
      return {
        left: hasTaxonomyGutter ? gutterWidth + 20 : 160,
        right: currentZoomState ? 148 : 96,
      };
    }

    function applySquareOverviewHeight(layout, margins) {
      const availableWidth = Math.max(220, container.clientWidth - margins.left - margins.right);
      const maximumGridSide = Math.max(220, MAX_CHART_HEIGHT - layout.top - layout.bottom);
      const gridSide = clamp(availableWidth, 220, maximumGridSide);
      const targetHeight = Math.round(layout.top + layout.bottom + gridSide);
      if (Math.abs(container.clientHeight - targetHeight) > 1) {
        container.style.height = `${targetHeight}px`;
        chart.resize();
      }
    }

    if (
      !Array.isArray(payload.cells)
      || payload.cells.length === 0
      || !Array.isArray(payload.taxa)
      || payload.taxa.length === 0
    ) {
      chart.setOption(
        buildEmptyOption(
          payload.mode === "signed_preference_map"
            ? "No visible codon preference cells"
            : "No visible taxon similarity cells",
          "Adjust the filters or choose a residue to populate the overview.",
        ),
      );
      return;
    }

    function refreshOverviewGutter() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const layout = currentOverviewLayout(visibleRowCount);
      const gutterWidth = overviewGutterWidth(visibleRowCount);
      const margins = currentOverviewMargins(gutterWidth);

      if (leftGutterOverlay) {
        leftGutterOverlay.render({
          showLabels: shouldShowTaxonLabels(visibleRowCount),
          zoomState: currentZoomState,
          gutterWidth,
          top: layout.top,
          bottom: layout.bottom,
          left: margins.left,
          right: margins.right,
        });
      }

      if (bottomGutterOverlay) {
        bottomGutterOverlay.render({
          zoomState: currentZoomState,
          gutterWidth,
          top: layout.top,
          bottom: layout.bottom,
          left: margins.left,
          right: margins.right,
          showLabels: layout.showBottomTreeLeafLabels,
          showBraceLabels: layout.showBottomTreeBraceLabels,
          bottomGutterHeight: overviewBottomTreeHeight(visibleRowCount),
        });
      }
    }

    function renderChart() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
      const showMatrixCellLabels = shouldShowMatrixCellLabels(visibleRowCount);
      const layout = currentOverviewLayout(visibleRowCount);
      const columnBounds = currentVisibleColumnBounds();
      const gutterWidth = overviewGutterWidth(visibleRowCount);
      const margins = currentOverviewMargins(gutterWidth);
      applySquareOverviewHeight(layout, margins);
      if (payload.mode === "signed_preference_map") {
        const preferenceData = payload.cells.map((cell) => ({
          value: [String(cell.columnTaxonId), String(cell.rowTaxonId), cell.signedDifference],
          rowTaxonId: String(cell.rowTaxonId),
          rowTaxonName: cell.rowTaxonName,
          rowObservationCount: cell.rowObservationCount,
          rowSpeciesCount: cell.rowSpeciesCount,
          rowCodonOneShare: cell.rowCodonOneShare,
          rowCodonTwoShare: cell.rowCodonTwoShare,
          rowScore: cell.rowScore,
          columnTaxonId: String(cell.columnTaxonId),
          columnTaxonName: cell.columnTaxonName,
          columnObservationCount: cell.columnObservationCount,
          columnSpeciesCount: cell.columnSpeciesCount,
          columnCodonOneShare: cell.columnCodonOneShare,
          columnCodonTwoShare: cell.columnCodonTwoShare,
          columnScore: cell.columnScore,
          signedDifference: cell.signedDifference,
          divergence: cell.divergence,
          reliability: cell.reliability,
          itemStyle: {
            borderColor: "rgba(255, 255, 255, 0.82)",
            borderWidth: 1,
          },
        }));
        chart.setOption({
          animation: false,
          grid: {
            left: margins.left,
            right: margins.right,
            top: layout.top,
            bottom: layout.bottom,
          },
          tooltip: {
            trigger: "item",
            formatter(params) {
              const cell = params.data || {};
              const preferredCodon = cell.signedDifference > 0
                ? payload.codonTwo
                : (cell.signedDifference < 0 ? payload.codonOne : "Balanced");
              return [
                `<strong>${cell.rowTaxonName}</strong> x <strong>${cell.columnTaxonName}</strong>`,
                `${payload.codonTwo} - ${payload.codonOne}: ${formatShare(cell.signedDifference)}`,
                `Row balance: ${formatShare(cell.rowScore)}`,
                `${cell.rowTaxonName} shares: ${payload.codonTwo} ${formatShare(cell.rowCodonTwoShare)}, ${payload.codonOne} ${formatShare(cell.rowCodonOneShare)}`,
                `Column balance: ${formatShare(cell.columnScore)}`,
                `${cell.columnTaxonName} shares: ${payload.codonTwo} ${formatShare(cell.columnCodonTwoShare)}, ${payload.codonOne} ${formatShare(cell.columnCodonOneShare)}`,
                `JSD: ${formatShare(cell.divergence)}`,
                `Species support: ${cell.rowSpeciesCount} vs ${cell.columnSpeciesCount}`,
                `Calls: ${cell.rowObservationCount} vs ${cell.columnObservationCount}`,
                `Interpretation: ${preferredCodon === "Balanced"
                  ? "matched balance"
                  : `${cell.rowTaxonName} is more ${preferredCodon}-preferring than ${cell.columnTaxonName}`}`,
              ].join("<br>");
            },
          },
          xAxis: {
            type: "category",
            data: taxonAxisValues,
            min: columnBounds.min,
            max: columnBounds.max,
            axisLabel: {
              show: layout.showMatrixColumnLabels,
              interval: 0,
              color: TEXT_COLOR,
              rotate: 42,
              hideOverlap: true,
              width: 120,
              overflow: "truncate",
              formatter: (value) => taxonLabelByAxisValue.get(String(value)) || String(value),
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
              show: !hasTaxonomyGutter && showTaxonLabels,
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
            min: signedPreferenceRange.min,
            max: signedPreferenceRange.max,
            calculable: false,
            orient: "vertical",
            right: currentZoomState ? 32 : 16,
            top: "center",
            itemWidth: 16,
            itemHeight: 160,
            text: [`${payload.codonTwo}-preferring`, `${payload.codonOne}-preferring`],
            textGap: 8,
            textStyle: {
              color: MUTED_TEXT_COLOR,
              fontSize: 11,
            },
            inRange: {
              color: ["#0f5964", "#f2efe6", "#d06e37"],
            },
          },
          dataZoom: buildYAxisZoom(rowCount, currentZoomState, {
            yAxisIndex: 0,
            right: 8,
            top: 28,
            bottom: 56,
            width: 12,
          }),
          series: [
            {
              type: "heatmap",
              data: preferenceData,
              encode: {
                x: 0,
                y: 1,
                value: 2,
              },
              label: {
                show: showMatrixCellLabels,
                formatter(params) {
                  return formatShare(
                    params.data && typeof params.data.signedDifference === "number"
                      ? params.data.signedDifference
                      : undefined,
                  );
                },
                color: TEXT_COLOR,
                fontSize: 11,
              },
              itemStyle: {
                borderColor: "rgba(255, 255, 255, 0.82)",
                borderWidth: 1,
              },
              emphasis: {
                itemStyle: {
                  borderColor: TEXT_COLOR,
                  borderWidth: 1.5,
                  shadowBlur: 10,
                  shadowColor: "rgba(0, 0, 0, 0.18)",
                },
              },
            },
          ],
        }, { notMerge: true });
        refreshOverviewGutter();
        return;
      }

      const heatmapData = payload.cells.map((cell) => ({
        value: [
          String(cell.columnTaxonId),
          String(cell.rowTaxonId),
          payload.displayMetric === "divergence" ? cell.divergence : cell.similarity,
        ],
        rowTaxonId: String(cell.rowTaxonId),
        rowTaxonName: cell.rowTaxonName,
        rowRank: cell.rowRank,
        rowObservationCount: cell.rowObservationCount,
        rowSpeciesCount: cell.rowSpeciesCount,
        columnTaxonId: String(cell.columnTaxonId),
        columnTaxonName: cell.columnTaxonName,
        columnRank: cell.columnRank,
        columnObservationCount: cell.columnObservationCount,
        columnSpeciesCount: cell.columnSpeciesCount,
        similarity: cell.similarity,
        divergence: cell.divergence,
        reliability: cell.reliability,
        itemStyle: {
          borderColor: "rgba(255, 255, 255, 0.82)",
          borderWidth: 1,
        },
      }));
      chart.setOption({
        animation: false,
        grid: {
          left: margins.left,
          right: margins.right,
          top: layout.top,
          bottom: layout.bottom,
        },
          tooltip: {
            trigger: "item",
            formatter(params) {
            const cell = params.data || {};
            const isSelfComparison = cell.rowTaxonId === cell.columnTaxonId;
            return [
              `<strong>${cell.rowTaxonName}</strong> x <strong>${cell.columnTaxonName}</strong>`,
              `Similarity: ${formatShare(cell.similarity)}`,
              `JSD: ${formatShare(cell.divergence)}`,
              `Species support: ${cell.rowSpeciesCount} vs ${cell.columnSpeciesCount}`,
              `Calls: ${cell.rowObservationCount} vs ${cell.columnObservationCount}`,
              `Reliability proxy: ${cell.reliability}`,
              isSelfComparison ? "Self-comparison: identical by definition." : "",
            ].filter(Boolean).join("<br>");
          },
        },
          xAxis: {
            type: "category",
            data: taxonAxisValues,
            min: columnBounds.min,
            max: columnBounds.max,
            axisLabel: {
              show: layout.showMatrixColumnLabels,
              interval: 0,
              color: TEXT_COLOR,
              rotate: 42,
            hideOverlap: true,
            width: 120,
            overflow: "truncate",
            formatter: (value) => taxonLabelByAxisValue.get(String(value)) || String(value),
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
            show: !hasTaxonomyGutter && showTaxonLabels,
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
          min: visualRange.min,
          max: visualRange.max,
          calculable: false,
          orient: "vertical",
          right: currentZoomState ? 32 : 16,
          top: "center",
          itemWidth: 16,
          itemHeight: 160,
          text: payload.displayMetric === "divergence"
            ? ["More divergent", "Less divergent"]
            : ["More similar", "More divergent"],
          textGap: 8,
          textStyle: {
            color: MUTED_TEXT_COLOR,
            fontSize: 11,
          },
          inRange: {
            color: ["#d06e37", "#0f5964"],
          },
        },
        dataZoom: buildYAxisZoom(rowCount, currentZoomState, {
          yAxisIndex: 0,
          right: 8,
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
              show: showMatrixCellLabels,
              formatter(params) {
                const pointValue = params.data && Array.isArray(params.data.value)
                  ? params.data.value[2]
                  : undefined;
                return formatShare(
                  typeof pointValue === "number"
                    ? pointValue
                    : undefined,
                );
              },
              color: TEXT_COLOR,
              fontSize: 11,
            },
            itemStyle: {
              borderColor: "rgba(255, 255, 255, 0.82)",
              borderWidth: 1,
            },
            emphasis: {
              itemStyle: {
                borderColor: TEXT_COLOR,
                borderWidth: 1.5,
                shadowBlur: 10,
                shadowColor: "rgba(0, 0, 0, 0.18)",
              },
            },
          },
        ],
      }, { notMerge: true });
      refreshOverviewGutter();
    }

    chart.off("datazoom");
    chart.on("datazoom", (params) => {
      const nextZoomState = resolveZoomState(chart, rowCount, params);
      currentZoomState = nextZoomState;
      renderChart();
    });

    renderChart();

    window.addEventListener("resize", () => {
      chart.resize();
      renderChart();
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
    const hasTaxonomyGutter = hasTaxonomyGutterPayload(taxonomyGutterPayload);
    const gutterOverlay = hasTaxonomyGutter ? attachTaxonomyGutter(chart, taxonomyGutterPayload) : null;
    let currentZoomState = normalizeZoomState(rowCount, null);
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

    function browseGutterWidth(visibleRowCount) {
      if (!hasTaxonomyGutter) {
        return 0;
      }
      return taxonomyGutterReservedWidth(taxonomyGutterPayload, {
        showLabels: shouldShowTaxonLabels(visibleRowCount),
        visibleLeafCount: visibleRowCount,
      });
    }

    function refreshBrowseGutter() {
      if (!gutterOverlay) {
        return;
      }
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      gutterOverlay.render({
        showLabels: shouldShowTaxonLabels(visibleRowCount),
        zoomState: currentZoomState,
        gutterWidth: browseGutterWidth(visibleRowCount),
        top: 72,
        bottom: 48,
      });
    }

    function renderChart() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
      chart.setOption({
        animation: false,
        grid: {
          left: hasTaxonomyGutter
            ? browseGutterWidth(visibleRowCount) + 20
            : 180,
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
            show: !hasTaxonomyGutter && showTaxonLabels,
            interval: 0,
            color: TEXT_COLOR,
            formatter: (value) => taxonLabelByAxisValue.get(String(value)) || String(value),
          },
        },
        dataZoom: buildYAxisZoom(rowCount, currentZoomState, {
          yAxisIndex: 0,
          right: 8,
          top: 72,
          bottom: 48,
        }),
        series,
      }, { notMerge: true });
      refreshBrowseGutter();
    }

    chart.off("datazoom");
    chart.on("datazoom", (params) => {
      const nextZoomState = resolveZoomState(chart, rowCount, params);
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
      if (
        previousVisibleRowCount !== nextVisibleRowCount
        || previousGutterWidth !== nextGutterWidth
      ) {
        renderChart();
        return;
      }
      refreshBrowseGutter();
    });

    renderChart();

    chart.on("click", (params) => {
      if (params && params.data && params.data.branchExplorerUrl) {
        window.location.href = params.data.branchExplorerUrl;
      }
    });

    window.addEventListener("resize", () => {
      chart.resize();
      refreshBrowseGutter();
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
