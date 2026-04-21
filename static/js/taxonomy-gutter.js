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
  const BOTTOM_TREE_PADDING = 12;
  const BOTTOM_LABEL_GAP = 10;
  const BOTTOM_LABEL_SECTION_GAP = 8;
  const BOTTOM_LABEL_BOTTOM_PADDING = 10;
  const BOTTOM_MAX_LEAF_LABEL_EXTENT = 120;
  const BOTTOM_MAX_BRACE_LABEL_EXTENT = 84;
  const BOTTOM_LEAF_FONT = "700 11px system-ui, sans-serif";
  const BOTTOM_BRACE_FONT = "600 10px system-ui, sans-serif";
  const GRAPHIC_ROOT_ID = "taxonomy-gutter-root";
  const TOOLTIP_DATA_KEY = "homorepeatTaxonomyGutterTooltip";
  const OVERLAY_DATA_KEY = "homorepeatTaxonomyGutterOverlay";
  const SVG_NS = "http://www.w3.org/2000/svg";

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

  function truncateTextToWidth(text, font, maximumWidth) {
    if (!text || maximumWidth <= 0) {
      return "";
    }
    if (measureTextWidth(text, font, maximumWidth) <= maximumWidth) {
      return text;
    }

    const ellipsis = "…";
    let truncatedText = String(text);
    while (truncatedText.length > 1) {
      truncatedText = truncatedText.slice(0, -1);
      const candidate = `${truncatedText}${ellipsis}`;
      if (measureTextWidth(candidate, font, maximumWidth) <= maximumWidth) {
        return candidate;
      }
    }
    return ellipsis;
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

  function reservedHeight(payload, options = {}) {
    if (!hasPayload(payload)) {
      return 0;
    }

    const showLabels = options.showLabels !== false;
    const showBraceLabels = options.showBraceLabels !== false;
    let bottomLeafLabelExtent = 0;
    let bottomBraceLabelExtent = 0;
    if (showLabels) {
      payload.leaves.forEach((leaf) => {
        bottomLeafLabelExtent = Math.max(
          bottomLeafLabelExtent,
          measureTextWidth(leaf.taxonName, BOTTOM_LEAF_FONT, BOTTOM_MAX_LEAF_LABEL_EXTENT),
        );
      });
    }
    if (showBraceLabels) {
      payload.leaves.forEach((leaf) => {
        if (!leaf.showBrace || !leaf.braceLabel) {
          return;
        }
        bottomBraceLabelExtent = Math.max(
          bottomBraceLabelExtent,
          measureTextWidth(`{ ${leaf.braceLabel}`, BOTTOM_BRACE_FONT, BOTTOM_MAX_BRACE_LABEL_EXTENT),
        );
      });
    }
    return (
      (Math.max(0, numericValue(payload.maxDepth, 0)) * DEPTH_STEP)
      + (BOTTOM_TREE_PADDING * 2)
      + (showLabels ? BOTTOM_LABEL_GAP + bottomLeafLabelExtent : 0)
      + (bottomBraceLabelExtent > 0 ? BOTTOM_LABEL_GAP + bottomBraceLabelExtent : 0)
      + ((showLabels || bottomBraceLabelExtent > 0) ? BOTTOM_LABEL_BOTTOM_PADDING : 0)
    );
  }

  function panelLayout(payload, options = {}) {
    const widths = layoutWidths(payload, options);
    const rootX = LEFT_PADDING + widths.internalLabelWidth;
    const leafLabelX = rootX + widths.treeWidth + (widths.showLabels ? LEAF_LABEL_GAP : MIN_LEAF_SECTION_WIDTH);
    const leafLineEndX = widths.showLabels ? leafLabelX - 6 : leafLabelX - 2;
    const braceMarkX = leafLabelX + widths.leafLabelWidth + BRACE_GAP;
    const braceLabelX = braceMarkX + BRACE_MARK_WIDTH + BRACE_LABEL_GAP;

    return {
      widths,
      rootX,
      leafLabelX,
      leafLineEndX,
      braceMarkX,
      braceLabelX,
      totalWidth: widths.total,
    };
  }

  function buildFullChildrenByParentId(payload) {
    const childrenByParentId = new Map();
    payload.edges.forEach((edge) => {
      const children = childrenByParentId.get(edge.parentNodeId) || [];
      children.push(edge.childNodeId);
      childrenByParentId.set(edge.parentNodeId, children);
    });
    return childrenByParentId;
  }

  function buildVisibleTreeState(payload, rowYByIndex, range, makeX) {
    if (!payload || !payload.root || !range || typeof makeX !== "function") {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    const rootNodeId = payload.root.nodeId;
    const fullChildrenByParentId = buildFullChildrenByParentId(payload);
    const visibleOriginalNodesById = new Map();

    payload.nodes.forEach((node) => {
      const clippedStart = Math.max(node.rowStart, range.start);
      const clippedEnd = Math.min(node.rowEnd, range.end);
      if (clippedStart > clippedEnd) {
        return;
      }

      const topY = rowYByIndex.get(clippedStart);
      const bottomY = rowYByIndex.get(clippedEnd);
      if (
        typeof topY !== "number"
        || !Number.isFinite(topY)
        || typeof bottomY !== "number"
        || !Number.isFinite(bottomY)
      ) {
        return;
      }

      const normalizedTopY = Math.min(topY, bottomY);
      const normalizedBottomY = Math.max(topY, bottomY);
      visibleOriginalNodesById.set(node.nodeId, {
        ...node,
        topY: normalizedTopY,
        bottomY: normalizedBottomY,
        y: (normalizedTopY + normalizedBottomY) / 2,
      });
    });

    if (!visibleOriginalNodesById.has(rootNodeId)) {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    function projectVisibleSubtree(nodeId) {
      const node = visibleOriginalNodesById.get(nodeId);
      if (!node) {
        return [];
      }

      const projectedChildren = [];
      const childNodeIds = fullChildrenByParentId.get(nodeId) || [];
      childNodeIds.forEach((childNodeId) => {
        projectedChildren.push(...projectVisibleSubtree(childNodeId));
      });

      const keepCurrent = nodeId === rootNodeId || node.isLeaf || projectedChildren.length !== 1;
      if (!keepCurrent) {
        return projectedChildren;
      }

      return [
        {
          ...node,
          children: projectedChildren,
          isPreservedSplit: projectedChildren.length >= 2,
        },
      ];
    }

    const projectedRoot = projectVisibleSubtree(rootNodeId)[0] || null;
    if (!projectedRoot) {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    const visibleNodesById = new Map();
    const childrenByParentId = new Map();

    function visitProjectedNode(projectedNode, parentNodeId, depth) {
      const orderedChildren = projectedNode.children
        .slice()
        .sort((leftNode, rightNode) => leftNode.y - rightNode.y);

      visibleNodesById.set(projectedNode.nodeId, {
        ...projectedNode,
        parentNodeId,
        depth,
        x: makeX(depth),
        isPreservedSplit: orderedChildren.length >= 2,
      });

      if (orderedChildren.length > 0) {
        childrenByParentId.set(
          projectedNode.nodeId,
          orderedChildren.map((childNode) => childNode.nodeId),
        );
      }

      orderedChildren.forEach((childNode) => {
        visitProjectedNode(childNode, projectedNode.nodeId, depth + 1);
      });
    }

    visitProjectedNode(projectedRoot, null, 0);
    return {
      visibleNodesById,
      childrenByParentId,
    };
  }

  function explicitLeafRange(payload, options = {}) {
    const leafCount = payload && Array.isArray(payload.leaves) ? payload.leaves.length : 0;
    if (leafCount < 1) {
      return null;
    }

    const explicitZoomState = options.zoomState || null;
    if (!explicitZoomState) {
      return {
        start: 0,
        end: leafCount - 1,
      };
    }

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

  function buildPanelState(payload, options, params, api) {
    const coordSys = params && params.coordSys ? params.coordSys : null;
    if (!coordSys) {
      return null;
    }

    const layout = panelLayout(payload, options);
    const range = explicitLeafRange(payload, options);
    if (!range) {
      return null;
    }
    const visibleLeaves = [];
    const rowYByIndex = new Map();
    const leafByNodeId = new Map();

    payload.leaves.forEach((leaf) => {
      if (leaf.rowIndex < range.start || leaf.rowIndex > range.end) {
        return;
      }
      const pixel = api.coord([0, leaf.axisValue]);
      const y = Array.isArray(pixel) ? pixel[1] : null;
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

    const { visibleNodesById, childrenByParentId } = buildVisibleTreeState(
      payload,
      rowYByIndex,
      range,
      (depth) => coordSys.x + layout.rootX + (depth * DEPTH_STEP),
    );

    return {
      widths: layout.widths,
      rootX: coordSys.x + layout.rootX,
      leafLabelX: coordSys.x + layout.leafLabelX,
      leafLineEndX: coordSys.x + layout.leafLineEndX,
      braceMarkX: coordSys.x + layout.braceMarkX,
      braceLabelX: coordSys.x + layout.braceLabelX,
      visibleLeaves,
      visibleNodesById,
      childrenByParentId,
      leafByNodeId,
    };
  }

  function panelLineElement(shape) {
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

  function panelNodeMarkerElement(node) {
    return {
      type: "circle",
      silent: true,
      shape: {
        cx: node.x,
        cy: node.y,
        r: nodeMarkerRadius(node),
      },
      style: nodeMarkerStyle(node),
      z: 5,
    };
  }

  function panelLeafHitAreaElement(state, leaf, node) {
    const braceLabelWidth = leaf.showBrace && leaf.braceLabel
      ? measureTextWidth(leaf.braceLabel, BRACE_FONT, MAX_BRACE_LABEL_WIDTH)
      : 0;
    const hitAreaRight = leaf.showBrace && leaf.braceLabel
      ? state.braceLabelX + braceLabelWidth + 8
      : state.leafLineEndX + 8;

    return {
      type: "rect",
      name: "leaf-target",
      info: {
        url: leaf.branchExplorerUrl || "",
      },
      cursor: leaf.branchExplorerUrl ? "pointer" : "default",
      silent: false,
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
    };
  }

  function buildPanelChildren(payload, state) {
    const children = [];
    const { widths, visibleNodesById, childrenByParentId, leafByNodeId } = state;

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (childNodeIds.length >= 2) {
        const firstChild = visibleNodesById.get(childNodeIds[0]);
        const lastChild = visibleNodesById.get(childNodeIds[childNodeIds.length - 1]);
        children.push(
          panelLineElement({
            x1: node.x,
            y1: firstChild.y,
            x2: node.x,
            y2: lastChild.y,
          }),
        );
      }

      childNodeIds.forEach((childNodeId) => {
        const childNode = visibleNodesById.get(childNodeId);
        children.push(
          panelLineElement({
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
      children.push(panelNodeMarkerElement(node));
    });

    state.visibleLeaves.forEach((leaf) => {
      const node = visibleNodesById.get(leaf.nodeId);
      if (!node) {
        return;
      }

      children.push(panelLeafHitAreaElement(state, leaf, node));
      children.push(
        panelLineElement({
          x1: node.x,
          y1: leaf.y,
          x2: state.leafLineEndX,
          y2: leaf.y,
        }),
      );

      if (widths.showLabels) {
        children.push(
          {
            type: "text",
            x: state.leafLabelX,
            y: leaf.y,
            silent: true,
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
        children.push(
          {
            type: "text",
            x: state.braceMarkX,
            y: leaf.y,
            silent: true,
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
        children.push(
          {
            type: "text",
            x: state.braceLabelX,
            y: leaf.y,
            silent: true,
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
        children.push(
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

    return children;
  }

  function buildPanel(payload, options = {}) {
    if (!hasPayload(payload)) {
      return null;
    }

    const layout = panelLayout(payload, options);
    const gridIndex = numericValue(options.gridIndex, 0);
    const xAxisIndex = numericValue(options.xAxisIndex, gridIndex);
    const yAxisIndex = numericValue(options.yAxisIndex, gridIndex);
    const seriesName = typeof options.seriesName === "string" && options.seriesName
      ? options.seriesName
      : "taxonomy-gutter";
    const seriesId = typeof options.seriesId === "string" && options.seriesId
      ? options.seriesId
      : `${seriesName}-series`;

    return {
      width: layout.totalWidth,
      seriesName,
      seriesId,
      grid: {
        left: numericValue(options.left, 0),
        width: layout.totalWidth,
        top: numericValue(options.top, 0),
        bottom: numericValue(options.bottom, 0),
        containLabel: false,
      },
      xAxis: {
        type: "value",
        min: 0,
        max: layout.totalWidth,
        show: false,
        gridIndex,
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: payload.leaves.map((leaf) => leaf.axisValue),
        show: false,
        axisLine: {
          show: false,
        },
        axisTick: {
          show: false,
        },
        axisLabel: {
          show: false,
        },
        gridIndex,
      },
      series: {
        id: seriesId,
        name: seriesName,
        type: "custom",
        coordinateSystem: "cartesian2d",
        xAxisIndex,
        yAxisIndex,
        encode: {
          x: -1,
          y: -1,
        },
        animation: false,
        silent: false,
        clip: true,
        tooltip: {
          show: false,
        },
        data: [0],
        renderItem(params, api) {
          const state = buildPanelState(payload, options, params, api);
          if (!state) {
            return {
              type: "group",
              children: [],
            };
          }
          return {
            type: "group",
            children: buildPanelChildren(payload, state),
          };
        },
      },
    };
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

  function explicitGridRect(chart, options = {}) {
    const top = numericValue(options.top, Number.NaN);
    const bottom = numericValue(options.bottom, Number.NaN);
    const left = numericValue(options.left, Number.NaN);
    const right = numericValue(options.right, 0);
    const gutterWidth = numericValue(options.gutterWidth, Number.NaN);
    const resolvedLeft = Number.isFinite(left)
      ? left
      : (Number.isFinite(gutterWidth) ? gutterWidth + TREE_TO_GRID_GAP : Number.NaN);
    if (!Number.isFinite(top) || !Number.isFinite(bottom) || !Number.isFinite(resolvedLeft)) {
      return null;
    }

    return {
      x: resolvedLeft,
      y: top,
      width: Math.max(0, chart.getWidth() - resolvedLeft - Math.max(0, right)),
      height: Math.max(0, chart.getHeight() - top - bottom),
    };
  }

  function yAxisIsInverse(chart) {
    const option = chart.getOption();
    const yAxis = Array.isArray(option.yAxis) ? option.yAxis[0] : option.yAxis;
    return Boolean(yAxis && yAxis.inverse);
  }

  function axisLeafCenterY(chart, leaf) {
    try {
      const model = chart.getModel ? chart.getModel() : null;
      const axisComponent = model && model.getComponent ? model.getComponent("yAxis", 0) : null;
      const axis = axisComponent ? axisComponent.axis : null;
      if (!axis || typeof axis.dataToCoord !== "function" || typeof axis.toGlobalCoord !== "function") {
        return null;
      }

      const localCoord = axis.dataToCoord(leaf.axisValue);
      if (typeof localCoord !== "number" || !Number.isFinite(localCoord)) {
        return null;
      }

      const globalCoord = axis.toGlobalCoord(localCoord);
      return typeof globalCoord === "number" && Number.isFinite(globalCoord) ? globalCoord : null;
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

  function leafCenterY(chart, leaf, range, currentGridRect) {
    const axisPixel = axisLeafCenterY(chart, leaf);
    if (axisPixel !== null) {
      return axisPixel;
    }

    const visibleRowCount = (range.end - range.start) + 1;
    if (!currentGridRect || visibleRowCount < 1) {
      return null;
    }

    const bandHeight = currentGridRect.height / visibleRowCount;
    if (!Number.isFinite(bandHeight) || bandHeight <= 0) {
      return null;
    }

    const topOrdinal = yAxisIsInverse(chart)
      ? leaf.rowIndex - range.start
      : range.end - leaf.rowIndex;
    return currentGridRect.y + ((topOrdinal + 0.5) * bandHeight);
  }

  function buildVisibleState(chart, payload, options) {
    const range = visibleLeafRange(chart, payload, options);
    if (!range) {
      return null;
    }

    const currentGridRect = explicitGridRect(chart, options) || gridRect(chart);
    const visibleLeaves = [];
    const rowYByIndex = new Map();
    const leafByNodeId = new Map();
    payload.leaves.forEach((leaf) => {
      if (leaf.rowIndex < range.start || leaf.rowIndex > range.end) {
        return;
      }
      const y = leafCenterY(chart, leaf, range, currentGridRect);
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

    const { visibleNodesById, childrenByParentId } = buildVisibleTreeState(
      payload,
      rowYByIndex,
      range,
      (depth) => rootX + (depth * DEPTH_STEP),
    );

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

  function buildHorizontalVisibleTreeState(payload, columnXByIndex, range, makeY) {
    if (!payload || !payload.root || !range || typeof makeY !== "function") {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    const rootNodeId = payload.root.nodeId;
    const fullChildrenByParentId = buildFullChildrenByParentId(payload);
    const visibleOriginalNodesById = new Map();

    payload.nodes.forEach((node) => {
      const clippedStart = Math.max(node.rowStart, range.start);
      const clippedEnd = Math.min(node.rowEnd, range.end);
      if (clippedStart > clippedEnd) {
        return;
      }

      const leftX = columnXByIndex.get(clippedStart);
      const rightX = columnXByIndex.get(clippedEnd);
      if (
        typeof leftX !== "number"
        || !Number.isFinite(leftX)
        || typeof rightX !== "number"
        || !Number.isFinite(rightX)
      ) {
        return;
      }

      const normalizedLeftX = Math.min(leftX, rightX);
      const normalizedRightX = Math.max(leftX, rightX);
      visibleOriginalNodesById.set(node.nodeId, {
        ...node,
        leftX: normalizedLeftX,
        rightX: normalizedRightX,
        x: (normalizedLeftX + normalizedRightX) / 2,
      });
    });

    if (!visibleOriginalNodesById.has(rootNodeId)) {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    function projectVisibleSubtree(nodeId) {
      const node = visibleOriginalNodesById.get(nodeId);
      if (!node) {
        return [];
      }

      const projectedChildren = [];
      const childNodeIds = fullChildrenByParentId.get(nodeId) || [];
      childNodeIds.forEach((childNodeId) => {
        projectedChildren.push(...projectVisibleSubtree(childNodeId));
      });

      const keepCurrent = nodeId === rootNodeId || node.isLeaf || projectedChildren.length !== 1;
      if (!keepCurrent) {
        return projectedChildren;
      }

      return [
        {
          ...node,
          children: projectedChildren,
          isPreservedSplit: projectedChildren.length >= 2,
        },
      ];
    }

    const projectedRoot = projectVisibleSubtree(rootNodeId)[0] || null;
    if (!projectedRoot) {
      return {
        visibleNodesById: new Map(),
        childrenByParentId: new Map(),
      };
    }

    const visibleNodesById = new Map();
    const childrenByParentId = new Map();

    function visitProjectedNode(projectedNode, parentNodeId, depth) {
      const orderedChildren = projectedNode.children
        .slice()
        .sort((leftNode, rightNode) => leftNode.x - rightNode.x);

      visibleNodesById.set(projectedNode.nodeId, {
        ...projectedNode,
        parentNodeId,
        depth,
        isPreservedSplit: orderedChildren.length >= 2,
      });

      if (orderedChildren.length > 0) {
        childrenByParentId.set(
          projectedNode.nodeId,
          orderedChildren.map((childNode) => childNode.nodeId),
        );
      }

      orderedChildren.forEach((childNode) => {
        visitProjectedNode(childNode, projectedNode.nodeId, depth + 1);
      });
    }

    visitProjectedNode(projectedRoot, null, 0);
    const projectedMaxDepth = Math.max(
      0,
      ...Array.from(visibleNodesById.values()).map((node) => numericValue(node.depth, 0)),
    );
    visibleNodesById.forEach((node) => {
      node.y = makeY(projectedMaxDepth - node.depth);
    });

    return {
      visibleNodesById,
      childrenByParentId,
    };
  }

  function buildHorizontalVisibleState(chart, payload, options) {
    const range = visibleLeafRange(chart, payload, options);
    if (!range) {
      return null;
    }

    const currentGridRect = explicitGridRect(chart, options) || gridRect(chart);
    const bottomGutterHeight = numericValue(options.bottomGutterHeight, Number.NaN);
    if (!currentGridRect || !Number.isFinite(bottomGutterHeight) || bottomGutterHeight <= 0) {
      return null;
    }

    const visibleLeafCount = (range.end - range.start) + 1;
    const bandWidth = currentGridRect.width / visibleLeafCount;
    if (!Number.isFinite(bandWidth) || bandWidth <= 0) {
      return null;
    }

    const bottomOffset = numericValue(options.bottomOffset, 0);
    const bottomTop = chart.getHeight() - bottomGutterHeight - bottomOffset;
    const showLabels = options.showLabels !== false;
    const showBraceLabels = options.showBraceLabels !== false;
    let bottomLeafLabelExtent = 0;
    let bottomBraceLabelExtent = 0;
    const leafXByIndex = new Map();
    const visibleLeaves = [];
    payload.leaves.forEach((leaf) => {
      if (leaf.rowIndex < range.start || leaf.rowIndex > range.end) {
        return;
      }
      const ordinal = leaf.rowIndex - range.start;
      const x = currentGridRect.x + ((ordinal + 0.5) * bandWidth);
      leafXByIndex.set(leaf.rowIndex, x);
      const leafLabelText = showLabels
        ? truncateTextToWidth(leaf.taxonName, BOTTOM_LEAF_FONT, BOTTOM_MAX_LEAF_LABEL_EXTENT)
        : "";
      const braceLabelText = showBraceLabels && leaf.showBrace && leaf.braceLabel
        ? truncateTextToWidth(`{ ${leaf.braceLabel}`, BOTTOM_BRACE_FONT, BOTTOM_MAX_BRACE_LABEL_EXTENT)
        : "";
      const leafLabelExtent = showLabels
        ? measureTextWidth(leafLabelText || leaf.taxonName, BOTTOM_LEAF_FONT, BOTTOM_MAX_LEAF_LABEL_EXTENT)
        : 0;
      const braceLabelExtent = braceLabelText
        ? measureTextWidth(braceLabelText, BOTTOM_BRACE_FONT, BOTTOM_MAX_BRACE_LABEL_EXTENT)
        : 0;
      bottomLeafLabelExtent = Math.max(bottomLeafLabelExtent, leafLabelExtent);
      bottomBraceLabelExtent = Math.max(bottomBraceLabelExtent, braceLabelExtent);
      visibleLeaves.push({
        ...leaf,
        x,
        bottomLeafLabelText: leafLabelText,
        bottomBraceLabelText: braceLabelText,
      });
    });

    const labelSectionHeight = (showLabels || bottomBraceLabelExtent > 0)
      ? BOTTOM_LABEL_GAP
        + (showLabels ? bottomLeafLabelExtent : 0)
        + (bottomBraceLabelExtent > 0 ? BOTTOM_LABEL_SECTION_GAP + bottomBraceLabelExtent : 0)
        + BOTTOM_LABEL_BOTTOM_PADDING
      : 0;

    const { visibleNodesById, childrenByParentId } = buildHorizontalVisibleTreeState(
      payload,
      leafXByIndex,
      range,
      (invertedDepth) => bottomTop + labelSectionHeight + BOTTOM_TREE_PADDING + (invertedDepth * DEPTH_STEP),
    );
    if (visibleNodesById.size === 0) {
      return null;
    }

    return {
      bottomTop,
      bottomHeight: bottomGutterHeight,
      bandWidth,
      labelSectionHeight,
      bottomLeafLabelExtent,
      bottomBraceLabelExtent,
      showLabels,
      showBraceLabels,
      visibleLeaves,
      visibleNodesById,
      childrenByParentId,
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

  function createSvgElement(tagName, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tagName);
    Object.entries(attributes).forEach(([name, value]) => {
      if (value == null) {
        return;
      }
      element.setAttribute(name, String(value));
    });
    return element;
  }

  function applySvgTextStyle(element, {
    fill,
    font,
    textAnchor = "start",
    dominantBaseline = "middle",
  }) {
    element.setAttribute("fill", fill);
    element.setAttribute("text-anchor", textAnchor);
    element.setAttribute("dominant-baseline", dominantBaseline);
    element.style.font = font;
  }

  function bindHoverEvents(element, chart, tooltip, text, x, y) {
    if (!element || !text) {
      return;
    }
    element.addEventListener("mouseenter", () => {
      showTooltip(chart, tooltip, text, x, y);
    });
    element.addEventListener("mousemove", () => {
      showTooltip(chart, tooltip, text, x, y);
    });
    element.addEventListener("mouseleave", () => {
      hideTooltip(tooltip);
    });
  }

  function overlayLayerKey(layerKey = "left") {
    return layerKey === "left" ? OVERLAY_DATA_KEY : `${OVERLAY_DATA_KEY}-${layerKey}`;
  }

  function ensureOverlayLayer(chart, layerKey = "left") {
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

    const resolvedLayerKey = overlayLayerKey(layerKey);
    let overlay = chartDom.querySelector(`[data-${resolvedLayerKey}]`);
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.setAttribute(`data-${resolvedLayerKey}`, "true");
      Object.assign(overlay.style, {
        position: "absolute",
        left: "0",
        top: "0",
        overflow: "hidden",
        pointerEvents: "none",
        zIndex: "6",
      });

      const svg = createSvgElement("svg");
      svg.style.display = "block";
      svg.style.overflow = "visible";
      overlay.appendChild(svg);
      chartDom.appendChild(overlay);
    }

    return overlay;
  }

  function clearOverlayLayer(overlay) {
    if (!overlay) {
      return;
    }
    const svg = overlay.querySelector("svg");
    if (svg) {
      svg.replaceChildren();
    }
    overlay.style.width = "0px";
    overlay.style.height = "0px";
  }

  function renderOverlay(chart, payload, state, tooltip) {
    const overlay = ensureOverlayLayer(chart);
    if (!overlay) {
      return;
    }

    const svg = overlay.querySelector("svg");
    if (!svg) {
      return;
    }

    overlay.style.width = `${Math.max(0, state.gutterRight)}px`;
    overlay.style.height = `${chart.getHeight()}px`;
    svg.setAttribute("width", String(chart.getWidth()));
    svg.setAttribute("height", String(chart.getHeight()));
    svg.setAttribute("viewBox", `0 0 ${chart.getWidth()} ${chart.getHeight()}`);
    svg.replaceChildren();

    const root = createSvgElement("g");
    svg.appendChild(root);

    const { widths, visibleNodesById, childrenByParentId, leafByNodeId } = state;

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (childNodeIds.length >= 2) {
        const firstChild = visibleNodesById.get(childNodeIds[0]);
        const lastChild = visibleNodesById.get(childNodeIds[childNodeIds.length - 1]);
        root.appendChild(
          createSvgElement("line", {
            x1: node.x,
            y1: firstChild.y,
            x2: node.x,
            y2: lastChild.y,
            stroke: LINE_COLOR,
            "stroke-width": LINE_WIDTH,
          }),
        );
      }

      childNodeIds.forEach((childNodeId) => {
        const childNode = visibleNodesById.get(childNodeId);
        root.appendChild(
          createSvgElement("line", {
            x1: node.x,
            y1: childNode.y,
            x2: childNode.x,
            y2: childNode.y,
            stroke: LINE_COLOR,
            "stroke-width": LINE_WIDTH,
          }),
        );
      });
    });

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (node.isLeaf || childNodeIds.length === 0) {
        return;
      }

      const style = nodeMarkerStyle(node);
      const marker = createSvgElement("circle", {
        cx: node.x,
        cy: node.y,
        r: nodeMarkerRadius(node),
        fill: style.fill,
        stroke: style.stroke,
        "stroke-width": style.lineWidth,
      });
      marker.style.pointerEvents = "auto";
      bindHoverEvents(chart ? marker : null, chart, tooltip, nodeTooltipText(node), node.x, node.y);
      root.appendChild(marker);
    });

    state.visibleLeaves.forEach((leaf) => {
      const node = visibleNodesById.get(leaf.nodeId);
      if (!node) {
        return;
      }

      const braceLabelWidth = leaf.showBrace && leaf.braceLabel
        ? measureTextWidth(leaf.braceLabel, BRACE_FONT, MAX_BRACE_LABEL_WIDTH)
        : 0;
      const hitAreaRight = leaf.showBrace && leaf.braceLabel
        ? state.braceLabelX + braceLabelWidth + 8
        : state.leafLineEndX + 8;
      const hoverText = leafHoverText(leaf);

      const hitArea = createSvgElement("rect", {
        x: node.x - 2,
        y: leaf.y - 10,
        width: Math.max(12, hitAreaRight - node.x + 2),
        height: 20,
        fill: "transparent",
      });
      hitArea.style.pointerEvents = "auto";
      hitArea.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
      if (leaf.branchExplorerUrl) {
        hitArea.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
      }
      bindHoverEvents(hitArea, chart, tooltip, hoverText, hitAreaRight, leaf.y);
      root.appendChild(hitArea);

      root.appendChild(
        createSvgElement("line", {
          x1: node.x,
          y1: leaf.y,
          x2: state.leafLineEndX,
          y2: leaf.y,
          stroke: LINE_COLOR,
          "stroke-width": LINE_WIDTH,
        }),
      );

      if (widths.showLabels) {
        const label = createSvgElement("text", {
          x: state.leafLabelX,
          y: leaf.y,
        });
        label.textContent = leaf.taxonName;
        applySvgTextStyle(label, {
          fill: LEAF_TEXT_COLOR,
          font: LEAF_FONT,
        });
        label.style.pointerEvents = "auto";
        label.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
        if (leaf.branchExplorerUrl) {
          label.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
        }
        bindHoverEvents(label, chart, tooltip, hoverText, state.leafLabelX, leaf.y);
        root.appendChild(label);
      }

      if (leaf.showBrace && leaf.braceLabel) {
        const braceMark = createSvgElement("text", {
          x: state.braceMarkX,
          y: leaf.y,
        });
        braceMark.textContent = "{";
        applySvgTextStyle(braceMark, {
          fill: INTERNAL_TEXT_COLOR,
          font: BRACE_MARK_FONT,
        });
        braceMark.style.pointerEvents = "auto";
        braceMark.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
        if (leaf.branchExplorerUrl) {
          braceMark.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
        }
        bindHoverEvents(braceMark, chart, tooltip, hoverText, state.braceMarkX, leaf.y);
        root.appendChild(braceMark);

        const braceLabel = createSvgElement("text", {
          x: state.braceLabelX,
          y: leaf.y,
        });
        braceLabel.textContent = leaf.braceLabel;
        applySvgTextStyle(braceLabel, {
          fill: INTERNAL_TEXT_COLOR,
          font: BRACE_FONT,
        });
        braceLabel.style.pointerEvents = "auto";
        braceLabel.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
        if (leaf.branchExplorerUrl) {
          braceLabel.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
        }
        bindHoverEvents(braceLabel, chart, tooltip, hoverText, state.braceLabelX, leaf.y);
        root.appendChild(braceLabel);
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

        const internalLabel = createSvgElement("text", {
          x: node.x - 8,
          y: node.y,
        });
        internalLabel.textContent = node.taxonName;
        applySvgTextStyle(internalLabel, {
          fill: INTERNAL_TEXT_COLOR,
          font: INTERNAL_FONT,
          textAnchor: "end",
        });
        root.appendChild(internalLabel);
      });
    }
  }

  function renderBottomOverlay(chart, payload, state, tooltip) {
    const overlay = ensureOverlayLayer(chart, "bottom");
    if (!overlay) {
      return;
    }

    const svg = overlay.querySelector("svg");
    if (!svg) {
      return;
    }

    overlay.style.width = `${chart.getWidth()}px`;
    overlay.style.height = `${chart.getHeight()}px`;
    svg.setAttribute("width", String(chart.getWidth()));
    svg.setAttribute("height", String(chart.getHeight()));
    svg.setAttribute("viewBox", `0 0 ${chart.getWidth()} ${chart.getHeight()}`);
    svg.replaceChildren();

    const root = createSvgElement("g");
    svg.appendChild(root);

    const clipPath = createSvgElement("clipPath", {
      id: `${GRAPHIC_ROOT_ID}-bottom-clip`,
    });
    clipPath.appendChild(
      createSvgElement("rect", {
        x: 0,
        y: state.bottomTop,
        width: chart.getWidth(),
        height: state.bottomHeight,
      }),
    );
    svg.appendChild(clipPath);
    root.setAttribute("clip-path", `url(#${GRAPHIC_ROOT_ID}-bottom-clip)`);

    const { visibleNodesById, childrenByParentId } = state;

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (childNodeIds.length >= 2) {
        const firstChild = visibleNodesById.get(childNodeIds[0]);
        const lastChild = visibleNodesById.get(childNodeIds[childNodeIds.length - 1]);
        root.appendChild(
          createSvgElement("line", {
            x1: firstChild.x,
            y1: node.y,
            x2: lastChild.x,
            y2: node.y,
            stroke: LINE_COLOR,
            "stroke-width": LINE_WIDTH,
          }),
        );
      }

      childNodeIds.forEach((childNodeId) => {
        const childNode = visibleNodesById.get(childNodeId);
        root.appendChild(
          createSvgElement("line", {
            x1: childNode.x,
            y1: node.y,
            x2: childNode.x,
            y2: childNode.y,
            stroke: LINE_COLOR,
            "stroke-width": LINE_WIDTH,
          }),
        );
      });
    });

    visibleNodesById.forEach((node) => {
      const childNodeIds = childrenByParentId.get(node.nodeId) || [];
      if (node.isLeaf || childNodeIds.length === 0) {
        return;
      }

      const style = nodeMarkerStyle(node);
      const marker = createSvgElement("circle", {
        cx: node.x,
        cy: node.y,
        r: nodeMarkerRadius(node),
        fill: style.fill,
        stroke: style.stroke,
        "stroke-width": style.lineWidth,
      });
      marker.style.pointerEvents = "auto";
      bindHoverEvents(marker, chart, tooltip, nodeTooltipText(node), node.x, node.y);
      root.appendChild(marker);
    });

    if ((!state.showLabels && !state.showBraceLabels) || !Array.isArray(state.visibleLeaves) || state.visibleLeaves.length === 0) {
      return;
    }

    const braceLabelTopY = state.bottomTop + BOTTOM_LABEL_GAP;
    const braceLabelCenterY = braceLabelTopY + (state.bottomBraceLabelExtent / 2);
    const leafLabelTopY = braceLabelTopY + (state.showBraceLabels && state.bottomBraceLabelExtent > 0 ? state.bottomBraceLabelExtent + BOTTOM_LABEL_SECTION_GAP : 0);
    const leafLabelCenterY = leafLabelTopY + (state.bottomLeafLabelExtent / 2);
    const lastLabelBottomY = state.showLabels && state.bottomLeafLabelExtent > 0
      ? leafLabelTopY + state.bottomLeafLabelExtent
      : (state.showBraceLabels && state.bottomBraceLabelExtent > 0 ? braceLabelTopY + state.bottomBraceLabelExtent : null);

    state.visibleLeaves.forEach((leaf) => {
      const node = visibleNodesById.get(leaf.nodeId);
      if (!node) {
        return;
      }

      if (typeof lastLabelBottomY === "number" && Number.isFinite(lastLabelBottomY)) {
        root.appendChild(
          createSvgElement("line", {
            x1: node.x,
            y1: lastLabelBottomY + 8,
            x2: node.x,
            y2: node.y,
            stroke: LINE_COLOR,
            "stroke-width": LINE_WIDTH,
          }),
        );
      }

      const hoverText = leafHoverText(leaf);
      if (state.showLabels && leaf.bottomLeafLabelText) {
        const leafLabel = createSvgElement("text", {
          x: leaf.x,
          y: leafLabelCenterY,
        });
        leafLabel.textContent = leaf.bottomLeafLabelText;
        applySvgTextStyle(leafLabel, {
          fill: LEAF_TEXT_COLOR,
          font: BOTTOM_LEAF_FONT,
          textAnchor: "middle",
        });
        leafLabel.setAttribute("transform", `rotate(-90 ${leaf.x} ${leafLabelCenterY})`);
        leafLabel.style.pointerEvents = "auto";
        leafLabel.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
        if (leaf.branchExplorerUrl) {
          leafLabel.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
        }
        bindHoverEvents(leafLabel, chart, tooltip, hoverText, leaf.x, leafLabelCenterY);
        root.appendChild(leafLabel);
      }

      if (state.showBraceLabels && leaf.showBrace && leaf.braceLabel && leaf.bottomBraceLabelText) {
        const braceLabel = createSvgElement("text", {
          x: leaf.x,
          y: braceLabelCenterY,
        });
        braceLabel.textContent = leaf.bottomBraceLabelText;
        applySvgTextStyle(braceLabel, {
          fill: INTERNAL_TEXT_COLOR,
          font: BOTTOM_BRACE_FONT,
          textAnchor: "middle",
        });
        braceLabel.setAttribute("transform", `rotate(-90 ${leaf.x} ${braceLabelCenterY})`);
        braceLabel.style.pointerEvents = "auto";
        braceLabel.style.cursor = leaf.branchExplorerUrl ? "pointer" : "default";
        if (leaf.branchExplorerUrl) {
          braceLabel.addEventListener("click", () => navigateTo(leaf.branchExplorerUrl));
        }
        bindHoverEvents(braceLabel, chart, tooltip, hoverText, leaf.x, braceLabelCenterY);
        root.appendChild(braceLabel);
      }
    });
  }

  function attach(chart, { payload, position = "left" } = {}) {
    const tooltip = ensureTooltip(chart);
    let pendingFrame = null;
    let pendingOptions = {};
    let overlay = null;

    function clear() {
      if (pendingFrame !== null) {
        cancelFrame(pendingFrame);
        pendingFrame = null;
      }
      hideTooltip(tooltip);
      if (!overlay) {
        overlay = ensureOverlayLayer(chart, position);
      }
      clearOverlayLayer(overlay);
    }

    function renderNow(options = {}) {
      if (!hasPayload(payload)) {
        clear();
        return;
      }

      hideTooltip(tooltip);
      if (!overlay) {
        overlay = ensureOverlayLayer(chart, position);
      }
      if (position === "bottom") {
        const bottomState = buildHorizontalVisibleState(chart, payload, options);
        if (!bottomState) {
          clear();
          return;
        }
        renderBottomOverlay(chart, payload, bottomState, tooltip);
        return;
      }
      const leftState = buildVisibleState(chart, payload, options);
      if (!leftState) {
        clear();
        return;
      }
      renderOverlay(chart, payload, leftState, tooltip);
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
    buildPanel,
    hasPayload,
    reservedHeight,
    reservedWidth,
  };
})();
