/**
 * Webmail — cihaz / istemci kurulum rehberi (IMAP/SMTP)
 */
document.addEventListener('alpine:init', function() {
    var AVATAR_COLORS = [
        '#8b6cef', '#6d4aff', '#3dd68c', '#f66f7a',
        '#f5c451', '#5b8def', '#e879f9', '#38bdf8'
    ];

    Alpine.data('clientSetupGuide', function() {
        return {
            loading: true,
            error: '',
            sidebarOpen: false,
            userEmail: '',
            clientSetup: null,
            clientTab: 'ios',
            copyToast: '',

            init: function() {
                var root = this.$el;
                this.userEmail = root.dataset.userEmail || '';
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

            load: function() {
                var self = this;
                self.loading = true;
                self.error = '';
                WmApi.json('/api/mail/client-setup').then(function(r) {
                    self.loading = false;
                    if (!r.data.success) {
                        self.error = r.data.message || 'Kurulum bilgisi yüklenemedi';
                        return;
                    }
                    self.clientSetup = r.data.client_setup || null;
                    if (self.clientSetup && self.clientSetup.clients && self.clientSetup.clients.length) {
                        self.clientTab = self.clientSetup.clients[0].id;
                    }
                }).catch(function() {
                    self.loading = false;
                    self.error = 'Bağlantı hatası';
                });
            },

            activeClientGuide: function() {
                if (!this.clientSetup || !this.clientSetup.clients) return null;
                var tab = this.clientTab;
                var found = this.clientSetup.clients.find(function(c) { return c.id === tab; });
                return found || this.clientSetup.clients[0] || null;
            },

            copyValue: function(text) {
                var self = this;
                var value = (text || '').toString();
                if (!value) return;
                var done = function(ok) {
                    self.copyToast = ok ? 'Panoya kopyalandı' : 'Kopyalanamadı — elle seçin';
                    window.setTimeout(function() { self.copyToast = ''; }, 2200);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(value).then(function() { done(true); }).catch(function() { done(false); });
                    return;
                }
                try {
                    var ta = document.createElement('textarea');
                    ta.value = value;
                    ta.setAttribute('readonly', '');
                    ta.style.position = 'absolute';
                    ta.style.left = '-9999px';
                    document.body.appendChild(ta);
                    ta.select();
                    done(document.execCommand('copy'));
                    document.body.removeChild(ta);
                } catch (e) {
                    done(false);
                }
            }
        };
    });
});
