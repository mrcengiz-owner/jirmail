/**
 * Jîr-Mail Application JavaScript
 * Version: 2.0.0
 * Stack: Django Templates + Alpine.js + Tailwind CSS
 */

(function() {
    'use strict';

    // ========================================================================
    // GLOBAL TOAST NOTIFICATION SYSTEM
    // ========================================================================
    window.showToast = function(message, type) {
        type = type || 'success';

        if (window.Alpine && Alpine.store('toast')) {
            Alpine.store('toast').add(message, type);
            return;
        }

        var container = document.querySelector('.toast-container') || createToastContainer();
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.style.cssText = 'position: fixed; top: 1rem; right: 1rem; z-index: 9999; padding: 1rem 1.5rem; border-radius: 0.75rem; backdrop-filter: blur(12px); pointer-events: auto; animation: toastIn 0.3s ease-out; display: flex; align-items: center; gap: 0.75rem; min-width: 280px; max-width: 400px;';

        var palette = {
            success: { bg: 'rgba(34, 197, 94, 0.1)',  border: 'rgba(34, 197, 94, 0.3)',  color: '#22c55e' },
            error:   { bg: 'rgba(239, 68, 68, 0.1)',  border: 'rgba(239, 68, 68, 0.3)',  color: '#ef4444' },
            warning: { bg: 'rgba(245, 158, 11, 0.1)', border: 'rgba(245, 158, 11, 0.3)', color: '#f59e0b' },
            info:    { bg: 'rgba(59, 130, 246, 0.1)', border: 'rgba(59, 130, 246, 0.3)', color: '#3b82f6' }
        };
        var theme = palette[type] || palette.info;
        toast.style.background = theme.bg;
        toast.style.border = '1px solid ' + theme.border;
        toast.style.color = theme.color;

        toast.innerHTML = '<span>' + escapeHtml(message) + '</span>';
        container.appendChild(toast);

        setTimeout(function() {
            toast.style.animation = 'toastOut 0.3s ease-out forwards';
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, 4000);
    };

    function createToastContainer() {
        var container = document.createElement('div');
        container.className = 'toast-container';
        container.style.cssText = 'position: fixed; top: 1rem; right: 1rem; z-index: 9999; display: flex; flex-direction: column; gap: 0.5rem; pointer-events: none;';
        document.body.appendChild(container);
        return container;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ========================================================================
    // FOCUS TRAP UTILITY (Modal accessibility)
    // ========================================================================
    window.trapFocus = function(element) {
        var focusable = element.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        var first = focusable[0];
        var last = focusable[focusable.length - 1];

        element.addEventListener('keydown', function(e) {
            if (e.key === 'Tab') {
                if (e.shiftKey) {
                    if (document.activeElement === first) {
                        e.preventDefault();
                        last.focus();
                    }
                } else {
                    if (document.activeElement === last) {
                        e.preventDefault();
                        first.focus();
                    }
                }
            }
            if (e.key === 'Escape') {
                element.dispatchEvent(new CustomEvent('close-modal'));
            }
        });
    };

    // ========================================================================
    // CSRF helper for fetch()
    // ========================================================================
    window.getCsrfToken = function() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    };

    // ========================================================================
    // ALPINE.JS STORES & COMPONENTS
    // ========================================================================
    document.addEventListener('alpine:init', function() {

        // ----------------------------------------------------------------
        // Theme Store (Dark/Light mode)
        // ----------------------------------------------------------------
        Alpine.store('theme', {
            current: 'dark',

            init: function() {
                try {
                    var saved = localStorage.getItem('theme');
                    if (saved === 'light' || saved === 'dark') {
                        this.current = saved;
                    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                        this.current = 'dark';
                    } else {
                        this.current = 'dark';
                    }
                } catch (e) {
                    this.current = 'dark';
                }
                this.apply();
            },

            toggle: function() {
                this.current = this.current === 'dark' ? 'light' : 'dark';
                try {
                    localStorage.setItem('theme', this.current);
                } catch (e) { /* ignore */ }
                this.apply();
            },

            apply: function() {
                if (this.current === 'dark') {
                    document.documentElement.classList.add('dark');
                } else {
                    document.documentElement.classList.remove('dark');
                }
            }
        });

        // ----------------------------------------------------------------
        // Toast Store (Notifications)
        // ----------------------------------------------------------------
        Alpine.store('toast', {
            notifications: [],
            maxVisible: 5,

            add: function(message, type) {
                type = type || 'success';
                var id = Date.now() + Math.random();
                var visible = this.notifications.filter(function(n) { return n.visible; }).length;

                if (!visible && this.notifications.length >= this.maxVisible) {
                    var oldest = this.notifications.find(function(n) { return n.visible; });
                    if (oldest) oldest.visible = false;
                }

                var notification = { id: id, message: message, type: type, visible: true };
                this.notifications.push(notification);

                var self = this;
                setTimeout(function() { self.remove(id); }, 5000);

                return id;
            },

            remove: function(id) {
                var notification = this.notifications.find(function(n) { return n.id === id; });
                if (notification) {
                    notification.visible = false;
                    var self = this;
                    setTimeout(function() {
                        self.notifications = self.notifications.filter(function(n) { return n.id !== id; });
                    }, 300);
                }
            }
        });

        // ----------------------------------------------------------------
        // Master Panel Component (Dashboard)
        // ----------------------------------------------------------------
        Alpine.data('masterPanel', function() {
            return {
                activeTab: 'dashboard',
                JIR_KEY: window.JIR_KEY || '',
                specs: {
                    cpu_percent: 0,
                    ram_percent: 0,
                    ram_used_gb: 0,
                    ram_total_gb: 0,
                    disk_percent: 0,
                    disk_used_gb: 0,
                    disk_total_gb: 0,
                    docker_containers: []
                },
                accounts: [],
                domains: [],
                backups: [],
                logs: [],
                containers: [],
                showAddModal: false,
                showAddDomainModal: false,
                showDeleteConfirm: false,
                showDNSModalFlag: false,
                selectedDomain: null,
                selectedAccount: null,
                newAccount: { username: '', domain: '', password: '' },
                newDomain: { name: '' },
                specsInterval: null,
                containersInterval: null,

                init: function() {
                    this.refreshAll();
                    var self = this;
                    this.specsInterval = setInterval(function() { self.fetchSpecs(); }, 10000);
                    this.containersInterval = setInterval(function() { self.fetchContainers(); }, 15000);
                    return function() {
                        if (self.specsInterval) clearInterval(self.specsInterval);
                        if (self.containersInterval) clearInterval(self.containersInterval);
                    };
                },

                refreshAll: function() {
                    this.fetchSpecs();
                    this.fetchAccounts();
                    this.fetchDomains();
                    this.fetchBackups();
                    this.fetchLogs();
                    this.fetchContainers();
                },

                fetchSpecs: function() {
                    var self = this;
                    fetch('/api/management/system-specs')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.specs = data; })
                        .catch(function(e) { console.error('Specs fetch error:', e); });
                },

                fetchContainers: function() {
                    var self = this;
                    fetch('/api/management/container-status')
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            self.containers = Array.isArray(data) ? data : (data.containers || []);
                        })
                        .catch(function(e) {
                            console.error('Container fetch error:', e);
                            self.containers = [];
                        });
                },

                fetchAccounts: function() {
                    var self = this;
                    fetch('/api/core/list-accounts?key=' + this.JIR_KEY)
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            if (data.status === 'success') self.accounts = data.accounts || [];
                        })
                        .catch(function(e) { console.error('Accounts fetch error:', e); });
                },

                fetchDomains: function() {
                    var self = this;
                    fetch('/api/core/list-domains?key=' + this.JIR_KEY)
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            if (data.status === 'success') self.domains = data.domains || [];
                        })
                        .catch(function(e) { console.error('Domains fetch error:', e); });
                },

                fetchBackups: function() {
                    var self = this;
                    fetch('/api/backup/list-backups')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.backups = data || []; })
                        .catch(function(e) { console.error('Backups fetch error:', e); });
                },

                fetchLogs: function() {
                    var self = this;
                    var url = '/api/management/logs?key=' + this.JIR_KEY + '&lines=50';
                    if (this.logFilter) url += '&filter_type=' + this.logFilter;
                    fetch(url)
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.logs = data || []; })
                        .catch(function(e) { console.error('Logs fetch error:', e); });
                },

                createAccount: function() {
                    if (!this.newAccount.username || !this.newAccount.password) {
                        window.showToast('Username and password are required', 'error');
                        return;
                    }
                    var self = this;
                    fetch('/api/management/create-account', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify(self.newAccount)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.status === 'success') {
                            self.showAddModal = false;
                            self.newAccount = { username: '', domain: '', password: '' };
                            self.fetchAccounts();
                            window.showToast('Account created successfully', 'success');
                        } else {
                            window.showToast(data.message || 'Failed to create account', 'error');
                        }
                    })
                    .catch(function() {
                        window.showToast('Failed to create account', 'error');
                    });
                },

                toggleAccount: function(email) {
                    var self = this;
                    fetch('/api/core/toggle-account/' + encodeURIComponent(email) + '?key=' + this.JIR_KEY, { method: 'PATCH' })
                        .then(function(res) { return res.json(); })
                        .then(function() { self.fetchAccounts(); })
                        .catch(function(e) { console.error('Toggle account error:', e); });
                },

                deleteAccount: function(account) {
                    var self = this;
                    if (!confirm('Delete account ' + account.email + '?')) return;
                    fetch('/api/core/delete-account/' + encodeURIComponent(account.email) + '?key=' + this.JIR_KEY, { method: 'DELETE' })
                        .then(function(res) { return res.json(); })
                        .then(function() {
                            self.fetchAccounts();
                            window.showToast('Account deleted', 'success');
                        })
                        .catch(function(e) { console.error('Delete error:', e); });
                },

                getRoleLabel: function(role) {
                    var labels = { 'FULL': 'Full Access', 'SEND': 'Send Only', 'RECV': 'Receive Only', 'BLOCK': 'Internal' };
                    return labels[role] || role;
                }
            };
        });

        // ----------------------------------------------------------------
        // System Metrics Component
        // ----------------------------------------------------------------
        Alpine.data('systemMetrics', function() {
            return {
                specs: {
                    cpu_percent: 0,
                    ram_used_gb: 0,
                    ram_total_gb: 0,
                    ram_percent: 0,
                    disk_used_gb: 0,
                    disk_total_gb: 0,
                    disk_percent: 0
                },
                interval: null,

                init: function() {
                    this.fetchData();
                    var self = this;
                    this.interval = setInterval(function() { self.fetchData(); }, 10000);
                    return function() {
                        if (self.interval) clearInterval(self.interval);
                    };
                },

                fetchData: function() {
                    var self = this;
                    fetch('/api/management/system-specs')
                        .then(function(res) {
                            if (!res.ok) throw new Error('API error');
                            return res.json();
                        })
                        .then(function(data) { self.specs = data; })
                        .catch(function(err) {
                            console.warn('[Jîr-Mail] Metrics fetch failed:', err);
                        });
                }
            };
        });

        // ----------------------------------------------------------------
        // Containers App Component
        // ----------------------------------------------------------------
        Alpine.data('containersApp', function() {
            return {
                containers: [],
                interval: null,
                composeMode: typeof window.JIR_COMPOSE_STACK !== 'undefined' && window.JIR_COMPOSE_STACK === true,

                init: function() {
                    this.fetchContainers();
                    var self = this;
                    this.interval = setInterval(function() { self.fetchContainers(); }, 10000);
                    return function() {
                        if (self.interval) clearInterval(self.interval);
                    };
                },

                fetchContainers: function() {
                    var self = this;
                    fetch('/api/management/container-status')
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            self.containers = Array.isArray(data) ? data : [];
                        })
                        .catch(function(e) {
                            console.error(e);
                            self.containers = [];
                        });
                },

                isManageable: function(container) {
                    if (!container) return false;
                    if (container.compose_managed) return false;
                    var id = (container.container_id || '').toLowerCase();
                    var name = (container.container_name || '').toLowerCase();
                    if (id === 'unavailable' || id === 'error' || id.indexOf('compose-') === 0) return false;
                    if (name.indexOf('docker unavailable') >= 0 || name.indexOf('docker proxy') >= 0) return false;
                    return true;
                },

                toggleContainer: function(container, action) {
                    if (!this.isManageable(container)) {
                        window.showToast(
                            'Bu ortamda konteynerler panelden yönetilmez. Dokploy veya `docker compose` kullanın.',
                            'warning'
                        );
                        return;
                    }
                    var self = this;
                    fetch('/api/management/container/' + encodeURIComponent(container.container_name) + '/' + action, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': window.getCsrfToken()
                        },
                        body: '{}'
                    })
                    .then(function(res) {
                        return res.text().then(function(text) {
                            var data;
                            try {
                                data = JSON.parse(text);
                            } catch(e) {
                                throw new Error(res.ok ? 'Yanıt çözümlenemedi' : ('HTTP ' + res.status));
                            }
                            if (!res.ok) {
                                throw new Error((data && data.message) || ('HTTP ' + res.status));
                            }
                            return data;
                        });
                    })
                    .then(function(data) {
                        if (data.status === 'success') {
                            window.showToast(data.message, 'success');
                            setTimeout(function() { self.fetchContainers(); }, 1000);
                        } else {
                            window.showToast(data.message || 'İşlem başarısız', 'error');
                        }
                    })
                    .catch(function(e) {
                        console.error('[Jîr-Mail] Toggle error:', e);
                        window.showToast(String(e.message || e), 'error');
                    });
                }
            };
        });

        // ----------------------------------------------------------------
        // Backup App Component
        // ----------------------------------------------------------------
        Alpine.data('backupApp', function() {
            return {
                backups: [],
                loading: false,
                creating: false,
                error: null,

                init: function() { this.fetchBackups(); },

                fetchBackups: function() {
                    var self = this;
                    self.loading = true;
                    fetch('/api/backup/list-backups')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.backups = data || []; })
                        .catch(function(e) { console.error(e); })
                        .finally(function() { self.loading = false; });
                },

                createBackup: function() {
                    var self = this;
                    self.creating = true;
                    self.error = null;
                    window.showToast('Yedekleme başlatılıyor...', 'info');
                    fetch('/api/backup/create-backup', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify({
                            backup_type: 'full',
                            include_database: true,
                            include_configs: true,
                            include_emails: false
                        })
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.status === 'success') {
                            window.showToast('Yedekleme başarıyla oluşturuldu!', 'success');
                            self.fetchBackups();
                        } else {
                            self.error = data.message || 'Yedekleme başarısız.';
                            window.showToast(self.error, 'error');
                        }
                    })
                    .catch(function() {
                        window.showToast('Bağlantı hatası.', 'error');
                    })
                    .finally(function() { self.creating = false; });
                }
            };
        });

        // ----------------------------------------------------------------
        // Domains yönetimi (ekleme, düzenleme, silme, DNS modal)
        // ----------------------------------------------------------------
        Alpine.data('domainsApp', function() {
            function parseJsonScript(id, fallback) {
                var el = document.getElementById(id);
                if (!el) return fallback;
                try {
                    var v = JSON.parse(el.textContent);
                    return v != null ? v : fallback;
                } catch (e) {
                    return fallback;
                }
            }
            return {
                JIR_KEY: window.JIR_KEY || '',
                domains: parseJsonScript('domains-bootstrap', []),
                dnsProviderChoices: parseJsonScript('dns-provider-choices', []),
                mailHostname: typeof window.MAIL_SERVER_HOSTNAME === 'string' ? window.MAIL_SERVER_HOSTNAME : '',
                showAddModal: false,
                showEditModal: false,
                showDnsModal: false,
                loading: false,
                dnsLoading: false,
                newDomainName: '',
                editForm: { name: '', is_active: true, dns_provider: 'manual' },
                dnsView: { name: '', spf: '', dkim: '', dmarc: '', mx: '', verification_status: 'pending' },

                init: function() {
                    this.mailHostname = typeof window.MAIL_SERVER_HOSTNAME === 'string' ? window.MAIL_SERVER_HOSTNAME : '';
                },

                activeDomainCount: function() {
                    return this.domains.filter(function(d) { return d.is_active; }).length;
                },

                coreQuery: function(extraPairs) {
                    var parts = [];
                    if (this.JIR_KEY) parts.push('key=' + encodeURIComponent(this.JIR_KEY));
                    if (extraPairs && typeof extraPairs === 'object') {
                        Object.keys(extraPairs).forEach(function(k) {
                            if (extraPairs[k] !== undefined && extraPairs[k] !== null) {
                                parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(extraPairs[k])));
                            }
                        });
                    }
                    return parts.length ? ('?' + parts.join('&')) : '';
                },

                apiUrl: function(path, queryPairs) {
                    return '/api/core' + path + this.coreQuery(queryPairs || null);
                },

                refreshDomains: function() {
                    var self = this;
                    return fetch(self.apiUrl('/list-domains'))
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.status === 'success') self.domains = data.domains || [];
                        })
                        .catch(function(e) {
                            console.error(e);
                            window.showToast('Domain listesi alınamadı', 'error');
                        });
                },

                spfLabel: function(d) {
                    if (!d || !d.spf_record) return 'Ayarlanmadı';
                    return 'Ayarlı';
                },

                dkimLabel: function(d) {
                    if (!d || !d.dkim_record) return 'Eksik';
                    return 'Hazır';
                },

                verificationBadgeClass: function(st) {
                    if (st === 'verified') return 'badge-success';
                    if (st === 'failed') return 'badge-danger';
                    return 'badge-warning';
                },

                verificationLabel: function(st) {
                    if (st === 'verified') return 'Doğrulandı';
                    if (st === 'failed') return 'Başarısız';
                    return 'Beklemede';
                },

                openAddModal: function() {
                    this.newDomainName = '';
                    this.showAddModal = true;
                },

                closeAddModal: function() {
                    this.showAddModal = false;
                },

                submitAdd: function() {
                    var name = (this.newDomainName || '').trim().toLowerCase();
                    if (!name || name.indexOf('.') < 0) {
                        window.showToast('Geçerli bir domain girin (ör. ornek.com)', 'warning');
                        return;
                    }
                    var self = this;
                    self.loading = true;
                    fetch(self.apiUrl('/add-domain'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify({ name: name, is_active: true })
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.loading = false;
                            if (data.status === 'success') {
                                self.closeAddModal();
                                window.showToast(data.message || 'Domain eklendi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Eklenemedi', 'error');
                            }
                        })
                        .catch(function() {
                            self.loading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                openEditModal: function(d) {
                    this.editForm = {
                        name: d.name,
                        is_active: !!d.is_active,
                        dns_provider: d.dns_provider || 'manual'
                    };
                    this.showEditModal = true;
                },

                closeEditModal: function() {
                    this.showEditModal = false;
                },

                saveEdit: function() {
                    var self = this;
                    var name = this.editForm.name;
                    self.loading = true;
                    fetch(self.apiUrl('/update-domain/' + encodeURIComponent(name)), {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify({
                            is_active: this.editForm.is_active,
                            dns_provider: this.editForm.dns_provider
                        })
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.loading = false;
                            if (data.status === 'success') {
                                self.closeEditModal();
                                window.showToast(data.message || 'Güncellendi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Güncellenemedi', 'error');
                            }
                        })
                        .catch(function() {
                            self.loading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                setDomainActive: function(d, active) {
                    var self = this;
                    if (!active && !confirm('Bu domain askıya alınsın mı? İlişkili hesaplar etkilenebilir.')) return;
                    self.loading = true;
                    fetch(self.apiUrl('/update-domain/' + encodeURIComponent(d.name)), {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify({ is_active: active })
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.loading = false;
                            if (data.status === 'success') {
                                window.showToast(data.message || 'Durum güncellendi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'İşlem başarısız', 'error');
                            }
                        })
                        .catch(function() {
                            self.loading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                syncDns: function(d) {
                    var self = this;
                    self.loading = true;
                    fetch(self.apiUrl('/generate-dns-records/' + encodeURIComponent(d.name)), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.loading = false;
                            if (data.status === 'success') {
                                window.showToast('DNS kayıtları senkronize edildi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'İşlem başarısız', 'error');
                            }
                        })
                        .catch(function() {
                            self.loading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                openDnsModal: function(d) {
                    var self = this;
                    self.showDnsModal = true;
                    self.dnsLoading = true;
                    self.dnsView = {
                        name: d.name,
                        spf: '',
                        dkim: '',
                        dmarc: '',
                        mx: '',
                        verification_status: d.verification_status || 'pending'
                    };
                    fetch(self.apiUrl('/generate-dns-records/' + encodeURIComponent(d.name)), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.dnsLoading = false;
                            if (data.status === 'success') {
                                self.dnsView.spf = data.spf_record || '';
                                self.dnsView.dkim = data.dkim_record || '';
                                self.dnsView.dmarc = data.dmarc_record || '';
                                self.dnsView.mx = data.mx_record || '';
                                self.dnsView.verification_status = data.verification_status || 'pending';
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Kayıtlar yüklenemedi', 'error');
                            }
                        })
                        .catch(function() {
                            self.dnsLoading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                closeDnsModal: function() {
                    this.showDnsModal = false;
                },

                regenerateDns: function() {
                    if (!confirm('DKIM anahtarları yenilenecek. DNS sağlayıcınızdaki TXT kaydını güncellemeniz gerekir. Devam edilsin mi?')) return;
                    var self = this;
                    var name = self.dnsView.name;
                    self.dnsLoading = true;
                    fetch(self.apiUrl('/generate-dns-records/' + encodeURIComponent(name), { regenerate: 'true' }), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.dnsLoading = false;
                            if (data.status === 'success') {
                                self.dnsView.spf = data.spf_record || '';
                                self.dnsView.dkim = data.dkim_record || '';
                                self.dnsView.dmarc = data.dmarc_record || '';
                                self.dnsView.mx = data.mx_record || '';
                                self.dnsView.verification_status = data.verification_status || 'pending';
                                window.showToast('Anahtarlar yenilendi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Yenileme başarısız', 'error');
                            }
                        })
                        .catch(function() {
                            self.dnsLoading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                markVerified: function() {
                    if (!confirm('DNS kayıtlarını eklediğinizi ve doğrulamayı tamamladığınızı onaylıyor musunuz?')) return;
                    var self = this;
                    var name = self.dnsView.name;
                    self.dnsLoading = true;
                    fetch(self.apiUrl('/verify-domain/' + encodeURIComponent(name)), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.dnsLoading = false;
                            if (data.status === 'success') {
                                self.dnsView.verification_status = data.verification_status || 'verified';
                                window.showToast(data.message || 'Domain doğrulandı', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Doğrulama başarısız', 'error');
                            }
                        })
                        .catch(function() {
                            self.dnsLoading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                deleteDomain: function(d) {
                    if (!confirm('"' + d.name + '" kalıcı olarak silinsin mi? Bu işlem geri alınamaz.')) return;
                    var self = this;
                    self.loading = true;
                    fetch(self.apiUrl('/delete-domain/' + encodeURIComponent(d.name)), {
                        method: 'DELETE',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            self.loading = false;
                            if (data.status === 'success') {
                                window.showToast(data.message || 'Domain silindi', 'success');
                                self.refreshDomains();
                            } else {
                                window.showToast(data.message || 'Silinemedi', 'error');
                            }
                        })
                        .catch(function() {
                            self.loading = false;
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                copyText: function(text) {
                    if (!text) return;
                    navigator.clipboard.writeText(text).then(function() {
                        window.showToast('Panoya kopyalandı', 'success');
                    }).catch(function() {
                        window.showToast('Kopyalanamadı', 'error');
                    });
                }
            };
        });

        // ----------------------------------------------------------------
        // Hesaplar yönetimi
        // ----------------------------------------------------------------
        Alpine.data('accountsApp', function() {
            function parseJsonScript(id, fallback) {
                var el = document.getElementById(id);
                if (!el) return fallback;
                try {
                    return JSON.parse(el.textContent) || fallback;
                } catch (e) {
                    return fallback;
                }
            }
            return {
                JIR_KEY: window.JIR_KEY || '',
                accounts: parseJsonScript('accounts-bootstrap', []),
                domains: window.DOMAINS || [],
                showAddModal: false,
                loading: false,
                newAccount: { username: '', domain: '', password: '', role: 'FULL' },

                init: function() {
                    if (!this.domains.length) {
                        var d = parseJsonScript('domains-bootstrap', null);
                        if (Array.isArray(d)) {
                            this.domains = d.map(function(x) { return typeof x === 'string' ? x : x.name; });
                        }
                    }
                    if (this.domains.length && !this.newAccount.domain) {
                        this.newAccount.domain = this.domains[0];
                    }
                    this.refreshAccounts();
                },

                refreshAccounts: function() {
                    var self = this;
                    return fetch('/api/core/list-accounts?key=' + encodeURIComponent(self.JIR_KEY))
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.status === 'success') self.accounts = data.accounts || [];
                        })
                        .catch(function(e) {
                            console.error(e);
                            window.showToast('Hesap listesi alınamadı', 'error');
                        });
                },

                openAddModal: function() {
                    this.newAccount = {
                        username: '',
                        domain: this.domains[0] || '',
                        password: '',
                        role: 'FULL'
                    };
                    this.showAddModal = true;
                },

                createAccount: function() {
                    var self = this;
                    if (!this.newAccount.username || !this.newAccount.password || !this.newAccount.domain) {
                        window.showToast('Kullanıcı adı, domain ve parola zorunludur.', 'warning');
                        return;
                    }
                    this.loading = true;
                    fetch('/api/management/create-account', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                        body: JSON.stringify({
                            username: this.newAccount.username,
                            domain: this.newAccount.domain,
                            password: this.newAccount.password
                        })
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.status === 'success') {
                                self.showAddModal = false;
                                window.showToast('Hesap oluşturuldu: ' + (data.email || ''), 'success');
                                self.refreshAccounts();
                            } else {
                                window.showToast(data.message || 'Hesap oluşturulamadı', 'error');
                            }
                        })
                        .catch(function() {
                            window.showToast('Bağlantı hatası', 'error');
                        })
                        .finally(function() { self.loading = false; });
                },

                toggleAccount: function(acc) {
                    var self = this;
                    fetch('/api/core/toggle-account/' + encodeURIComponent(acc.email) + '?key=' + encodeURIComponent(self.JIR_KEY), {
                        method: 'PATCH',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.status === 'success') {
                                window.showToast('Hesap durumu güncellendi', 'success');
                                self.refreshAccounts();
                            } else {
                                window.showToast(data.message || 'İşlem başarısız', 'error');
                            }
                        })
                        .catch(function() {
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                deleteAccount: function(acc) {
                    if (!confirm(acc.email + ' hesabı silinsin mi?')) return;
                    var self = this;
                    fetch('/api/core/delete-account/' + encodeURIComponent(acc.email) + '?key=' + encodeURIComponent(self.JIR_KEY), {
                        method: 'DELETE',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.status === 'success') {
                                window.showToast('Hesap silindi', 'success');
                                self.refreshAccounts();
                            } else {
                                window.showToast(data.message || 'Silinemedi', 'error');
                            }
                        })
                        .catch(function() {
                            window.showToast('Bağlantı hatası', 'error');
                        });
                },

                roleLabel: function(role) {
                    var labels = { FULL: 'Tam erişim', SEND: 'Yalnız gönder', RECV: 'Yalnız al', BLOCK: 'Dahili' };
                    return labels[role] || role;
                }
            };
        });

        // ----------------------------------------------------------------
        // Live log tail (SSE) — logs sayfası; kaldırılınca EventSource kapanır
        // ----------------------------------------------------------------
        Alpine.data('liveLogTail', function() {
            return {
                lines: [],
                maxLines: 500,
                container: 'jir_postfix',
                streaming: false,
                eventSource: null,

                init: function() {
                    this.openStream();
                    var self = this;
                    return function() {
                        if (self.eventSource) {
                            try { self.eventSource.close(); } catch(e) {}
                            self.eventSource = null;
                        }
                        self.streaming = false;
                    };
                },

                openStream: function() {
                    var self = this;
                    if (this.eventSource) {
                        try { this.eventSource.close(); } catch(e) {}
                        this.eventSource = null;
                    }
                    try {
                        this.eventSource = new EventSource('/api/monitoring/logs/stream?container=' + encodeURIComponent(this.container) + '&lines=100');
                        this.streaming = true;
                        this.eventSource.onmessage = function(msg) {
                            try {
                                var parsed = JSON.parse(msg.data);
                                if (parsed.error) {
                                    self.lines.push('[ERROR] ' + parsed.error);
                                } else if (parsed.line) {
                                    self.lines.push(parsed.line);
                                    if (self.lines.length > self.maxLines) {
                                        self.lines.splice(0, self.lines.length - self.maxLines);
                                    }
                                    self.$nextTick(function() {
                                        if (self.$refs.logArea) {
                                            self.$refs.logArea.scrollTop = self.$refs.logArea.scrollHeight;
                                        }
                                    });
                                }
                            } catch(e) { /* ignore */ }
                        };
                        this.eventSource.onerror = function() {
                            self.streaming = false;
                            try {
                                if (self.eventSource) {
                                    self.eventSource.close();
                                }
                            } catch(e) { /* ignore */ }
                            self.eventSource = null;
                        };
                    } catch(e) {
                        this.streaming = false;
                    }
                },

                toggleStream: function() {
                    if (this.streaming && this.eventSource) {
                        try { this.eventSource.close(); } catch(e) {}
                        this.eventSource = null;
                        this.streaming = false;
                    } else {
                        this.openStream();
                    }
                },

                reconnect: function() {
                    if (this.eventSource) {
                        try { this.eventSource.close(); } catch(e) {}
                        this.eventSource = null;
                    }
                    this.openStream();
                },

                clearLines: function() {
                    this.lines = [];
                }
            };
        });

        // ----------------------------------------------------------------
        // Logs App Component
        // ----------------------------------------------------------------
        Alpine.data('logsApp', function() {
            return {
                logs: [],
                filter: '',
                pollInterval: null,

                init: function() {
                    this.fetchLogs();
                    var self = this;
                    this.pollInterval = setInterval(function() { self.fetchLogs(); }, 30000);
                    return function() {
                        if (self.pollInterval) clearInterval(self.pollInterval);
                    };
                },

                get filteredLogs() {
                    if (!this.filter) return this.logs;
                    return this.logs.filter(function(log) {
                        return log.type === this.filter;
                    });
                },

                fetchLogs: function() {
                    var self = this;
                    var key = window.JIR_KEY || '';
                    fetch('/api/management/logs?key=' + encodeURIComponent(key) + '&lines=100')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.logs = data || []; })
                        .catch(function(e) { console.error(e); });
                }
            };
        });

        // ----------------------------------------------------------------
        // Mail Application Component (3-column layout)
        // ----------------------------------------------------------------
        Alpine.data('mailApp', function() {
            // Klasör adlarını UI label <-> IMAP folder mapping
            var FOLDER_MAP = {
                inbox: 'INBOX',
                sent: 'Sent',
                drafts: 'Drafts',
                trash: 'Trash',
                starred: 'INBOX'  // starred sadece flag filtresi
            };

            return {
                currentFolder: 'inbox',
                mobileView: 'list',
                showCompose: false,
                selectedMail: null,
                searchQuery: '',
                unreadCount: 0,
                mails: [],
                page: 1,
                pageSize: 50,
                hasMore: false,
                composeTo: '',
                composeSubject: '',
                composeBody: '',
                composeType: 'new',
                sendingMail: false,
                loadingMails: false,
                eventSource: null,
                _mailRefreshTimer: null,
                _searchTimer: null,
                _folderLabels: {
                    inbox: 'Gelen Kutusu',
                    starred: 'Yıldızlı',
                    sent: 'Gönderilen',
                    drafts: 'Taslaklar',
                    trash: 'Çöp Kutusu'
                },

                init: function() {
                    var self = this;
                    this.syncAllFolders().then(function() {
                        self.fetchMails();
                    });
                    var stopFolderWatch = this.$watch('currentFolder', function() {
                        self.page = 1;
                        self.selectedMail = null;
                        self.fetchMails();
                    });
                    var stopSearchWatch = this.$watch('searchQuery', function() {
                        if (self._searchTimer) clearTimeout(self._searchTimer);
                        self._searchTimer = setTimeout(function() {
                            self._searchTimer = null;
                            self.page = 1;
                            self.selectedMail = null;
                            self.fetchMails();
                        }, 400);
                    });
                    this.openStream();
                    return function() {
                        if (typeof stopFolderWatch === 'function') stopFolderWatch();
                        if (typeof stopSearchWatch === 'function') stopSearchWatch();
                        if (self._mailRefreshTimer) {
                            clearTimeout(self._mailRefreshTimer);
                            self._mailRefreshTimer = null;
                        }
                        if (self._searchTimer) {
                            clearTimeout(self._searchTimer);
                            self._searchTimer = null;
                        }
                        if (self.eventSource) {
                            try { self.eventSource.close(); } catch(e) {}
                            self.eventSource = null;
                        }
                    };
                },

                switchFolder: function(name) {
                    this.currentFolder = name;
                    this.mobileView = 'list';
                    this.selectedMail = null;
                    this.page = 1;
                },

                folderLabel: function() {
                    return this._folderLabels[this.currentFolder] || this.currentFolder;
                },

                imapFolder: function() {
                    return FOLDER_MAP[this.currentFolder] || 'INBOX';
                },

                fetchMails: async function(allowSync) {
                    if (allowSync === undefined) allowSync = true;
                    this.loadingMails = true;
                    try {
                        var url = '/api/mail/messages?folder=' + encodeURIComponent(this.imapFolder()) +
                                  '&page=' + this.page + '&page_size=' + this.pageSize;
                        if (this.searchQuery) url += '&q=' + encodeURIComponent(this.searchQuery);

                        var res = await fetch(url, { credentials: 'same-origin' });
                        if (!res.ok) {
                            await this.syncInbox();
                            this.mails = [];
                            return;
                        }
                        var data = await res.json();
                        if (!data.success) {
                            this.mails = [];
                            return;
                        }

                        this.mails = (data.messages || []).map(function(m) {
                            return {
                                id: m.uid,
                                uid: m.uid,
                                from: m.from_name || m.from,
                                from_addr: m.from,
                                subject: m.subject || '(konu yok)',
                                preview: m.snippet || '',
                                date: m.date || new Date().toISOString(),
                                body: '',
                                bodyLoaded: false,
                                unread: !m.is_seen,
                                starred: m.is_flagged,
                                hasAttachments: m.has_attachments,
                                folder: this.currentFolder,
                                deliveryStatus: m.delivery_status || (m.is_seen ? 'read' : 'unread'),
                                source: m.source || 'imap'
                            };
                        }, this);
                        this.hasMore = (this.page * this.pageSize) < (data.total || 0);
                        this.updateUnread();

                        if (allowSync && this.mails.length === 0 && this.page === 1 &&
                            !this.searchQuery && this.currentFolder !== 'starred') {
                            await this.syncInbox();
                            return this.fetchMails(false);
                        }
                    } catch(e) {
                        console.error('Mail fetch error:', e);
                        window.showToast('Mailler yüklenemedi: ' + e.message, 'error');
                    } finally {
                        this.loadingMails = false;
                    }
                },

                syncInbox: async function() {
                    try {
                        await fetch('/api/mail/sync', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                            body: JSON.stringify({ folder: this.imapFolder(), limit: 100 })
                        });
                    } catch(e) { /* ignore */ }
                },

                syncAllFolders: async function() {
                    try {
                        var res = await fetch('/api/mail/sync-all', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                            credentials: 'same-origin'
                        });
                        var data = await res.json();
                        if (!data.success && data.message) {
                            console.warn('Mail sync-all:', data.message);
                        }
                    } catch(e) { /* ignore */ }
                },

                get filteredMails() {
                    if (this.currentFolder !== 'starred') return this.mails;
                    return this.mails.filter(function(m) { return m.starred; });
                },

                updateUnread: function() {
                    this.unreadCount = this.mails.filter(function(m) { return m.unread; }).length;
                },

                selectMail: async function(mail) {
                    this.selectedMail = mail;
                    this.showCompose = false;

                    if (!mail.bodyLoaded) {
                        try {
                            var res = await fetch('/api/mail/messages/' + mail.uid + '/body?folder=' + encodeURIComponent(this.imapFolder()),
                                                  { credentials: 'same-origin' });
                            var data = await res.json();
                            if (data.success) {
                                mail.body = data.html || ('<pre style="white-space:pre-wrap;font-family:inherit">' +
                                            (data.plain || '').replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</pre>');
                                mail.bodyLoaded = true;
                            }
                        } catch(e) {
                            mail.body = '<p class="text-red-400">Mesaj yüklenemedi: ' + e.message + '</p>';
                        }
                    }

                    if (mail.unread) {
                        mail.unread = false;
                        this.updateUnread();
                        this.patchFlags(mail.uid, { seen: true });
                    }
                },

                patchFlags: async function(uid, payload) {
                    if (uid < 0) return;
                    try {
                        payload.folder = this.imapFolder();
                        await fetch('/api/mail/messages/' + uid + '/flags', {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                            body: JSON.stringify(payload)
                        });
                    } catch(e) { /* ignore */ }
                },

                formatDate: function(isoString) {
                    if (!isoString) return '';
                    var date = new Date(isoString);
                    var now = new Date();
                    if (date.toDateString() === now.toDateString()) {
                        return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
                    }
                    return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
                },

                formatDateTime: function(isoString) {
                    if (!isoString) return '';
                    var date = new Date(isoString);
                    return date.toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
                },

                mailStatusDotClass: function(mail) {
                    var s = (mail && mail.deliveryStatus) || 'read';
                    if (s === 'unread') return 'bg-primary-400 ring-primary-400/30';
                    if (s === 'pending' || s === 'deferred') return 'bg-warning-400 ring-warning-400/30';
                    if (s === 'failed') return 'bg-danger-400 ring-danger-400/30';
                    if (s === 'sent') return 'bg-success-400 ring-success-400/30';
                    return 'bg-slate-600 ring-slate-600/20';
                },

                mailStatusTitle: function(mail) {
                    var s = (mail && mail.deliveryStatus) || 'read';
                    var map = {
                        unread: 'Okunmadı',
                        read: 'Okundu',
                        pending: 'Gönderim bekleniyor',
                        sent: 'Gönderildi (SMTP kabul)',
                        failed: 'Gönderilemedi',
                        deferred: 'Ertelendi / kuyrukta'
                    };
                    return map[s] || s;
                },

                formatBody: function(html) { return html || ''; },

                toggleStar: function(mail) {
                    mail.starred = !mail.starred;
                    this.patchFlags(mail.uid, { flagged: mail.starred });
                },

                deleteMail: async function(mail) {
                    try {
                        await fetch('/api/mail/messages/' + mail.uid + '?folder=' + encodeURIComponent(this.imapFolder()), {
                            method: 'DELETE',
                            headers: { 'X-CSRFToken': window.getCsrfToken() }
                        });
                        this.mails = this.mails.filter(function(m) { return m.uid !== mail.uid; });
                        if (this.selectedMail && this.selectedMail.uid === mail.uid) this.selectedMail = null;
                        window.showToast('Mesaj silindi.', 'info');
                    } catch(e) {
                        window.showToast('Silme başarısız: ' + e.message, 'error');
                    }
                },

                replyTo: function(mail) {
                    this.composeTo = mail.from_addr || mail.from;
                    this.composeSubject = 'Re: ' + mail.subject;
                    this.composeBody = '\n\n--- Orijinal Mesaj ---\nGönderen: ' + mail.from + '\nTarih: ' + this.formatDateTime(mail.date) + '\n\n';
                    this.composeType = 'reply';
                    this.selectedMail = null;
                    this.showCompose = true;
                },

                forwardMail: function(mail) {
                    this.composeTo = '';
                    this.composeSubject = 'Fwd: ' + mail.subject;
                    this.composeBody = '\n\n--- İletilen Mesaj ---\nGönderen: ' + mail.from + '\nTarih: ' + this.formatDateTime(mail.date) + '\n\n';
                    this.composeType = 'forward';
                    this.selectedMail = null;
                    this.showCompose = true;
                },

                closeCompose: function() {
                    this.showCompose = false;
                    this.composeTo = '';
                    this.composeSubject = '';
                    this.composeBody = '';
                },

                saveDraft: function() {
                    window.showToast('Taslak kaydetme yakında.', 'info');
                },

                sendMail: async function() {
                    if (!this.composeTo || !this.composeSubject) {
                        window.showToast('Alıcı ve konu alanları zorunludur.', 'warning');
                        return;
                    }
                    this.sendingMail = true;
                    try {
                        var res = await fetch('/api/mail/send', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() },
                            credentials: 'same-origin',
                            body: JSON.stringify({
                                to: this.composeTo,
                                subject: this.composeSubject,
                                body_text: this.composeBody
                            })
                        });
                        var raw = await res.text();
                        var data;
                        try {
                            data = JSON.parse(raw);
                        } catch (parseErr) {
                            throw new Error(
                                res.ok
                                    ? 'Sunucu geçersiz yanıt döndü'
                                    : ('HTTP ' + res.status + ' — oturum süresi dolmuş veya sunucu hatası olabilir')
                            );
                        }
                        if (data.success) {
                            window.showToast(data.message || 'Mesaj Postfix tarafından kabul edildi.', 'success');
                            this.closeCompose();
                            this.currentFolder = 'sent';
                            this.page = 1;
                            await this.syncInbox();
                            await this.fetchMails(false);
                        } else {
                            window.showToast(data.message || 'Gönderme başarısız.', 'error');
                        }
                    } catch(e) {
                        window.showToast('Bağlantı hatası: ' + e.message, 'error');
                    } finally {
                        this.sendingMail = false;
                    }
                },

                openStream: function() {
                    var self = this;
                    if (this.eventSource) {
                        try { this.eventSource.close(); } catch(e) {}
                        this.eventSource = null;
                    }
                    try {
                        this.eventSource = new EventSource('/api/mail/stream');
                        this.eventSource.onmessage = function(msg) {
                            try {
                                var parsed = JSON.parse(msg.data);
                                if (parsed.type === 'new_mail') {
                                    if (self._mailRefreshTimer) clearTimeout(self._mailRefreshTimer);
                                    self._mailRefreshTimer = setTimeout(function() {
                                        self._mailRefreshTimer = null;
                                        self.fetchMails();
                                    }, 600);
                                    window.showToast('Yeni mail geldi', 'info');
                                }
                            } catch(e) { /* ignore */ }
                        };
                        this.eventSource.onerror = function() {
                            try {
                                if (self.eventSource) self.eventSource.close();
                            } catch(e) { /* ignore */ }
                            self.eventSource = null;
                        };
                    } catch(e) { /* SSE unavailable */ }
                }
            };
        });

        // ----------------------------------------------------------------
        // Monitoring Components (Phase 5)
        // ----------------------------------------------------------------
        Alpine.data('mailQueueCard', function() {
            return {
                count: 0,
                loading: false,
                pollInterval: null,
                showHelp: false,
                init: function() {
                    this.refresh(false);
                    var self = this;
                    this.pollInterval = setInterval(function() { self.refresh(true); }, 30000);
                    return function() {
                        if (self.pollInterval) clearInterval(self.pollInterval);
                    };
                },
                refresh: function(silent) {
                    var self = this;
                    if (!silent) this.loading = true;
                    fetch('/api/monitoring/queue/count', { credentials: 'same-origin' })
                        .then(function(r) { return r.json(); })
                        .then(function(d) { if (d.success) self.count = d.count; })
                        .catch(function() {})
                        .finally(function() { if (!silent) self.loading = false; });
                },
                flushQueue: function() {
                    if (!confirm('Mail kuyruğunu flush etmek istiyor musunuz?')) return;
                    var self = this;
                    this.loading = true;
                    fetch('/api/monitoring/queue/flush', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': window.getCsrfToken() }
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            window.showToast(d.success ? 'Kuyruk flush edildi' : 'Flush başarısız', d.success ? 'success' : 'error');
                            self.refresh(true);
                        })
                        .catch(function(e) { window.showToast('Hata: ' + e.message, 'error'); })
                        .finally(function() { self.loading = false; });
                }
            };
        });

        window.JIR_CARD_HELP = {
            mailQueue: {
                title: 'Mail kuyruğu',
                body: 'Postfix’te henüz teslim edilmemiş veya ertelenmiş iletilerin sayısı. Flush, kuyruğu zorla yeniden işlemeye alır. Yüksek sayı DNS, relay veya alıcı sunucu sorununa işaret edebilir.'
            },
            dnsbl: {
                title: 'DNSBL (kara liste)',
                body: 'Sunucunuzun çıkış IP adresinin bilinen spam kara listelerinde (DNSBL) olup olmadığını kontrol eder. Listelenmiş IP’lerde alıcı sunucular postanızı reddedebilir veya spam klasörüne atabilir.'
            },
            reputation: {
                title: 'Son 24 saat',
                body: 'Postfix mail.log veya webmail gönderim kayıtlarından özet: gönderilen, ertelenen, bounce ve red sayıları. Yüzde, kabul edilen / toplam oranıdır. Log yoksa panel gönderim kayıtlarını kullanır.'
            }
        };

        Alpine.data('dnsblCard', function() {
            return {
                status: 'unknown',
                ip: '',
                listedCount: 0,
                results: [],
                showHelp: false,
                init: function() {
                    this.detectIPAndCheck();
                },
                detectIPAndCheck: function() {
                    var self = this;
                    fetch('https://api.ipify.org?format=json')
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            self.ip = d.ip;
                            return fetch('/api/monitoring/dnsbl/' + d.ip);
                        })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            if (!d.success) { self.status = 'unknown'; return; }
                            self.results = d.results || [];
                            self.listedCount = d.listed_count || 0;
                            self.status = d.clean ? 'clean' : 'listed';
                        })
                        .catch(function() { self.status = 'unknown'; });
                },
                refresh: function() { this.detectIPAndCheck(); }
            };
        });

        Alpine.data('reputationCard', function() {
            return {
                stats: { sent: 0, bounced: 0, deferred: 0, rejected: 0, delivery_rate_percent: 0, available: false },
                pollInterval: null,
                showHelp: false,
                init: function() {
                    this.refresh();
                    var self = this;
                    this.pollInterval = setInterval(function() { self.refresh(); }, 60000);
                    return function() {
                        if (self.pollInterval) clearInterval(self.pollInterval);
                    };
                },
                deliveryRateLabel: function() {
                    if (!this.stats.available) return '—';
                    var p = this.stats.delivery_rate_percent;
                    if (p === null || p === undefined || isNaN(p)) return '0%';
                    return Math.round(p) + '%';
                },
                refresh: function() {
                    var self = this;
                    fetch('/api/monitoring/reputation?window_hours=24', { credentials: 'same-origin' })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            if (d.success) {
                                if (d.delivery_rate_percent === undefined || d.delivery_rate_percent === null) {
                                    d.delivery_rate_percent = 0;
                                }
                                self.stats = d;
                            }
                        })
                        .catch(function() {});
                }
            };
        });

        // ----------------------------------------------------------------
        // Services Status Component
        // ----------------------------------------------------------------
        Alpine.data('servicesStatus', function() {
            return {
                canManageDocker: typeof window !== 'undefined' && window.CAN_MANAGE_DOCKER === true,
                services: [
                    { name: 'PostgreSQL', status: 'checking', port: 5432, container: 'jir_postgres', actionLoading: false },
                    { name: 'Postfix',  status: 'checking', port: 25,   container: 'jir_postfix',  actionLoading: false },
                    { name: 'Dovecot',  status: 'checking', port: 993,  container: 'jir_dovecot',  actionLoading: false },
                    { name: 'Redis',    status: 'checking', port: 6379, container: 'jir_redis',    actionLoading: false }
                ],
                interval: null,

                init: function() {
                    this.canManageDocker = typeof window !== 'undefined' && window.CAN_MANAGE_DOCKER === true;
                    this.fetchServiceStatus();
                    var self = this;
                    this.interval = setInterval(function() { self.fetchServiceStatus(); }, 15000);
                    return function() {
                        if (self.interval) clearInterval(self.interval);
                    };
                },

                fetchServiceStatus: function() {
                    var self = this;
                    fetch('/api/management/system-requirements', { credentials: 'same-origin' })
                        .then(function(res) {
                            if (!res.ok) throw new Error('API error');
                            return res.json();
                        })
                        .then(function(data) {
                            if (data.services && data.services.length > 0) {
                                data.services.forEach(function(svc) {
                                    var service = self.services.find(function(s) { return s.name === svc.name; });
                                    if (service) {
                                        service.status = String(svc.status || 'unknown').toLowerCase();
                                        if (svc.container) {
                                            service.container = svc.container;
                                        }
                                    }
                                });
                            } else {
                                self.services.forEach(function(s) {
                                    if (s.status === 'checking') s.status = 'unknown';
                                });
                            }
                        })
                        .catch(function(e) {
                            console.warn('[Jîr-Mail] Service status unavailable:', e);
                            self.services.forEach(function(s) {
                                if (s.status === 'checking') s.status = 'unknown';
                            });
                        });
                },

                confirmStart: function(service) {
                    if (!this.canManageDocker) return;
                    if (!confirm('Bu servisi başlatmak istediğinizden emin misiniz?')) return;
                    this.toggleService(service, 'start');
                },

                confirmStop: function(service) {
                    if (!this.canManageDocker) return;
                    if (!confirm('Bu servisi durdurmak istediğinizden emin misiniz?')) return;
                    this.toggleService(service, 'stop');
                },

                toggleService: function(service, forcedAction) {
                    if (!this.canManageDocker) return;
                    var action = forcedAction || (service.status === 'running' ? 'stop' : 'start');
                    var self = this;
                    var cname = service.container || ('jir_' + service.name).toLowerCase();
                    service.actionLoading = true;

                    fetch('/api/management/container/' + encodeURIComponent(cname) + '/' + action, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': window.getCsrfToken()
                        },
                        body: '{}'
                    })
                    .then(function(res) {
                        return res.text().then(function(text) {
                            var data;
                            try {
                                data = JSON.parse(text);
                            } catch(e) {
                                throw new Error(res.ok ? 'Yanıt çözümlenemedi' : ('HTTP ' + res.status));
                            }
                            if (!res.ok) {
                                throw new Error((data && data.message) || ('HTTP ' + res.status));
                            }
                            return data;
                        });
                    })
                    .then(function(data) {
                        if (data.status === 'success') {
                            window.showToast(data.message || 'İşlem tamam', 'success');
                            service.status = 'checking';
                            setTimeout(function() { self.fetchServiceStatus(); }, 1200);
                        } else {
                            window.showToast(data.message || 'İşlem başarısız', 'error');
                        }
                    })
                    .catch(function(e) {
                        console.error('[Jîr-Mail] Toggle error:', e);
                        window.showToast(String(e.message || e), 'error');
                    })
                    .finally(function() {
                        service.actionLoading = false;
                    });
                }
            };
        });

    });

    // ========================================================================
    // CSS animations for fallback toast
    // ========================================================================
    var style = document.createElement('style');
    style.textContent = [
        '@keyframes toastIn { from { opacity: 0; transform: translateX(100%); } to { opacity: 1; transform: translateX(0); } }',
        '@keyframes toastOut { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(100%); } }'
    ].join('\n');
    document.head.appendChild(style);

})();
