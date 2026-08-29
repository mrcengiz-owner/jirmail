/**
 * Jîr-Mail Webmail v4 — AI-native Alpine.js SPA
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
            aiEnabled: false,
            aiAvailable: false,
            aiPanelOpen: false,
            aiMessages: [],
            aiInput: '',
            aiLoading: false,
            aiTasks: [],
            outboundPending: [],
            agentProfile: null,
            aiRules: [],
            aiDigest: '',
            aiPanelTab: 'chat',
            agentRunning: false,
            agentStats: null,
            pendingApprovals: [],
            vipSenders: [],
            vipInput: '',
            aiReplyDraft: null,
            aiReplyLoading: false,
            needsReplyList: [],
            customFolders: [],
            activeCustomFolder: '',
            newFolderName: '',
            showNewFolderInput: false,
            moveFolderOpen: false,
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
                self.aiEnabled = root.dataset.aiEnabled === 'true';
                var params = new URLSearchParams(window.location.search);
                var folderParam = params.get('folder');
                if (folderParam === 'custom') {
                    var customName = params.get('name');
                    if (customName) {
                        self.activeCustomFolder = customName;
                        self.currentFolder = 'custom';
                    }
                } else if (folderParam && FOLDER_MAP[folderParam]) {
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
                self.loadCustomFolders();
                self.fetchMails();
                self.loadSpamUnread();
                self.loadOutboundPending();
                if (self.aiEnabled) {
                    self.loadAiStatus();
                    self.loadAgentProfile();
                    self.loadAgentStats();
                    self.loadAiRules();
                    self.loadNeedsReplyList();
                    self.loadPendingApprovals();
                }
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
                if (this.activeCustomFolder) return this.activeCustomFolder;
                return FOLDER_MAP[this.currentFolder] || 'INBOX';
            },

            folderTitle: function() {
                if (this.activeCustomFolder) {
                    var self = this;
                    var hit = (self.customFolders || []).find(function(f) {
                        return f.name === self.activeCustomFolder;
                    });
                    if (hit && hit.display_name) return hit.display_name;
                    var parts = self.activeCustomFolder.split(/[./]/);
                    return parts[parts.length - 1] || self.activeCustomFolder;
                }
                return FOLDER_TITLES[this.currentFolder] || 'Posta';
            },

            loadCustomFolders: function() {
                var self = this;
                WmApi.json('/api/mail/folders').then(function(r) {
                    if (!r.data || !r.data.success) return;
                    self.customFolders = r.data.custom_folders || (r.data.folders || []).filter(function(f) {
                        return f.kind === 'custom';
                    });
                });
            },

            createCustomFolder: function() {
                var self = this;
                var name = (self.newFolderName || '').trim();
                if (!name) {
                    showToast('Klasör adı girin', 'warning');
                    return;
                }
                WmApi.json('/api/mail/folders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name })
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        showToast('Klasör oluşturuldu', 'success');
                        self.newFolderName = '';
                        self.showNewFolderInput = false;
                        self.loadCustomFolders();
                        if (r.data.folder && r.data.folder.name) {
                            self.setCustomFolder(r.data.folder.name);
                        }
                    } else {
                        showToast((r.data && r.data.message) || 'Klasör oluşturulamadı', 'error');
                    }
                });
            },

            deleteCustomFolder: function(folderName, ev) {
                if (ev) ev.stopPropagation();
                var self = this;
                if (!folderName) return;
                if (!window.confirm('“' + folderName + '” klasörü silinsin mi?')) return;
                WmApi.json('/api/mail/folders?name=' + encodeURIComponent(folderName), {
                    method: 'DELETE'
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        showToast('Klasör silindi', 'success');
                        if (self.activeCustomFolder === folderName) {
                            self.setFolder('inbox');
                        }
                        self.loadCustomFolders();
                    } else {
                        showToast((r.data && r.data.message) || 'Silinemedi', 'error');
                    }
                });
            },

            setCustomFolder: function(imapName) {
                if (!imapName) return;
                this.activeCustomFolder = imapName;
                this.currentFolder = 'custom';
                this.mobileView = 'list';
                this.closeMobileSidebar();
                this.selectedMail = null;
                this.closeCompose();
                this.page = 1;
                this.fetchMails();
                try {
                    var u = new URL(window.location.href);
                    u.searchParams.set('folder', 'custom');
                    u.searchParams.set('name', imapName);
                    history.replaceState(null, '', u.pathname + u.search);
                } catch (e) { /* ignore */ }
            },

            moveMailToFolder: function(mail, targetFolder) {
                if (!mail || mail.uid <= 0 || !targetFolder) return;
                var self = this;
                self.moveFolderOpen = false;
                WmApi.json('/api/mail/messages/' + mail.uid + '/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folder: self.imapFolder(), target: targetFolder })
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        showToast('Klasöre taşındı', 'success');
                        self.mails = self.mails.filter(function(m) { return m.uid !== mail.uid; });
                        if (self.selectedMail && self.selectedMail.uid === mail.uid) {
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        }
                        self.loadCustomFolders();
                    } else {
                        showToast((r.data && r.data.message) || 'Taşınamadı', 'error');
                    }
                });
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

            canArchive: function() {
                return ['inbox', 'spam', 'starred'].indexOf(this.currentFolder) >= 0 ||
                    (this.currentFolder && this.currentFolder.indexOf('custom:') === 0);
            },

            isTrashFolder: function() {
                return this.currentFolder === 'trash';
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

            closeMobileSidebar: function() {
                if (typeof Alpine !== 'undefined' && Alpine.store('wmPortal')) {
                    Alpine.store('wmPortal').closeMobileSidebar();
                }
            },

            setFolder: function(id) {
                if (this.currentFolder === id && !this.activeCustomFolder) {
                    this.closeMobileSidebar();
                    return;
                }
                this.activeCustomFolder = '';
                this.currentFolder = id;
                this.mobileView = 'list';
                this.closeMobileSidebar();
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
                var url;
                if (self.currentFolder === 'starred') {
                    url = '/api/mail/messages?flagged=1&page=' + self.page + '&page_size=' + self.pageSize;
                } else {
                    url = '/api/mail/messages?folder=' + encodeURIComponent(self.imapFolder()) +
                        '&page=' + self.page + '&page_size=' + self.pageSize;
                }
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
                            hasAttachments: m.has_attachments,
                            ai_meta: m.ai_meta || {}
                        };
                    });
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
                if (self.currentFolder === 'drafts' && mail.uid > 0) {
                    self.openDraftInCompose(mail);
                    return;
                }
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

            ensureMailBody: function(mail) {
                var self = this;
                return new Promise(function(resolve) {
                    if (!mail || mail.uid <= 0) {
                        resolve('');
                        return;
                    }
                    if (mail.bodyLoaded && mail.body) {
                        var tmp = document.createElement('div');
                        tmp.innerHTML = mail.body || '';
                        resolve((tmp.innerText || tmp.textContent || '').trim());
                        return;
                    }
                    WmApi.json('/api/mail/messages/' + mail.uid + '/body?folder=' +
                        encodeURIComponent(self.imapFolder()))
                        .then(function(r) {
                            if (r.data && r.data.success) {
                                mail.body = r.data.html || '<pre>' + self.escapeHtml(r.data.plain || '') + '</pre>';
                                mail.attachments = r.data.attachments || [];
                                mail.bodyLoaded = true;
                                var tmp = document.createElement('div');
                                tmp.innerHTML = mail.body || '';
                                resolve((tmp.innerText || tmp.textContent || r.data.plain || '').trim());
                            } else {
                                resolve('');
                            }
                        }).catch(function() { resolve(''); });
                });
            },

            openDraftInCompose: function(mail) {
                var self = this;
                self.ensureMailBody(mail).then(function(plain) {
                    self.composeTo = '';
                    self.composeCc = '';
                    self.composeSubject = mail.subject || '';
                    self.draftUid = mail.uid;
                    self.openCompose();
                    self.$nextTick(function() {
                        if (self.quill) {
                            if (mail.body && mail.body.indexOf('<') >= 0) {
                                self.quill.clipboard.dangerouslyPasteHTML(mail.body);
                            } else {
                                self.quill.setText(plain || '');
                            }
                        }
                    });
                });
            },

            downloadAttachment: function(att, index) {
                var self = this;
                if (!self.selectedMail || self.selectedMail.uid <= 0) return;
                var idx = (att && att.index != null) ? att.index : index;
                var url = '/api/mail/messages/' + self.selectedMail.uid + '/attachments/' + idx +
                    '?folder=' + encodeURIComponent(self.imapFolder());
                window.open(url, '_blank');
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
                self.closeMobileSidebar();
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
                        if (r.data.draft_uid) {
                            self.draftUid = r.data.draft_uid;
                        }
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
                if (action === 'delete') {
                    var msg = self.isTrashFolder()
                        ? uids.length + ' mesaj kalıcı olarak silinsin mi?'
                        : uids.length + ' mesaj çöp kutusuna taşınsın mı?';
                    if (!confirm(msg)) return;
                }
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
                        if (action === 'delete' || action === 'spam' || action === 'not_spam' || action === 'archive') {
                            self.mails = self.mails.filter(function(m) {
                                return uids.indexOf(m.uid) < 0;
                            });
                        } else if (action === 'seen') {
                            self.mails.forEach(function(m) {
                                if (uids.indexOf(m.uid) >= 0) m.unread = false;
                            });
                        } else if (action === 'unseen') {
                            self.mails.forEach(function(m) {
                                if (uids.indexOf(m.uid) >= 0) m.unread = true;
                            });
                        }
                        self.clearSelection();
                        if (self.selectedMail && uids.indexOf(self.selectedMail.uid) >= 0 &&
                            (action === 'delete' || action === 'spam' || action === 'not_spam' || action === 'archive')) {
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
                var msg = self.isTrashFolder()
                    ? 'Bu mesaj kalıcı olarak silinsin mi?'
                    : 'Bu mesaj çöp kutusuna taşınsın mı?';
                if (!confirm(msg)) return;
                WmApi.json('/api/mail/messages/' + mail.uid + '?folder=' +
                    encodeURIComponent(self.imapFolder()), { method: 'DELETE' })
                    .then(function(r) {
                        if (r.data.success) {
                            showToast(self.isTrashFolder() ? 'Mesaj silindi' : 'Çöp kutusuna taşındı', 'success');
                            self.mails = self.mails.filter(function(m) { return m.uid !== mail.uid; });
                            self.selectedMail = null;
                            self.mobileView = 'list';
                        } else {
                            showToast(r.data.message || 'Silinemedi', 'error');
                        }
                    });
            },

            onFiles: function(ev) {
                var incoming = Array.from(ev.target.files || []);
                this.composeFiles = (this.composeFiles || []).concat(incoming);
                if (ev.target) ev.target.value = '';
            },

            removeComposeFile: function(index) {
                if (!this.composeFiles) return;
                this.composeFiles.splice(index, 1);
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
                var bodyText = self.getEditorText();
                var bodyHtml = self.getEditorHtml();
                var files = self.composeFiles.slice();
                var payload = {
                    to: self.composeTo,
                    cc: self.composeCc || '',
                    subject: self.composeSubject,
                    body_text: bodyText,
                    body_html: bodyHtml,
                    background: true
                };
                var snapshot = {
                    to: payload.to,
                    subject: payload.subject
                };

                self.stopDraftAutosave();
                self.closeCompose();
                showToast('Mesaj arka planda gönderiliyor…', 'success');

                var onQueued = function(d) {
                    if (d.success && (d.queued || d.outbound_id)) {
                        self.trackOutbound({
                            id: d.outbound_id,
                            to: snapshot.to,
                            subject: snapshot.subject,
                            status: 'pending'
                        });
                        if (d.warnings && d.warnings.length) {
                            setTimeout(function() { showToast(d.warnings[0], 'warning'); }, 500);
                        }
                        return;
                    }
                    if (d.success) {
                        showToast(d.message || 'Mesaj gönderildi', 'success');
                        self.currentFolder = 'sent';
                        self.fetchMails();
                        return;
                    }
                    showToast(d.message || 'Gönderilemedi', 'error');
                };

                if (files.length) {
                    var fd = new FormData();
                    fd.append('to', payload.to);
                    fd.append('cc', payload.cc);
                    fd.append('subject', payload.subject);
                    fd.append('body_text', bodyText);
                    fd.append('body_html', bodyHtml);
                    fd.append('background', 'true');
                    files.forEach(function(f) { fd.append('attachments', f); });
                    WmApi.fetch('/api/mail/send-attachments', { method: 'POST', body: fd, timeoutMs: 120000 })
                        .then(function(r) { return r.json(); })
                        .then(onQueued)
                        .catch(function(e) {
                            showToast(e.message || 'Gönderim başlatılamadı', 'error');
                        });
                } else {
                    WmApi.fetch('/api/mail/send', {
                        method: 'POST',
                        timeoutMs: 30000,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    })
                        .then(function(r) { return r.json(); })
                        .then(onQueued)
                        .catch(function(e) {
                            showToast(e.message || 'Gönderim başlatılamadı', 'error');
                        });
                }
            },

            loadOutboundPending: function() {
                var self = this;
                WmApi.json('/api/mail/outbound/pending').then(function(r) {
                    if (r.data && r.data.success) {
                        self.outboundPending = (r.data.items || []).map(function(it) {
                            return {
                                id: it.id,
                                to: it.to,
                                subject: it.subject,
                                status: 'pending'
                            };
                        });
                    }
                });
            },

            trackOutbound: function(item) {
                if (!item || !item.id) return;
                var exists = this.outboundPending.some(function(o) { return o.id === item.id; });
                if (!exists) {
                    this.outboundPending.unshift(item);
                }
            },

            onOutboundStatus: function(payload) {
                var self = this;
                if (!payload || !payload.outbound_id) return;
                var id = payload.outbound_id;
                var st = payload.status;
                self.outboundPending = self.outboundPending.filter(function(o) {
                    return o.id !== id;
                });
                if (st === 'sent') {
                    showToast('Mesaj gönderildi: ' + (payload.message || ''), 'success');
                    if (self.currentFolder === 'sent') {
                        self.fetchMails();
                    }
                } else if (st === 'failed') {
                    showToast('Gönderim başarısız: ' + (payload.message || ''), 'error');
                    self.fetchMails();
                }
            },

            toggleAiPanel: function() {
                this.aiPanelOpen = !this.aiPanelOpen;
                if (this.aiPanelOpen && !this.aiMessages.length) {
                    this.aiMessages.push({
                        role: 'assistant',
                        text: 'Merhaba! Gelen kutunuzu düzenler, özet çıkarır, taslak yazar ve mailleri klasörlere taşırım. Örnek: "Bugünkü özeti ver" veya "Gelen kutusunu düzenle".'
                    });
                }
                if (this.aiPanelOpen && this.aiEnabled) {
                    this.loadAgentProfile();
                    this.loadAgentStats();
                    this.loadNeedsReplyList();
                }
            },

            loadAgentStats: function() {
                var self = this;
                WmApi.json('/api/mail/ai/agent/stats').then(function(r) {
                    if (r.data && r.data.success) {
                        self.agentStats = r.data;
                    }
                });
            },

            loadPendingApprovals: function() {
                var self = this;
                WmApi.json('/api/mail/ai/approvals').then(function(r) {
                    if (r.data && r.data.success) {
                        self.pendingApprovals = r.data.items || [];
                    }
                });
            },

            approvePending: function(actionId) {
                var self = this;
                WmApi.json('/api/mail/ai/approvals/' + actionId + '/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}'
                }).then(function(r) {
                    var d = r.data || {};
                    showToast(d.message || (d.success ? 'Onaylandı' : 'Hata'), d.success ? 'success' : 'error');
                    if (d.success) {
                        self.loadPendingApprovals();
                        self.loadAgentStats();
                        self.fetchMails();
                    }
                });
            },

            rejectPending: function(actionId) {
                var self = this;
                WmApi.json('/api/mail/ai/approvals/' + actionId + '/reject', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}'
                }).then(function(r) {
                    var d = r.data || {};
                    showToast(d.message || (d.success ? 'Reddedildi' : 'Hata'), d.success ? 'success' : 'warning');
                    if (d.success) {
                        self.loadPendingApprovals();
                        self.loadAgentStats();
                    }
                });
            },

            loadVipSenders: function() {
                var self = this;
                WmApi.json('/api/mail/ai/vip').then(function(r) {
                    if (r.data && r.data.success) {
                        self.vipSenders = r.data.items || [];
                    }
                });
            },

            addVipSender: function() {
                var self = this;
                var pat = (self.vipInput || '').trim();
                if (!pat) {
                    showToast('Gönderen deseni girin', 'warning');
                    return;
                }
                WmApi.json('/api/mail/ai/vip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pattern: pat, label: '' })
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        self.vipInput = '';
                        self.loadVipSenders();
                        showToast('VIP eklendi', 'success');
                    } else {
                        showToast((r.data && r.data.message) || 'Eklenemedi', 'error');
                    }
                });
            },

            removeVip: function(vipId) {
                var self = this;
                WmApi.json('/api/mail/ai/vip/' + vipId, { method: 'DELETE' }).then(function(r) {
                    if (r.data && r.data.success) {
                        self.loadVipSenders();
                        showToast('VIP kaldırıldı', 'success');
                    }
                });
            },

            onApprovalUpdate: function(payload) {
                this.loadAgentStats();
                this.loadPendingApprovals();
                if (payload && payload.event === 'pending_created') {
                    showToast('Yeni onay bekleyen aksiyon', 'info');
                }
            },

            aiPriorityLabel: function(mail) {
                var ai = (mail && mail.ai_meta) || {};
                var p = ai.priority || '';
                if (p === 'urgent') return 'Acil';
                if (p === 'high') return 'Yüksek';
                if (p === 'low') return 'Düşük';
                return '';
            },

            aiCategoryLabel: function(mail) {
                var ai = (mail && mail.ai_meta) || {};
                var c = ai.category || '';
                var map = {
                    personal: 'Kişisel', work: 'İş', finance: 'Finans',
                    newsletter: 'Bülten', promo: 'Promo', spam: 'Spam',
                    transactional: 'Bildirim', support: 'Destek', other: ''
                };
                return map[c] || c;
            },

            loadAgentProfile: function() {
                var self = this;
                WmApi.json('/api/mail/ai/agent/profile').then(function(r) {
                    if (r.data && r.data.success) {
                        self.agentProfile = r.data.profile;
                    }
                });
            },

            saveAgentProfile: function() {
                var self = this;
                if (!self.agentProfile) return;
                WmApi.json('/api/mail/ai/agent/profile', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(self.agentProfile)
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        self.agentProfile = r.data.profile;
                        showToast('Ajan ayarları kaydedildi', 'success');
                    }
                });
            },

            runAgentNow: function() {
                var self = this;
                if (self.agentRunning) return;
                self.agentRunning = true;
                WmApi.json('/api/mail/ai/agent/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ triage: true, organize: true, digest: false })
                }).then(function(r) {
                    showToast(
                        (r.data && r.data.message) || 'AI ajan çalıştırıldı',
                        r.data && r.data.success ? 'success' : 'warning'
                    );
                }).finally(function() {
                    self.agentRunning = false;
                });
            },

            triageInboxNow: function() {
                var self = this;
                self.aiLoading = true;
                WmApi.json('/api/mail/ai/triage/inbox?limit=20', { method: 'POST' })
                    .then(function(r) {
                        self.aiLoading = false;
                        if (r.data && r.data.success) {
                            showToast((r.data.triaged || 0) + ' mail sınıflandırıldı', 'success');
                            self.fetchMails();
                        } else {
                            showToast((r.data && r.data.message) || 'Triage başarısız', 'error');
                        }
                    }).catch(function() { self.aiLoading = false; });
            },

            organizeInboxNow: function() {
                var self = this;
                self.aiLoading = true;
                WmApi.json('/api/mail/ai/organize/inbox', { method: 'POST' })
                    .then(function(r) {
                        self.aiLoading = false;
                        if (r.data && r.data.success) {
                            var n = (r.data.applied || []).length;
                            showToast(n ? n + ' aksiyon uygulandı' : 'Organize önerileri hazır', 'success');
                            self.fetchMails();
                        }
                    }).catch(function() { self.aiLoading = false; });
            },

            loadDigest: function(refresh) {
                var self = this;
                var url = '/api/mail/ai/digest' + (refresh ? '?refresh=true' : '');
                WmApi.json(url).then(function(r) {
                    if (r.data && r.data.success) {
                        self.aiDigest = r.data.digest || '';
                    }
                });
            },

            loadAiRules: function() {
                var self = this;
                WmApi.json('/api/mail/ai/rules').then(function(r) {
                    if (r.data && r.data.success) {
                        self.aiRules = r.data.items || [];
                    }
                });
            },

            onAgentCycleComplete: function(payload) {
                showToast('AI ajan döngüsü tamamlandı', 'success');
                this.fetchMails();
                this.loadAgentProfile();
                this.loadAgentStats();
                this.loadNeedsReplyList();
                this.loadPendingApprovals();
                if (payload && payload.steps && payload.steps.digest) {
                    this.aiDigest = payload.steps.digest.digest || this.aiDigest;
                }
            },

            loadNeedsReplyList: function() {
                var self = this;
                WmApi.json('/api/mail/ai/reply/pending?limit=15').then(function(r) {
                    if (r.data && r.data.success) {
                        self.needsReplyList = r.data.items || [];
                    }
                });
            },

            generateAiReply: function(instruction) {
                var self = this;
                var mail = self.selectedMail;
                if (!mail || !mail.uid) {
                    showToast('Önce bir mail seçin', 'warning');
                    return;
                }
                self.aiReplyLoading = true;
                var plain = (mail.body || '').replace(/<[^>]+>/g, ' ').slice(0, 8000);
                WmApi.json('/api/mail/ai/reply/draft', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        folder: self.imapFolder(),
                        uid: mail.uid,
                        tone: 'professional',
                        instruction: instruction || '',
                        context_subject: mail.subject || '',
                        context_from: mail.from_addr || mail.from || '',
                        context_body: plain
                    })
                }).then(function(r) {
                    self.aiReplyLoading = false;
                    var d = r.data || {};
                    if (!d.success) {
                        showToast(d.message || 'Yanıt üretilemedi', 'error');
                        return;
                    }
                    self.aiReplyDraft = d;
                    if (mail.ai_meta) {
                        mail.ai_meta.reply_draft = d.body;
                    } else {
                        mail.ai_meta = { reply_draft: d.body, needs_reply: true };
                    }
                    showToast('AI yanıt taslağı hazır', 'success');
                }).catch(function() {
                    self.aiReplyLoading = false;
                });
            },

            openReplyDraftInCompose: function() {
                var self = this;
                var draft = self.aiReplyDraft;
                var mail = self.selectedMail;
                if (!draft && mail && mail.ai_meta && mail.ai_meta.reply_draft) {
                    draft = {
                        to: mail.from_addr || mail.from || '',
                        subject: 'Re: ' + (mail.subject || '').replace(/^Re:\s*/i, ''),
                        body: mail.ai_meta.reply_draft
                    };
                }
                if (!draft) {
                    showToast('Önce AI yanıt üretin', 'warning');
                    return;
                }
                self.composeTo = draft.to || '';
                self.composeSubject = draft.subject || '';
                self.openCompose();
                self.$nextTick(function() {
                    if (self.quill && draft.body) {
                        var html = draft.body_html || ('<p>' + draft.body.replace(/\n/g, '</p><p>') + '</p>');
                        self.quill.clipboard.dangerouslyPasteHTML(html);
                    }
                });
            },

            sendAiReplyNow: function() {
                var self = this;
                var draft = self.aiReplyDraft;
                if (!draft && self.selectedMail && self.selectedMail.ai_meta && self.selectedMail.ai_meta.reply_draft) {
                    var addr = self.selectedMail.from_addr || self.selectedMail.from || '';
                    var match = addr.match(/<([^>]+)>/) || [null, addr];
                    draft = {
                        to: match[1] || addr,
                        subject: 'Re: ' + (self.selectedMail.subject || '').replace(/^Re:\s*/i, ''),
                        body: self.selectedMail.ai_meta.reply_draft
                    };
                }
                if (!draft || !draft.to) {
                    showToast('Gönderilecek yanıt yok', 'warning');
                    return;
                }
                if (!window.confirm('Bu yanıt arka planda gönderilsin mi?')) return;
                WmApi.json('/api/mail/ai/reply/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to: draft.to,
                        subject: draft.subject,
                        body_text: draft.body,
                        body_html: draft.body_html || '',
                        uid: self.selectedMail ? self.selectedMail.uid : 0,
                        folder: self.imapFolder()
                    })
                }).then(function(r) {
                    var d = r.data || {};
                    if (d.success) {
                        showToast(d.message || 'Yanıt gönderiliyor…', 'success');
                        if (d.outbound_id) {
                            self.trackOutbound({
                                id: d.outbound_id,
                                to: draft.to,
                                subject: draft.subject,
                                status: 'pending'
                            });
                        }
                        self.aiReplyDraft = null;
                    } else {
                        showToast(d.message || 'Gönderilemedi', 'error');
                    }
                });
            },

            selectNeedsReplyMail: function(item) {
                var self = this;
                var mail = self.mails.find(function(m) { return m.uid === item.uid; });
                if (mail) {
                    self.selectMail(mail);
                    self.generateAiReply('');
                    return;
                }
                if (item.uid) {
                    self.setFolder('inbox');
                    self.$nextTick(function() {
                        WmApi.json('/api/mail/messages?folder=INBOX&page=1&page_size=100').then(function(r) {
                            if (r.data && r.data.success) {
                                var hit = (r.data.messages || []).find(function(m) { return m.uid === item.uid; });
                                if (hit) {
                                    self.selectMail({
                                        uid: hit.uid,
                                        subject: hit.subject,
                                        from: hit.from,
                                        from_addr: hit.from_addr,
                                        unread: !hit.is_seen,
                                        starred: hit.is_flagged,
                                        bodyLoaded: false,
                                        body: ''
                                    });
                                }
                            }
                            self.generateAiReply('');
                        });
                    });
                }
            },

            loadAiStatus: function() {
                var self = this;
                WmApi.json('/api/mail/ai/status').then(function(r) {
                    if (r.data && r.data.success) {
                        self.aiAvailable = !!r.data.ai_available;
                    }
                });
                self.loadAiTasks();
            },

            loadAiTasks: function() {
                var self = this;
                WmApi.json('/api/mail/ai/tasks').then(function(r) {
                    if (r.data && r.data.success) {
                        self.aiTasks = r.data.items || [];
                    }
                });
            },

            aiContextPayload: function() {
                var self = this;
                var ctx = {
                    context_subject: '',
                    context_from: '',
                    context_body: '',
                    inbox_summary: '',
                    selected_uid: 0,
                    selected_folder: self.imapFolder()
                };
                if (self.selectedMail) {
                    ctx.selected_uid = self.selectedMail.uid || 0;
                    ctx.context_subject = self.selectedMail.subject || '';
                    ctx.context_from = self.selectedMail.from_addr || self.selectedMail.from || '';
                    ctx.context_body = (self.selectedMail.body || '').replace(/<[^>]+>/g, ' ').slice(0, 6000);
                }
                var recent = (self.mails || []).slice(0, 8).map(function(m) {
                    return '- ' + (m.subject || '(konu yok)') + ' ← ' + (m.from || m.from_addr || '');
                });
                if (recent.length) {
                    ctx.inbox_summary = recent.join('\n');
                }
                return ctx;
            },

            aiQuickCommand: function(text) {
                this.aiInput = text || '';
                this.sendAiMessage();
            },

            aiIntentLabel: function(intent) {
                var map = {
                    digest: 'Özet',
                    organize_inbox: 'Düzenle',
                    triage_inbox: 'Sınıflandır',
                    run_agent: 'Ajan',
                    analyze: 'Mail özeti',
                    reply: 'Yanıt',
                    send_mail: 'Gönder',
                    batch_move: 'Taşı',
                    create_folder: 'Klasör',
                    create_rule: 'Kural',
                    archive: 'Arşiv',
                    spam: 'Spam',
                    mark_read: 'Okundu',
                    move: 'Taşı',
                    schedule_mail: 'Zamanla'
                };
                var key = (intent || '').toLowerCase();
                return map[key] || intent || '';
            },

            sendAiMessage: function() {
                var self = this;
                var msg = (self.aiInput || '').trim();
                if (!msg || self.aiLoading) return;
                if (!self.aiAvailable) {
                    showToast('AI kapalı — Ayarlar’dan API anahtarı ekleyin.', 'warning');
                    return;
                }
                self.aiMessages.push({ role: 'user', text: msg });
                self.aiInput = '';
                self.aiLoading = true;
                var history = (self.aiMessages || []).slice(-12).map(function(m) {
                    return { role: m.role, text: m.text || '' };
                });
                var body = Object.assign({ message: msg, chat_history: history }, self.aiContextPayload());
                WmApi.json('/api/mail/ai/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                }).then(function(r) {
                    self.aiLoading = false;
                    var d = r.data || {};
                    if (!d.success) {
                        self.aiMessages.push({ role: 'assistant', text: d.message || 'AI yanıt veremedi.' });
                        return;
                    }
                    self.aiMessages.push({
                        role: 'assistant',
                        text: d.reply || '(boş yanıt)',
                        intent: (d.action && d.action.intent) || '',
                        done: !!(d.executed && d.executed.success)
                    });
                    if (d.executed) {
                        self.onAiExecuted(d.executed, d.action);
                    }
                    if (d.action && d.action.intent === 'digest' && d.reply) {
                        self.aiDigest = d.reply;
                    }
                    if (d.action) {
                        self.handleAiAction(d.action, d.reply, d.executed);
                    }
                }).catch(function(e) {
                    self.aiLoading = false;
                    self.aiMessages.push({ role: 'assistant', text: e.message || 'Bağlantı hatası' });
                });
            },

            onAiExecuted: function(executed, action) {
                if (!executed) return;
                var ok = !!executed.success;
                var msg = executed.message || executed.digest || '';
                if (msg && msg.length < 120) {
                    showToast(msg, ok ? 'success' : 'error');
                } else if (msg && !ok) {
                    showToast(msg.slice(0, 140) + '…', 'error');
                }
                if (ok) {
                    this.fetchMails();
                    this.loadCustomFolders();
                    this.loadAgentStats();
                    this.loadNeedsReplyList();
                    if (action && (action.intent === 'triage_inbox' || action.intent === 'run_agent')) {
                        var self = this;
                        setTimeout(function() { self.fetchMails(); }, 2500);
                    }
                }
            },

            executeAiAction: function(action, confirmMsg) {
                var self = this;
                if (confirmMsg && !window.confirm(confirmMsg)) return;
                WmApi.json('/api/mail/ai/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(action)
                }).then(function(r) {
                    var d = r.data || {};
                    self.onAiExecuted(d, action);
                    if (d.success && d.reply) {
                        self.aiMessages.push({ role: 'assistant', text: d.message || d.reply });
                    }
                });
            },

            handleAiAction: function(action, replyText, executed) {
                var self = this;
                if (!action || !action.intent) return;
                if (executed && executed.success) return;
                var intent = (action.intent || 'chat').toLowerCase();
                if (intent === 'chat') return;
                if (intent === 'analyze') {
                    if (action.summary && replyText) {
                        var last = self.aiMessages[self.aiMessages.length - 1];
                        if (last && last.role === 'assistant' && !last.text) {
                            last.text = action.summary;
                        }
                    }
                    return;
                }

                var autoIntents = [
                    'move', 'archive', 'spam', 'mark_read', 'batch_move', 'create_folder',
                    'create_rule', 'organize_inbox', 'run_agent', 'triage_inbox', 'digest'
                ];
                if (autoIntents.indexOf(intent) >= 0) {
                    self.executeAiAction(action);
                    return;
                }

                if (intent === 'send_mail' && action.to && action.subject && action.body) {
                    if (window.confirm('AI bu mesajı göndermek istiyor. Onaylıyor musunuz?')) {
                        WmApi.json('/api/mail/ai/execute', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(action)
                        }).then(function(r) {
                            if (r.data && r.data.success) {
                                showToast(r.data.message || 'Gönderim kuyruğa alındı', 'success');
                                if (r.data.outbound_id) {
                                    self.trackOutbound({
                                        id: r.data.outbound_id,
                                        to: action.to,
                                        subject: action.subject,
                                        status: 'pending'
                                    });
                                }
                            } else {
                                showToast((r.data && r.data.message) || 'Gönderilemedi', 'error');
                            }
                        });
                    }
                    return;
                }

                if (intent === 'reply' || intent === 'send_mail') {
                    if (action.to) self.composeTo = action.to;
                    if (action.subject) self.composeSubject = action.subject;
                    if (action.body) {
                        self.openCompose();
                        self.$nextTick(function() {
                            if (self.quill) {
                                self.quill.clipboard.dangerouslyPasteHTML(action.body);
                            }
                        });
                    }
                    return;
                }

                if (intent === 'schedule_mail') {
                    WmApi.json('/api/mail/ai/execute', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(action)
                    }).then(function(r) {
                        if (r.data && r.data.success) {
                            showToast(r.data.message || 'Planlandı', 'success');
                        } else {
                            showToast((r.data && r.data.message) || 'Planlanamadı', 'error');
                        }
                    });
                }
            },

            analyzeSelectedMail: function() {
                var self = this;
                if (!self.selectedMail) {
                    showToast('Önce bir mail seçin', 'warning');
                    return;
                }
                if (!self.aiAvailable) {
                    showToast('AI kapalı — Ayarlar’dan etkinleştirin.', 'warning');
                    return;
                }
                self.aiPanelOpen = true;
                self.aiLoading = true;
                self.ensureMailBody(self.selectedMail).then(function(plain) {
                    WmApi.json('/api/mail/ai/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            message: 'Bu maili analiz et',
                            context_subject: self.selectedMail.subject || '',
                            context_from: self.selectedMail.from_addr || self.selectedMail.from || '',
                            context_body: plain.slice(0, 8000),
                            selected_uid: self.selectedMail.uid || 0,
                            selected_folder: self.imapFolder()
                        })
                    }).then(function(r) {
                        self.aiLoading = false;
                        var d = r.data || {};
                        self.aiMessages.push({
                            role: 'assistant',
                            text: d.reply || d.message || 'Analiz tamamlandı.',
                            intent: 'analyze'
                        });
                    }).catch(function() {
                        self.aiLoading = false;
                    });
                });
            },

            aiComposeDraft: function() {
                var self = this;
                var instruction = (self.aiInput || '').trim();
                if (!instruction) {
                    showToast('Taslak talimatı yazın', 'warning');
                    return;
                }
                self.aiLoading = true;
                WmApi.json('/api/mail/ai/compose', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: instruction })
                }).then(function(r) {
                    self.aiLoading = false;
                    if (r.data && r.data.success && r.data.body) {
                        self.openCompose();
                        self.$nextTick(function() {
                            if (self.quill) {
                                self.quill.clipboard.dangerouslyPasteHTML(r.data.body);
                            }
                        });
                        showToast('Taslak editöre eklendi', 'success');
                    } else {
                        showToast((r.data && r.data.message) || 'Taslak üretilemedi', 'error');
                    }
                }).catch(function() {
                    self.aiLoading = false;
                });
            },

            queueAiTask: function(instruction, taskType) {
                var self = this;
                if (!instruction) return;
                var ctx = self.aiContextPayload();
                WmApi.json('/api/mail/ai/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        instruction: instruction,
                        task_type: taskType || 'custom',
                        context_subject: ctx.context_subject,
                        context_from: ctx.context_from,
                        context_body: ctx.context_body
                    })
                }).then(function(r) {
                    if (r.data && r.data.success) {
                        showToast('AI görevi kuyruğa alındı', 'success');
                        self.loadAiTasks();
                    } else {
                        showToast((r.data && r.data.message) || 'Görev oluşturulamadı', 'error');
                    }
                });
            },

            onAiTaskStatus: function(payload) {
                if (!payload) return;
                showToast('AI görevi: ' + (payload.status || ''), payload.status === 'done' ? 'success' : 'warning');
                this.loadAiTasks();
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

            fromName: function(mail) {
                if (!mail) return 'Bilinmeyen';
                if (mail.from_name) return mail.from_name;
                var addr = mail.from_addr || mail.from || '';
                if (addr.indexOf('@') >= 0) {
                    var local = addr.split('@')[0];
                    return local.replace(/[._-]+/g, ' ').replace(/\b\w/g, function(c) {
                        return c.toUpperCase();
                    }) || addr;
                }
                return addr || 'Bilinmeyen';
            },

            fromEmail: function(mail) {
                if (!mail) return '';
                return mail.from_addr || mail.from || '';
            },

            isBodyLoading: function(mail) {
                return !!(mail && mail.uid > 0 && !mail.bodyLoaded);
            },

            hasMailBody: function(mail) {
                if (!mail || !mail.bodyLoaded) return false;
                var html = mail.body || '';
                if (!String(html).trim()) return false;
                var tmp = document.createElement('div');
                tmp.innerHTML = html;
                var text = (tmp.innerText || tmp.textContent || '').replace(/\s+/g, ' ').trim();
                if (text.length > 0) return true;
                return !!tmp.querySelector('img, table, video, iframe');
            },

            attachmentKind: function(filename) {
                var ext = String(filename || '').split('.').pop().toLowerCase();
                if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'heic'].indexOf(ext) >= 0) return 'image';
                if (ext === 'pdf') return 'pdf';
                if (['doc', 'docx', 'odt', 'rtf', 'txt'].indexOf(ext) >= 0) return 'doc';
                if (['xls', 'xlsx', 'csv', 'ods'].indexOf(ext) >= 0) return 'sheet';
                if (['zip', 'rar', '7z', 'tar', 'gz'].indexOf(ext) >= 0) return 'archive';
                return 'file';
            },

            attachmentIcon: function(filename) {
                var kind = this.attachmentKind(filename);
                var map = {
                    image: 'image',
                    pdf: 'picture_as_pdf',
                    doc: 'description',
                    sheet: 'table_chart',
                    archive: 'folder_zip',
                    file: 'attach_file'
                };
                return map[kind] || 'attach_file';
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
                        if (!ev.data) return;
                        var parsed = null;
                        try {
                            parsed = JSON.parse(ev.data);
                        } catch (e) {
                            if (ev.data.indexOf('new_mail') >= 0) {
                                if (self._streamDebounce) clearTimeout(self._streamDebounce);
                                self._streamDebounce = setTimeout(function() {
                                    self.fetchMails();
                                }, 2000);
                            }
                            return;
                        }
                        if (parsed.type === 'new_mail') {
                            if (self._streamDebounce) clearTimeout(self._streamDebounce);
                            self._streamDebounce = setTimeout(function() {
                                self.fetchMails();
                            }, 2000);
                        } else if (parsed.type === 'outbound_status') {
                            self.onOutboundStatus(parsed.payload || {});
                        } else if (parsed.type === 'ai_task_status') {
                            self.onAiTaskStatus(parsed.payload || {});
                        } else if (parsed.type === 'agent_cycle_complete') {
                            self.onAgentCycleComplete(parsed.payload || {});
                        } else if (parsed.type === 'approval_update') {
                            self.onApprovalUpdate(parsed.payload || {});
                        }
                    };
                } catch (e) { /* ignore */ }
            }
        };
    });
});
