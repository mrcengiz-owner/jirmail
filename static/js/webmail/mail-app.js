/**
 * Jîr-Mail Webmail v3 — Alpine.js SPA
 */
document.addEventListener('alpine:init', function() {
    var FOLDER_MAP = {
        inbox: 'INBOX',
        spam: 'Junk',
        sent: 'Sent',
        drafts: 'Drafts',
        archive: 'Archive',
        trash: 'Trash',
        starred: 'INBOX'
    };
    var FOLDER_TITLES = {
        inbox: 'Gelen kutusu',
        spam: 'Spam',
        sent: 'Gönderilen',
        drafts: 'Taslaklar',
        archive: 'Arşiv',
        trash: 'Çöp kutusu',
        starred: 'Yıldızlı'
    };
    // Jîr brand purple paletinden türetilmiş soft avatar tonları (ProtonMail tarzı tek-aileli).
    var AVATAR_COLORS = [
        '#5b6cff', '#7785ff', '#4855e6', '#3641cf',
        '#6f7aff', '#8b94ff', '#5566eb', '#4351d6'
    ];
    Alpine.data('mailApp', function() {
        return {
            folderNav: [
                { id: 'inbox', label: 'Gelen kutusu', ms: 'inbox' },
                { id: 'spam', label: 'Spam', ms: 'report' },
                { id: 'sent', label: 'Gönderilen', ms: 'send' },
                { id: 'drafts', label: 'Taslaklar', ms: 'draft' },
                { id: 'archive', label: 'Arşiv', ms: 'archive' },
                { id: 'starred', label: 'Yıldızlı', ms: 'star' },
                { id: 'trash', label: 'Çöp kutusu', ms: 'delete' }
            ],
            spamUnread: 0,
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
            composeExpanded: false,
            themeSync: '',
            bounceRawOpen: false,
            diagRunning: false,
            diagResult: null,
            _fetchSeq: 0,
            _syncInFlight: false,
            _streamDebounce: null,
            _folderSyncAttempted: '',

            get hasSelection() {
                return this.selectedIds.length > 0;
            },

            init: function() {
                var self = this;
                var root = this.$el;
                self.userEmail = root.dataset.userEmail || '';
                var params = new URLSearchParams(window.location.search);
                var folderParam = params.get('folder');
                if (folderParam && FOLDER_MAP[folderParam]) {
                    self.currentFolder = folderParam;
                }
                // Diğer sayfalardan "Yeni mesaj" linki ?compose=1 ile gelir —
                // gelir gelmez compose modal'ı aç ve param'ı URL'den temizle.
                if (params.get('compose') === '1') {
                    setTimeout(function() { self.openCompose(); }, 60);
                    try {
                        var u = new URL(window.location.href);
                        u.searchParams.delete('compose');
                        history.replaceState(null, '', u.pathname + u.search);
                    } catch (e) { /* ignore */ }
                }
                self.loadQuota();
                self.fetchMails();
                self.loadSpamUnread();
                self.syncAllFoldersBackground();
                self.$watch('currentFolder', function() {
                    self.page = 1;
                    self.selectedMail = null;
                    self.clearSelection();
                    self._folderSyncAttempted = '';
                    self.fetchMails();
                });
                window.addEventListener('wm-theme-change', function(e) {
                    self.themeSync = (e.detail && e.detail.theme) || (window.WmTheme && window.WmTheme.get());
                });
                self.themeSync = window.WmTheme ? window.WmTheme.get() : 'light';
                self.openStream();
            },

            syncAllFoldersBackground: function() {
                var self = this;
                if (self._syncInFlight) return;
                self._syncInFlight = true;
                WmApi.json('/api/mail/sync-all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}'
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        self.fetchMails();
                    } else if (r.data && r.data.message) {
                        showToast(r.data.message, 'warning');
                    }
                }).catch(function() { /* arka plan */ })
                    .finally(function() { self._syncInFlight = false; });
            },

            syncCurrentFolder: function() {
                return WmApi.json('/api/mail/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folder: this.imapFolder(), limit: 200 })
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
                if (this.currentFolder === 'spam') return 'Spam klasörü boş — harika!';
                if (this.currentFolder === 'trash') return 'Çöp kutusu boş.';
                return 'Bu klasörde mesaj yok.';
            },

            canMarkSpam: function() {
                return ['inbox', 'sent', 'archive', 'starred'].indexOf(this.currentFolder) >= 0;
            },

            loadSpamUnread: function() {
                var self = this;
                WmApi.json('/api/mail/messages?folder=' + encodeURIComponent(FOLDER_MAP.spam) + '&page=1&page_size=1')
                    .then(function(r) {
                        if (!r.data || !r.data.success) return;
                        WmApi.json('/api/mail/messages?folder=' + encodeURIComponent(FOLDER_MAP.spam) + '&page=1&page_size=50')
                            .then(function(r2) {
                                if (r2.data && r2.data.success) {
                                    self.spamUnread = (r2.data.messages || []).filter(function(m) {
                                        return !m.is_seen;
                                    }).length;
                                }
                            });
                    });
            },

            reportSpam: function(mail) {
                if (!mail || mail.uid <= 0) return;
                this._moveBulkAction([mail.uid], 'spam');
            },

            notSpam: function(mail) {
                if (!mail || mail.uid <= 0) return;
                this._moveBulkAction([mail.uid], 'not_spam');
            },

            _moveBulkAction: function(uids, action) {
                var self = this;
                WmApi.json('/api/mail/messages/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        folder: self.imapFolder(),
                        uids: uids,
                        action: action
                    })
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        var msg = action === 'spam' ? 'Spam klasörüne taşındı' : 'Gelen kutusuna taşındı';
                        showToast(msg, 'success');
                        self.mails = self.mails.filter(function(m) {
                            return uids.indexOf(m.uid) < 0;
                        });
                        if (self.selectedMail && uids.indexOf(self.selectedMail.uid) >= 0) {
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        }
                        self.clearSelection();
                        self.loadSpamUnread();
                    } else {
                        showToast((r.data && r.data.message) || 'İşlem başarısız', 'error');
                    }
                });
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
                if (this.currentFolder === id) {
                    this.sidebarOpen = false;
                    return;
                }
                this.currentFolder = id;
                this.mobileView = 'list';
                this.sidebarOpen = false;
                this.selectedMail = null;
                this.closeCompose();
                try {
                    var u = new URL(window.location.href);
                    if (id === 'inbox') {
                        u.searchParams.delete('folder');
                    } else {
                        u.searchParams.set('folder', id);
                    }
                    history.replaceState(null, '', u.pathname + u.search);
                } catch (e) { /* ignore */ }
            },

            fetchMails: function() {
                var self = this;
                var seq = ++self._fetchSeq;
                self.loadingMails = true;
                var url = '/api/mail/messages?folder=' + encodeURIComponent(self.imapFolder()) +
                    '&page=' + self.page + '&page_size=' + self.pageSize;
                if (self.searchQuery) {
                    url += '&q=' + encodeURIComponent(self.searchQuery);
                }
                WmApi.json(url).then(function(r) {
                    if (seq !== self._fetchSeq) return;
                    if (!r.ok || !r.data || !r.data.success) {
                        self.mails = [];
                        showToast((r.data && r.data.message) || 'Mesajlar yüklenemedi', 'error');
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
                    if (self.currentFolder === 'spam') {
                        self.spamUnread = list.filter(function(m) { return m.unread; }).length;
                    }
                    self.clearSelection();
                    var folderKey = self.currentFolder + ':' + self.imapFolder();
                    if (list.length === 0 && !self.searchQuery && self.page === 1 &&
                        self._folderSyncAttempted !== folderKey) {
                        self._folderSyncAttempted = folderKey;
                        self.syncCurrentFolder().then(function(sr) {
                            if (seq !== self._fetchSeq) return;
                            if (sr.data && sr.data.success) {
                                self.fetchMails();
                            }
                        });
                    }
                }).catch(function() {
                    if (seq !== self._fetchSeq) return;
                    self.mails = [];
                    showToast('Bağlantı hatası', 'error');
                }).finally(function() {
                    if (seq === self._fetchSeq) {
                        self.loadingMails = false;
                    }
                });
            },

            syncNow: function() {
                var self = this;
                self.syncing = true;
                self.syncCurrentFolder()
                    .then(function(r) {
                        if (r.data && r.data.success) {
                            return self.fetchMails();
                        }
                        showToast((r.data && r.data.message) || 'Senkron başarısız', 'error');
                    })
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
                                mail.bounceReport = r.data.bounce_report || null;
                                mail.bounceSummary = r.data.bounce_summary || self.parseBounceSummary(mail);
                                mail.bodyLoaded = true;
                                self.bounceRawOpen = false;
                                self.diagResult = null;
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
                self.composeExpanded = false;
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
                self.composeExpanded = false;
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
                if (action === 'spam' && !confirm(uids.length + ' mesaj spam olarak işaretlensin mi?')) return;
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
                        if (action === 'delete' || action === 'spam' || action === 'not_spam') {
                            self.mails = self.mails.filter(function(m) {
                                return uids.indexOf(m.uid) < 0;
                            });
                        } else if (action === 'seen') {
                            self.mails.forEach(function(m) {
                                if (uids.indexOf(m.uid) >= 0) m.unread = false;
                            });
                        }
                        self.clearSelection();
                        if (self.selectedMail && uids.indexOf(self.selectedMail.uid) >= 0 &&
                            (action === 'delete' || action === 'spam' || action === 'not_spam')) {
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        }
                        self.loadSpamUnread();
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
                var done = function(ok, msg, warnings) {
                    self.sendingMail = false;
                    if (ok) {
                        showToast(msg || 'Mesaj sunucuya iletildi', 'success');
                        if (warnings && warnings.length) {
                            setTimeout(function() {
                                showToast(warnings[0], 'warning');
                            }, 400);
                        }
                        self.stopDraftAutosave();
                        self.closeCompose();
                        self.currentFolder = 'sent';
                        self.fetchMails();
                    } else {
                        showToast(msg || 'Gönderilemedi', 'error');
                    }
                };
                if (self.composeFiles.length) {
                    var fd = new FormData();
                    fd.append('to', self.composeTo);
                    fd.append('subject', self.composeSubject);
                    fd.append('body_text', bodyText);
                    fd.append('body_html', bodyHtml);
                    self.composeFiles.forEach(function(f) { fd.append('attachments', f); });
                    WmApi.fetch('/api/mail/send-attachments', { method: 'POST', body: fd, timeoutMs: 90000 })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            done(d.success, d.message || (d.success ? 'Mesaj sunucuya iletildi' : 'Hata'), d.warnings);
                        })
                        .catch(function(e) {
                            var msg = e.name === 'AbortError'
                                ? 'Gönderim zaman aşımı (90 sn). Postfix/Dovecot loglarına bakın.'
                                : (e.message || 'Bağlantı hatası');
                            done(false, msg);
                        });
                } else {
                    WmApi.fetch('/api/mail/send', {
                        method: 'POST',
                        timeoutMs: 90000,
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
                        .then(function(d) {
                            done(d.success, d.message || (d.success ? 'Mesaj sunucuya iletildi' : 'Gönderilemedi'), d.warnings);
                        })
                        .catch(function(e) {
                            var msg = e.name === 'AbortError'
                                ? 'Gönderim zaman aşımı (90 sn). Postfix/Dovecot loglarına bakın.'
                                : (e.message || 'Bağlantı hatası');
                            done(false, msg);
                        });
                }
            },

            runOutboundDiagnostics: function() {
                var self = this;
                if (self.diagRunning) return;
                self.diagRunning = true;
                self.diagResult = null;

                function applyResult(data) {
                    if (!data || data.success === false) {
                        self.diagResult = {
                            message: (data && data.message) || 'Tanılama başarısız',
                            fix_steps: (data && data.fix_steps) || [
                                'Sunucuda şu komutu çalıştırın:',
                                'docker exec jir_postfix timeout 6 bash -c "echo >/dev/tcp/gmail-smtp-in.l.google.com/25" && echo OK || echo KAPALI'
                            ]
                        };
                        return;
                    }
                    self.diagResult = {
                        message: data.message || '',
                        fix_steps: data.fix_steps || [],
                        ok: data.ok,
                        mode: data.mode,
                        relayhost: data.relayhost,
                        routing: data.routing || null
                    };
                }

                function finish() {
                    self.diagRunning = false;
                }

                // quota?outbound=1 — mevcut deploy'larda da çalışır
                WmApi.json('/api/mail/quota?outbound=1').then(function(r) {
                    if (r.ok && r.data && r.data.success !== false && !r.data.html_response) {
                        finish();
                        applyResult(r.data);
                        return;
                    }
                    return WmApi.json('/api/mail/diagnostics/outbound').then(function(r2) {
                        finish();
                        if (r2.ok && r2.data && !r2.data.html_response) {
                            applyResult(r2.data);
                        } else {
                            applyResult(r.data || r2.data);
                        }
                    });
                }).catch(function(e) {
                    finish();
                    self.diagResult = {
                        message: e.message || 'Bağlantı hatası',
                        fix_steps: ['docker exec jir_django python manage.py check_outbound_smtp']
                    };
                });
            },

            isBounceMail: function(mail) {
                if (!mail) return false;
                var subj = (mail.subject || '').toLowerCase();
                var from = (mail.from || mail.from_display || '').toLowerCase();
                return subj.indexOf('undelivered') >= 0 ||
                    subj.indexOf('returned to sender') >= 0 ||
                    from.indexOf('mailer-daemon') >= 0 ||
                    from.indexOf('mail delivery') >= 0;
            },

            parseBounceSummary: function(mail) {
                if (!mail || !this.isBounceMail(mail)) return '';
                var text = '';
                if (mail.body) {
                    var tmp = document.createElement('div');
                    tmp.innerHTML = mail.body;
                    text = tmp.innerText || tmp.textContent || '';
                }
                var patterns = [
                    /Diagnostic-Code:\s*([^\n]+)/i,
                    /Status:\s*([^\n]+)/i,
                    /\bsaid:\s*([^\n]+)/i
                ];
                var i;
                for (i = 0; i < patterns.length; i++) {
                    var m = text.match(patterns[i]);
                    if (m && m[1] && m[1].trim().length > 6) {
                        return m[1].trim().slice(0, 500);
                    }
                }
                var lines = text.split('\n');
                for (i = 0; i < lines.length; i++) {
                    var low = lines[i].toLowerCase();
                    if (low.indexOf('550') >= 0 || low.indexOf('553') >= 0 || low.indexOf('user unknown') >= 0 ||
                        low.indexOf('relay') >= 0 || low.indexOf('refused') >= 0) {
                        return lines[i].trim().slice(0, 500);
                    }
                }
                return 'Alıcıya teslim edilemedi. Aşağıdaki tam metinde teknik ayrıntı vardır.';
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

            unreadInFolderBadge: function() {
                return this.currentFolder === 'inbox'
                    ? this.unreadCount
                    : this.mails.filter(function(m) { return m.unread; }).length;
            },

            toggleTheme: function() {
                if (window.WmTheme) {
                    window.WmTheme.toggle();
                    this.themeSync = window.WmTheme.get();
                }
            },

            toggleComposeExpand: function() {
                this.composeExpanded = !this.composeExpanded;
            },

            archiveMailRow: function(mail, ev) {
                if (ev) ev.stopPropagation();
                return this.archiveMail(mail);
            },

            archiveMail: function(mail) {
                if (!mail || mail.uid <= 0) return;
                var self = this;
                WmApi.json('/api/mail/messages/' + mail.uid + '/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folder: self.imapFolder(), target: 'Archive' })
                }).then(function(r) {
                    if (r.data.success) {
                        showToast('Arşive taşındı', 'success');
                        self.mails = self.mails.filter(function(m) { return m.uid !== mail.uid; });
                        if (self.selectedMail && self.selectedMail.uid === mail.uid) {
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        }
                    } else {
                        showToast(r.data.message || 'Arşivlenemedi', 'error');
                    }
                });
            },

            deleteMailRow: function(mail, ev) {
                if (ev) ev.stopPropagation();
                this.deleteMail(mail);
            },

            forwardMail: function() {
                var sm = this.selectedMail;
                if (!sm) return;
                var subj = (sm.subject || '').replace(/^Fwd:\s*/i, '');
                this.composeTo = '';
                this.composeCc = '';
                this.composeSubject = 'Fwd: ' + subj;
                var sub = sm.subject || '';
                var snippet = '';
                if (sm.bodyLoaded) {
                    var tmp = document.createElement('div');
                    tmp.innerHTML = sm.body || '';
                    snippet = (tmp.innerText || tmp.textContent || '').slice(0, 1800);
                } else {
                    snippet = sm.preview || '';
                }
                this.openCompose();
                var self = this;
                this.$nextTick(function() {
                    if (self.quill) {
                        self.quill.setContents([]);
                        var block = '\n\n---------- İletilen ileti ----------\nKonu: ' + sub +
                            '\nİçerik özeti:\n' + snippet;
                        self.quill.setText(block);
                    }
                });
            },

            formatDetailDate: function(iso) {
                if (!iso) return '';
                var d = new Date(iso);
                return d.toLocaleString('tr-TR', {
                    weekday: 'short',
                    day: 'numeric',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            },

            openStream: function() {
                var self = this;
                try {
                    if (self.eventSource) {
                        self.eventSource.close();
                    }
                    self.eventSource = new EventSource('/api/mail/stream');
                    self.eventSource.onmessage = function(ev) {
                        if (!ev.data || ev.data.indexOf('new_mail') === -1) return;
                        if (self._streamDebounce) clearTimeout(self._streamDebounce);
                        self._streamDebounce = setTimeout(function() {
                            self.fetchMails();
                        }, 2000);
                    };
                } catch (e) { /* ignore */ }
            }
        };
    });
});
