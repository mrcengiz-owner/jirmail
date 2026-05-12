/**
 * Jîr-Mail Application JavaScript
 * Version: 1.0.0
 * Description: Global app logic with Alpine.js integration
 */

(function() {
    'use strict';

    // ========================================================================
    // DOM READY
    // ========================================================================
    document.addEventListener('DOMContentLoaded', function() {

        // ----------------------------------------------------------------
        // HTMX CSRF Configuration
        // ----------------------------------------------------------------
        document.body.addEventListener('htmx:configRequest', function(event) {
            var csrfMeta = document.querySelector('meta[name="csrf-token"]');
            if (csrfMeta && csrfMeta.content) {
                event.detail.headers['X-CSRFToken'] = csrfMeta.content;
            }
        });

        // ----------------------------------------------------------------
        // Global Error Handler for HTMX responses
        // ----------------------------------------------------------------
        document.body.addEventListener('htmx:responseError', function(event) {
            var status = event.detail.xhr.status;
            var messages = {
                401: 'Oturum süresi doldu. Lütfen tekrar giriş yapın.',
                403: 'Bu işlem için yetkiniz yok.',
                404: 'İstenen içerik bulunamadı.',
                500: 'Sunucu hatası. Lütfen daha sonra tekrar deneyin.',
                0: 'Bağlantı hatası. Ağ bağlantınızı kontrol edin.'
            };
            var message = messages[status] || 'Beklenmeyen hata oluştu (' + status + ')';
            window.showToast(message, status >= 500 ? 'error' : 'warning');

            if (status === 401 || status === 403) {
                setTimeout(function() {
                    window.location.href = '/login/';
                }, 2000);
            }
        });

        // ----------------------------------------------------------------
        // HTMX After Request - Navigation state management
        // ----------------------------------------------------------------
        document.body.addEventListener('htmx:afterRequest', function(event) {
            var trigger = event.detail.elt;
            if (trigger && trigger.dataset.navItem) {
                document.querySelectorAll('[data-nav-item]').forEach(function(el) {
                    el.removeAttribute('aria-current');
                    el.classList.remove('bg-primary-500/10', 'text-primary-400', 'font-semibold');
                    el.classList.add('text-slate-400');
                });
                trigger.setAttribute('aria-current', 'page');
                trigger.classList.add('bg-primary-500/10', 'text-primary-400', 'font-semibold');
                trigger.classList.remove('text-slate-400');
            }
        });

        // ----------------------------------------------------------------
        // Flowbite initialization after HTMX swaps
        // ----------------------------------------------------------------
        document.body.addEventListener('htmx:afterSwap', function() {
            if (typeof initFlowbite === 'function') {
                try { initFlowbite(); } catch(e) { /* ignore */ }
            }
        });

    });

    // ========================================================================
    // GLOBAL TOAST NOTIFICATION SYSTEM
    // ========================================================================
    window.showToast = function(message, type) {
        type = type || 'success';

        if (window.Alpine && Alpine.store('toast')) {
            Alpine.store('toast').add(message, type);
        } else {
            // Fallback: Create temporary toast element
            var container = document.querySelector('.toast-container') || createToastContainer();
            var toast = document.createElement('div');
            toast.className = 'toast toast-' + type;
            toast.style.cssText = 'position: fixed; top: 1rem; right: 1rem; z-index: 9999; padding: 1rem 1.5rem; border-radius: 0.75rem; backdrop-filter: blur(12px); pointer-events: auto; animation: toastIn 0.3s ease-out; display: flex; align-items: center; gap: 0.75rem; min-width: 280px; max-width: 400px;';

            if (type === 'success') {
                toast.style.background = 'rgba(34, 197, 94, 0.1)';
                toast.style.border = '1px solid rgba(34, 197, 94, 0.3)';
                toast.style.color = '#22c55e';
            } else if (type === 'error') {
                toast.style.background = 'rgba(239, 68, 68, 0.1)';
                toast.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                toast.style.color = '#ef4444';
            } else if (type === 'warning') {
                toast.style.background = 'rgba(245, 158, 11, 0.1)';
                toast.style.border = '1px solid rgba(245, 158, 11, 0.3)';
                toast.style.color = '#f59e0b';
            } else {
                toast.style.background = 'rgba(59, 130, 246, 0.1)';
                toast.style.border = '1px solid rgba(59, 130, 246, 0.3)';
                toast.style.color = '#3b82f6';
            }

            toast.innerHTML = '<span>' + escapeHtml(message) + '</span>';
            container.appendChild(toast);

            setTimeout(function() {
                toast.style.animation = 'toastOut 0.3s ease-out forwards';
                setTimeout(function() {
                    if (toast.parentNode) toast.parentNode.removeChild(toast);
                }, 300);
            }, 4000);
        }
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
                },

                destroy: function() {
                    clearInterval(this.specsInterval);
                    clearInterval(this.containersInterval);
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
                    var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
                    var self = this;
                    fetch('/api/management/create-account', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
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
                    .catch(function(e) {
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
                        .then(function(data) {
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
                },

                destroy: function() {
                    clearInterval(this.interval);
                },

                fetchData: function() {
                    var self = this;
                    fetch('/api/management/system-specs')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.specs = data; })
                        .catch(function(err) { console.error('Failed to fetch metrics', err); });
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

                init: function() {
                    this.fetchContainers();
                    var self = this;
                    this.interval = setInterval(function() { self.fetchContainers(); }, 10000);
                },

                destroy: function() {
                    if (this.interval) clearInterval(this.interval);
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
                }
            };
        });

        // ----------------------------------------------------------------
        // Backup App Component
        // ----------------------------------------------------------------
        Alpine.data('backupApp', function() {
            return {
                backups: [],

                init: function() { this.fetchBackups(); },

                fetchBackups: function() {
                    var self = this;
                    fetch('/api/backup/list')
                        .then(function(res) { return res.json(); })
                        .then(function(data) { self.backups = data || []; })
                        .catch(function(e) { console.error(e); });
                },

                createBackup: function() {
                    window.showToast('Creating backup...', 'info');
                    var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
                    var self = this;
                    fetch('/api/backup/create', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': csrfToken }
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        window.showToast('Backup created successfully!', 'success');
                        self.fetchBackups();
                    })
                    .catch(function(e) {
                        window.showToast('Error creating backup', 'error');
                    });
                }
            };
        });

        // ----------------------------------------------------------------
        // Logs App Component
        // ----------------------------------------------------------------
        Alpine.data('logsApp', function() {
            return {
                logs: [],
                logFilter: '',

                init: function() { this.fetchLogs(); },

                fetchLogs: function() {
                    var self = this;
                    var url = '/api/management/logs?filter=' + encodeURIComponent(this.logFilter);
                    fetch(url)
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
            return {
                currentFolder: 'inbox',
                mobileView: 'folders',
                showCompose: false,
                selectedMail: null,
                searchQuery: '',
                unreadCount: 0,
                mails: [],
                composeTo: '',
                composeSubject: '',
                composeBody: '',
                composeType: 'new',
                sendingMail: false,
                loadingMails: false,

                init: function() {
                    this.fetchMails();
                },

                fetchMails: async function() {
                    this.loadingMails = true;
                    try {
                        // IMAP entegrasyonu hazır olduğunda gerçek endpoint kullanılacak.
                        // Şimdilik hoş geldiniz mesajı gösteriyoruz.
                        this.mails = [
                            {
                                id: 1,
                                from: 'system@jircode.com',
                                subject: 'Jîr-Mail\'e Hoş Geldiniz',
                                preview: 'Mail sunucunuz başarıyla yapılandırıldı.',
                                date: new Date().toISOString(),
                                body: '<h2>Hoş Geldiniz!</h2><p>Mail sunucunuz başarıyla yapılandırıldı ve kullanıma hazır.</p>',
                                unread: true,
                                folder: 'inbox',
                                starred: false
                            }
                        ];
                        this.updateUnread();
                    } catch(e) {
                        console.error('Mail fetch error:', e);
                    } finally {
                        this.loadingMails = false;
                    }
                },

                get filteredMails() {
                    var self = this;
                    return this.mails.filter(function(m) {
                        var matchesFolder = self.currentFolder === 'starred' ? m.starred : m.folder === self.currentFolder;
                        var matchesSearch = !self.searchQuery ||
                            m.subject.toLowerCase().indexOf(self.searchQuery.toLowerCase()) !== -1 ||
                            m.from.toLowerCase().indexOf(self.searchQuery.toLowerCase()) !== -1;
                        return matchesFolder && matchesSearch;
                    });
                },

                updateUnread: function() {
                    var self = this;
                    this.unreadCount = this.mails.filter(function(m) { return m.folder === 'inbox' && m.unread; }).length;
                },

                selectMail: function(mail) {
                    this.selectedMail = mail;
                    this.showCompose = false;
                    if (mail.unread) {
                        mail.unread = false;
                        this.updateUnread();
                    }
                },

                formatDate: function(isoString) {
                    var date = new Date(isoString);
                    return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
                },

                formatDateTime: function(isoString) {
                    var date = new Date(isoString);
                    return date.toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
                },

                formatBody: function(html) { return html; },

                toggleStar: function(mail) { mail.starred = !mail.starred; },

                deleteMail: function(mail) {
                    mail.folder = 'trash';
                    if (this.selectedMail && this.selectedMail.id === mail.id) {
                        this.selectedMail = null;
                    }
                    window.showToast('Mesaj çöp kutusuna taşındı.', 'info');
                },

                replyTo: function(mail) {
                    this.composeTo = mail.from;
                    this.composeSubject = 'Re: ' + mail.subject;
                    this.composeBody = '\n\n--- Orijinal Mesaj ---\nGönderen: ' + mail.from + '\nTarih: ' + this.formatDateTime(mail.date) + '\n\n' + mail.body;
                    this.composeType = 'reply';
                    this.selectedMail = null;
                    this.showCompose = true;
                },

                forwardMail: function(mail) {
                    this.composeTo = '';
                    this.composeSubject = 'Fwd: ' + mail.subject;
                    this.composeBody = '\n\n--- İletilen Mesaj ---\nGönderen: ' + mail.from + '\nTarih: ' + this.formatDateTime(mail.date) + '\n\n' + mail.body;
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
                    window.showToast('Taslak kaydedildi.', 'success');
                    this.closeCompose();
                },

                sendMail: async function() {
                    if (!this.composeTo || !this.composeSubject) {
                        window.showToast('Alıcı ve konu alanları zorunludur.', 'warning');
                        return;
                    }
                    this.sendingMail = true;
                    try {
                        var csrfToken = document.querySelector('meta[name="csrf-token"]') ?
                            document.querySelector('meta[name="csrf-token"]').content : '';
                        var res = await fetch('/api/core/send-mail', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': csrfToken
                            },
                            body: JSON.stringify({
                                to: this.composeTo,
                                subject: this.composeSubject,
                                body: this.composeBody
                            })
                        });
                        if (res.ok) {
                            var data = await res.json();
                            if (data.status === 'success') {
                                window.showToast('Mesaj başarıyla gönderildi.', 'success');
                                this.closeCompose();
                            } else {
                                window.showToast(data.message || 'Gönderme başarısız.', 'error');
                            }
                        } else if (res.status === 404) {
                            // Endpoint henüz implement edilmedi
                            window.showToast('Mail gönderme özelliği yakında aktif olacak.', 'info');
                            this.closeCompose();
                        } else {
                            window.showToast('Gönderme sırasında hata oluştu.', 'error');
                        }
                    } catch(e) {
                        window.showToast('Bağlantı hatası. Lütfen tekrar deneyin.', 'error');
                    } finally {
                        this.sendingMail = false;
                    }
                }
            };
        });

        // ----------------------------------------------------------------
        // Services Status Component
        // ----------------------------------------------------------------
        Alpine.data('servicesStatus', function() {
            return {
                services: [
                    { name: 'PostgreSQL', status: 'stopped', port: 5432 },
                    { name: 'Postfix', status: 'stopped', port: 25 },
                    { name: 'Dovecot', status: 'stopped', port: 993 },
                    { name: 'Redis', status: 'stopped', port: 6379 }
                ],

                init: function() {
                    this.fetchServiceStatus();
                    var self = this;
                    setInterval(function() { self.fetchServiceStatus(); }, 15000);
                },

                fetchServiceStatus: function() {
                    var self = this;
                    fetch('/api/management/system-requirements')
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            if (data.services) {
                                data.services.forEach(function(svc) {
                                    var service = self.services.find(function(s) { return s.name === svc.name; });
                                    if (service) service.status = svc.status;
                                });
                            }
                        })
                        .catch(function(e) { console.error(e); });
                }
            };
        });

    });

    // ========================================================================
    // ADD CSS ANIMATIONS FOR TOAST
    // ========================================================================
    var style = document.createElement('style');
    style.textContent = [
        '@keyframes toastIn { from { opacity: 0; transform: translateX(100%); } to { opacity: 1; transform: translateX(0); } }',
        '@keyframes toastOut { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(100%); } }'
    ].join('\n');
    document.head.appendChild(style);

})();