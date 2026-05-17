/** Webmail — CSRF, toast store, yardımcılar (dashboard app.js gerekmez) */
(function() {
    document.addEventListener('alpine:init', function() {
        if (typeof Alpine === 'undefined') return;
        if (!Alpine.store('toast')) {
            Alpine.store('toast', {
                notifications: [],
                add: function(message, type, duration) {
                    type = type || 'info';
                    duration = duration || 4000;
                    var id = Date.now() + Math.random();
                    this.notifications.push({ id: id, message: message, type: type, visible: true });
                    var self = this;
                    setTimeout(function() { self.remove(id); }, duration);
                },
                remove: function(id) {
                    this.notifications = this.notifications.filter(function(n) { return n.id !== id; });
                }
            });
        }
    });

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
        try {
            if (typeof Alpine !== 'undefined' && Alpine.store('toast')) {
                Alpine.store('toast').add(msg, type);
                return;
            }
        } catch (e) { /* fallback */ }
        console.log('[toast]', type, msg);
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
                        return { ok: false, status: r.status, data: { success: false, message: raw.slice(0, 200) } };
                    }
                });
            });
        }
    };
})();
