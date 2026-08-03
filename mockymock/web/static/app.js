/* Polls /api/status and paints it. The page holds no state of its own:
   every render is a pure function of the last payload, so adding a panel
   later means adding a render function and calling it from render(). */

(function () {
  "use strict";

  var POLL_MS = 5000;
  var STATE_RANK = { down: 0, warn: 1, unknown: 2, ok: 3 };

  var el = {
    pollDot: document.getElementById("poll-dot"),
    pollText: document.getElementById("poll-text"),
    banner: document.getElementById("banner"),
    bannerTitle: document.getElementById("banner-title"),
    bannerSubtitle: document.getElementById("banner-subtitle"),
    checks: document.getElementById("checks"),
    refresh: document.getElementById("refresh"),
    metaImage: document.getElementById("meta-image"),
    metaContainer: document.getElementById("meta-container"),
    metaCobc: document.getElementById("meta-cobc"),
    metaChecked: document.getElementById("meta-checked")
  };

  var timer = null;

  function byId(checks, id) {
    for (var i = 0; i < checks.length; i++) {
      if (checks[i].id === id) return checks[i];
    }
    return null;
  }

  function worstState(checks) {
    var worst = "ok";
    for (var i = 0; i < checks.length; i++) {
      if (STATE_RANK[checks[i].state] < STATE_RANK[worst]) worst = checks[i].state;
    }
    return worst;
  }

  function renderBanner(status) {
    var daemon = byId(status.checks, "daemon");
    var daemonUp = daemon && daemon.state === "ok";
    var tone, title, subtitle;

    if (status.ready) {
      tone = "ok";
      title = "Docker is running";
      subtitle = "Toolchain ready — mockymock run will work.";
    } else if (!daemonUp) {
      tone = "down";
      title = "Docker is not running";
      subtitle = daemon ? daemon.detail : "The Docker daemon is unreachable.";
    } else {
      // Daemon is fine; something further down the lifecycle isn't.
      var worst = worstState(status.checks);
      tone = worst === "ok" ? "warn" : worst;
      title = "Docker is running";
      subtitle = "The toolchain isn't ready yet — run `mockymock setup`.";
    }

    el.banner.className = "banner banner--" + tone;
    el.bannerTitle.textContent = title;
    el.bannerSubtitle.textContent = subtitle;
  }

  function renderChecks(status) {
    el.checks.replaceChildren();
    status.checks.forEach(function (check) {
      var item = document.createElement("li");
      item.className = "check check--" + check.state;

      var dot = document.createElement("span");
      dot.className = "check-dot";

      var copy = document.createElement("div");
      copy.className = "check-copy";

      var label = document.createElement("span");
      label.className = "check-label";
      label.textContent = check.label;

      var detail = document.createElement("span");
      detail.className = "check-detail";
      detail.textContent = check.detail;

      copy.append(label, detail);
      item.append(dot, copy);
      el.checks.append(item);
    });
  }

  function renderMeta(status) {
    el.metaImage.textContent = status.image;
    el.metaContainer.textContent = status.container;
    el.metaCobc.textContent = status.cobc_version || "unavailable";
    var when = new Date(status.checked_at);
    el.metaChecked.textContent = isNaN(when) ? status.checked_at : when.toLocaleTimeString();
  }

  function render(status) {
    renderBanner(status);
    renderChecks(status);
    renderMeta(status);
  }

  function renderServerLost(error) {
    el.banner.className = "banner banner--down";
    el.bannerTitle.textContent = "Dashboard disconnected";
    el.bannerSubtitle.textContent =
      "Can't reach the mockymock dashboard server — it may have stopped. (" + error + ")";
  }

  function setPoll(state, text) {
    el.pollDot.className = "poll-dot " + state;
    el.pollText.textContent = text;
  }

  function refresh() {
    el.refresh.disabled = true;
    return fetch("/api/status", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (status) {
        render(status);
        setPoll("live", "live");
      })
      .catch(function (error) {
        renderServerLost(error.message);
        setPoll("lost", "disconnected");
      })
      .finally(function () {
        el.refresh.disabled = false;
      });
  }

  function startPolling() {
    stopPolling();
    timer = setInterval(refresh, POLL_MS);
  }

  function stopPolling() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  // Each poll shells out to `docker` three or four times, so a background
  // tab shouldn't keep doing it.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
      setPoll("", "paused");
    } else {
      refresh();
      startPolling();
    }
  });

  el.refresh.addEventListener("click", refresh);

  refresh();
  startPolling();
})();
