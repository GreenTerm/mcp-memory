(() => {
  const storage = window.localStorage;
  const root = document.documentElement;

  const applyTheme = (theme) => {
    const nextTheme = theme === "light" ? "light" : "dark";
    root.dataset.theme = nextTheme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(nextTheme === "light"));
    });
  };

  const savedTheme = storage.getItem("mcp-memory-theme");
  if (savedTheme) {
    applyTheme(savedTheme);
  }

  const closeConstructorRoleMenus = (except) => {
    document.querySelectorAll(".constructor-role-menu[open]").forEach((menu) => {
      if (menu !== except) {
        menu.open = false;
      }
    });
  };

  document.addEventListener("click", async (event) => {
    const roleMenu = event.target.closest(".constructor-role-menu");
    closeConstructorRoleMenus(roleMenu);

    const themeToggle = event.target.closest("[data-theme-toggle]");
    if (themeToggle) {
      const nextTheme = root.dataset.theme === "light" ? "dark" : "light";
      storage.setItem("mcp-memory-theme", nextTheme);
      applyTheme(nextTheme);
      return;
    }

    const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) {
      const collapsed = document.body.classList.toggle("sidebar-collapsed");
      storage.setItem("mcp-memory-sidebar-collapsed", collapsed ? "1" : "0");
      sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
      return;
    }

    const copyButton = event.target.closest("[data-copy-target]");
    if (!copyButton) {
      return;
    }

    const target = document.querySelector(copyButton.dataset.copyTarget);
    const text = target ? target.textContent.trim() : copyButton.dataset.copyText || "";
    if (!text || !navigator.clipboard) {
      return;
    }

    await navigator.clipboard.writeText(text);
    const previousLabel = copyButton.textContent;
    copyButton.textContent = copyButton.dataset.copiedLabel || "Copied";
    window.setTimeout(() => {
      copyButton.textContent = previousLabel;
    }, 1400);
  });

  if (storage.getItem("mcp-memory-sidebar-collapsed") === "1") {
    document.body.classList.add("sidebar-collapsed");
    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.setAttribute("aria-expanded", "false");
    });
  }

  const initGraphCanvas = (canvas) => {
    const graphHost = canvas.querySelector("[data-graph-cytoscape]");
    const elementsScript = canvas.querySelector("[data-graph-elements]");
    if (!graphHost || !elementsScript || !window.cytoscape) {
      return;
    }

    const colors = getComputedStyle(document.documentElement);
    const color = (name) => colors.getPropertyValue(name).trim();
    const elements = JSON.parse(elementsScript.textContent || "[]");
    const layoutOptions = [
      {
        key: "force",
        label: "Force",
        options: {
          name: elements.length > 1 ? "cose" : "grid",
          animate: false,
          componentSpacing: 80,
          idealEdgeLength: 130,
          nodeOverlap: 18,
          nodeRepulsion: 7000,
          padding: 48,
          randomize: false,
        },
      },
      {
        key: "tree",
        label: "Tree",
        options: {
          name: "breadthfirst",
          animate: false,
          directed: true,
          grid: false,
          padding: 48,
          spacingFactor: 1.15,
        },
      },
      {
        key: "circle",
        label: "Circle",
        options: {
          name: "circle",
          animate: false,
          padding: 48,
        },
      },
      {
        key: "grid",
        label: "Grid",
        options: {
          name: "grid",
          animate: false,
          padding: 48,
        },
      },
      {
        key: "radial",
        label: "Radial",
        options: {
          name: "concentric",
          animate: false,
          minNodeSpacing: 48,
          padding: 48,
        },
      },
    ];
    const layoutByKey = new Map(layoutOptions.map((layout) => [layout.key, layout]));
    const layoutSelect = canvas.querySelector("[data-graph-layout-select]");
    const workspacePrefixIndex = window.location.pathname.indexOf("/ui/");
    const workspacePrefix = workspacePrefixIndex > 0 ? window.location.pathname.slice(0, workspacePrefixIndex) : "";
    const normalizeGraphHref = (href) => {
      if (!href || !href.startsWith("/ui/") || !workspacePrefix || href.startsWith(`${workspacePrefix}/ui/`)) {
        return href;
      }
      return `${workspacePrefix}${href}`;
    };
    const clampScale = (value) => Math.min(2.8, Math.max(0.45, value));
    const updateViewportState = (cy) => {
      const pan = cy.pan();
      canvas.dataset.graphZoom = cy.zoom().toFixed(3);
      canvas.dataset.graphPanX = pan.x.toFixed(1);
      canvas.dataset.graphPanY = pan.y.toFixed(1);
    };
    const viewportCenter = () => ({
      x: graphHost.clientWidth / 2,
      y: graphHost.clientHeight / 2,
    });
    const cy = window.cytoscape({
      container: graphHost,
      elements,
      autoungrabify: true,
      minZoom: 0.45,
      maxZoom: 2.8,
      wheelSensitivity: 0.16,
      boxSelectionEnabled: false,
      userPanningEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "background-color": color("--panel-strong"),
            "border-color": color("--accent"),
            "border-width": 2,
            "color": color("--ink-soft"),
            "font-family": "Segoe UI, Inter, Aptos, Tahoma, sans-serif",
            "font-size": 12,
            "height": 48,
            "label": "data(label)",
            "text-halign": "center",
            "text-margin-y": 8,
            "text-max-width": 110,
            "text-valign": "bottom",
            "text-wrap": "ellipsis",
            "width": 48,
          },
        },
        {
          selector: 'node[entityType = "structure"]',
          style: { "border-color": color("--success") },
        },
        {
          selector: 'node[entityType = "global_hypothesis"], node[entityType = "hypothesis"]',
          style: { "border-color": color("--warning") },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "font-size": 10,
            "label": "data(label)",
            "line-color": color("--border-strong"),
            "target-arrow-color": color("--border-strong"),
            "target-arrow-shape": "triangle",
            "text-background-color": color("--panel"),
            "text-background-opacity": 0.72,
            "text-background-padding": 2,
            "text-rotation": "autorotate",
            "width": 1.4,
            "color": color("--muted"),
          },
        },
        {
          selector: ".dimmed",
          style: { opacity: 0.18 },
        },
        {
          selector: ".connected",
          style: {
            opacity: 1,
            "line-color": color("--accent"),
            "target-arrow-color": color("--accent"),
            "width": 2.2,
          },
        },
        {
          selector: "node.connected",
          style: {
            "background-color": color("--panel-strong"),
            "border-width": 3,
          },
        },
      ],
      layout: layoutOptions[0].options,
    });
    canvas.__graphCy = cy;
    let activeNodeId = "";
    let clearActiveTimer = 0;
    let layoutKey = layoutOptions[0].key;
    const panState = {
      active: false,
      moved: false,
      lastX: 0,
      lastY: 0,
      pointerId: null,
      suppressTap: false,
    };

    const animateGraph = (params, duration) => {
      cy.stop();
      cy.animate(params, {
        duration,
        easing: "ease-in-out-cubic",
        complete: () => updateViewportState(cy),
      });
    };
    const zoomBy = (factor) => {
      animateGraph(
        {
          zoom: {
            level: clampScale(cy.zoom() * factor),
            renderedPosition: viewportCenter(),
          },
        },
        160,
      );
    };
    const reset = () => {
      animateGraph({ fit: { eles: cy.elements(), padding: 48 } }, 220);
    };
    const updateLayoutControl = () => {
      const layout = layoutByKey.get(layoutKey) || layoutOptions[0];
      canvas.dataset.graphLayout = layout.key;
      if (layoutSelect) {
        layoutSelect.value = layout.key;
        layoutSelect.setAttribute("title", `Graph layout: ${layout.label}`);
      }
    };
    const animatedLayoutOptions = (layout) =>
      Object.assign({}, layout.options, {
        animate: true,
        animationDuration: 320,
        animationEasing: "ease-in-out-cubic",
      });
    const runLayout = (nextKey) => {
      const layout = layoutByKey.get(nextKey) || layoutOptions[0];
      layoutKey = layout.key;
      canvas.classList.add("is-changing-layout");
      const activeLayout = cy.layout(animatedLayoutOptions(layout));
      activeLayout.run();
      window.setTimeout(() => {
        reset();
        canvas.classList.remove("is-changing-layout");
      }, 340);
      updateLayoutControl();
    };
    const updateFullscreenButton = () => {
      const isFullscreen = canvas.classList.contains("is-fullscreen") || document.fullscreenElement === canvas;
      canvas.dataset.graphFullscreen = isFullscreen ? "true" : "false";
      canvas.querySelectorAll('[data-graph-action="fullscreen"]').forEach((button) => {
        button.textContent = isFullscreen ? "Exit" : "Full";
        button.setAttribute("title", isFullscreen ? "Exit full screen" : "Expand graph");
        button.setAttribute("aria-label", isFullscreen ? "Exit full screen" : "Expand graph");
      });
    };
    const resizeAndFit = () => {
      cy.resize();
      reset();
    };
    const applyFullscreenState = (enabled) => {
      if (enabled === canvas.classList.contains("is-fullscreen")) {
        updateFullscreenButton();
        return;
      }
      if (enabled) {
        canvas.classList.add("is-fullscreen");
        document.body.classList.add("graph-fullscreen-open");
        updateFullscreenButton();
        window.setTimeout(resizeAndFit, 190);
        return;
      }
      canvas.classList.add("is-closing");
      document.body.classList.remove("graph-fullscreen-open");
      window.setTimeout(() => {
        canvas.classList.remove("is-fullscreen", "is-closing");
        updateFullscreenButton();
        resizeAndFit();
      }, 170);
    };
    const setFullscreen = (enabled) => {
      if (enabled) {
        if (canvas.requestFullscreen) {
          canvas.requestFullscreen().catch(() => applyFullscreenState(true));
        } else {
          applyFullscreenState(true);
        }
        return;
      }
      if (document.fullscreenElement === canvas && document.exitFullscreen) {
        document.exitFullscreen();
      } else {
        applyFullscreenState(false);
      }
    };
    const setActiveNode = (node) => {
      if (clearActiveTimer) {
        window.clearTimeout(clearActiveTimer);
        clearActiveTimer = 0;
      }
      const nodeId = node ? node.id() : "";
      if (nodeId === activeNodeId) {
        return;
      }
      activeNodeId = nodeId;
      cy.elements().removeClass("dimmed connected");
      canvas.classList.toggle("has-active-node", Boolean(node));
      if (!node) {
        return;
      }
      const connected = node.closedNeighborhood();
      cy.elements().difference(connected).addClass("dimmed");
      connected.addClass("connected");
    };
    const clearActiveNode = () => {
      if (clearActiveTimer) {
        window.clearTimeout(clearActiveTimer);
      }
      clearActiveTimer = window.setTimeout(() => setActiveNode(null), 90);
    };

    canvas.querySelectorAll("[data-graph-action]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.graphAction === "zoom-in") {
          zoomBy(1.18);
        } else if (button.dataset.graphAction === "zoom-out") {
          zoomBy(0.85);
        } else if (button.dataset.graphAction === "reset") {
          reset();
        } else if (button.dataset.graphAction === "fullscreen") {
          setFullscreen(!canvas.classList.contains("is-fullscreen"));
        }
      });
    });
    if (layoutSelect) {
      layoutSelect.addEventListener("change", () => runLayout(layoutSelect.value));
    }

    cy.on("pan zoom", () => updateViewportState(cy));
    cy.on("mouseover", "node", (event) => setActiveNode(event.target));
    cy.on("mouseout", "node", clearActiveNode);
    cy.on("tap", "node", (event) => {
      if (panState.suppressTap) {
        panState.suppressTap = false;
        return;
      }
      const href = event.target.data("href");
      if (href) {
        window.location.href = normalizeGraphHref(href);
      }
    });
    cy.ready(() => {
      cy.fit(cy.elements(), 48);
      updateViewportState(cy);
      updateLayoutControl();
      updateFullscreenButton();
    });
    window.addEventListener("resize", () => {
      cy.resize();
      updateViewportState(cy);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && canvas.classList.contains("is-fullscreen")) {
        setFullscreen(false);
      }
    });
    document.addEventListener("fullscreenchange", () => {
      applyFullscreenState(document.fullscreenElement === canvas);
    });
    graphHost.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }
      panState.active = true;
      panState.moved = false;
      panState.lastX = event.clientX;
      panState.lastY = event.clientY;
      panState.pointerId = event.pointerId;
      canvas.classList.add("is-panning");
      graphHost.setPointerCapture(event.pointerId);
    });
    graphHost.addEventListener("pointermove", (event) => {
      if (!panState.active) {
        return;
      }
      const deltaX = event.clientX - panState.lastX;
      const deltaY = event.clientY - panState.lastY;
      panState.moved = panState.moved || Math.abs(deltaX) > 2 || Math.abs(deltaY) > 2;
      panState.lastX = event.clientX;
      panState.lastY = event.clientY;
      if (!panState.moved) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      cy.panBy({ x: deltaX, y: deltaY });
      updateViewportState(cy);
    });
    const finishPan = (event) => {
      if (!panState.active) {
        return;
      }
      panState.active = false;
      panState.suppressTap = panState.suppressTap || panState.moved;
      canvas.classList.remove("is-panning");
      const pointerId = event && Number.isInteger(event.pointerId) ? event.pointerId : panState.pointerId;
      panState.pointerId = null;
      if (pointerId !== null && graphHost.hasPointerCapture(pointerId)) {
        graphHost.releasePointerCapture(pointerId);
      }
    };
    graphHost.addEventListener("pointerup", finishPan);
    graphHost.addEventListener("pointercancel", finishPan);
    graphHost.addEventListener("lostpointercapture", finishPan);
    graphHost.addEventListener(
      "click",
      (event) => {
        if (!panState.suppressTap) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        window.setTimeout(() => {
          panState.suppressTap = false;
        }, 0);
      },
      true,
    );
    canvas.addEventListener("dragstart", (event) => event.preventDefault());
    canvas.addEventListener("selectstart", (event) => event.preventDefault());
  };

  document.querySelectorAll("[data-graph-canvas]").forEach(initGraphCanvas);
})();
