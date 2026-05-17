/**
 * Webmail — modüler Alpine uygulaması (Gmail tarzı, kompakt)
 */
document.addEventListener('alpine:init', function() {
    var FOLDER_MAP = { inbox: 'INBOX', sent: 'Sent', drafts: 'Drafts', trash: 'Trash', starred: 'INBOX' };

    Alpine.data('mailApp', function() {
        return {
            currentFolder: 'inbox',
            mobileView: 'list',
            showCompose: false,
            showAi: false,
            selectedMail: null,
            searchQuery: '',
            unreadCount: 0,
            mails: [],
            page: 1,
            pageSize: 50,
            composeTo: '', composeCc: '', composeSubject: '', composeBody: '',
            composeFiles: [],
            scheduleAt: '',
            sendingMail: false,
            loadingMails: false,
            aiEnabled: false,
            aiMessages: [],
            aiInput: '',
            aiLoading: false,
            eventSource: null,

            init: function() {
                var self = this;
                this.loadAiStatus();
                this.syncAllFolders().then(function() { self.fetchMails(); });
                this.$watch('currentFolder', function() {
                    self.page = 1;
                    self.selectedMail = null;
                    self.fetchMails();
                });
                this.openStream();
            },

            loadAiStatus: function() {
                var self = this;
                WmApi.json('/api/mail/ai/status').then(function(r) {
                    if (r.data.success) self.aiEnabled = r.data.ai_available;
                });
            },

            imapFolder: function() { return FOLDER_MAP[this.currentFolder] || 'INBOX'; },

            fetchMails: function() {
                var self = this;
                self.loadingMails = true;
                var url = '/api/mail/messages?folder=' + encodeURIComponent(self.imapFolder()) +
                    '&page=' + self.page + '&page_size=' + self.pageSize;
                if (self.searchQuery) url += '&q=' + encodeURIComponent(self.searchQuery);
                WmApi.json(url).then(function(r) {
                    if (!r.data.success) { self.mails = []; return; }
                    self.mails = (r.data.messages || []).map(function(m) {
                        return {
                            uid: m.uid, from: m.from_name || m.from, from_addr: m.from,
                            subject: m.subject || '(konu yok)', preview: m.snippet || '',
                            date: m.date, body: '', bodyLoaded: false,
                            unread: !m.is_seen, starred: m.is_flagged,
                            hasAttachments: m.has_attachments,
                            deliveryStatus: m.delivery_status || 'read'
                        };
                    });
                    self.unreadCount = self.mails.filter(function(m) { return m.unread; }).length;
                }).finally(function() { self.loadingMails = false; });
            },

            syncAllFolders: function() {
                return WmApi.json('/api/mail/sync-all', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            },

            selectMail: function(mail) {
                var self = this;
                self.selectedMail = mail;
                self.showCompose = false;
                if (!mail.bodyLoaded && mail.uid > 0) {
                    WmApi.json('/api/mail/messages/' + mail.uid + '/body?folder=' + encodeURIComponent(self.imapFolder()))
                        .then(function(r) {
                            if (r.data.success) {
                                mail.body = r.data.html || '<pre>' + (r.data.plain || '') + '</pre>';
                                mail.bodyLoaded = true;
                            }
                        });
                }
                if (mail.unread) {
                    mail.unread = false;
                    WmApi.json('/api/mail/messages/' + mail.uid + '/flags', {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ folder: self.imapFolder(), seen: true })
                    });
                }
            },

            openCompose: function() {
                this.showCompose = true;
                this.mobileView = 'detail';
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
                    if (ok) { self.closeCompose(); self.currentFolder = 'sent'; self.fetchMails(); }
                };
                if (self.composeFiles.length) {
                    var fd = new FormData();
                    fd.append('to', self.composeTo);
                    fd.append('subject', self.composeSubject);
                    fd.append('body_text', self.composeBody);
                    self.composeFiles.forEach(function(f) { fd.append('attachments', f); });
                    WmApi.fetch('/api/mail/send-attachments', { method: 'POST', body: fd })
                        .then(function(r) { return r.json(); })
                        .then(function(d) { done(d.success, d.message || (d.success ? 'Gönderildi' : 'Hata')); })
                        .catch(function(e) { done(false, e.message); });
                } else {
                    WmApi.json('/api/mail/send', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ to: self.composeTo, cc: self.composeCc, subject: self.composeSubject, body_text: self.composeBody })
                    }).then(function(r) { done(r.data.success, r.data.message || ''); });
                }
            },

            scheduleMail: function() {
                var self = this;
                WmApi.json('/api/mail/schedule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to: self.composeTo, subject: self.composeSubject,
                        body_text: self.composeBody, send_at: self.scheduleAt, cc: self.composeCc
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
                this.composeTo = this.composeCc = this.composeSubject = this.composeBody = '';
                this.composeFiles = [];
                this.scheduleAt = '';
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
                }).finally(function() { self.aiLoading = false; });
            },

            formatDate: function(iso) {
                if (!iso) return '';
                var d = new Date(iso);
                var n = new Date();
                if (d.toDateString() === n.toDateString()) {
                    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
                }
                return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
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
