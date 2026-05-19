/**
 * Hesaplar sayfası — accountsApp (app.js'den bağımsız, güncel sürüm).
 * alpine:init öncesi veya sonrası kayıt için çift yol.
 */
(function() {
    'use strict';

    function parseJsonScript(id, fallback) {
        var el = document.getElementById(id);
        if (!el) return fallback;
        try {
            return JSON.parse(el.textContent) || fallback;
        } catch (e) {
            return fallback;
        }
    }

    var defaultRoles = [
        { value: 'FULL', label: 'Süper Yönetici', description: 'Mail sunucusu paneli + webmail.' },
        { value: 'USER', label: 'Webmail Kullanıcısı', description: 'Yalnızca webmail; panele erişim yok.' },
        { value: 'SEND', label: 'Yalnızca Gönderme', description: 'Webmail; gönderim açık.' },
        { value: 'RECV', label: 'Yalnızca Alma', description: 'Webmail; gelen kutusu açık.' },
        { value: 'BLOCK', label: 'Şirket İçi', description: 'Webmail; dış gönderim kapalı.' }
    ];

    function accountsAppFactory() {
        return {
            JIR_KEY: window.JIR_KEY || '',
            accounts: parseJsonScript('accounts-bootstrap', []),
            roleChoices: parseJsonScript('role-choices', defaultRoles),
            domains: window.DOMAINS || [],
            showAddModal: false,
            showRoleModal: false,
            editAccount: null,
            editRole: 'USER',
            roleSaving: false,
            roleSaveError: '',
            loading: false,
            newAccount: { username: '', domain: '', password: '', role: 'USER' },

            init: function() {
                var roles = parseJsonScript('role-choices', null);
                if (Array.isArray(roles) && roles.length) {
                    this.roleChoices = roles;
                }
                if (!this.domains.length) {
                    var d = parseJsonScript('domains-bootstrap', null);
                    if (Array.isArray(d)) {
                        this.domains = d.map(function(x) { return typeof x === 'string' ? x : x.name; });
                    }
                }
                if (this.domains.length && !this.newAccount.domain) {
                    this.newAccount.domain = this.domains[0];
                }
                var boot = parseJsonScript('accounts-bootstrap', null);
                if (Array.isArray(boot)) {
                    this.accounts = boot;
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
                        if (window.showToast) window.showToast('Hesap listesi alınamadı', 'error');
                    });
            },

            closeAddModal: function() {
                this.showAddModal = false;
                if (!this.showRoleModal) document.body.style.overflow = '';
            },

            openAddModal: function() {
                this.newAccount = {
                    username: '',
                    domain: this.domains[0] || '',
                    password: '',
                    role: 'USER'
                };
                this.showAddModal = true;
                document.body.style.overflow = 'hidden';
            },

            openRoleModal: function(acc) {
                this.editAccount = acc;
                this.editRole = acc.role || 'USER';
                this.roleSaveError = '';
                this.showRoleModal = true;
                document.body.style.overflow = 'hidden';
            },

            closeRoleModal: function() {
                if (this.roleSaving) return;
                this.showRoleModal = false;
                this.roleSaveError = '';
                this.editAccount = null;
                document.body.style.overflow = '';
            },

            selectRole: function(value) {
                this.editRole = value;
                this.roleSaveError = '';
            },

            rolePermFlags: function(role) {
                var r = (role || '').toUpperCase();
                return {
                    panel: r === 'FULL',
                    webmail: r === 'FULL' || r === 'USER' || r === 'SEND' || r === 'RECV' || r === 'BLOCK',
                    send: r === 'FULL' || r === 'USER' || r === 'SEND',
                    recv: r === 'FULL' || r === 'USER' || r === 'RECV'
                };
            },

            saveRole: function() {
                var self = this;
                if (!this.editAccount || !this.editRole) return;
                this.roleSaving = true;
                this.roleSaveError = '';
                var url = '/api/core/update-role/' + encodeURIComponent(this.editAccount.email);
                if (self.JIR_KEY) url += '?key=' + encodeURIComponent(self.JIR_KEY);
                fetch(url, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : ''
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({ role: this.editRole })
                })
                    .then(function(r) {
                        return r.json().then(function(data) {
                            return { ok: r.ok, status: r.status, data: data };
                        }).catch(function() {
                            return { ok: false, status: r.status, data: { message: 'Sunucu yanıtı okunamadı' } };
                        });
                    })
                    .then(function(res) {
                        if (res.ok && res.data && res.data.status === 'success') {
                            self.closeRoleModal();
                            if (window.showToast) window.showToast(res.data.message || 'Yetki güncellendi', 'success');
                            self.refreshAccounts();
                        } else {
                            var msg = (res.data && res.data.message) || 'Yetki güncellenemedi';
                            self.roleSaveError = msg;
                            if (window.showToast) window.showToast(msg, 'error');
                        }
                    })
                    .catch(function() {
                        self.roleSaveError = 'Bağlantı hatası. Sayfayı yenileyip tekrar deneyin.';
                        if (window.showToast) window.showToast('Bağlantı hatası', 'error');
                    })
                    .finally(function() { self.roleSaving = false; });
            },

            roleDescription: function(role) {
                var r = (this.roleChoices || []).find(function(x) { return x.value === role; });
                return r ? r.description : '';
            },

            permissionHint: function(acc) {
                var p = acc.permissions || {};
                if (p.can_access_panel) return 'Mail sunucusu paneli + webmail';
                return 'Yalnızca webmail';
            },

            createAccount: function() {
                var self = this;
                if (!this.newAccount.username || !this.newAccount.password || !this.newAccount.domain) {
                    if (window.showToast) window.showToast('Kullanıcı adı, domain ve parola zorunludur.', 'warning');
                    return;
                }
                this.loading = true;
                fetch('/api/management/create-account', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : '' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        username: this.newAccount.username,
                        domain: this.newAccount.domain,
                        password: this.newAccount.password,
                        role: this.newAccount.role || 'USER'
                    })
                })
                    .then(function(r) {
                        if (!r.ok && r.status === 403) {
                            throw new Error('Oturum veya CSRF hatası');
                        }
                        return r.json();
                    })
                    .then(function(data) {
                        if (data.status === 'success') {
                            self.showAddModal = false;
                            if (window.showToast) window.showToast('Hesap oluşturuldu: ' + (data.email || ''), 'success');
                            self.refreshAccounts();
                        } else {
                            if (window.showToast) window.showToast(data.message || 'Hesap oluşturulamadı', 'error');
                        }
                    })
                    .catch(function() {
                        if (window.showToast) window.showToast('Bağlantı hatası', 'error');
                    })
                    .finally(function() { self.loading = false; });
            },

            toggleAccount: function(acc) {
                var self = this;
                fetch('/api/core/toggle-account/' + encodeURIComponent(acc.email) + '?key=' + encodeURIComponent(self.JIR_KEY), {
                    method: 'PATCH',
                    headers: { 'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : '' }
                })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.status === 'success') {
                            if (window.showToast) window.showToast('Hesap durumu güncellendi', 'success');
                            self.refreshAccounts();
                        } else {
                            if (window.showToast) window.showToast(data.message || 'İşlem başarısız', 'error');
                        }
                    })
                    .catch(function() {
                        if (window.showToast) window.showToast('Bağlantı hatası', 'error');
                    });
            },

            deleteAccount: function(acc) {
                if (acc.is_superuser) {
                    if (window.showToast) window.showToast('Kurulum yöneticisi silinemez.', 'warning');
                    return;
                }
                if (!confirm(acc.email + ' hesabı silinsin mi?')) return;
                var self = this;
                fetch('/api/core/delete-account/' + encodeURIComponent(acc.email) + '?key=' + encodeURIComponent(self.JIR_KEY), {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : '' }
                })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.status === 'success') {
                            if (window.showToast) window.showToast('Hesap silindi', 'success');
                            self.refreshAccounts();
                        } else {
                            if (window.showToast) window.showToast(data.message || 'Silinemedi', 'error');
                        }
                    })
                    .catch(function() {
                        if (window.showToast) window.showToast('Bağlantı hatası', 'error');
                    });
            },

            roleLabel: function(role) {
                var labels = {
                    FULL: 'Süper Yönetici',
                    USER: 'Webmail',
                    SEND: 'Yalnız gönder',
                    RECV: 'Yalnız al',
                    BLOCK: 'Dahili'
                };
                return labels[role] || role;
            }
        };
    }

    function registerAccountsApp() {
        if (typeof Alpine === 'undefined') return;
        Alpine.data('accountsApp', accountsAppFactory);
    }

    window.accountsApp = accountsAppFactory;
    document.addEventListener('alpine:init', registerAccountsApp);
    if (typeof Alpine !== 'undefined') {
        registerAccountsApp();
    }
})();
