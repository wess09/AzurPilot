/**
 * Alas WebUI Utilities
 * 公告弹窗、截图查看器、自动刷新等前端功能
 * 从 app.py run_js() 运行时注入迁移为静态加载
 */

// ============================================================
// 自动刷新（断连后自动 reload）
// [For develop] Disable by run `reload=0` in console
// ============================================================
(function () {
    window.reload = 1;
    if (window.WebIO && WebIO._state && WebIO._state.CurrentSession) {
        WebIO._state.CurrentSession.on_session_close(function () {
            setTimeout(function () {
                if (window.reload == 1) {
                    location.reload();
                }
            }, 4000);
        });
    }
})();

// ============================================================
// 截图查看器（点击截图放大、缩放、拖拽）
// ============================================================
(function () {
    function sanitizeUrl(url) {
        if (!url) return '';
        var protocol = url.split(':')[0].toLowerCase().trim();
        if (['javascript', 'data', 'vbscript'].indexOf(protocol) !== -1) {
            // Only allow data:image/ for base64 images
            if (url.startsWith('data:image/')) return url;
            return '';
        }
        return url;
    }

    function ensureScreenshotModal() {
        if (document.getElementById('screenshot-modal')) return;
        var modal = document.createElement('div');
        modal.id = 'screenshot-modal';
        Object.assign(modal.style, {
            position: 'fixed',
            left: 0,
            top: 0,
            width: '100vw',
            height: '100vh',
            display: 'none',
            justifyContent: 'center',
            alignItems: 'center',
            background: 'rgba(0,0,0,0.65)',
            zIndex: 99999,
            overflow: 'hidden',
            padding: '20px',
            boxSizing: 'border-box',
            cursor: 'grab'
        });
        var modalImg = document.createElement('img');
        modalImg.id = 'screenshot-modal-img';
        Object.assign(modalImg.style, {
            maxWidth: '100%',
            maxHeight: '90vh',
            objectFit: 'contain',
            boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
            transition: 'transform 0.05s linear',
            transformOrigin: 'center center',
            willChange: 'transform'
        });
        modal.appendChild(modalImg);

        modal.dataset.scale = 1;
        modal.dataset.tx = 0;
        modal.dataset.ty = 0;
        modal.dataset.panning = 0;

        function applyTransform() {
            var s = parseFloat(modal.dataset.scale) || 1;
            var tx = parseFloat(modal.dataset.tx) || 0;
            var ty = parseFloat(modal.dataset.ty) || 0;
            modalImg.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + s + ')';
        }

        modal.addEventListener('wheel', function (e) {
            if (e.ctrlKey) return;
            e.preventDefault();
            var rect = modalImg.getBoundingClientRect();
            var cx = e.clientX - (rect.left + rect.width / 2);
            var cy = e.clientY - (rect.top + rect.height / 2);
            var scale = parseFloat(modal.dataset.scale) || 1;
            var delta = -e.deltaY;
            var factor = delta > 0 ? 1.12 : 0.88;
            var newScale = Math.min(6, Math.max(0.3, scale * factor));

            var tx = parseFloat(modal.dataset.tx) || 0;
            var ty = parseFloat(modal.dataset.ty) || 0;
            modal.dataset.tx = tx - cx * (newScale - scale);
            modal.dataset.ty = ty - cy * (newScale - scale);
            modal.dataset.scale = newScale;
            applyTransform();
        }, { passive: false });

        var start = { x: 0, y: 0 };
        modalImg.addEventListener('mousedown', function (e) {
            e.preventDefault();
            modal.dataset.panning = 1;
            start.x = e.clientX;
            start.y = e.clientY;
            modal.style.cursor = 'grabbing';
        });
        window.addEventListener('mousemove', function (e) {
            if (modal.dataset.panning !== '1') return;
            var dx = e.clientX - start.x;
            var dy = e.clientY - start.y;
            start.x = e.clientX;
            start.y = e.clientY;
            modal.dataset.tx = (parseFloat(modal.dataset.tx) || 0) + dx;
            modal.dataset.ty = (parseFloat(modal.dataset.ty) || 0) + dy;
            applyTransform();
        });
        window.addEventListener('mouseup', function (e) {
            if (modal.dataset.panning === '1') {
                modal.dataset.panning = 0;
                modal.style.cursor = 'grab';
            }
        });

        modalImg.addEventListener('dblclick', function (e) {
            modal.dataset.scale = 1;
            modal.dataset.tx = 0;
            modal.dataset.ty = 0;
            applyTransform();
        });

        modal.addEventListener('click', function (e) {
            if (e.target === modal) modal.style.display = 'none';
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                var m = document.getElementById('screenshot-modal');
                if (m) m.style.display = 'none';
            }
        });

        document.body.appendChild(modal);
    }

    // Ensure modal exists and wire click handler to #screenshot-img
    ensureScreenshotModal();
    function bindScreenshotImg() {
        var img = document.getElementById('screenshot-img');
        if (!img) return;
        img.style.cursor = 'zoom-in';
        img.onclick = function (e) {
            var m = document.getElementById('screenshot-modal');
            var mi = document.getElementById('screenshot-modal-img');
            if (!m || !mi) return;
            var src = img.getAttribute('data-modal-src') || img.src;
            mi.src = sanitizeUrl(src);
            m.dataset.scale = 1;
            m.dataset.tx = 0;
            m.dataset.ty = 0;
            mi.style.transform = '';
            m.style.display = 'flex';
        };
    }
    // Try binding now and also when DOM changes
    bindScreenshotImg();
    var obs = new MutationObserver(function () { bindScreenshotImg(); });
    obs.observe(document.body, { childList: true, subtree: true });
})();

// ============================================================
// 公告系统
// ============================================================
(function () {
    var STORAGE_KEY = 'alas_shown_announcements';

    window.alasGetShownAnnouncements = function () {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            return [];
        }
    };

    window.alasMarkAnnouncementShown = function (announcementId) {
        try {
            var shown = window.alasGetShownAnnouncements();
            if (shown.indexOf(announcementId) === -1) {
                shown.push(announcementId);
                localStorage.setItem(STORAGE_KEY, JSON.stringify(shown));
            }
        } catch (e) { }
    };

    window.alasHasBeenShown = function (announcementId) {
        var shown = window.alasGetShownAnnouncements();
        return shown.indexOf(announcementId) !== -1;
    };

    window.alasShowAnnouncement = function (title, content, announcementId, url, force) {
        if ((!force && window.alasHasBeenShown(announcementId)) || document.getElementById('alas-announcement-modal')) {
            return;
        }

        // Create modal overlay
        var overlay = document.createElement('div');
        overlay.id = 'alas-announcement-modal';
        overlay.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;background:rgba(0,0,0,0.5);z-index:100000;display:flex;justify-content:center;align-items:center;';

        // Create modal content
        var modal = document.createElement('div');
        var isWeb = !!url;

        if (isWeb) {
            // Web page style: larger, fixed height
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:16px;width:95%;max-width:1200px;height:85vh;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.3);';
        } else {
            // Text style: automatic height, narrower
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.3);';
        }

        // Title
        var titleEl = document.createElement('h3');
        titleEl.textContent = title;
        titleEl.style.cssText = 'margin:0 0 12px 0;font-size:1.25rem;color:#333;border-bottom:2px solid #4fc3f7;padding-bottom:8px;flex-shrink:0;';

        modal.appendChild(titleEl);

        // Content (Text or Iframe)
        if (isWeb) {
            var iframe = document.createElement('iframe');
            iframe.src = sanitizeUrl(url);
            iframe.style.cssText = 'flex:1;border:none;width:100%;background:#f5f5f5;border-radius:4px;';
            modal.appendChild(iframe);
        } else {
            var contentEl = document.createElement('div');
            contentEl.textContent = content;
            contentEl.style.cssText = 'font-size:1rem;color:#555;line-height:1.6;margin-bottom:20px;white-space:pre-wrap;';
            modal.appendChild(contentEl);
        }

        // Close button area
        var btnContainer = document.createElement('div');
        btnContainer.style.cssText = 'margin-top:16px;text-align:center;flex-shrink:0;';

        var closeBtn = document.createElement('button');
        closeBtn.textContent = '确认';
        closeBtn.style.cssText = 'background:linear-gradient(90deg,#00b894,#0984e3);color:#fff;border:none;padding:10px 32px;border-radius:6px;cursor:pointer;font-size:1rem;display:inline-block;';
        closeBtn.onmouseover = function () { closeBtn.style.opacity = '0.9'; };
        closeBtn.onmouseout = function () { closeBtn.style.opacity = '1'; };
        closeBtn.onclick = function () {
            window.alasMarkAnnouncementShown(announcementId);
            overlay.remove();
        };

        btnContainer.appendChild(closeBtn);
        modal.appendChild(btnContainer);

        overlay.appendChild(modal);

        // Close on overlay click
        overlay.onclick = function (e) {
            if (e.target === overlay) {
                window.alasMarkAnnouncementShown(announcementId);
                overlay.remove();
            }
        };

        document.body.appendChild(overlay);

        // Apply dark theme if needed
        try {
            var isDark = document.body.classList.contains('pywebio-dark') ||
                document.documentElement.getAttribute('data-theme') === 'dark' ||
                localStorage.getItem('Theme') === 'dark';
            if (isDark) {
                modal.style.background = '#2d3436';
                titleEl.style.color = '#dfe6e9';
                if (!isWeb) {
                    // contentEl only exists in text mode
                    var c = modal.querySelector('div[style*="font-size:1rem"]');
                    if (c) c.style.color = '#b2bec3';
                }
            }
        } catch (e) { }
    };
})();
