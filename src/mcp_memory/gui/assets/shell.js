// ========================================
// PHASE 2: SHELL INTERACTIVITY
// ========================================

(function() {
  'use strict';

  // Theme toggle
  function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  }

  // Sidebar toggle
  function initSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
      const collapsed = localStorage.getItem('sidebar-collapsed') === 'true';
      if (collapsed) {
        sidebar.classList.add('collapsed');
      }
    }
  }

  function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
      sidebar.classList.toggle('collapsed');
      const isCollapsed = sidebar.classList.contains('collapsed');
      localStorage.setItem('sidebar-collapsed', isCollapsed);
    }
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      initTheme();
      initSidebar();
    });
  } else {
    initTheme();
    initSidebar();
  }

  // Global functions for onclick handlers
  window.toggleTheme = toggleTheme;
  window.toggleSidebar = toggleSidebar;
})();