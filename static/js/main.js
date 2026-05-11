/**
 * Jir-Mail Global JavaScript
 * Global CSRF handling, HTMX configuration, and common utilities
 */

(function() {
    'use strict';

    // Get CSRF token from meta tag or cookie
    function getCsrfToken() {
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            return metaToken.getAttribute('content');
        }
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='));
        if (cookieValue) {
            return cookieValue.split('=')[1];
        }
        return '';
    }

    // Initialize HTMX with global configuration
    document.addEventListener('DOMContentLoaded', function() {
        // Configure HTMX to include CSRF token in all requests
        htmx.config.globalConfigConfig = {
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest'
            }
        };

        // Add CSRF token to all HTMX requests
        document.body.addEventListener('htmx:config-request', function(evt) {
            evt.detail.headers['X-CSRFToken'] = getCsrfToken();
        });

        // Log HTMX events for debugging (remove in production)
        document.body.addEventListener('htmx:response-error', function(evt) {
            console.error('HTMX Response Error:', evt.detail);
            if (evt.detail.xhr && evt.detail.xhr.status === 403) {
                showToast('Yetkisiz işlem. Lütfen tekrar giriş yapın.', 'error');
            }
        });

        document.body.addEventListener('htmx:before-swap', function(evt) {
            if (evt.detail.target) {
                evt.detail.target.classList.add('content-fade-in');
            }
        });
    });

    // Show toast notification globally
    function showToast(message, type) {
        const toast = document.querySelector('[x-data]')?.__x?.$data;
        if (toast && typeof toast.showToast === 'function') {
            toast.showToast(message, type);
        } else {
            // Fallback for non-Alpine contexts
            alert(message);
        }
    }

    // Copy to clipboard utility
    function copyToClipboard(text) {
        if (!text) return false;
        try {
            if (window.clipboardData && window.clipboardData.setData) {
                window.clipboardData.setData('Text', text);
                return true;
            }
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.cssText = 'position:fixed;top:-9999px;left:-9999px;';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            return true;
        } catch (err) {
            console.warn('Copy failed:', err);
            return false;
        }
    }

    // HTMX helper for content area updates
    function htmxLoadContent(url, targetSelector) {
        const target = document.querySelector(targetSelector || '#content-area');
        if (target && htmx) {
            htmx.ajax('GET', url, {
                target: target,
                swap: 'innerHTML',
                showIndicator: '#content-loading'
            });
        }
    }

    // Format date utility
    function formatDate(date) {
        if (!(date instanceof Date)) {
            date = new Date(date);
        }
        const now = new Date();
        const diff = now - date;
        const days = Math.floor(diff / 86400000);

        if (days === 0) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        if (days === 1) return 'Yesterday';
        if (days < 7) return date.toLocaleDateString([], { weekday: 'short' });
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }

    function formatDateTime(date) {
        if (!(date instanceof Date)) {
            date = new Date(date);
        }
        return date.toLocaleString([], {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // Export to global scope
    window.JirMail = window.JirMail || {};
    window.JirMail.getCsrfToken = getCsrfToken;
    window.JirMail.showToast = showToast;
    window.JirMail.copyToClipboard = copyToClipboard;
    window.JirMail.htmxLoadContent = htmxLoadContent;
    window.JirMail.formatDate = formatDate;
    window.JirMail.formatDateTime = formatDateTime;

})();