/**
 * Webmail ayarlar sayfası
 */
document.addEventListener('alpine:init', function() {
    Alpine.data('settingsApp', function() {
        return {
            loading: true,
            saving: false,
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
                this.theme = window.WmTheme ? window.WmTheme.get() : 'dark';
                this.load();
            },

            toggleTheme: function() {
                if (window.WmTheme) this.theme = window.WmTheme.toggle();
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
                    self.email = d.email || '';
                    self.ai_enabled = !!d.ai_enabled;
                    self.ai_provider = d.ai_provider || 'openrouter';
                    self.ai_model = d.ai_model || 'openai/gpt-4o-mini';
                    self.ai_system_prompt = d.ai_system_prompt || '';
                    self.has_api_key = !!d.has_api_key;
                    self.api_key_hint = d.api_key_hint || '';
                    self.providers = d.providers || [];
                    self.ai_api_key = '';
                }).catch(function() {
                    self.loading = false;
                    self.message = 'Bağlantı hatası';
                    self.messageOk = false;
                });
            },

            onProviderChange: function() {
                var p = this.providers.find(function(x) { return x.id === this.ai_provider; }.bind(this));
                if (p && p.default_model && !this.ai_model) {
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
