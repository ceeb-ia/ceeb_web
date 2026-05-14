(function () {
  const liveToolbar = document.querySelector("[data-calendaritzacions-live='1']");
  if (!liveToolbar) {
    return;
  }

  const statusUrl = liveToolbar.dataset.statusUrl;
  const badge = document.querySelector("[data-status-badge]");
  const progressText = document.querySelector("[data-progress-text]");
  const progressBar = document.querySelector("[data-progress-bar]");
  const logsPanel = document.querySelector("[data-logs-panel]");
  const componentRunsBody = document.querySelector("[data-component-runs-body]");
  const initialAuditCount = parseInt(liveToolbar.dataset.initialAuditCount || "0", 10) || 0;
  const initialPlotCount = parseInt(liveToolbar.dataset.initialPlotCount || "0", 10) || 0;
  let hasReloaded = false;

  function statusPollUrl() {
    const url = new URL(statusUrl, window.location.href);
    url.searchParams.set("_", Date.now().toString());
    return url.toString();
  }

  function badgeClass(status) {
    if (status === "success") return "badge badge-success";
    if (status === "error") return "badge badge-danger";
    if (status === "running") return "badge badge-warning";
    return "badge badge-secondary";
  }

  function renderStatus(payload) {
    if (badge && payload.status) {
      badge.textContent = payload.status;
      badge.className = badgeClass(payload.status);
    }
    if (progressText) {
      progressText.textContent = Number.isInteger(payload.progress) ? `${payload.progress}%` : "";
    }
    if (progressBar && Number.isInteger(payload.progress)) {
      progressBar.style.width = `${Math.max(0, Math.min(100, payload.progress))}%`;
    }
    if (logsPanel && Array.isArray(payload.logs) && payload.logs.length) {
      logsPanel.textContent = payload.logs.join("\n");
      logsPanel.scrollTop = logsPanel.scrollHeight;
    }
    if (componentRunsBody && Array.isArray(payload.components)) {
      componentRunsBody.replaceChildren();
      payload.components.forEach(function (component) {
        const row = document.createElement("tr");
        [
          component.component_id || "",
          component.status || "",
          `${component.attempt || ""}/${component.active_attempt || ""}`,
          component.team_count || 0,
          component.candidate_count || 0,
          component.heartbeat_at || "-",
          component.finished_at || "-",
        ].forEach(function (value, index) {
          const cell = document.createElement("td");
          cell.textContent = String(value);
          if (index === 0) cell.className = "font-weight-bold";
          if (index >= 5) cell.className = "small";
          row.appendChild(cell);
        });
        const logsCell = document.createElement("td");
        const logs = Array.isArray(component.logs_tail) ? component.logs_tail : [];
        if (logs.length || component.error_message) {
          const pre = document.createElement("pre");
          pre.className = "mb-0 calendaritzacions-pre small";
          pre.textContent = logs.length ? logs.join("\n") : component.error_message;
          logsCell.appendChild(pre);
        } else {
          const empty = document.createElement("span");
          empty.className = "text-muted small";
          empty.textContent = "-";
          logsCell.appendChild(empty);
        }
        row.appendChild(logsCell);
        componentRunsBody.appendChild(row);
      });
    }
    const auditCount = Array.isArray(payload.audits) ? payload.audits.length : initialAuditCount;
    const plotCount = Array.isArray(payload.plot_galleries)
      ? payload.plot_galleries.reduce(function (count, gallery) {
          return count + (Array.isArray(gallery.plots) ? gallery.plots.length : 0);
        }, 0)
      : initialPlotCount;
    if ((payload.is_finished || auditCount > initialAuditCount || plotCount > initialPlotCount) && !hasReloaded) {
      hasReloaded = true;
      window.setTimeout(function () {
        window.location.reload();
      }, 800);
    }
  }

  function pollStatus() {
    fetch(statusPollUrl(), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        return response.json();
      })
      .then(renderStatus)
      .catch(function () {
        return null;
      })
      .finally(function () {
        if (!hasReloaded) {
          window.setTimeout(pollStatus, 2500);
        }
      });
  }

  pollStatus();
})();
