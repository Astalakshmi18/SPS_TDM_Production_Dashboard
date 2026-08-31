/* Swift Prosys — lightweight animation helpers, sidebar interactivity, real-time sync & React-like SPA router. */
(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function animateCount(el) {
    var raw = el.textContent.trim();
    var match = raw.match(/^([\d,]+(\.\d+)?)(%?)$/);
    if (!match) return;

    var target = parseFloat(match[1].replace(/,/g, ""));
    var suffix = match[3] || "";
    var isInt = !raw.includes(".");
    var duration = 800;
    var start = null;

    function step(ts) {
      if (start === null) start = ts;
      var progress = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = target * eased;
      el.textContent = (isInt ? Math.round(current).toLocaleString() : current.toFixed(2)) + suffix;
      if (progress < 1) requestAnimationFrame(step);
      else el.textContent = (isInt ? Math.round(target).toLocaleString() : target.toFixed(2)) + suffix;
    }
    requestAnimationFrame(step);
  }

  function initCounters() {
    if (prefersReducedMotion) return;
    document.querySelectorAll(".kpi-value").forEach(function (el) {
      animateCount(el);
    });
  }

  function initSidebarToggle() {
    var sidebar = document.querySelector(".sp-sidebar");
    if (!sidebar) return;

    function updateToggleState(collapsed) {
      var chevronBtns = document.querySelectorAll(".sp-toggle-btn");
      chevronBtns.forEach(function (btn) {
        var icon = btn.querySelector("i");
        if (icon) {
          if (collapsed) {
            icon.className = "bi bi-chevron-right text-white";
            btn.setAttribute("title", "Expand Sidebar (Ctrl+B)");
          } else {
            icon.className = "bi bi-chevron-left text-white";
            btn.setAttribute("title", "Collapse Sidebar (Ctrl+B)");
          }
        }
      });

      var desktopToggleText = document.getElementById("spDesktopNavToggleText");
      if (desktopToggleText) {
        desktopToggleText.textContent = collapsed ? "Show Nav" : "Hide Nav";
      }
    }

    function toggleSidebar() {
      var collapsed = sidebar.classList.toggle("sp-sidebar-collapsed");
      localStorage.setItem("spSidebarCollapsed", collapsed ? "true" : "false");
      updateToggleState(collapsed);
    }

    // Apply saved state on load
    var isCollapsed = localStorage.getItem("spSidebarCollapsed") === "true";
    if (isCollapsed) {
      sidebar.classList.add("sp-sidebar-collapsed");
      updateToggleState(true);
    }

    // Event delegation for toggle triggers
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".sp-toggle-btn");
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        toggleSidebar();
      }
    });

    // Keyboard shortcut (Ctrl+B or Cmd+B) to toggle navigation bar
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        var activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
        if (activeTag !== "input" && activeTag !== "textarea" && activeTag !== "select") {
          e.preventDefault();
          toggleSidebar();
        }
      }
    });

    // Auto-dismiss mobile offcanvas drawer on nav link click
    document.addEventListener("click", function (e) {
      var offcanvasLink = e.target.closest(".sp-offcanvas .nav-link");
      if (offcanvasLink) {
        var offcanvasEl = document.getElementById("spSidebarOffcanvas");
        if (offcanvasEl && typeof bootstrap !== "undefined" && bootstrap.Offcanvas) {
          var bsOffcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
          if (bsOffcanvas) {
            bsOffcanvas.hide();
          }
        }
      }
    });
  }

  // Real-time Background Data Polling & Hot Update without page reload
  function initRealtimeSync() {
    var lastUpdatedEl = document.getElementById("spLastUpdated");
    if (!lastUpdatedEl) return;

    function syncDashboardData() {
      var currentUrl = window.location.pathname + window.location.search;
      var fetchUrl = currentUrl + (currentUrl.includes('?') ? '&' : '?') + 'format=json';

      fetch(fetchUrl, {
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
      .then(function(res) {
        if (!res.ok) throw new Error("Sync failed");
        return res.json();
      })
      .then(function(data) {
        if (!data || !data.kpis) return;

        // 1. Update KPI numbers live with smooth count animation
        Object.keys(data.kpis).forEach(function(key) {
          if (key === 'last_updated') {
            if (lastUpdatedEl && data.kpis.last_updated) {
              lastUpdatedEl.textContent = data.kpis.last_updated;
            }
            return;
          }

          var kpiEl = document.querySelector('[data-kpi="' + key + '"]');
          if (kpiEl) {
            var val = data.kpis[key];
            var suffix = (key.endsWith('_pct')) ? '%' : '';
            var formatted = (typeof val === 'number' && !key.endsWith('_pct')) ? val.toLocaleString() : val + suffix;

            if (kpiEl.textContent.trim() !== formatted) {
              kpiEl.textContent = formatted;
              if (!prefersReducedMotion) {
                animateCount(kpiEl);
              }
            }
          }
        });

        // 2. Live Chart.js datasets update if charts are active
        if (window.branchChart && data.branch_chart) {
          window.branchChart.data.labels = data.branch_chart.labels;
          window.branchChart.data.datasets[0].data = data.branch_chart.target;
          window.branchChart.data.datasets[1].data = data.branch_chart.delivered;
          window.branchChart.update('none');
        }

        if (window.completionChart && data.completion_chart) {
          window.completionChart.data.datasets[0].data = [
            data.completion_chart.delivered,
            data.completion_chart.remaining
          ];
          window.completionChart.update('none');
        }
      })
      .catch(function(err) {
        // Silent catch for background sync network fluctuations
      });
    }

    // Auto-poll every 15 seconds in the background
    setInterval(syncDashboardData, 15000);
  }

  // React-like Single Page Application (SPA) Router Engine
  function updateActiveSidebarLink(url) {
    var links = document.querySelectorAll(".sp-sidebar .nav-link, .sp-offcanvas .nav-link");
    try {
      var targetPath = new URL(url, window.location.origin).pathname;
      links.forEach(function (link) {
        var href = link.getAttribute("href");
        if (!href) return;
        var linkPath = new URL(href, window.location.origin).pathname;
        if (linkPath === targetPath) {
          link.classList.add("active");
        } else {
          link.classList.remove("active");
        }
      });
    } catch (err) {}
  }

  function loadSpaPage(url, pushState) {
    // Clean up modal backdrops and body lock states before content swapping
    document.querySelectorAll(".modal-backdrop").forEach(function(b) { b.remove(); });
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");

    var contentEl = document.querySelector(".sp-content");
    if (!contentEl) return;

    contentEl.style.opacity = "0.55";

    fetch(url, {
      headers: {
        "X-Requested-With": "XMLHttpRequest"
      }
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Failed to load page");
        return res.text();
      })
      .then(function (html) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, "text/html");

        var newContent = doc.querySelector(".sp-content");
        if (newContent) {
          contentEl.innerHTML = newContent.innerHTML;
          contentEl.style.opacity = "1";

          contentEl.classList.remove("sp-fade-in");
          void contentEl.offsetWidth; // trigger reflow
          contentEl.classList.add("sp-fade-in");

          if (doc.title) {
            document.title = doc.title;
          }

          if (pushState) {
            window.history.pushState({ url: url }, "", url);
          }

          updateActiveSidebarLink(url);

          // Re-execute scripts inside newly fetched page content (e.g., Chart initializers)
          var scripts = newContent.querySelectorAll("script");
          scripts.forEach(function (oldScript) {
            var newScript = document.createElement("script");
            Array.from(oldScript.attributes).forEach(function (attr) {
              newScript.setAttribute(attr.name, attr.value);
            });
            newScript.textContent = oldScript.textContent;
            document.body.appendChild(newScript);
          });

          // Re-initialize UI counters & tooltips
          initCounters();
          initTooltips();
          window.scrollTo({ top: 0, behavior: "instant" });
        } else {
          window.location.href = url;
        }
      })
      .catch(function () {
        window.location.href = url;
      });
  }

  function initSpaRouter() {
    document.addEventListener("click", function (e) {
      var link = e.target.closest(".sp-sidebar .nav-link, .sp-offcanvas .nav-link, a.sp-project-link");
      if (!link) return;

      var href = link.getAttribute("href");
      if (!href || href === "#" || href.startsWith("javascript:")) return;
      if (href.includes("/accounts/logout/") || href.startsWith("http://") || href.startsWith("https://")) return;

      e.preventDefault();
      loadSpaPage(href, true);
    });

    window.addEventListener("popstate", function () {
      loadSpaPage(window.location.href, false);
    });
  }

  // Hot CSS & Theme Style Reloading Helper
  function initHotStyleSync() {
    window.spReloadStyles = function() {
      var links = document.querySelectorAll('link[rel="stylesheet"]');
      links.forEach(function(link) {
        var href = link.getAttribute('href');
        if (href && href.includes('dashboard.css')) {
          var cleanHref = href.split('?')[0];
          link.setAttribute('href', cleanHref + '?v=' + new Date().getTime());
        }
      });
    };
  }

  function initTooltips() {
    if (typeof bootstrap !== "undefined" && bootstrap.Tooltip) {
      var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
      tooltipTriggerList.forEach(function (tooltipTriggerEl) {
        new bootstrap.Tooltip(tooltipTriggerEl, { trigger: 'hover' });
      });
    }
  }

  function initFadeInOnScroll() {
    if (!("IntersectionObserver" in window) || prefersReducedMotion) return;
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("sp-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });
    document.querySelectorAll(".sp-panel, .kpi-card").forEach(function (el) {
      observer.observe(el);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCounters();
    initSidebarToggle();
    initRealtimeSync();
    initSpaRouter();
    initHotStyleSync();
    initTooltips();
    initFadeInOnScroll();
  });
})();
