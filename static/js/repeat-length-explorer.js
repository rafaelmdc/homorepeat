(() => {
  const BOX_FILL = "#dcebef";
  const BOX_BORDER = "#0f5964";
  const MEDIAN_COLOR = "#d06e37";
  const GRID_COLOR = "rgba(23, 36, 44, 0.1)";
  const TEXT_COLOR = "#17242c";
  const MUTED_TEXT_COLOR = "#63727a";
  const DEFAULT_VISIBLE_ROWS = 12;
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

  function truncateTaxonName(taxonName) {
    if (taxonName.length <= 28) {
      return taxonName;
    }
    return `${taxonName.slice(0, 25)}...`;
  }

  function rowCategoryValue(row) {
    return String(row.taxonId);
  }

  function chartHeightForRowCount(rowCount) {
    if (rowCount <= 0) {
      return MIN_CHART_HEIGHT;
    }
    return clamp((rowCount * ROW_HEIGHT) + CHART_PADDING, MIN_CHART_HEIGHT, MAX_CHART_HEIGHT);
  }

  function lengthBounds(payload) {
    if (!Array.isArray(payload.rows) || payload.rows.length === 0) {
      return [0, 1];
    }

    const span = payload.x_max - payload.x_min;
    const padding = span > 0 ? Math.max(1, Math.round(span * 0.08)) : 1;
    return [Math.max(0, payload.x_min - padding), payload.x_max + padding];
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

  function buildTooltip(row) {
    return [
      `<strong>${row.taxonName}</strong>`,
      `Observations: ${row.observationCount}`,
      `Min-Max: ${row.min}-${row.max}`,
      `Median: ${row.median}`,
      `IQR: ${row.q1}-${row.q3}`,
    ].join("<br>");
  }

  function buildChartOption(payload) {
    if (!Array.isArray(payload.rows) || payload.rows.length === 0) {
      return buildEmptyOption(payload);
    }

    const rows = payload.rows;
    const categories = rows.map((row) => rowCategoryValue(row));
    const boxplotData = rows.map((row) => [row.min, row.q1, row.median, row.q3, row.max]);
    const [xMin, xMax] = lengthBounds(payload);
    const visibleRowWindow = Math.min(rows.length, DEFAULT_VISIBLE_ROWS);
    const needsZoom = rows.length > visibleRowWindow;

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
          return buildTooltip(rows[params.dataIndex]);
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
          formatter(value, index) {
            const row = rows[index];
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
              startValue: 0,
              endValue: visibleRowWindow - 1,
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
              startValue: 0,
              endValue: visibleRowWindow - 1,
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
          data: rows.map((row, index) => [row.median, index]),
          symbol: "circle",
          symbolSize: 7,
          itemStyle: {
            color: MEDIAN_COLOR,
          },
          z: 4,
          tooltip: {
            show: false,
          },
        },
      ],
    };
  }

  function openBranchExplorer(rows, rowIndex) {
    const row = rows[rowIndex];
    if (!row || !row.branchExplorerUrl) {
      return;
    }
    window.location.assign(row.branchExplorerUrl);
  }

  function rowIndexForAxisValue(rows, axisValue) {
    return rows.findIndex((row) => rowCategoryValue(row) === String(axisValue));
  }

  function installDrilldown(chart, payload) {
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    if (rows.length === 0) {
      return;
    }

    chart.on("click", (params) => {
      if (typeof params.dataIndex === "number") {
        openBranchExplorer(rows, params.dataIndex);
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

  function mountLengthChart() {
    const container = document.getElementById("repeat-length-chart");
    const payload = parsePayload("repeat-length-chart-payload");
    if (!container || !payload || typeof window.echarts === "undefined") {
      return;
    }

    container.style.height = `${chartHeightForRowCount(payload.visibleTaxaCount || 0)}px`;

    const chart = window.echarts.init(container, null, { renderer: "svg" });
    chart.setOption(buildChartOption(payload));
    installDrilldown(chart, payload);

    window.addEventListener("resize", () => {
      chart.resize();
    });
  }

  document.addEventListener("DOMContentLoaded", mountLengthChart);
})();
