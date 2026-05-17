/** Webmail — CSRF ve toast (dashboard app.js’e bağımlılık yok) */
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

    if (!window.showToast) {
        window.showToast = function(msg, type) {
            type = type || 'info';
            try {
                var box = document.getElementById('toast-container');
                if (!box) {
                    box = document.createElement('div');
                    box.id = 'toast-container';
                    box.className = 'fixed bottom-4 right-4 z-[9999] space-y-2';
                    document.body.appendChild(box);
                }
                var t = document.createElement('div');
                t.className = 'px-4 py-2 rounded-lg text-sm shadow-lg bg-slate-800 text-white border border-slate-700';
                if (type === 'error') t.classList.add('border-red-500/50');
                if (type === 'success') t.classList.add('border-emerald-500/50');
                t.textContent = msg;
                box.appendChild(t);
                setTimeout(function() { t.remove(); }, 4000);
            } catch (e) {
                console.log('[toast]', type, msg);
            }
        };
    }

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
