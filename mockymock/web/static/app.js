/* Polls /api/status and paints it. The page holds no state of its own:
   every render is a pure function of the last payload, so adding a panel
   later means adding a render function and calling it from render().
   Two more panels sit beside it: the `mockymock report` pages found under
   the reports root (/api/reports, refreshed on a slower timer since it
   walks a directory tree), and the cobol-testing plugin's install check
   (/api/plugin) with its Install button (POST /api/plugin/install). */

(function () {
  "use strict";

  var POLL_MS = 5000;
  var REPORTS_EVERY = 3; // walk the reports tree every third status poll
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
    metaChecked: document.getElementById("meta-checked"),
    reportsRoot: document.getElementById("reports-root"),
    reports: document.getElementById("reports"),
    viewer: document.getElementById("viewer"),
    viewerTitle: document.getElementById("viewer-title"),
    viewerOpen: document.getElementById("viewer-open"),
    viewerFrame: document.getElementById("viewer-frame"),
    pluginVerdict: document.getElementById("plugin-verdict"),
    pluginSkills: document.getElementById("plugin-skills"),
    pluginInstall: document.getElementById("plugin-install"),
    pluginMessage: document.getElementById("plugin-message")
  };

  var timer = null;
  var polls = 0;
  var selectedReport = null;
  var lastPlugin = null;

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

  // --- test results ---------------------------------------------------

  function reportUrl(path) {
    return "/reports/" + path.split("/").map(encodeURIComponent).join("/");
  }

  function showReport(report) {
    selectedReport = report.path;
    var url = reportUrl(report.path);
    el.viewer.hidden = false;
    el.viewerTitle.textContent = report.program;
    el.viewerOpen.href = url;
    // Reloading the frame on every poll would reset its scroll position.
    if (el.viewerFrame.getAttribute("src") !== url) el.viewerFrame.src = url;
    var items = el.reports.querySelectorAll(".report-item");
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute("aria-current", String(items[i].dataset.path === report.path));
    }
  }

  function renderReports(payload) {
    el.reportsRoot.textContent = payload.root;
    el.reports.replaceChildren();
    if (!payload.reports.length) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent =
        "No test reports here yet. Run `mockymock report <program>` to write one " +
        "(<program>.report.html), or start the dashboard with --reports-dir.";
      el.reports.append(empty);
      el.viewer.hidden = true;
      selectedReport = null;
      return;
    }
    var keep = null;
    payload.reports.forEach(function (report) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "report-item";
      button.dataset.path = report.path;

      var copy = document.createElement("span");
      var name = document.createElement("span");
      name.className = "report-name";
      name.textContent = report.program;
      var path = document.createElement("span");
      path.className = "report-path";
      path.textContent = report.path;
      copy.append(name, path);

      var when = document.createElement("span");
      when.className = "report-when";
      var date = new Date(report.modified);
      when.textContent = isNaN(date) ? report.modified : date.toLocaleString();

      button.append(copy, when);
      button.addEventListener("click", function () { showReport(report); });
      item.append(button);
      el.reports.append(item);
      if (report.path === selectedReport) keep = report;
    });
    if (payload.truncated) {
      var more = document.createElement("li");
      more.className = "empty";
      more.textContent = "Showing the first " + payload.reports.length +
        " reports found; start the dashboard with --reports-dir to narrow the search.";
      el.reports.append(more);
    }
    // Newest first, so a fresh `mockymock report` run shows up selected
    // unless the user picked another one.
    showReport(keep || payload.reports[0]);
  }

  function loadReports() {
    return fetch("/api/reports", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(renderReports)
      .catch(function () { /* the status banner already reports a lost server */ });
  }

  // --- plugin -----------------------------------------------------------

  var SKILL_TONE = { ok: "ok", outdated: "warn", missing: "down", broken: "down" };

  function renderPlugin(payload) {
    lastPlugin = payload;
    var states = payload.skills.map(function (s) { return s.state; });
    var needsForce = states.some(function (s) { return s === "outdated" || s === "broken"; });
    var tone, verdict;
    if (payload.installed) {
      tone = "ok";
      verdict = "Installed and verified: all " + payload.skills.length +
        " skills match this mockymock, in " + payload.location + ".";
    } else if (states.every(function (s) { return s === "missing"; })) {
      tone = "down";
      verdict = "Not installed. Install copies the skills to " + payload.location +
        " (the same as `mockymock skills install`).";
    } else {
      tone = needsForce ? "warn" : "down";
      verdict = "Not fully installed: see the skills below.";
    }
    el.pluginVerdict.className = "plugin-verdict " + tone;
    el.pluginVerdict.textContent = verdict;

    el.pluginSkills.replaceChildren();
    payload.skills.forEach(function (skill) {
      var item = document.createElement("li");
      item.className = "check check--" + (SKILL_TONE[skill.state] || "unknown");
      var dot = document.createElement("span");
      dot.className = "check-dot";
      var copy = document.createElement("div");
      copy.className = "check-copy";
      var label = document.createElement("span");
      label.className = "check-label";
      label.textContent = skill.name + " — " + skill.state;
      var detail = document.createElement("span");
      detail.className = "check-detail";
      detail.textContent = skill.detail + " · " + skill.path;
      copy.append(label, detail);
      if (skill.differing && skill.differing.length) {
        var files = document.createElement("ul");
        files.className = "check-files";
        skill.differing.forEach(function (line) {
          var li = document.createElement("li");
          li.textContent = line;
          files.append(li);
        });
        copy.append(files);
      }
      item.append(dot, copy);
      el.pluginSkills.append(item);
    });

    el.pluginInstall.hidden = payload.installed;
    el.pluginInstall.textContent = needsForce ? "Reinstall plugin" : "Install plugin";
  }

  function loadPlugin() {
    return fetch("/api/plugin", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(renderPlugin)
      .catch(function (error) {
        el.pluginVerdict.className = "plugin-verdict down";
        el.pluginVerdict.textContent = "Could not check the plugin (" + error.message + ").";
      });
  }

  function showPluginMessage(text) {
    el.pluginMessage.hidden = !text;
    el.pluginMessage.textContent = text || "";
  }

  function installPlugin() {
    var force = false;
    if (lastPlugin) {
      var replaced = lastPlugin.skills.filter(function (s) {
        return s.state === "outdated" || s.state === "broken";
      });
      if (replaced.length) {
        var names = replaced.map(function (s) { return s.name; }).join(", ");
        if (!window.confirm(
          "Replace the installed " + names + " with this mockymock's copy? " +
          "Any local edits to those skills will be lost.")) return;
        force = true;
      }
    }
    el.pluginInstall.disabled = true;
    showPluginMessage("Installing…");
    fetch("/api/plugin/install", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: force })
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (result) {
        renderPlugin(result);
        var parts = [];
        if (result.written.length) parts.push("Installed " + result.written.join(", ") + ".");
        result.skipped.forEach(function (s) { parts.push(s.name + " left alone: " + s.reason + "."); });
        result.errors.forEach(function (e) { parts.push(e.name + " failed: " + e.error); });
        if (result.installed) {
          parts.push("Verified. Start a new Claude Code session to pick up the skills.");
        }
        showPluginMessage(parts.join(" "));
      })
      .catch(function (error) {
        showPluginMessage("Install failed (" + error.message + ").");
      })
      .finally(function () {
        el.pluginInstall.disabled = false;
      });
  }

  function tick() {
    refresh();
    polls += 1;
    if (polls % REPORTS_EVERY === 0) loadReports();
  }

  function refreshAll() {
    refresh();
    loadReports();
    loadPlugin();
  }

  function startPolling() {
    stopPolling();
    timer = setInterval(tick, POLL_MS);
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
      refreshAll();
      startPolling();
    }
  });

  el.refresh.addEventListener("click", refreshAll);
  el.pluginInstall.addEventListener("click", installPlugin);

  refreshAll();
  startPolling();
})();
