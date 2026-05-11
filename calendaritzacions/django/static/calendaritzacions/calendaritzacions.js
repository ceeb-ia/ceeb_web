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
    if (payload.is_finished && !hasReloaded) {
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
