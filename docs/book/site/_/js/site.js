/* Docling-pipelines Documentation — Site JS */

(function () {
  'use strict';

  // ── Highlight.js ───────────────────────────────────────────────────────────
  if (window.hljs) {
    hljs.configure({ ignoreUnescapedHTML: true });
    document.querySelectorAll('pre code').forEach(function (block) {
      hljs.highlightElement(block);
    });
  }

  // ── Build Table of Contents ───────────────────────────────────────────────
  (function () {
    var tocNav = document.querySelector('.toc-nav');
    if (!tocNav) return;

    var tocMenu = tocNav.querySelector('.toc-menu') || tocNav;
    var headings = document.querySelectorAll('.doc h2, .doc h3');
    var validHeadings = [];

    headings.forEach(function (h) {
      if (h.id && h.id !== '_chapters') {
        validHeadings.push(h);
      }
    });

    if (validHeadings.length <= 1) {
      tocNav.style.display = 'none';
      return;
    }

    tocNav.style.display = '';
    tocMenu.innerHTML = '';

    validHeadings.forEach(function (h) {
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = h.textContent.trim();
      var tag = h.tagName.toLowerCase();
      if (tag === 'h2') {
        a.classList.add('toc-h2');
      } else if (tag === 'h3') {
        a.classList.add('toc-h3');
      } else if (tag === 'h4') {
        a.classList.add('toc-h4');
      }
      tocMenu.appendChild(a);
    });

    // ── Active TOC link on scroll ────────────────────────────────────────────
    var tocLinks = tocNav.querySelectorAll('a');
    if (tocLinks.length && validHeadings.length) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var id = entry.target.id;
            tocLinks.forEach(function (a) {
              a.classList.toggle('is-active', a.getAttribute('href') === '#' + id);
            });
          }
        });
      }, { rootMargin: '-60px 0px -70% 0px' });

      validHeadings.forEach(function (h) { observer.observe(h); });
    }
  }());

  // ── Keyboard shortcut: / focuses search (future) ──────────────────────────
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault();
      var searchInput = document.getElementById('search-input');
      if (searchInput) searchInput.focus();
    }
  });

  // ── Copy button on code blocks ─────────────────────────────────────────────
  document.querySelectorAll('pre').forEach(function (pre) {
    var btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.title = 'Copy to clipboard';
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
    pre.style.position = 'relative';
    pre.appendChild(btn);

    btn.addEventListener('click', function () {
      var code = pre.querySelector('code');
      if (code) {
        navigator.clipboard.writeText(code.innerText).then(function () {
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
          setTimeout(function () {
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
          }, 1800);
        });
      }
    });
  });
})();
