(() => {
  const LINE_COLOR = "rgba(23, 36, 44, 0.34)";
  const INTERNAL_TEXT_COLOR = "#63727a";
  const LEAF_TEXT_COLOR = "#17242c";
  const LEFT_PADDING = 12;
  const RIGHT_PADDING = 10;
  const TREE_TO_GRID_GAP = 20;
  const DEPTH_STEP = 28;
  const LEAF_LABEL_GAP = 12;
  const MIN_LEAF_SECTION_WIDTH = 12;
  const BRACE_GAP = 10;
  const BRACE_MARK_WIDTH = 10;
  const BRACE_LABEL_GAP = 4;
  const LINE_WIDTH = 1.3;
  const LEAF_FONT = "700 12px system-ui, sans-serif";
  const INTERNAL_FONT = "600 11px system-ui, sans-serif";
  const BRACE_FONT = "600 11px system-ui, sans-serif";
  const BRACE_MARK_FONT = "700 16px system-ui, sans-serif";
  const NODE_STROKE_COLOR = "rgba(23, 36, 44, 0.52)";
  const NODE_UNARY_FILL = "rgba(255, 253, 249, 0.94)";
  const NODE_SPLIT_FILL = "#ffffff";
  const NODE_ROOT_FILL = "#17242c";
  const ROOT_NODE_RADIUS = 4.8;
  const SPLIT_NODE_RADIUS = 3.8;
  const UNARY_NODE_RADIUS = 3.1;
  const MAX_INTERNAL_LABEL_WIDTH = 140;
  const MAX_LEAF_LABEL_WIDTH = 180;
  const MAX_BRACE_LABEL_WIDTH = 96;
  const MAX_VISIBLE_ROWS_WITH_INTERNAL_LABELS = 14;
  const GRAPHIC_ROOT_ID = "taxonomy-gutter-root";
  const TOOLTIP_DATA_KEY = "homorepeatTaxonomyGutterTooltip";

  let measureCanvas = null;

  function clamp(number, minimum, maximum) {
    return Math.min(Math.max(number, minimum), maximum);
  }

  function numericValue(value, fallbackValue) {
    if (Array.isArray(value)) {
      return numericValue(value[0], fallbackValue);
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string") {
      const parsedValue = Number.parseFloat(value);
      if (Number.isFinite(parsedValue)) {
        return parsedValue;
      }
    }
    return fallbackValue;
  }

  function requestFrame(callback) {
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      return window.requestAnimationFrame(callback);
    }
    return setTimeout(callback, 0);
  }

  function cancelFrame(handle) {
    if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(handle);
      return;
    }
    clearTimeout(handle);
  }

  function hasPayload(payload) {
    return Boolean(
      payload
      && payload.root
      && Array.isArray(payload.nodes)
      && payload.nodes.length > 0
      && Array.isArray(payload.leaves)
      && payload.leaves.length > 0,
    );
  }

  function measureTextWidth(text, font, maximumWidth) {
    if (!text) {
      return 0;
    }

    if (typeof document !== "undefined") {
      if (!measureCanvas) {
        measureCanvas = document.createElement("canvas");
      }
      const context = measureCanvas.getContext("2d");
      if (context) {
        context.font = font;
        return Math.min(maximumWidth, Math.ceil(context.measureText(text).width));
      }
    }

    return Math.min(maximumWidth, Math.ceil(String(text).length * 7));
  }

  function internalSplitNodes(payload) {
    return payload.nodes.filter((node) => node && node.isPreservedSplit && !node.isLeaf && node.rank !== "no rank");
  }

  function showInternalLabels(options, visibleLeafCount) {
    return Boolean(options && options.showInternalLabels) && visibleLeafCount <= MAX_VISIBLE_ROWS_WITH_INTERNAL_LABELS;
  }

  function layoutWidths(payload, options) {
    const showLabels = !options || options.showLabels !== false;
    const visibleLeafCount = numericValue(options ? options.visibleLeafCount : undefined, payload.leaves.length);
    const showSplitLabels = showInternalLabels(options, visibleLeafCount);

    let internalLabelWidth = 0;
    if (showSplitLabels) {
      internalSplitNodes(payload).forEach((node) => {
        internalLabelWidth = Math.max(
          internalLabelWidth,
          measureTextWidth(node.taxonName, INTERNAL_FONT, MAX_INTERNAL_LABEL_WIDTH),
        );
      });
    }

    let leafLabelWidth = 0;
    if (showLabels) {
      payload.leaves.forEach((leaf) => {
        leafLabelWidth = Math.max(
          leafLabelWidth,
          measureTextWidth(leaf.taxonName, LEAF_FONT, MAX_LEAF_LABEL_WIDTH),
        );
      });
    }

    let braceLabelWidth = 0;
    payload.leaves.forEach((leaf) => {
      if (!leaf.showBrace || !leaf.braceLabel) {
        return;
      }
      braceLabelWidth = Math.max(
        braceLabelWidth,
        measureTextWidth(leaf.braceLabel, BRACE_FONT, MAX_BRACE_LABEL_WIDTH),
      );
    });

    const treeWidth = Math.max(0, numericValue(payload.maxDepth, 0)) * DEPTH_STEP;
    const labelSectionWidth = showLabels ? LEAF_LABEL_GAP + leafLabelWidth : MIN_LEAF_SECTION_WIDTH;
    const braceSectionWidth = braceLabelWidth > 0
      ? BRACE_GAP + BRACE_MARK_WIDTH + BRACE_LABEL_GAP + braceLabelWidth
      : 0;

    return {
      showLabels,
      showSplitLabels,
      visibleLeafCount,
      internalLabelWidth,
      leafLabelWidth,
      braceLabelWidth,
      treeWidth,
      labelSectionWidth,
      braceSectionWidth,
      total: LEFT_PADDING + internalLabelWidth + treeWidth + labelSectionWidth + braceSectionWidth + RIGHT_PADDING,
    };
  }

  function reservedWidth(payload, options = {}) {
    if (!hasPayload(payload)) {
      return 0;
    }
    return layoutWidths(payload, options).total;
  }

  function gridLeft(chart) {
    const option = chart.getOption();
    const grid = Array.isArray(option.grid) ? option.grid[0] : option.grid;
    return numericValue(grid ? grid.left : undefined, 0);
  }

  function gridRect(chart) {
    try {
      const model = chart.getModel ? chart.getModel() : null;
      const gridComponent = model && model.getComponent ? model.getComponent("grid", 0) : null;
      const coordinateSystem = gridComponent ? gridComponent.coordinateSystem : null;
      const rect = coordinateSystem && coordinateSystem.getRect ? coordinateSystem.getRect() : null;
      if (!rect) {
        return null;
      }
      return {
        x: numericValue(rect.x, 0),
        y: numericValue(rect.y, 0),
        width: numericValue(rect.width, 0),
        height: numericValue(rect.height, 0),
      };
    } catch (error) {
      return null;
    }
  }

  function ensureTooltip(chart) {
    if (typeof document === "undefined") {
      return null;
    }

    const chartDom = chart.getDom();
    if (!chartDom) {
      return null;
    }

    if (!chartDom.style.position) {
      chartDom.style.position = "relative";
    }

    let tooltip = chartDom.querySelector(`[data-${TOOLTIP_DATA_KEY}]`);
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.setAttribute(`data-${TOOLTIP_DATA_KEY}`, "true");
      Object.assign(tooltip.style, {
        position: "absolute",
        display: "none",
        pointerEvents: "none",
        zIndex: "20",
        maxWidth: "220px",
        padding: "6px 8px",
        borderRadius: "8px",
        border: "1px solid rgba(23, 36, 44, 0.12)",
        background: "rgba(255, 253, 249, 0.98)",
        color: LEAF_TEXT_COLOR,
        font: "600 12px system-ui, sans-serif",
        lineHeight: "1.3",
        whiteSpace: "nowrap",
        boxShadow: "0 6px 18px rgba(23, 36, 44, 0.12)",
      });
      chartDom.appendChild(tooltip);
    }
    return tooltip;
  }

  function hideTooltip(tooltip) {
    if (!tooltip) {
      return;
    }
    tooltip.style.display = "none";
  }

  function showTooltip(chart, tooltip, text, x, y) {
    if (!tooltip || !text) {
      hideTooltip(tooltip);
      return;
    }

    tooltip.textContent = text;
    tooltip.style.display = "block";

    const chartDom = chart.getDom();
    const tooltipWidth = tooltip.offsetWidth || 0;
    const tooltipHeight = tooltip.offsetHeight || 0;
    const maxLeft = Math.max(8, chartDom.clientWidth - tooltipWidth - 8);
    const maxTop = Math.max(8, chartDom.clientHeight - tooltipHeight - 8);
    const left = clamp(Math.round(x + 12), 8, maxLeft);
    const top = clamp(Math.round(y - tooltipHeight - 10), 8, maxTop);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function visibleLeafRange(chart, payload, options = {}) {
    const leafCount = payload.leaves.length;
    if (leafCount < 1) {
      return null;
    }

    const explicitZoomState = options.zoomState || null;
    if (explicitZoomState) {
      const start = clamp(
        Math.round(numericValue(explicitZoomState.startValue, 0)),
        0,
        leafCount - 1,
      );
      const end = clamp(
        Math.round(numericValue(explicitZoomState.endValue, leafCount - 1)),
        start,
        leafCount - 1,
      );
      return { start, end };
    }

    const option = chart.getOption();
    const dataZoom = option ? option.dataZoom : null;
    if (!Array.isArray(dataZoom) || dataZoom.length === 0) {
      return {
        start: 0,
        end: leafCount - 1,
      };
    }

    const start = clamp(
      Math.round(numericValue(dataZoom[0].startValue, 0)),
      0,
      leafCount - 1,
    );
    const end = clamp(
      Math.round(numericValue(dataZoom[0].endValue, leafCount - 1)),
      start,
      leafCount - 1,
    );
    return { start, end };
  }

  function navigateTo(url) {
    if (typeof url !== "string" || !url) {
      return;
    }
    window.location.href = url;
  }

  function buildVisibleState(chart, payload, options) {
    const range = visibleLeafRange(chart, payload, options);
    if (!range) {
      return null;
    }

    const currentGridRect = gridRect(chart);
    const visibleLeafCount = (range.end - range.start) + 1;
    const rowBandHeight = currentGridRect && visibleLeafCount > 0
      ? currentGridRect.height / visibleLeafCount
      : null;
    const visibleLeaves = [];
    const rowYByIndex = new Map();
    const leafByNodeId = new Map();
    payload.leaves.forEach((leaf) => {
      if (leaf.rowIndex < range.start || leaf.rowIndex > range.end) {
        return;
      }
      const y = currentGridRect && rowBandHeight
        ? currentGridRect.y + (((leaf.rowIndex - range.start) + 0.5) * rowBandHeight)
        : chart.convertToPixel({ yAxisIndex: 0 }, leaf.axisValue);
      if (typeof y !== "number" || !Number.isFinite(y)) {
        return;
      }
      visibleLeaves.push({ ...leaf, y });
      rowYByIndex.set(leaf.rowIndex, y);
      leafByNodeId.set(leaf.nodeId, { ...leaf, y });
    });

    if (visibleLeaves.length === 0) {
      return null;
    }

    const widths = layoutWidths(payload, {
      showLabels: !options || options.showLabels !== false,
      visibleLeafCount: visibleLeaves.length,
    });
    const rootX = LEFT_PADDING + widths.internalLabelWidth;
    const leafLabelX = rootX + widths.treeWidth + (widths.showLabels ? LEAF_LABEL_GAP : MIN_LEAF_SECTION_WIDTH);
    const leafLineEndX = widths.showLabels ? leafLabelX - 6 : leafLabelX - 2;
    const braceMarkX = leafLabelX + widths.leafLabelWidth + BRACE_GAP;
    const braceLabelX = braceMarkX + BRACE_MARK_WIDTH + BRACE_LABEL_GAP;
    const gutterRight = (currentGridRect ? currentGridRect.x : gridLeft(chart)) - TREE_TO_GRID_GAP;

    const visibleNodesById = new Map();
    payload.nodes.forEach((node) => {
      const clippedStart = Math.max(node.rowStart, range.start);
      const clippedEnd = Math.min(node.rowEnd, range.end);
      if (clippedStart > clippedEnd) {
        return;
      }
      const topY = rowYByIndex.get(clippedStart);
      const bottomY = rowYByIndex.get(clippedEnd);
      if (typeof topY !== "number" || typeof bottomY !== "number") {
        return;
      }
      const normalizedTopY = Math.min(topY, bottomY);
      const normalizedBottomY = Math.max(topY, bottomY);
      visibleNodesById.set(node.nodeId, {
        ...node,
        x: rootX + (node.depth * DEPTH_STEP),
        y: (normalizedTopY + normalizedBottomY) / 2,
        topY: normalizedTopY,
        bottomY: normalizedBottomY,
      });
    });

    const childrenByParentId = new Map();
    payload.edges.forEach((edge) => {
      if (!visibleNodesById.has(edge.parentNodeId) || !visibleNodesById.has(edge.childNodeId)) {
        return;
      }
      const children = childrenByParentId.get(edge.parentNodeId) || [];
      children.push(edge.childNodeId);
      childrenByParentId.set(edge.parentNodeId, children);
    });
    childrenByParentId.forEach((childNodeIds, parentNodeId) => {
      childNodeIds.sort((leftNodeId, rightNodeId) => {
        return visibleNodesById.get(leftNodeId).y - visibleNodesById.get(rightNodeId).y;
      });
      childrenByParentId.set(parentNodeId, childNodeIds);
    });

    return {
      widths,
      rootX,
      leafLabelX,
      leafLineEndX,
      braceMarkX,
      braceLabelX,
      gutterRight,
      visibleLeaves,
      visibleNodesById,
      childrenByParentId,
      leafByNodeId,
    };
  }

  function lineElement(shape) {
    return {
      type: "line",
      silent: true,
      shape,
      style: {
        stroke: LINE_COLOR,
        lineWidth: LINE_WIDTH,
      },
      z: 2,
    };
  }

  function nodeMarkerRadius(node) {
    if (node.parentNodeId === null) {
      return ROOT_NODE_RADIUS;
    }
    if (node.isPreservedSplit) {
      return SPLIT_NODE_RADIUS;
    }
    return UNARY_NODE_RADIUS;
  }

  function nodeMarkerStyle(node) {
    if (node.parentNodeId === null) {
      return {
        fill: NODE_ROOT_FILL,
        stroke: NODE_ROOT_FILL,
        lineWidth: 1.2,
      };
    }
    if (node.isPreservedSplit) {
      return {
        fill: NODE_SPLIT_FILL,
        stroke: NODE_STROKE_COLOR,
        lineWidth: 1.2,
      };
    }
    return {
      fill: NODE_UNARY_FILL,
      stroke: LINE_COLOR,
      lineWidth: 1,
    };
  }

  function nodeTooltipText(node) {
    if (!node) {
      return "";
    }
    if (!node.rank || node.rank === "no rank") {
      return node.taxonName;
    }
    return `${node.taxonName} (${node.rank})`;
  }

  function hoverHandlers(chart, tooltip, text, x, y) {
    return {
      onmouseover() {
        showTooltip(chart, tooltip, text, x, y);
      },
      onmousemove() {
        showTooltip(chart, tooltip, text, x, y);
      },
      onmouseout() {
        hideTooltip(tooltip);
      },
    };
  }

  function nodeMarkerElement(chart, tooltip, node) {
    return {
      type: "circle",
      cursor: "default",
      silent: false,
      shape: {
        cx: node.x,
        cy: node.y,
        r: nodeMarkerRadius(node),
      },
      style: nodeMarkerStyle(node),
      z: 5,
      ...hoverHandlers(chart, tooltip, nodeTooltipText(node), node.x, node.y),
    };
  }

  function leafHoverText(leaf) {
    if (!leaf) {
      return "";
    }
    if (leaf.showBrace && leaf.braceLabel) {
      return `${leaf.taxonName} (${leaf.braceLabel})`;
    }
    return leaf.taxonName;
  }

  function leafHitAreaElement(chart, tooltip, state, leaf, node) {
    const braceLabelWidth = leaf.showBrace && leaf.braceLabel
      ? measureTextWidth(leaf.braceLabel, BRACE_FONT, MAX_BRACE_LABEL_WIDTH)
      : 0;
    const hitAreaRight = leaf.showBrace && leaf.braceLabel
      ? state.braceLabelX + braceLabelWidth + 8
      : state.leafLineEndX + 8;

    return {
      type: "rect",
      cursor: leaf.branchExplorerUrl ? "pointer" : "default",
      silent: false,
      onclick: () => navigateTo(leaf.branchExplorerUrl),
      shape: {
        x: node.x - 2,
        y: leaf.y - 10,
        width: Math.max(12, hitAreaRight - node.x + 2),
        height: 20,
      },
      style: {
        fill: "rgba(0, 0, 0, 0)",
      },
      z: 1,
      ...hoverHandlers(chart, tooltip, leafHoverText(leaf), hitAreaRight, leaf.y),
    };
  }

  function buildGraphics(chart, payload, state, tooltip) {
    const graphics = [];
    const { widths, visibleNodesById, childrenByParentId, leafByNodeId } = state;

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (childNodeIds.length >= 2) {
        const firstChild = visibleNodesById.get(childNodeIds[0]);
        const lastChild = visibleNodesById.get(childNodeIds[childNodeIds.length - 1]);
        graphics.push(
          lineElement({
            x1: node.x,
            y1: firstChild.y,
            x2: node.x,
            y2: lastChild.y,
          }),
        );
      }

      childNodeIds.forEach((childNodeId) => {
        const childNode = visibleNodesById.get(childNodeId);
        graphics.push(
          lineElement({
            x1: node.x,
            y1: childNode.y,
            x2: childNode.x,
            y2: childNode.y,
          }),
        );
      });
    });

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (node.isLeaf || childNodeIds.length === 0) {
        return;
      }
      graphics.push(nodeMarkerElement(chart, tooltip, node));
    });

    state.visibleLeaves.forEach((leaf) => {
      const node = visibleNodesById.get(leaf.nodeId);
      if (!node) {
        return;
      }

      graphics.push(leafHitAreaElement(chart, tooltip, state, leaf, node));

      graphics.push(
        lineElement({
          x1: node.x,
          y1: leaf.y,
          x2: state.leafLineEndX,
          y2: leaf.y,
        }),
      );

      if (widths.showLabels) {
        graphics.push(
          {
            type: "text",
            x: state.leafLabelX,
            y: leaf.y,
            cursor: leaf.branchExplorerUrl ? "pointer" : "default",
            onclick: () => navigateTo(leaf.branchExplorerUrl),
            ...hoverHandlers(chart, tooltip, leafHoverText(leaf), state.leafLabelX, leaf.y),
            style: {
              text: leaf.taxonName,
              fill: LEAF_TEXT_COLOR,
              font: LEAF_FONT,
              textAlign: "left",
              verticalAlign: "middle",
            },
            z: 4,
          },
        );
      }

      if (leaf.showBrace && leaf.braceLabel) {
        graphics.push(
          {
            type: "text",
            x: state.braceMarkX,
            y: leaf.y,
            cursor: leaf.branchExplorerUrl ? "pointer" : "default",
            onclick: () => navigateTo(leaf.branchExplorerUrl),
            ...hoverHandlers(chart, tooltip, leafHoverText(leaf), state.braceMarkX, leaf.y),
            style: {
              text: "{",
              fill: INTERNAL_TEXT_COLOR,
              font: BRACE_MARK_FONT,
              textAlign: "left",
              verticalAlign: "middle",
            },
            z: 4,
          },
        );
        graphics.push(
          {
            type: "text",
            x: state.braceLabelX,
            y: leaf.y,
            cursor: leaf.branchExplorerUrl ? "pointer" : "default",
            onclick: () => navigateTo(leaf.branchExplorerUrl),
            ...hoverHandlers(chart, tooltip, leafHoverText(leaf), state.braceLabelX, leaf.y),
            style: {
              text: leaf.braceLabel,
              fill: INTERNAL_TEXT_COLOR,
              font: BRACE_FONT,
              textAlign: "left",
              verticalAlign: "middle",
            },
            z: 4,
          },
        );
      }
    });

    if (widths.showSplitLabels) {
      visibleNodesById.forEach((node) => {
        if (!node.isPreservedSplit || node.isLeaf || node.rank === "no rank") {
          return;
        }
        if ((node.bottomY - node.topY) < 24) {
          return;
        }
        if (leafByNodeId.has(node.nodeId)) {
          return;
        }
        graphics.push(
          {
            type: "text",
            x: node.x - 8,
            y: node.y,
            silent: true,
            style: {
              text: node.taxonName,
              fill: INTERNAL_TEXT_COLOR,
              font: INTERNAL_FONT,
              textAlign: "right",
              verticalAlign: "middle",
            },
            z: 3,
          },
        );
      });
    }

    return [
      {
        id: GRAPHIC_ROOT_ID,
        type: "group",
        left: 0,
        top: 0,
        silent: false,
        clipPath: {
          type: "rect",
          shape: {
            x: 0,
            y: 0,
            width: Math.max(0, state.gutterRight),
            height: chart.getHeight(),
          },
        },
        children: graphics,
      },
    ];
  }

  function attach(chart, { payload }) {
    const tooltip = ensureTooltip(chart);
    let pendingFrame = null;
    let pendingOptions = {};

    function clear() {
      if (pendingFrame !== null) {
        cancelFrame(pendingFrame);
        pendingFrame = null;
      }
      hideTooltip(tooltip);
      chart.setOption(
        { graphic: [] },
        { replaceMerge: ["graphic"], lazyUpdate: true },
      );
    }

    function renderNow(options = {}) {
      if (!hasPayload(payload)) {
        clear();
        return;
      }

      hideTooltip(tooltip);
      const state = buildVisibleState(chart, payload, options);
      if (!state) {
        clear();
        return;
      }

      chart.setOption(
        { graphic: buildGraphics(chart, payload, state, tooltip) },
        { replaceMerge: ["graphic"], lazyUpdate: true },
      );
    }

    function render(options = {}) {
      pendingOptions = options;
      if (pendingFrame !== null) {
        cancelFrame(pendingFrame);
      }
      pendingFrame = requestFrame(() => {
        pendingFrame = null;
        renderNow(pendingOptions);
      });
    }

    return {
      clear,
      render,
    };
  }

  window.HomorepeatTaxonomyGutter = {
    attach,
    hasPayload,
    reservedWidth,
  };
})();
