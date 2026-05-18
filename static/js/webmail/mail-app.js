/**
 * Jîr-Mail Webmail — Proton tarzı Alpine uygulaması
 */
document.addEventListener('alpine:init', function() {
    var FOLDER_MAP = {
        inbox: 'INBOX',
        sent: 'Sent',
        drafts: 'Drafts',
        trash: 'Trash',
        starred: 'INBOX'
    };
    var FOLDER_TITLES = {
        inbox: 'Gelen kutusu',
        sent: 'Gönderilen',
        drafts: 'Taslaklar',
        trash: 'Çöp kutusu',
        starred: 'Yıldızlı'
    };
    var AVATAR_COLORS = [
        '#8b6cef', '#6d4aff', '#3dd68c', '#f66f7a',
        '#f5c451', '#5b8def', '#e879f9', '#38bdf8'
    ];

    Alpine.data('mailApp', function() {
        return {
            currentFolder: 'inbox',
            mobileView: 'list',
            sidebarOpen: false,
            showCompose: false,
            showAi: false,
            selectedMail: null,
            searchQuery: '',
            unreadCount: 0,
            mails: [],
            page: 1,
            pageSize: 50,
            composeTo: '',
            composeCc: '',
            composeSubject: '',
            composeBody: '',
            composeFiles: [],
            scheduleAt: '',
            sendingMail: false,
            loadingMails: false,
            syncing: false,
            aiEnabled: false,
            userEmail: '',
            aiMessages: [],
            aiInput: '',
            aiLoading: false,
            eventSource: null,

            init: function() {
                var self = this;
                var root = this.$el;
                self.userEmail = root.dataset.userEmail || '';
                if (root.dataset.aiEnabled === 'true') {
                    self.aiEnabled = true;
                }
                self.loadAiStatus();
                self.syncAllFolders().then(function() { self.fetchMails(); });
                self.$watch('currentFolder', function() {
                    self.page = 1;
                    self.selectedMail = null;
                    self.fetchMails();
                });
                self.openStream();
            },

            loadAiStatus: function() {
                var self = this;
                WmApi.json('/api/mail/ai/status').then(function(r) {
                    if (r.data.success) self.aiEnabled = r.data.ai_available;
                });
            },

            imapFolder: function() {
                return FOLDER_MAP[this.currentFolder] || 'INBOX';
            },

            folderTitle: function() {
                return FOLDER_TITLES[this.currentFolder] || 'Posta';
            },

            emptyFolderMessage: function() {
                if (this.searchQuery) return 'Aramanızla eşleşen mesaj yok.';
                return 'Bu klasörde mesaj yok.';
            },

            setFolder: function(id) {
                this.currentFolder = id;
                this.mobileView = 'list';
                this.sidebarOpen = false;
                this.selectedMail = null;
                this.showCompose = false;
            },

            fetchMails: function() {
                var self = this;
                self.loadingMails = true;
                var url = '/api/mail/messages?folder=' + encodeURIComponent(self.imapFolder()) +
                    '&page=' + self.page + '&page_size=' + self.pageSize;
                if (self.searchQuery) {
                    url += '&q=' + encodeURIComponent(self.searchQuery);
                }
                WmApi.json(url).then(function(r) {
                    if (!r.data.success) {
                        self.mails = [];
                        return;
                    }
                    var list = (r.data.messages || []).map(function(m) {
                        return {
                            uid: m.uid,
                            from: m.from_name || m.from,
                            from_addr: m.from,
                            subject: m.subject || '(konu yok)',
                            preview: m.snippet || '',
                            date: m.date,
                            body: '',
                            bodyLoaded: false,
                            unread: !m.is_seen,
                            starred: m.is_flagged,
                            hasAttachments: m.has_attachments,
                            deliveryStatus: m.delivery_status || 'read'
                        };
                    });
                    if (self.currentFolder === 'starred') {
                        list = list.filter(function(m) { return m.starred; });
                    }
                    self.mails = list;
                    self.unreadCount = list.filter(function(m) { return m.unread; }).length;
                }).finally(function() {
                    self.loadingMails = false;
                });
            },

            syncNow: function() {
                var self = this;
                self.syncing = true;
                self.syncAllFolders()
                    .then(function() { return self.fetchMails(); })
                    .finally(function() { self.syncing = false; });
            },

            syncAllFolders: function() {
                return WmApi.json('/api/mail/sync-all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}'
                });
            },

            selectMail: function(mail) {
                var self = this;
                self.selectedMail = mail;
                self.showCompose = false;
                self.mobileView = 'detail';
                if (!mail.bodyLoaded && mail.uid > 0) {
                    WmApi.json('/api/mail/messages/' + mail.uid + '/body?folder=' +
                        encodeURIComponent(self.imapFolder()))
                        .then(function(r) {
                            if (r.data.success) {
                                mail.body = r.data.html || '<pre>' + (r.data.plain || '') + '</pre>';
                                mail.bodyLoaded = true;
                            }
                        });
                }
                if (mail.unread) {
                    mail.unread = false;
                    self.unreadCount = Math.max(0, self.unreadCount - 1);
                    WmApi.json('/api/mail/messages/' + mail.uid + '/flags', {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ folder: self.imapFolder(), seen: true })
                    });
                }
            },

            goBack: function() {
                this.mobileView = 'list';
                this.selectedMail = null;
            },

            openCompose: function() {
                this.showCompose = true;
                this.selectedMail = null;
                this.mobileView = 'compose';
                this.sidebarOpen = false;
            },

            openAi: function() {
                this.showAi = true;
                this.mobileView = 'ai';
            },

            closeAi: function() {
                this.showAi = false;
                if (this.mobileView === 'ai') {
                    this.mobileView = this.selectedMail ? 'detail' : 'list';
                }
            },

            replyTo: function() {
                if (!this.selectedMail) return;
                var addr = this.selectedMail.from_addr || this.selectedMail.from || '';
                var match = addr.match(/<([^>]+)>/) || [null, addr];
                this.composeTo = match[1] || addr;
                this.composeSubject = 'Re: ' + (this.selectedMail.subject || '').replace(/^Re:\s*/i, '');
                this.composeBody = '\n\n---\n';
                this.openCompose();
            },

            toggleStar: function(mail) {
                if (!mail || !mail.uid) return;
                var self = this;
                var next = !mail.starred;
                mail.starred = next;
                WmApi.json('/api/mail/messages/' + mail.uid + '/flags', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folder: self.imapFolder(), flagged: next })
                }).then(function(r) {
                    if (!r.data.success) mail.starred = !next;
                });
            },

            deleteMail: function(mail) {
                if (!mail || !mail.uid) return;
                var self = this;
                if (!confirm('Bu mesaj silinsin mi?')) return;
                WmApi.json('/api/mail/messages/' + mail.uid + '?folder=' +
                    encodeURIComponent(self.imapFolder()), { method: 'DELETE' })
                    .then(function(r) {
                        if (r.data.success) {
                            showToast('Mesaj silindi', 'success');
                            self.mails = self.mails.filter(function(m) { return m.uid !== mail.uid; });
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        } else {
                            showToast(r.data.message || 'Silinemedi', 'error');
                        }
                    });
            },

            onFiles: function(ev) {
                this.composeFiles = Array.from(ev.target.files || []);
            },

            sendMail: function() {
                var self = this;
                if (!self.composeTo || !self.composeSubject) {
                    showToast('Alıcı ve konu zorunlu', 'warning');
                    return;
                }
                if (self.scheduleAt) {
                    return self.scheduleMail();
                }
                self.sendingMail = true;
                var done = function(ok, msg) {
                    self.sendingMail = false;
                    showToast(msg, ok ? 'success' : 'error');
                    if (ok) {
                        self.closeCompose();
                        self.currentFolder = 'sent';
                        self.fetchMails();
                    }
                };
                if (self.composeFiles.length) {
                    var fd = new FormData();
                    fd.append('to', self.composeTo);
                    fd.append('subject', self.composeSubject);
                    fd.append('body_text', self.composeBody);
                    self.composeFiles.forEach(function(f) { fd.append('attachments', f); });
                    WmApi.fetch('/api/mail/send-attachments', { method: 'POST', body: fd })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            done(d.success, d.message || (d.success ? 'Gönderildi' : 'Hata'));
                        })
                        .catch(function(e) { done(false, e.message); });
                } else {
                    WmApi.json('/api/mail/send', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            to: self.composeTo,
                            cc: self.composeCc,
                            subject: self.composeSubject,
                            body_text: self.composeBody
                        })
                    }).then(function(r) {
                        done(r.data.success, r.data.message || '');
                    });
                }
            },

            scheduleMail: function() {
                var self = this;
                WmApi.json('/api/mail/schedule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to: self.composeTo,
                        subject: self.composeSubject,
                        body_text: self.composeBody,
                        send_at: self.scheduleAt,
                        cc: self.composeCc
                    })
                }).then(function(r) {
                    if (r.data.success) {
                        showToast('Planlandı: ' + r.data.send_at, 'success');
                        self.closeCompose();
                    } else {
                        showToast(r.data.message || 'Planlama başarısız', 'error');
                    }
                });
            },

            closeCompose: function() {
                this.showCompose = false;
                this.composeTo = '';
                this.composeCc = '';
                this.composeSubject = '';
                this.composeBody = '';
                this.composeFiles = [];
                this.scheduleAt = '';
                this.mobileView = this.selectedMail ? 'detail' : 'list';
            },

            sendAi: function() {
                var self = this;
                if (!self.aiInput.trim() || self.aiLoading) return;
                var msg = self.aiInput.trim();
                self.aiMessages.push({ role: 'user', text: msg });
                self.aiInput = '';
                self.aiLoading = true;
                WmApi.json('/api/mail/ai/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: msg,
                        context_subject: self.selectedMail ? self.selectedMail.subject : ''
                    })
                }).then(function(r) {
                    if (r.data.success) {
                        self.aiMessages.push({ role: 'assistant', text: r.data.reply });
                        var act = r.data.action || {};
                        if (act.intent === 'send_mail' && act.to) {
                            self.composeTo = act.to;
                            self.composeSubject = act.subject || '';
                            self.composeBody = act.body || '';
                            self.openCompose();
                        }
                        if (act.intent === 'schedule_mail' && act.to) {
                            self.composeTo = act.to;
                            self.composeSubject = act.subject || '';
                            self.composeBody = act.body || '';
                            if (act.send_at) self.scheduleAt = act.send_at;
                            self.openCompose();
                        }
                    } else {
                        showToast(r.data.message || 'AI hatası', 'error');
                    }
                }).finally(function() {
                    self.aiLoading = false;
                });
            },

            initials: function(name) {
                if (!name) return '?';
                var s = String(name).replace(/<[^>]+>/g, '').trim();
                var parts = s.split(/\s+/).filter(Boolean);
                if (parts.length >= 2) {
                    return (parts[0][0] + parts[1][0]).toUpperCase();
                }
                return s.slice(0, 2).toUpperCase();
            },

            avatarColor: function(name) {
                var s = String(name || '');
                var h = 0;
                for (var i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i);
                return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
            },

            displayFrom: function(mail) {
                if (!mail) return '';
                var f = mail.from || '';
                return f.replace(/<[^>]+>/g, '').trim() || mail.from_addr || f;
            },

            formatDate: function(iso) {
                if (!iso) return '';
                var d = new Date(iso);
                var n = new Date();
                if (d.toDateString() === n.toDateString()) {
                    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
                }
                var y = new Date();
                y.setFullYear(y.getFullYear() - 1);
                if (d > y) {
                    return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
                }
                return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric' });
            },

            openStream: function() {
                var self = this;
                try {
                    self.eventSource = new EventSource('/api/mail/stream');
                    self.eventSource.onmessage = function() { self.fetchMails(); };
                } catch (e) { /* ignore */ }
            }
        };
    });
});
