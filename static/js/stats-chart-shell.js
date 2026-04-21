(() => {
  const DEFAULT_VISIBLE_ROWS = 12;
  const DEFAULT_MAX_CHART_HEIGHT = 1300;
  const DEFAULT_ROW_HEIGHT = 38;
  const DEFAULT_CHART_PADDING = 120;
  const DEFAULT_MUTED_TEXT_COLOR = "#63727a";

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

  function numericValue(value, fallbackValue) {
    if (Array.isArray(value)) {
      return numericValue(value[0], fallbackValue);
    }
    return typeof value === "number" && Number.isFinite(value) ? value : fallbackValue;
  }

  function chartHeightForRowCount(rowCount, {
    minimumHeight,
    maxChartHeight = DEFAULT_MAX_CHART_HEIGHT,
    rowHeight = DEFAULT_ROW_HEIGHT,
    chartPadding = DEFAULT_CHART_PADDING,
  } = {}) {
    if (rowCount <= 0) {
      return minimumHeight;
    }
    return clamp((rowCount * rowHeight) + chartPadding, minimumHeight, maxChartHeight);
  }

  function defaultZoomState(rowCount, {
    defaultVisibleRows = DEFAULT_VISIBLE_ROWS,
  } = {}) {
    return {
      startValue: 0,
      endValue: Math.max(0, Math.min(rowCount - 1, defaultVisibleRows - 1)),
    };
  }

  function normalizeZoomState(rowCount, zoomState, {
    defaultVisibleRows = DEFAULT_VISIBLE_ROWS,
  } = {}) {
    if (rowCount <= defaultVisibleRows) {
      return null;
    }

    const fallback = defaultZoomState(rowCount, { defaultVisibleRows });
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

  function zoomSliderStyle(mutedTextColor) {
    return {
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
        color: mutedTextColor,
      },
    };
  }

  function buildYAxisZoom(rowCount, zoomState, {
    yAxisIndex = 0,
    right = 8,
    top = 24,
    bottom = 64,
    width = 14,
    mutedTextColor = DEFAULT_MUTED_TEXT_COLOR,
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
        moveOnMouseWheel: false,
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
        zoomOnMouseWheel: "shift",
        startValue: zoomState.startValue,
        endValue: zoomState.endValue,
        ...zoomSliderStyle(mutedTextColor),
      },
    ];
  }

  function buildXAxisZoom(columnCount, zoomState, {
    xAxisIndex = 0,
    insideId,
    sliderId,
    left = 96,
    right = 96,
    bottom = 24,
    height = 18,
    mutedTextColor = DEFAULT_MUTED_TEXT_COLOR,
  } = {}) {
    if (!zoomState) {
      return [];
    }

    return [
      {
        ...(insideId ? { id: insideId } : {}),
        type: "inside",
        xAxisIndex,
        filterMode: "none",
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        startValue: zoomState.startValue,
        endValue: Math.min(zoomState.endValue, Math.max(0, columnCount - 1)),
      },
      {
        ...(sliderId ? { id: sliderId } : {}),
        type: "slider",
        xAxisIndex,
        filterMode: "none",
        left,
        right,
        bottom,
        height,
        brushSelect: false,
        zoomOnMouseWheel: false,
        startValue: zoomState.startValue,
        endValue: Math.min(zoomState.endValue, Math.max(0, columnCount - 1)),
        ...zoomSliderStyle(mutedTextColor),
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

  function zoomStateFromEventParams(params, rowCount, {
    defaultVisibleRows = DEFAULT_VISIBLE_ROWS,
  } = {}) {
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
      }, { defaultVisibleRows });
    }

    if (payload.start != null || payload.end != null) {
      return normalizeZoomState(rowCount, {
        startValue: zoomPercentageToIndex(rowCount, payload.start, 0, "floor"),
        endValue: zoomPercentageToIndex(rowCount, payload.end, Math.max(0, rowCount - 1), "ceil"),
      }, { defaultVisibleRows });
    }

    return null;
  }

  function zoomStateFromChart(chart, rowCount, {
    defaultVisibleRows = DEFAULT_VISIBLE_ROWS,
  } = {}) {
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
      }, { defaultVisibleRows });
    }

    if (zoomComponent.start != null || zoomComponent.end != null) {
      return normalizeZoomState(rowCount, {
        startValue: zoomPercentageToIndex(rowCount, zoomComponent.start, 0, "floor"),
        endValue: zoomPercentageToIndex(rowCount, zoomComponent.end, Math.max(0, rowCount - 1), "ceil"),
      }, { defaultVisibleRows });
    }

    return null;
  }

  function resolveZoomState(chart, rowCount, params, {
    defaultVisibleRows = DEFAULT_VISIBLE_ROWS,
  } = {}) {
    return (
      zoomStateFromEventParams(params, rowCount, { defaultVisibleRows })
      || zoomStateFromChart(chart, rowCount, { defaultVisibleRows })
    );
  }

  function installWheelHandler(chart, rowCount, getCurrentZoomState) {
    if (rowCount <= 1) return;
    chart.getDom().addEventListener("wheel", (event) => {
      event.preventDefault();
      const zoomState = getCurrentZoomState();
      if (!zoomState) return;
      const direction = event.deltaY > 0 ? 1 : -1;
      const { startValue, endValue } = zoomState;
      const windowSize = endValue - startValue;
      let newStart;
      let newEnd;
      if (event.shiftKey) {
        const step = Math.max(1, Math.round(windowSize * 0.15));
        const newWindowSize = clamp(windowSize + direction * 2 * step, 1, rowCount);
        const rawPivot = chart.convertFromPixel({ yAxisIndex: 0 }, [event.offsetX, event.offsetY]);
        const pivot = (typeof rawPivot === "number" && Number.isFinite(rawPivot))
          ? clamp(rawPivot, startValue, endValue)
          : (startValue + endValue) / 2;
        const fraction = windowSize > 0 ? (pivot - startValue) / windowSize : 0.5;
        newStart = clamp(Math.round(pivot - fraction * newWindowSize), 0, Math.max(0, rowCount - newWindowSize));
        newEnd = Math.min(newStart + newWindowSize, rowCount - 1);
        if (newEnd <= newStart) return;
      } else {
        const step = Math.max(1, Math.round(windowSize * 0.2));
        newStart = clamp(Math.round(startValue + direction * step), 0, Math.max(0, rowCount - 1 - windowSize));
        newEnd = newStart + windowSize;
      }
      chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 0, startValue: newStart, endValue: newEnd });
    }, { passive: false, capture: true });
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

  window.HomorepeatStatsChartShell = {
    attachTaxonomyGutter,
    buildXAxisZoom,
    buildYAxisZoom,
    chartHeightForRowCount,
    clamp,
    defaultZoomState,
    hasTaxonomyGutterPayload,
    installWheelHandler,
    normalizeZoomState,
    numericValue,
    parsePayload,
    resolveZoomState,
    taxonomyGutterApi,
    taxonomyGutterPanel,
    taxonomyGutterReservedHeight,
    taxonomyGutterReservedWidth,
    visibleRowCountForZoom,
    zoomPercentageToIndex,
    zoomStateFromChart,
    zoomStateFromEventParams,
  };
})();
