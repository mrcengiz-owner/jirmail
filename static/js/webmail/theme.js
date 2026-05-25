/**
 * Webmail tema — wm-theme verisi + Tailwind darkMode: 'class'
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'wm-theme';

    function getStored() {
        try {
            var t = localStorage.getItem(STORAGE_KEY);
            if (t === 'light' || t === 'dark') return t;
        } catch (e) { /* ignore */ }
        return 'light';
    }

    function apply(theme) {
        var t = theme === 'light' ? 'light' : 'dark';
        var root = document.documentElement;
        if (t === 'dark') {
            root.classList.add('dark');
        } else {
            root.classList.remove('dark');
        }
        root.setAttribute('data-wm-theme', t);
        root.classList.toggle('wm-light', t === 'light');
        root.classList.toggle('wm-dark', t === 'dark');

        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', t === 'light' ? '#f4f4f8' : '#16161d');
        var scheme = document.querySelector('meta[name="color-scheme"]');
        if (scheme) scheme.setAttribute('content', t === 'light' ? 'light' : 'dark');
        try { localStorage.setItem(STORAGE_KEY, t); } catch (e) { /* ignore */ }
        return t;
    }

    function toggle() {
        var next = getStored() === 'light' ? 'dark' : 'light';
        apply(next);
        window.dispatchEvent(new CustomEvent('wm-theme-change', { detail: { theme: next } }));
        return next;
    }

    function set(theme) {
        var t = apply(theme);
        window.dispatchEvent(new CustomEvent('wm-theme-change', { detail: { theme: t } }));
        return t;
    }

    window.WmTheme = {
        get: getStored,
        apply: apply,
        set: set,
        toggle: toggle,
        init: function() { apply(getStored()); }
    };

    window.WmTheme.init();
})();
