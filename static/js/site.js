(() => {
  function buildSpacer(colspan, position) {
    const row = document.createElement("tr");
    row.className = "virtual-scroll-spacer";
    row.dataset.virtualSpacer = position;
    row.hidden = true;

    const cell = document.createElement("td");
    cell.colSpan = colspan;

    const fill = document.createElement("div");
    fill.className = "virtual-scroll-spacer-fill";
    cell.appendChild(fill);
    row.appendChild(cell);

    return { row, fill };
  }

  function updateSpacerHeight(spacer, height) {
    const normalizedHeight = Math.max(0, Math.round(height));
    spacer.fill.style.height = `${normalizedHeight}px`;
    spacer.row.hidden = normalizedHeight === 0;
  }

  function sumRowHeight(rows) {
    return rows.reduce((total, row) => total + row.getBoundingClientRect().height, 0);
  }

  function updateAverageRowHeight(state, rows) {
    const totalHeight = sumRowHeight(rows);
    if (!totalHeight || !rows.length) {
      return;
    }

    const measuredAverage = totalHeight / rows.length;
    state.averageRowHeight = state.averageRowHeight
      ? ((state.averageRowHeight * 2) + measuredAverage) / 3
      : measuredAverage;
  }

  function pageRows(state, pageKey) {
    return Array.from(state.body.querySelectorAll(`tr[data-virtual-page-key="${pageKey}"]`));
  }

  function updateSpacers(state) {
    updateSpacerHeight(state.topSpacer, state.hiddenTopRows * state.averageRowHeight);
    updateSpacerHeight(state.bottomSpacer, state.hiddenBottomRows * state.averageRowHeight);
  }

  function parseRows(rowsHtml) {
    const container = document.createElement("tbody");
    container.innerHTML = rowsHtml.trim();
    return Array.from(container.children).filter((node) => node.tagName === "TR");
  }

  function currentTopPage(state) {
    return state.pages[0] || null;
  }

  function currentBottomPage(state) {
    return state.pages[state.pages.length - 1] || null;
  }

  function mountedRows(state) {
    return Array.from(state.body.querySelectorAll("tr[data-virtual-row]"));
  }

  function parseOptionalCount(value) {
    const parsed = Number.parseInt(value ?? "", 10);
    if (Number.isNaN(parsed)) {
      return null;
    }
    return Math.max(0, parsed);
  }

  function firstMountedRow(state) {
    return mountedRows(state)[0] || null;
  }

  function lastMountedRow(state) {
    const rows = mountedRows(state);
    return rows[rows.length - 1] || null;
  }

  function seedPageLimit(state) {
    return Math.min(3, state.maxPages);
  }

  function distanceToBottom(state) {
    return state.root.scrollHeight - state.root.clientHeight - state.root.scrollTop;
  }

  function edgeThreshold(state) {
    return Math.max(220, state.averageRowHeight * 4);
  }

  function distanceToLoadedTop(state) {
    const row = firstMountedRow(state);
    if (!row) {
      return Number.POSITIVE_INFINITY;
    }

    return row.getBoundingClientRect().top - state.root.getBoundingClientRect().top;
  }

  function distanceToLoadedBottom(state) {
    const row = lastMountedRow(state);
    if (!row) {
      return Number.POSITIVE_INFINITY;
    }

    return row.getBoundingClientRect().bottom - state.root.getBoundingClientRect().bottom;
  }

  function canEvictTop(state) {
    return state.root.scrollTop > edgeThreshold(state);
  }

  function canEvictBottom(state) {
    return distanceToBottom(state) > edgeThreshold(state);
  }

  function evictTopPage(state) {
    if (state.pages.length <= 1) {
      return;
    }

    const page = state.pages.shift();
    const rows = pageRows(state, page.key);
    rows.forEach((row) => row.remove());
    state.hiddenTopRows += page.rowCount;
    updateSpacers(state);
  }

  function evictBottomPage(state) {
    if (state.pages.length <= 1) {
      return;
    }

    const page = state.pages.pop();
    const rows = pageRows(state, page.key);
    rows.forEach((row) => row.remove());
    state.hiddenBottomRows += page.rowCount;
    updateSpacers(state);
  }

  function trimWindow(state, direction) {
    while (state.pages.length > state.maxPages) {
      if (direction === "previous") {
        if (!canEvictBottom(state)) {
          break;
        }
        evictBottomPage(state);
        continue;
      }

      if (!canEvictTop(state)) {
        break;
      }
      evictTopPage(state);
    }
  }

  async function fetchPage(state, queryString) {
    const url = new URL(state.fragmentUrl, window.location.origin);
    const params = new URLSearchParams(queryString);
    params.set("fragment", "virtual-scroll");
    url.search = params.toString();

    const response = await fetch(url.toString(), {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
      },
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error(`Virtual scroll request failed with ${response.status}`);
    }

    return response.json();
  }

  function insertRows(state, rows, direction) {
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => fragment.appendChild(row));

    if (direction === "previous") {
      state.body.insertBefore(fragment, state.topSpacer.row.nextSibling);
      return;
    }

    state.body.insertBefore(fragment, state.bottomSpacer.row);
  }

  function registerPage(state, payload, direction) {
    const rows = parseRows(payload.rows_html || "");
    const payloadCount = parseOptionalCount(payload.count);
    if (payloadCount !== null) {
      state.totalRows = payloadCount;
    }
    if (!rows.length) {
      const boundaryPage = direction === "previous" ? currentTopPage(state) : currentBottomPage(state);
      if (boundaryPage) {
        if (direction === "previous") {
          boundaryPage.previousQuery = "";
        } else {
          boundaryPage.nextQuery = "";
        }
      }
      return;
    }

    const pageKey = `page-${state.pageSequence}`;
    state.pageSequence += 1;

    rows.forEach((row) => {
      row.dataset.virtualRow = "1";
      row.dataset.virtualPageKey = pageKey;
    });
    insertRows(state, rows, direction);
    updateAverageRowHeight(state, rows);
    const insertedRowCount = payload.row_count || rows.length;

    if (direction === "previous") {
      state.hiddenTopRows = Math.max(0, state.hiddenTopRows - insertedRowCount);
      state.pages.unshift({
        key: pageKey,
        rowCount: insertedRowCount,
        previousQuery: payload.previous_query || "",
        nextQuery: payload.next_query || "",
      });
      trimWindow(state, "previous");
    } else {
      state.hiddenBottomRows = Math.max(0, state.hiddenBottomRows - insertedRowCount);
      state.pages.push({
        key: pageKey,
        rowCount: insertedRowCount,
        previousQuery: payload.previous_query || "",
        nextQuery: payload.next_query || "",
      });
      trimWindow(state, "next");
    }

    updateSpacers(state);
  }

  async function loadPrevious(state) {
    const page = currentTopPage(state);
    if (!page || !page.previousQuery || state.loadingPrevious) {
      return;
    }

    state.loadingPrevious = true;
    try {
      const payload = await fetchPage(state, page.previousQuery);
      registerPage(state, payload, "previous");
    } catch (error) {
      window.console.error(error);
    } finally {
      state.loadingPrevious = false;
      scheduleRefresh(state);
    }
  }

  async function loadNext(state) {
    const page = currentBottomPage(state);
    if (!page || !page.nextQuery || state.loadingNext) {
      return;
    }

    state.loadingNext = true;
    try {
      const payload = await fetchPage(state, page.nextQuery);
      registerPage(state, payload, "next");
    } catch (error) {
      window.console.error(error);
    } finally {
      state.loadingNext = false;
      scheduleRefresh(state);
    }
  }

  function refresh(state) {
    state.refreshFrame = null;
    const threshold = edgeThreshold(state);
    const loadedTopDistance = distanceToLoadedTop(state);
    const loadedBottomDistance = distanceToLoadedBottom(state);
    const shouldSeedWindow = (
      state.pages.length < seedPageLimit(state)
      && mountedRows(state).length < state.root.clientHeight / Math.max(state.averageRowHeight, 1)
    );

    if (state.hiddenTopRows > 0 && loadedTopDistance >= -threshold) {
      loadPrevious(state);
    }
    if (loadedBottomDistance <= threshold || shouldSeedWindow) {
      loadNext(state);
    }
  }

  function scheduleRefresh(state) {
    if (state.refreshFrame !== null) {
      return;
    }

    state.refreshFrame = window.requestAnimationFrame(() => refresh(state));
  }

  function initVirtualScroll(root) {
    const body = root.querySelector("[data-virtual-scroll-body]");
    if (!body) {
      return;
    }

    const initialRows = Array.from(body.querySelectorAll("tr[data-virtual-row]"));
    if (!initialRows.length) {
      return;
    }

    const surface = root.closest("[data-virtual-scroll-surface]");
    const pagination = surface ? surface.querySelector("[data-virtual-scroll-pagination]") : null;
    const colspan = Number.parseInt(root.dataset.virtualScrollColspan || "1", 10);
    const state = {
      root,
      body,
      fragmentUrl: root.dataset.virtualScrollUrl,
      totalRows: Math.max(0, Number.parseInt(root.dataset.virtualScrollTotalRows || "0", 10)),
      maxPages: Math.max(2, Number.parseInt(root.dataset.virtualScrollWindowPages || "8", 10)),
      averageRowHeight: 0,
      hiddenTopRows: 0,
      hiddenBottomRows: 0,
      topSpacer: buildSpacer(colspan, "top"),
      bottomSpacer: buildSpacer(colspan, "bottom"),
      pages: [],
      pageSequence: 1,
      loadingPrevious: false,
      loadingNext: false,
      refreshFrame: null,
    };

    body.prepend(state.topSpacer.row);
    body.append(state.bottomSpacer.row);
    initialRows.forEach((row) => {
      row.dataset.virtualPageKey = "page-0";
    });
    state.pages.push({
      key: "page-0",
      rowCount: initialRows.length,
      previousQuery: root.dataset.virtualScrollPreviousQuery || "",
      nextQuery: root.dataset.virtualScrollNextQuery || "",
    });
    updateAverageRowHeight(state, initialRows);
    state.hiddenBottomRows = Math.max(0, state.totalRows - initialRows.length);
    updateSpacers(state);

    root.dataset.virtualScrollReady = "true";
    if (pagination) {
      pagination.hidden = true;
    }

    root.addEventListener(
      "scroll",
      () => {
        scheduleRefresh(state);
      },
      { passive: true },
    );
    scheduleRefresh(state);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-virtual-scroll-root]").forEach((root) => {
      initVirtualScroll(root);
    });
  });
})();

(() => {
  const DEFAULT_IMPORT_REFRESH_MS = 5000;
  const MIN_IMPORT_REFRESH_MS = 3000;
  const FORM_CONTROL_SELECTOR = "input, textarea, select, button, [contenteditable='true']";

  function refreshInterval(marker) {
    const parsed = Number.parseInt(marker.dataset.refreshIntervalMs || "", 10);
    if (!Number.isFinite(parsed)) {
      return DEFAULT_IMPORT_REFRESH_MS;
    }
    return Math.max(MIN_IMPORT_REFRESH_MS, parsed);
  }

  function formControlHasFocus() {
    const activeElement = document.activeElement;
    return activeElement instanceof Element && activeElement.matches(FORM_CONTROL_SELECTOR);
  }

  function mountImportAutoRefresh() {
    const marker = document.querySelector("[data-import-auto-refresh]");
    if (!marker) {
      return;
    }

    window.setInterval(() => {
      if (document.hidden || formControlHasFocus()) {
        return;
      }
      window.location.reload();
    }, refreshInterval(marker));
  }

  document.addEventListener("DOMContentLoaded", () => {
    mountImportAutoRefresh();
  });
})();

(() => {
  const DEFAULT_SUMMARY_PAGE_SIZE = 25;

  function clamp(number, minimum, maximum) {
    return Math.min(Math.max(number, minimum), maximum);
  }

  function positiveInteger(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      return fallback;
    }
    return parsed;
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

  document.addEventListener("DOMContentLoaded", () => {
    mountSummaryTablePagination();
  });
})();
