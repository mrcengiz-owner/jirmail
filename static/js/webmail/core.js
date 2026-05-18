/** Webmail — CSRF ve toast bildirimleri */
(function() {
    function getCookie(name) {
        var m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
        return m ? decodeURIComponent(m[1]) : '';
    }

    window.getCsrfToken = function() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        return getCookie('csrftoken');
    };

    window.showToast = function(msg, type) {
        type = type || 'info';
        var root = document.getElementById('wm-toast-root');
        if (!root) {
            console.log('[toast]', type, msg);
            return;
        }
        var el = document.createElement('div');
        el.className = 'wm-toast wm-toast--' + type;
        el.textContent = msg;
        root.appendChild(el);
        setTimeout(function() {
            el.style.opacity = '0';
            el.style.transform = 'translateY(8px)';
            el.style.transition = 'opacity 0.25s, transform 0.25s';
            setTimeout(function() { el.remove(); }, 280);
        }, 4200);
    };

    window.WmApi = {
        fetch: function(url, opts) {
            opts = opts || {};
            opts.credentials = 'same-origin';
            opts.headers = opts.headers || {};
            if (!opts.headers['X-CSRFToken']) {
                opts.headers['X-CSRFToken'] = window.getCsrfToken();
            }
            return fetch(url, opts);
        },
        json: function(url, opts) {
            return this.fetch(url, opts).then(function(r) {
                return r.text().then(function(raw) {
                    try {
                        return { ok: r.ok, status: r.status, data: JSON.parse(raw) };
                    } catch (e) {
                        return {
                            ok: false,
                            status: r.status,
                            data: { success: false, message: raw.slice(0, 200) }
                        };
                    }
                });
            });
        }
    };
})();
