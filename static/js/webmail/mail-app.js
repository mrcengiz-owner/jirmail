/**
 * Jîr-Mail Webmail — Proton tarzı SPA (Alpine.js + Fetch API)
 */
document.addEventListener('alpine:init', function() {
    var FOLDER_MAP = {
        inbox: 'INBOX',
        sent: 'Sent',
        drafts: 'Drafts',
        archive: 'Archive',
        trash: 'Trash',
        starred: 'INBOX'
    };
    var FOLDER_TITLES = {
        inbox: 'Gelen kutusu',
        sent: 'Gönderilen',
        drafts: 'Taslaklar',
        archive: 'Arşiv',
        trash: 'Çöp kutusu',
        starred: 'Yıldızlı'
    };
    var AVATAR_COLORS = [
        '#6366f1', '#8b5cf6', '#10b981', '#f43f5e',
        '#f59e0b', '#3b82f6', '#ec4899', '#06b6d4'
    ];
    var ICON_INBOX = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859M12 3v10.5m0 0l-3.75-3.75M12 13.5l3.75-3.75"/></svg>';
    var ICON_SENT = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"/></svg>';
    var ICON_DRAFT = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>';
    var ICON_ARCHIVE = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5a1.125 1.125 0 00-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/></svg>';
    var ICON_TRASH = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/></svg>';
    var ICON_STAR = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/></svg>';

    Alpine.data('mailApp', function() {
        return {
            folderNav: [
                { id: 'inbox', label: 'Gelen kutusu', icon: ICON_INBOX },
                { id: 'sent', label: 'Gönderilen', icon: ICON_SENT },
                { id: 'drafts', label: 'Taslaklar', icon: ICON_DRAFT },
                { id: 'archive', label: 'Arşiv', icon: ICON_ARCHIVE },
                { id: 'starred', label: 'Yıldızlı', icon: ICON_STAR },
                { id: 'trash', label: 'Çöp kutusu', icon: ICON_TRASH }
            ],
            currentFolder: 'inbox',
            mobileView: 'list',
            sidebarOpen: false,
            composeOpen: false,
            composeMinimized: false,
            selectedMail: null,
            searchQuery: '',
            unreadCount: 0,
            mails: [],
            page: 1,
            pageSize: 50,
            composeTo: '',
            composeCc: '',
            composeSubject: '',
            composeBodyHtml: '',
            composeBodyText: '',
            composeFiles: [],
            sendingMail: false,
            loadingMails: false,
            syncing: false,
            userEmail: '',
            selectedIds: [],
            allSelected: false,
            quota: null,
            quill: null,
            draftTimer: null,
            draftUid: null,
            draftSaving: false,
            draftSavedAt: '',
            eventSource: null,

            get hasSelection() {
                return this.selectedIds.length > 0;
            },

            init: function() {
                var self = this;
                var root = this.$el;
                self.userEmail = root.dataset.userEmail || '';
                self.loadQuota();
                self.syncAllFolders().then(function() { self.fetchMails(); });
                self.$watch('currentFolder', function() {
                    self.page = 1;
                    self.selectedMail = null;
                    self.clearSelection();
                    self.fetchMails();
                });
                self.openStream();
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

            quotaLabel: function() {
                if (!this.quota) return '';
                if (this.quota.unlimited) return 'Sınırsız';
                var u = (this.quota.used_bytes / (1024 * 1024)).toFixed(1);
                var q = (this.quota.quota_bytes / (1024 * 1024)).toFixed(0);
                return u + ' / ' + q + ' MB';
            },

            loadQuota: function() {
                var self = this;
                WmApi.json('/api/mail/quota').then(function(r) {
                    if (r.data.success) self.quota = r.data;
                });
            },

            onSearch: function() {
                this.page = 1;
                this.fetchMails();
            },

            setFolder: function(id) {
                this.currentFolder = id;
                this.mobileView = 'list';
                this.sidebarOpen = false;
                this.selectedMail = null;
                this.closeCompose();
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
                            from: m.from,
                            from_name: m.from_name,
                            from_addr: m.from_addr || m.from,
                            from_display: m.from,
                            subject: m.subject || '(konu yok)',
                            preview: m.snippet || '',
                            date: m.date,
                            body: '',
                            bodyLoaded: false,
                            attachments: [],
                            unread: !m.is_seen,
                            starred: m.is_flagged,
                            hasAttachments: m.has_attachments
                        };
                    });
                    if (self.currentFolder === 'starred') {
                        list = list.filter(function(m) { return m.starred; });
                    }
                    self.mails = list;
                    if (self.currentFolder === 'inbox') {
                        self.unreadCount = list.filter(function(m) { return m.unread; }).length;
                    }
                    self.clearSelection();
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
                self.composeOpen = false;
                self.mobileView = 'detail';
                if (!mail.bodyLoaded && mail.uid > 0) {
                    WmApi.json('/api/mail/messages/' + mail.uid + '/body?folder=' +
                        encodeURIComponent(self.imapFolder()))
                        .then(function(r) {
                            if (r.data.success) {
                                mail.body = r.data.html || '<pre>' + self.escapeHtml(r.data.plain || '') + '</pre>';
                                mail.attachments = r.data.attachments || [];
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

            sanitizeHtml: function(html) {
                if (!html) return '';
                if (window.DOMPurify) {
                    return DOMPurify.sanitize(html, {
                        USE_PROFILES: { html: true },
                        FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form'],
                        FORBID_ATTR: ['onerror', 'onload', 'onclick']
                    });
                }
                return this.escapeHtml(html).replace(/\n/g, '<br>');
            },

            escapeHtml: function(s) {
                var d = document.createElement('div');
                d.textContent = s || '';
                return d.innerHTML;
            },

            openCompose: function() {
                var self = this;
                self.composeOpen = true;
                self.composeMinimized = false;
                self.selectedMail = null;
                self.mobileView = 'detail';
                self.sidebarOpen = false;
                self.$nextTick(function() { self.initQuill(); self.startDraftAutosave(); });
            },

            closeCompose: function() {
                var self = this;
                if (self.composeTo || self.composeSubject || self.getEditorText()) {
                    self.saveDraft(false);
                }
                self.stopDraftAutosave();
                self.destroyQuill();
                self.composeOpen = false;
                self.composeMinimized = false;
                self.composeTo = '';
                self.composeCc = '';
                self.composeSubject = '';
                self.composeBodyHtml = '';
                self.composeBodyText = '';
                self.composeFiles = [];
                self.draftUid = null;
                self.draftSavedAt = '';
                self.mobileView = self.selectedMail ? 'detail' : 'list';
            },

            initQuill: function() {
                if (this.quill || typeof Quill === 'undefined') return;
                var el = document.getElementById('wm-quill-editor');
                if (!el) return;
                this.quill = new Quill(el, {
                    theme: 'snow',
                    placeholder: 'Mesajınızı yazın…',
                    modules: {
                        toolbar: [
                            ['bold', 'italic', 'underline'],
                            [{ list: 'ordered' }, { list: 'bullet' }],
                            ['link'],
                            ['clean']
                        ]
                    }
                });
                var self = this;
                this.quill.on('text-change', function() {
                    self.composeBodyHtml = self.quill.root.innerHTML;
                    self.composeBodyText = self.quill.getText().trim();
                });
            },

            destroyQuill: function() {
                if (this.quill) {
                    var el = document.getElementById('wm-quill-editor');
                    if (el) el.innerHTML = '';
                    this.quill = null;
                }
            },

            getEditorText: function() {
                if (this.quill) return this.quill.getText().trim();
                return this.composeBodyText || '';
            },

            getEditorHtml: function() {
                if (this.quill) return this.quill.root.innerHTML;
                return this.composeBodyHtml || '';
            },

            startDraftAutosave: function() {
                var self = this;
                self.stopDraftAutosave();
                self.draftTimer = setInterval(function() {
                    if (self.composeOpen && !self.composeMinimized) {
                        self.saveDraft(false);
                    }
                }, 10000);
            },

            stopDraftAutosave: function() {
                if (this.draftTimer) {
                    clearInterval(this.draftTimer);
                    this.draftTimer = null;
                }
            },

            saveDraft: function(showToastOnSuccess) {
                var self = this;
                if (!self.composeTo && !self.composeSubject && !self.getEditorText()) return;
                self.draftSaving = true;
                WmApi.json('/api/mail/drafts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to: self.composeTo,
                        cc: self.composeCc,
                        subject: self.composeSubject,
                        body_text: self.getEditorText(),
                        body_html: self.getEditorHtml(),
                        draft_uid: self.draftUid || null
                    })
                }).then(function(r) {
                    self.draftSaving = false;
                    if (r.data.success) {
                        var now = new Date();
                        self.draftSavedAt = now.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
                        if (showToastOnSuccess) showToast('Taslak kaydedildi', 'success');
                    } else if (showToastOnSuccess) {
                        showToast(r.data.message || 'Taslak kaydedilemedi', 'error');
                    }
                }).catch(function() {
                    self.draftSaving = false;
                });
            },

            isSelected: function(uid) {
                return this.selectedIds.indexOf(uid) >= 0;
            },

            toggleSelect: function(uid) {
                var i = this.selectedIds.indexOf(uid);
                if (i >= 0) this.selectedIds.splice(i, 1);
                else this.selectedIds.push(uid);
                this.allSelected = this.mails.length > 0 && this.selectedIds.length === this.mails.length;
            },

            toggleSelectAll: function(checked) {
                if (checked) {
                    this.selectedIds = this.mails.map(function(m) { return m.uid; });
                } else {
                    this.selectedIds = [];
                }
                this.allSelected = checked;
            },

            clearSelection: function() {
                this.selectedIds = [];
                this.allSelected = false;
            },

            bulkAction: function(action) {
                var self = this;
                var uids = self.selectedIds.filter(function(u) { return u > 0; });
                if (!uids.length) return;
                if (action === 'delete' && !confirm(uids.length + ' mesaj silinsin mi?')) return;
                WmApi.json('/api/mail/messages/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        folder: self.imapFolder(),
                        uids: uids,
                        action: action
                    })
                }).then(function(r) {
                    if (r.data.success) {
                        showToast('İşlem tamamlandı', 'success');
                        if (action === 'delete') {
                            self.mails = self.mails.filter(function(m) {
                                return uids.indexOf(m.uid) < 0;
                            });
                        } else if (action === 'seen') {
                            self.mails.forEach(function(m) {
                                if (uids.indexOf(m.uid) >= 0) m.unread = false;
                            });
                        }
                        self.clearSelection();
                        if (self.selectedMail && uids.indexOf(self.selectedMail.uid) >= 0 && action === 'delete') {
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        }
                    } else {
                        showToast(r.data.message || 'Hata', 'error');
                    }
                });
            },

            replyTo: function() {
                if (!this.selectedMail) return;
                var addr = this.selectedMail.from_addr || this.selectedMail.from || '';
                var match = addr.match(/<([^>]+)>/) || [null, addr];
                this.composeTo = match[1] || addr;
                this.composeSubject = 'Re: ' + (this.selectedMail.subject || '').replace(/^Re:\s*/i, '');
                this.openCompose();
                var self = this;
                this.$nextTick(function() {
                    if (self.quill) {
                        self.quill.setText('\n\n---\n');
                    }
                });
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
                if (self.composeCc && self.composeCc.trim() && self.composeCc.indexOf('@') < 0) {
                    showToast('Cc alanına geçerli e-posta yazın veya boş bırakın', 'warning');
                    return;
                }
                self.sendingMail = true;
                var bodyText = self.getEditorText();
                var bodyHtml = self.getEditorHtml();
                var done = function(ok, msg) {
                    self.sendingMail = false;
                    showToast(msg, ok ? 'success' : 'error');
                    if (ok) {
                        self.stopDraftAutosave();
                        self.closeCompose();
                        self.currentFolder = 'sent';
                        self.fetchMails();
                    }
                };
                if (self.composeFiles.length) {
                    var fd = new FormData();
                    fd.append('to', self.composeTo);
                    fd.append('subject', self.composeSubject);
                    fd.append('body_text', bodyText);
                    fd.append('body_html', bodyHtml);
                    self.composeFiles.forEach(function(f) { fd.append('attachments', f); });
                    WmApi.fetch('/api/mail/send-attachments', { method: 'POST', body: fd })
                        .then(function(r) { return r.json(); })
                        .then(function(d) { done(d.success, d.message || (d.success ? 'Gönderildi' : 'Hata')); })
                        .catch(function(e) { done(false, e.message || 'Bağlantı hatası'); });
                } else {
                    WmApi.fetch('/api/mail/send', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            to: self.composeTo,
                            cc: self.composeCc,
                            subject: self.composeSubject,
                            body_text: bodyText,
                            body_html: bodyHtml
                        })
                    })
                        .then(function(r) { return r.json(); })
                        .then(function(d) { done(d.success, d.message || ''); })
                        .catch(function(e) { done(false, e.message || 'Bağlantı hatası'); });
                }
            },

            initials: function(name) {
                if (!name) return '?';
                var s = String(name).replace(/<[^>]+>/g, '').trim();
                var parts = s.split(/\s+/).filter(Boolean);
                if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
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
                if (mail.from_display) return mail.from_display;
                var name = mail.from_name || '';
                var addr = mail.from_addr || mail.from || '';
                if (name && addr && name.toLowerCase() !== addr.toLowerCase()) {
                    return name + ' <' + addr + '>';
                }
                return addr || name || 'Bilinmeyen';
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

            formatSize: function(bytes) {
                if (!bytes) return '0 B';
                if (bytes < 1024) return bytes + ' B';
                if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
                return (bytes / 1048576).toFixed(1) + ' MB';
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
