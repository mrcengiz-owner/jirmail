/**
 * Webmail ayarlar sayfası — sidebar kabuk ile
 */
document.addEventListener('alpine:init', function() {
    var AVATAR_COLORS = [
        '#8b6cef', '#6d4aff', '#3dd68c', '#f66f7a',
        '#f5c451', '#5b8def', '#e879f9', '#38bdf8'
    ];

    Alpine.data('settingsApp', function() {
        return {
            loading: true,
            saving: false,
            sidebarOpen: false,
            userEmail: '',
            email: '',
            ai_enabled: false,
            ai_provider: 'openrouter',
            ai_model: 'openai/gpt-4o-mini',
            ai_api_key: '',
            ai_system_prompt: '',
            has_api_key: false,
            api_key_hint: '',
            providers: [],
            message: '',
            messageOk: false,
            theme: 'dark',

            init: function() {
                var root = this.$el;
                this.theme = window.WmTheme ? window.WmTheme.get() : 'dark';
                this.userEmail = root.dataset.userEmail || '';
                this.email = this.userEmail;
                window.addEventListener('wm-theme-change', function(e) {
                    this.theme = (e.detail && e.detail.theme) || this.theme;
                }.bind(this));
                this.load();
            },

            avatarColor: function(str) {
                if (!str) return AVATAR_COLORS[0];
                var h = 0;
                for (var i = 0; i < str.length; i++) {
                    h = str.charCodeAt(i) + ((h << 5) - h);
                }
                return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
            },

            initials: function(str) {
                if (!str) return '?';
                var local = (str.split('@')[0] || str).trim();
                var parts = local.split(/[.\s_-]+/).filter(Boolean);
                if (parts.length >= 2) {
                    return (parts[0][0] + parts[1][0]).toUpperCase();
                }
                return local.slice(0, 2).toUpperCase();
            },

            toggleTheme: function() {
                if (window.WmTheme) this.theme = window.WmTheme.toggle();
            },

            setTheme: function(name) {
                if (window.WmTheme) {
                    window.WmTheme.set(name);
                    this.theme = name;
                }
            },

            load: function() {
                var self = this;
                self.loading = true;
                WmApi.json('/api/mail/settings').then(function(r) {
                    self.loading = false;
                    if (!r.data.success) {
                        self.message = r.data.message || 'Ayarlar yüklenemedi';
                        self.messageOk = false;
                        return;
                    }
                    var d = r.data;
                    self.email = d.email || self.userEmail;
                    self.userEmail = self.email;
                    self.ai_enabled = !!d.ai_enabled;
                    self.ai_provider = d.ai_provider || 'openrouter';
                    self.ai_model = d.ai_model || 'openai/gpt-4o-mini';
                    self.ai_system_prompt = d.ai_system_prompt || '';
                    self.has_api_key = !!d.has_api_key;
                    self.api_key_hint = d.api_key_hint || '';
                    self.providers = d.providers || [];
                    self.ai_api_key = '';
                    if (!self.ai_model && self.providers.length) {
                        var p = self.providers.find(function(x) { return x.id === self.ai_provider; });
                        if (p && p.default_model) self.ai_model = p.default_model;
                    }
                }).catch(function() {
                    self.loading = false;
                    self.message = 'Bağlantı hatası';
                    self.messageOk = false;
                });
            },

            onProviderChange: function() {
                var p = this.providers.find(function(x) { return x.id === this.ai_provider; }.bind(this));
                if (p && p.default_model) {
                    this.ai_model = p.default_model;
                }
            },

            save: function() {
                var self = this;
                self.saving = true;
                self.message = '';
                var body = {
                    ai_enabled: self.ai_enabled,
                    ai_provider: self.ai_provider,
                    ai_model: self.ai_model,
                    ai_system_prompt: self.ai_system_prompt
                };
                if (self.ai_api_key && self.ai_api_key.trim()) {
                    body.ai_api_key = self.ai_api_key.trim();
                }
                WmApi.json('/api/mail/settings', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                }).then(function(r) {
                    self.saving = false;
                    if (r.data.success) {
                        self.message = 'Ayarlar kaydedildi';
                        self.messageOk = true;
                        self.has_api_key = !!r.data.has_api_key;
                        self.api_key_hint = r.data.api_key_hint || '';
                        self.ai_api_key = '';
                    } else {
                        self.message = r.data.message || 'Kaydedilemedi';
                        self.messageOk = false;
                    }
                }).catch(function() {
                    self.saving = false;
                    self.message = 'Bağlantı hatası';
                    self.messageOk = false;
                });
            },

            clearApiKey: function() {
                if (!confirm('API anahtarı silinsin mi?')) return;
                var self = this;
                self.saving = true;
                WmApi.json('/api/mail/settings', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ai_api_key: '' })
                }).then(function(r) {
                    self.saving = false;
                    if (r.data.success) {
                        self.has_api_key = false;
                        self.api_key_hint = '';
                        self.ai_enabled = false;
                        self.message = 'API anahtarı kaldırıldı';
                        self.messageOk = true;
                    }
                });
            }
        };
    });
});
