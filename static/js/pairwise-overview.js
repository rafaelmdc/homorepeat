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
  const MAX_OVERVIEW_BORDERS = 24;
  const SIGNED_PREFERENCE_LEGEND_EXTENT = 1.25;
  const DEFAULT_SIGNED_PREFERENCE_MAGNITUDE = SIGNED_PREFERENCE_LEGEND_EXTENT;
  const MIN_SIGNED_PREFERENCE_MAGNITUDE = 0.05;
  const SIGNED_PREFERENCE_MAGNITUDE_STEP = 0.05;
  const DISTANCE_SCALE_STEP = 0.02;
  const DISTANCE_SCALE_DEFAULT_MIN = 0;
  const DISTANCE_SCALE_DEFAULT_MAX = 1;
  const ROW_HEIGHT = 38;
  const CHART_PADDING = 120;

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

  function normalizedSignedPreferenceMagnitude(value) {
    const safeMagnitude = clamp(
      numericValue(value, DEFAULT_SIGNED_PREFERENCE_MAGNITUDE),
      MIN_SIGNED_PREFERENCE_MAGNITUDE,
      SIGNED_PREFERENCE_LEGEND_EXTENT,
    );
    const roundedMagnitude = Math.round(safeMagnitude / SIGNED_PREFERENCE_MAGNITUDE_STEP)
      * SIGNED_PREFERENCE_MAGNITUDE_STEP;
    return Number(
      clamp(
        roundedMagnitude,
        MIN_SIGNED_PREFERENCE_MAGNITUDE,
        SIGNED_PREFERENCE_LEGEND_EXTENT,
      ).toFixed(2),
    );
  }

  function currentSignedPreferenceRange(magnitude) {
    const resolvedMagnitude = normalizedSignedPreferenceMagnitude(magnitude);
    return {
      magnitude: resolvedMagnitude,
      min: -resolvedMagnitude,
      max: resolvedMagnitude,
    };
  }

  function loadSignedPreferenceMagnitude(storageKey) {
    try {
      const rawValue = window.sessionStorage.getItem(storageKey);
      return normalizedSignedPreferenceMagnitude(
        rawValue == null ? DEFAULT_SIGNED_PREFERENCE_MAGNITUDE : Number.parseFloat(rawValue),
      );
    } catch (error) {
      return DEFAULT_SIGNED_PREFERENCE_MAGNITUDE;
    }
  }

  function persistSignedPreferenceMagnitude(storageKey, magnitude) {
    try {
      window.sessionStorage.setItem(
        storageKey,
        String(normalizedSignedPreferenceMagnitude(magnitude)),
      );
    } catch (error) {
    }
  }

  function clipSignedPreferenceValue(value, magnitude) {
    const safeValue = numericValue(value, 0);
    const safeMagnitude = normalizedSignedPreferenceMagnitude(magnitude);
    return clamp(safeValue, -safeMagnitude, safeMagnitude);
  }

  function signedPreferenceOffsetForValue(value, trackHeight) {
    if (!(trackHeight > 0)) {
      return 0;
    }
    const safeValue = clamp(
      numericValue(value, 0),
      -SIGNED_PREFERENCE_LEGEND_EXTENT,
      SIGNED_PREFERENCE_LEGEND_EXTENT,
    );
    const normalizedOffset = 0.5 - (safeValue / (SIGNED_PREFERENCE_LEGEND_EXTENT * 2));
    return clamp(normalizedOffset * trackHeight, 0, trackHeight);
  }

  function signedPreferenceMagnitudeFromPointerOffset(offsetY, trackHeight) {
    if (!(trackHeight > 0)) {
      return DEFAULT_SIGNED_PREFERENCE_MAGNITUDE;
    }
    const normalizedOffset = clamp(offsetY / trackHeight, 0, 1);
    const signedValue = (0.5 - normalizedOffset) * 2 * SIGNED_PREFERENCE_LEGEND_EXTENT;
    return normalizedSignedPreferenceMagnitude(Math.abs(signedValue));
  }

  function createSignedPreferenceLegend(container, {
    onMagnitudeChange,
    onResetMagnitude,
  }) {
    container.style.position = "relative";
    const root = document.createElement("div");
    root.className = "codon-preference-scale";
    root.hidden = true;
    root.innerHTML = `
      <div class="codon-preference-scale__panel">
        <div class="codon-preference-scale__header">
          <div>
            <div class="codon-preference-scale__title">Current scale</div>
            <div class="codon-preference-scale__value" data-role="value"></div>
          </div>
          <button type="button" class="codon-preference-scale__reset" data-role="reset">Reset</button>
        </div>
        <div class="codon-preference-scale__copy" data-role="copy"></div>
        <div class="codon-preference-scale__body">
          <div class="codon-preference-scale__label codon-preference-scale__label--positive" data-role="positive-label"></div>
          <div class="codon-preference-scale__track-shell">
            <div class="codon-preference-scale__tick-column">
              <span class="codon-preference-scale__tick codon-preference-scale__tick--top" data-role="tick-top"></span>
              <span class="codon-preference-scale__tick codon-preference-scale__tick--middle">0</span>
              <span class="codon-preference-scale__tick codon-preference-scale__tick--bottom" data-role="tick-bottom"></span>
            </div>
            <button
              type="button"
              class="codon-preference-scale__track"
              data-role="track"
              aria-label="Click to set the symmetric heatmap color scale"
            >
              <span class="codon-preference-scale__clip codon-preference-scale__clip--top" data-role="top-clip"></span>
              <span class="codon-preference-scale__clip codon-preference-scale__clip--bottom" data-role="bottom-clip"></span>
              <span class="codon-preference-scale__active-band" data-role="active-band"></span>
              <span class="codon-preference-scale__marker codon-preference-scale__marker--positive" data-role="positive-marker"></span>
              <span class="codon-preference-scale__marker codon-preference-scale__marker--negative" data-role="negative-marker"></span>
              <span class="codon-preference-scale__zero" data-role="zero-marker"></span>
            </button>
          </div>
          <div class="codon-preference-scale__label codon-preference-scale__label--negative" data-role="negative-label"></div>
        </div>
        <div class="codon-preference-scale__hint">Click to choose the symmetric clipping range. Double-click or reset to restore the default.</div>
      </div>
    `;
    container.append(root);

    const valueNode = root.querySelector('[data-role="value"]');
    const copyNode = root.querySelector('[data-role="copy"]');
    const positiveLabelNode = root.querySelector('[data-role="positive-label"]');
    const negativeLabelNode = root.querySelector('[data-role="negative-label"]');
    const tickTopNode = root.querySelector('[data-role="tick-top"]');
    const tickBottomNode = root.querySelector('[data-role="tick-bottom"]');
    const resetButton = root.querySelector('[data-role="reset"]');
    const track = root.querySelector('[data-role="track"]');
    const topClip = root.querySelector('[data-role="top-clip"]');
    const bottomClip = root.querySelector('[data-role="bottom-clip"]');
    const activeBand = root.querySelector('[data-role="active-band"]');
    const positiveMarker = root.querySelector('[data-role="positive-marker"]');
    const negativeMarker = root.querySelector('[data-role="negative-marker"]');

    function trackMagnitudeForEvent(event) {
      const trackBounds = track.getBoundingClientRect();
      return signedPreferenceMagnitudeFromPointerOffset(
        event.clientY - trackBounds.top,
        trackBounds.height,
      );
    }

    function updateTrackMarkers(magnitude) {
      const trackHeight = track.clientHeight;
      const positiveMarkerOffset = signedPreferenceOffsetForValue(magnitude, trackHeight);
      const negativeMarkerOffset = signedPreferenceOffsetForValue(-magnitude, trackHeight);
      const activeBandHeight = Math.max(0, negativeMarkerOffset - positiveMarkerOffset);
      activeBand.style.top = `${positiveMarkerOffset}px`;
      activeBand.style.height = `${activeBandHeight}px`;
      positiveMarker.style.top = `${positiveMarkerOffset}px`;
      negativeMarker.style.top = `${negativeMarkerOffset}px`;
      topClip.style.height = `${Math.max(0, positiveMarkerOffset)}px`;
      bottomClip.style.top = `${negativeMarkerOffset}px`;
      bottomClip.style.height = `${Math.max(0, trackHeight - negativeMarkerOffset)}px`;
    }

    track.addEventListener("click", (event) => {
      onMagnitudeChange(trackMagnitudeForEvent(event));
    });
    track.addEventListener("dblclick", (event) => {
      event.preventDefault();
      onResetMagnitude();
    });
    resetButton.addEventListener("click", () => {
      onResetMagnitude();
    });

    return {
      render({
        magnitude,
        codonOne,
        codonTwo,
        rightOffset,
        top,
        bottom,
      }) {
        const formattedMagnitude = formatShare(magnitude);
        root.hidden = false;
        root.style.right = `${rightOffset}px`;
        root.style.top = `${Math.max(16, top - 4)}px`;
        root.style.bottom = `${Math.max(16, bottom - 4)}px`;
        valueNode.textContent = `±${formattedMagnitude}`;
        copyNode.textContent = `Current scale: ±${formattedMagnitude}`;
        positiveLabelNode.textContent = `${codonTwo}-preferring`;
        negativeLabelNode.textContent = `${codonOne}-preferring`;
        tickTopNode.textContent = `+${formatShare(SIGNED_PREFERENCE_LEGEND_EXTENT)}`;
        tickBottomNode.textContent = `-${formatShare(SIGNED_PREFERENCE_LEGEND_EXTENT)}`;
        updateTrackMarkers(magnitude);
        window.requestAnimationFrame(() => {
          updateTrackMarkers(magnitude);
        });
      },
      hide() {
        root.hidden = true;
      },
    };
  }

  function distanceScaleOffsetForValue(value, trackHeight) {
    return clamp((1 - clamp(value, 0, 1)) * trackHeight, 0, trackHeight);
  }

  function distanceScaleValueFromOffset(offsetY, trackHeight) {
    if (!(trackHeight > 0)) return 0.5;
    return clamp(1 - offsetY / trackHeight, 0, 1);
  }

  function normalizedDistanceScaleRange(minValue, maxValue) {
    const safeMin = clamp(numericValue(minValue, 0), 0, 1);
    const safeMax = clamp(numericValue(maxValue, 1), 0, 1);
    if (safeMax <= safeMin + DISTANCE_SCALE_STEP) {
      return { min: Math.max(0, safeMin), max: Math.min(1, safeMin + DISTANCE_SCALE_STEP * 2) };
    }
    return { min: safeMin, max: safeMax };
  }

  function loadDistanceScaleRange(storageKey) {
    try {
      const raw = storageKey ? window.sessionStorage.getItem(storageKey) : null;
      if (!raw) return { min: DISTANCE_SCALE_DEFAULT_MIN, max: DISTANCE_SCALE_DEFAULT_MAX };
      const parsed = JSON.parse(raw);
      return normalizedDistanceScaleRange(parsed.min, parsed.max);
    } catch {
      return { min: DISTANCE_SCALE_DEFAULT_MIN, max: DISTANCE_SCALE_DEFAULT_MAX };
    }
  }

  function persistDistanceScaleRange(storageKey, min, max) {
    try {
      if (storageKey) window.sessionStorage.setItem(storageKey, JSON.stringify({ min, max }));
    } catch {}
  }

  function createDistanceScaleLegend(container, { onRangeChange, onReset }) {
    container.querySelector(".pairwise-distance-scale")?.remove();
    container.style.position = "relative";

    const root = document.createElement("div");
    root.className = "pairwise-distance-scale";
    root.hidden = true;
    root.innerHTML = `
      <div class="pairwise-distance-scale__panel">
        <div class="pairwise-distance-scale__header">
          <div>
            <div class="pairwise-distance-scale__title">Color range</div>
            <div class="pairwise-distance-scale__value" data-role="value"></div>
          </div>
          <button type="button" class="pairwise-distance-scale__reset" data-role="reset">Reset</button>
        </div>
        <div class="pairwise-distance-scale__body">
          <div class="pairwise-distance-scale__label pairwise-distance-scale__label--max">Different</div>
          <div class="pairwise-distance-scale__track-shell">
            <div class="pairwise-distance-scale__tick-column">
              <span class="pairwise-distance-scale__tick pairwise-distance-scale__tick--top" data-role="tick-top"></span>
              <span class="pairwise-distance-scale__tick pairwise-distance-scale__tick--middle">0.5</span>
              <span class="pairwise-distance-scale__tick pairwise-distance-scale__tick--bottom" data-role="tick-bottom"></span>
            </div>
            <button type="button" class="pairwise-distance-scale__track" data-role="track"
                    aria-label="Click to set color range. Double-click to reset.">
              <span class="pairwise-distance-scale__clip pairwise-distance-scale__clip--top" data-role="top-clip"></span>
              <span class="pairwise-distance-scale__clip pairwise-distance-scale__clip--bottom" data-role="bottom-clip"></span>
              <span class="pairwise-distance-scale__active-band" data-role="active-band"></span>
              <span class="pairwise-distance-scale__marker" data-role="max-marker"></span>
              <span class="pairwise-distance-scale__marker" data-role="min-marker"></span>
            </button>
          </div>
          <div class="pairwise-distance-scale__label pairwise-distance-scale__label--min">Identical</div>
        </div>
        <div class="pairwise-distance-scale__hint">Click to adjust range. Double-click to reset.</div>
      </div>
    `;
    container.append(root);

    const valueNode = root.querySelector('[data-role="value"]');
    const tickTopNode = root.querySelector('[data-role="tick-top"]');
    const tickBottomNode = root.querySelector('[data-role="tick-bottom"]');
    const resetButton = root.querySelector('[data-role="reset"]');
    const track = root.querySelector('[data-role="track"]');
    const topClip = root.querySelector('[data-role="top-clip"]');
    const bottomClip = root.querySelector('[data-role="bottom-clip"]');
    const activeBand = root.querySelector('[data-role="active-band"]');
    const maxMarker = root.querySelector('[data-role="max-marker"]');
    const minMarker = root.querySelector('[data-role="min-marker"]');
    let lastRange = { min: DISTANCE_SCALE_DEFAULT_MIN, max: DISTANCE_SCALE_DEFAULT_MAX };

    function updateTrackMarkers(min, max) {
      const trackHeight = track.clientHeight;
      const maxOffset = distanceScaleOffsetForValue(max, trackHeight);
      const minOffset = distanceScaleOffsetForValue(min, trackHeight);
      const bandHeight = Math.max(0, minOffset - maxOffset);
      activeBand.style.top = `${maxOffset}px`;
      activeBand.style.height = `${bandHeight}px`;
      maxMarker.style.top = `${maxOffset}px`;
      minMarker.style.top = `${minOffset}px`;
      topClip.style.height = `${Math.max(0, maxOffset)}px`;
      bottomClip.style.top = `${minOffset}px`;
      bottomClip.style.height = `${Math.max(0, trackHeight - minOffset)}px`;
    }

    track.addEventListener("click", (event) => {
      const bounds = track.getBoundingClientRect();
      const clicked = distanceScaleValueFromOffset(event.clientY - bounds.top, bounds.height);
      const { min: curMin, max: curMax } = lastRange;
      if (Math.abs(clicked - curMax) <= Math.abs(clicked - curMin)) {
        const newMax = Number(clamp(
          Math.round(clicked / DISTANCE_SCALE_STEP) * DISTANCE_SCALE_STEP,
          curMin + DISTANCE_SCALE_STEP,
          1,
        ).toFixed(2));
        onRangeChange(curMin, newMax);
      } else {
        const newMin = Number(clamp(
          Math.round(clicked / DISTANCE_SCALE_STEP) * DISTANCE_SCALE_STEP,
          0,
          curMax - DISTANCE_SCALE_STEP,
        ).toFixed(2));
        onRangeChange(newMin, curMax);
      }
    });
    track.addEventListener("dblclick", (event) => { event.preventDefault(); onReset(); });
    resetButton.addEventListener("click", () => onReset());

    return {
      render({ min, max, rightOffset, top, bottom }) {
        lastRange = { min, max };
        root.hidden = false;
        root.style.right = `${rightOffset}px`;
        root.style.top = `${Math.max(16, top - 4)}px`;
        root.style.bottom = `${Math.max(16, bottom - 4)}px`;
        valueNode.textContent = `${min.toFixed(2)} – ${max.toFixed(2)}`;
        tickTopNode.textContent = max.toFixed(2);
        tickBottomNode.textContent = min.toFixed(2);
        updateTrackMarkers(min, max);
        window.requestAnimationFrame(() => updateTrackMarkers(min, max));
      },
      hide() { root.hidden = true; },
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

  function matrixValueAt(matrix, rowIndex, columnIndex, fallbackValue = 0) {
    if (!Array.isArray(matrix)) {
      return fallbackValue;
    }
    const row = matrix[rowIndex];
    if (!Array.isArray(row)) {
      return fallbackValue;
    }
    return numericValue(row[columnIndex], fallbackValue);
  }

  function overviewHeatmapStyles(visibleRowCount) {
    if (visibleRowCount <= MAX_OVERVIEW_BORDERS) {
      return {
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
      };
    }
    return {
      itemStyle: {
        borderWidth: 0,
      },
      emphasis: {
        itemStyle: {
          borderWidth: 0,
        },
      },
    };
  }

  function defaultSignedTooltipFormatter(params, payload) {
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
  }

  function defaultSimilarityTooltipFormatter(params) {
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
  }

  function renderPairwiseOverview({
    container,
    payload,
    taxonomyGutterPayload,
    emptyStateMessages = {},
    emptyStateDetail = "Adjust the filters to populate the overview.",
    signedPreferenceStorageKey = "",
    distanceScaleStorageKey = "",
    similarityTooltipFormatter = defaultSimilarityTooltipFormatter,
    signedTooltipFormatter = defaultSignedTooltipFormatter,
  }) {
    if (!payload || !container || typeof window.echarts === "undefined") {
      return null;
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
    installWheelHandler(chart, rowCount, () => currentZoomState);
    const taxonAxisValues = (payload.taxa || []).map((row) => String(row.taxonId));
    const visualRange = resolvedMatrixVisualRange(payload.valueMin, payload.valueMax);
    const taxonLabelByAxisValue = new Map(
      (payload.taxa || []).map((row) => [String(row.taxonId), row.taxonName]),
    );
    let currentSignedPreferenceMagnitude = loadSignedPreferenceMagnitude(signedPreferenceStorageKey);
    const signedPreferenceLegend = createSignedPreferenceLegend(container, {
      onMagnitudeChange(nextMagnitude) {
        const resolvedMagnitude = normalizedSignedPreferenceMagnitude(nextMagnitude);
        if (resolvedMagnitude === currentSignedPreferenceMagnitude) {
          return;
        }
        currentSignedPreferenceMagnitude = resolvedMagnitude;
        persistSignedPreferenceMagnitude(signedPreferenceStorageKey, resolvedMagnitude);
        renderChart();
      },
      onResetMagnitude() {
        currentSignedPreferenceMagnitude = DEFAULT_SIGNED_PREFERENCE_MAGNITUDE;
        persistSignedPreferenceMagnitude(signedPreferenceStorageKey, currentSignedPreferenceMagnitude);
        renderChart();
      },
    });
    let currentDistanceRange = loadDistanceScaleRange(distanceScaleStorageKey);
    const distanceScaleLegend = createDistanceScaleLegend(container, {
      onRangeChange(newMin, newMax) {
        const range = normalizedDistanceScaleRange(newMin, newMax);
        if (range.min === currentDistanceRange.min && range.max === currentDistanceRange.max) return;
        currentDistanceRange = range;
        persistDistanceScaleRange(distanceScaleStorageKey, range.min, range.max);
        renderChart();
      },
      onReset() {
        currentDistanceRange = { min: DISTANCE_SCALE_DEFAULT_MIN, max: DISTANCE_SCALE_DEFAULT_MAX };
        persistDistanceScaleRange(distanceScaleStorageKey, currentDistanceRange.min, currentDistanceRange.max);
        renderChart();
      },
    });

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
          startValue: 0,
          endValue: Math.max(0, rowCount - 1),
          min: 0,
          max: Math.max(0, rowCount - 1),
        };
      }
      return {
        startValue: currentZoomState.startValue,
        endValue: currentZoomState.endValue,
        min: currentZoomState.startValue,
        max: currentZoomState.endValue,
      };
    }

    function currentOverviewMargins(gutterWidth) {
      const rightMargin = currentZoomState ? 176 : 132;
      return {
        left: hasTaxonomyGutter ? gutterWidth + 20 : 160,
        right: rightMargin,
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
      !Array.isArray(payload.taxa)
      || payload.taxa.length === 0
      || !Array.isArray(payload.divergenceMatrix)
      || payload.divergenceMatrix.length === 0
    ) {
      signedPreferenceLegend.hide();
      chart.setOption(
        buildEmptyOption(
          payload.mode === "signed_preference_map"
            ? (emptyStateMessages.signed || "No visible preference cells")
            : (emptyStateMessages.similarity || "No visible taxon similarity cells"),
          emptyStateDetail,
        ),
      );
      return chart;
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

    const visibleSimilarityWindowCache = new Map();
    const visibleSignedWindowBaseCache = new Map();
    const visibleSignedWindowCache = new Map();

    function overviewWindowKey(bounds) {
      return `${bounds.startValue}:${bounds.endValue}`;
    }

    function buildVisibleSimilarityData(bounds) {
      const cacheKey = `${overviewWindowKey(bounds)}:${payload.displayMetric}`;
      const cachedData = visibleSimilarityWindowCache.get(cacheKey);
      if (cachedData) {
        return cachedData;
      }

      const visibleData = [];
      for (let rowIndex = bounds.startValue; rowIndex <= bounds.endValue; rowIndex += 1) {
        const row = payload.taxa[rowIndex];
        if (!row) {
          continue;
        }
        for (let columnIndex = bounds.startValue; columnIndex <= bounds.endValue; columnIndex += 1) {
          const column = payload.taxa[columnIndex];
          if (!column) {
            continue;
          }
          const divergence = matrixValueAt(payload.divergenceMatrix, rowIndex, columnIndex, 0);
          const similarity = Math.max(0, 1 - divergence);
          visibleData.push({
            value: [
              String(column.taxonId),
              String(row.taxonId),
              payload.displayMetric === "divergence" ? divergence : similarity,
            ],
            rowTaxonId: String(row.taxonId),
            rowTaxonName: row.taxonName,
            rowRank: row.rank,
            rowObservationCount: row.observationCount,
            rowSpeciesCount: row.speciesCount,
            columnTaxonId: String(column.taxonId),
            columnTaxonName: column.taxonName,
            columnRank: column.rank,
            columnObservationCount: column.observationCount,
            columnSpeciesCount: column.speciesCount,
            similarity,
            divergence,
            reliability: Math.min(row.speciesCount, column.speciesCount),
          });
        }
      }

      visibleSimilarityWindowCache.set(cacheKey, visibleData);
      return visibleData;
    }

    function buildVisibleSignedWindowBase(bounds) {
      const cacheKey = overviewWindowKey(bounds);
      const cachedData = visibleSignedWindowBaseCache.get(cacheKey);
      if (cachedData) {
        return cachedData;
      }

      const visibleData = [];
      for (let rowIndex = bounds.startValue; rowIndex <= bounds.endValue; rowIndex += 1) {
        const row = payload.taxa[rowIndex];
        if (!row) {
          continue;
        }
        for (let columnIndex = bounds.startValue; columnIndex <= bounds.endValue; columnIndex += 1) {
          const column = payload.taxa[columnIndex];
          if (!column) {
            continue;
          }
          visibleData.push({
            rowTaxonId: String(row.taxonId),
            rowTaxonName: row.taxonName,
            rowObservationCount: row.observationCount,
            rowSpeciesCount: row.speciesCount,
            rowCodonOneShare: row.codonOneShare,
            rowCodonTwoShare: row.codonTwoShare,
            rowScore: row.score,
            columnTaxonId: String(column.taxonId),
            columnTaxonName: column.taxonName,
            columnObservationCount: column.observationCount,
            columnSpeciesCount: column.speciesCount,
            columnCodonOneShare: column.codonOneShare,
            columnCodonTwoShare: column.codonTwoShare,
            columnScore: column.score,
            signedDifference: row.score - column.score,
            divergence: matrixValueAt(payload.divergenceMatrix, rowIndex, columnIndex, 0),
            reliability: Math.min(row.speciesCount, column.speciesCount),
          });
        }
      }

      visibleSignedWindowBaseCache.set(cacheKey, visibleData);
      return visibleData;
    }

    function buildVisibleSignedData(bounds, magnitude) {
      const resolvedMagnitude = normalizedSignedPreferenceMagnitude(magnitude);
      const cacheKey = `${overviewWindowKey(bounds)}:${resolvedMagnitude}`;
      const cachedData = visibleSignedWindowCache.get(cacheKey);
      if (cachedData) {
        return cachedData;
      }

      const clippedVisibleData = buildVisibleSignedWindowBase(bounds).map((cell) => ({
        ...cell,
        value: [
          cell.columnTaxonId,
          cell.rowTaxonId,
          clipSignedPreferenceValue(cell.signedDifference, resolvedMagnitude),
        ],
      }));
      visibleSignedWindowCache.set(cacheKey, clippedVisibleData);
      return clippedVisibleData;
    }

    function renderChart() {
      const visibleRowCount = visibleRowCountForZoom(rowCount, currentZoomState);
      const showTaxonLabels = shouldShowTaxonLabels(visibleRowCount);
      const showMatrixCellLabels = shouldShowMatrixCellLabels(visibleRowCount);
      const layout = currentOverviewLayout(visibleRowCount);
      const columnBounds = currentVisibleColumnBounds();
      const gutterWidth = overviewGutterWidth(visibleRowCount);
      const margins = currentOverviewMargins(gutterWidth);
      const heatmapStyles = overviewHeatmapStyles(visibleRowCount);
      applySquareOverviewHeight(layout, margins);

      if (payload.mode === "signed_preference_map") {
        const signedPreferenceRange = currentSignedPreferenceRange(currentSignedPreferenceMagnitude);
        const preferenceData = buildVisibleSignedData(columnBounds, signedPreferenceRange.magnitude);
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
            formatter: (params) => signedTooltipFormatter(params, payload),
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
            show: false,
            min: signedPreferenceRange.min,
            max: signedPreferenceRange.max,
            calculable: false,
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
              itemStyle: heatmapStyles.itemStyle,
              emphasis: heatmapStyles.emphasis,
            },
          ],
        }, { notMerge: true });
        distanceScaleLegend.hide();
        signedPreferenceLegend.render({
          magnitude: signedPreferenceRange.magnitude,
          codonOne: payload.codonOne,
          codonTwo: payload.codonTwo,
          rightOffset: currentZoomState ? 28 : 14,
          top: layout.top,
          bottom: layout.bottom,
        });
        refreshOverviewGutter();
        return;
      }

      signedPreferenceLegend.hide();
      distanceScaleLegend.render({
        min: currentDistanceRange.min,
        max: currentDistanceRange.max,
        rightOffset: currentZoomState ? 28 : 14,
        top: layout.top,
        bottom: layout.bottom,
      });
      const heatmapData = buildVisibleSimilarityData(columnBounds);
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
          formatter: (params) => similarityTooltipFormatter(params, payload),
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
          show: false,
          min: currentDistanceRange.min,
          max: currentDistanceRange.max,
          calculable: false,
          inRange: {
            color: payload.displayMetric === "divergence"
              ? ["#0f5964", "#f2efe6", "#d06e37"]
              : ["#d06e37", "#f2efe6", "#0f5964"],
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
            itemStyle: heatmapStyles.itemStyle,
            emphasis: heatmapStyles.emphasis,
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

    return chart;
  }

  window.HomorepeatPairwiseOverview = {
    renderPairwiseOverview,
  };
})();
