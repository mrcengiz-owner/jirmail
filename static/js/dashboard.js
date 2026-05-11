/**
 * Jir-Mail Dashboard (Master Panel) Logic
 * Handles system specs, accounts, domains, backups, logs, and container status
 */

function masterPanel() {
    return {
        activeTab: 'dashboard',
        JIR_KEY: window.JIR_KEY || '',

        toastMessage: '',
        toastType: 'success',
        showToast: false,

        specs: {
            cpu_percent: 0,
            ram_percent: 0,
            ram_used_gb: 0,
            ram_total_gb: 0,
            disk_percent: 0,
            disk_used_gb: 0,
            disk_total_gb: 0,
            total_container_cpu: 0,
            total_container_ram_mb: 0,
            docker_containers: []
        },

        accounts: [],
        domains: [],
        backups: [],
        logs: [],
        logFilter: '',

        containers: [],

        showAddModal: false,
        showAddDomainModal: false,
        showDeleteConfirm: false,
        showDNSModalFlag: false,
        selectedDomain: null,
        selectedAccount: null,

        newAccount: { username: '', domain: '', password: '' },
        newDomain: { name: '' },

        init() {
            this.fetchSpecs();
            this.fetchAccounts();
            this.fetchDomains();
            this.fetchBackups();
            this.fetchLogs();
            this.fetchContainers();

            setInterval(() => this.fetchSpecs(), 30000);
            setInterval(() => this.fetchContainers(), 60000);
        },

        async fetchContainers() {
            try {
                const res = await fetch('/api/management/container-status');
                if (res.ok) {
                    const data = await res.json();
                    this.containers = data.containers || data || [];
                }
            } catch (e) {
                console.error('Container fetch error:', e);
                this.containers = [];
            }
        },

        showToast(message, type = 'success') {
            this.toastMessage = message;
            this.toastType = type;
            this.showToast = true;
            setTimeout(() => {
                this.showToast = false;
            }, 3000);
        },

        refreshAll() {
            this.fetchSpecs();
            this.fetchAccounts();
            this.fetchDomains();
            this.fetchBackups();
            this.fetchLogs();
            this.fetchContainers();
        },

        async fetchSpecs() {
            try {
                const res = await fetch('/api/management/system-specs');
                if (res.ok) {
                    this.specs = await res.json();
                }
            } catch (e) {
                console.error('Specs fetch error:', e);
            }
        },

        async fetchAccounts() {
            try {
                const res = await fetch('/api/core/list-accounts?key=' + this.JIR_KEY);
                if (!res.ok) throw new Error('Failed to fetch accounts');
                const data = await res.json();
                if (data.status === 'success') {
                    this.accounts = data.accounts || [];
                }
            } catch (e) {
                console.error('Accounts fetch error:', e);
            }
        },

        async fetchDomains() {
            try {
                const res = await fetch('/api/core/list-domains?key=' + this.JIR_KEY);
                if (!res.ok) throw new Error('Failed to fetch domains');
                const data = await res.json();
                if (data.status === 'success') {
                    this.domains = data.domains || [];
                }
            } catch (e) {
                console.error('Domains fetch error:', e);
            }
        },

        async fetchBackups() {
            try {
                const res = await fetch('/api/backup/list-backups');
                if (res.ok) {
                    this.backups = await res.json();
                }
            } catch (e) {
                console.error('Backups fetch error:', e);
            }
        },

        async fetchLogs() {
            try {
                const url = '/api/management/logs?key=' + this.JIR_KEY + '&lines=50' + (this.logFilter ? '&filter_type=' + this.logFilter : '');
                const res = await fetch(url);
                if (res.ok) {
                    this.logs = await res.json();
                }
            } catch (e) {
                console.error('Logs fetch error:', e);
            }
        },

        async createAccount() {
            if (!this.newAccount.username || !this.newAccount.password) {
                this.showToast('Username and password are required', 'error');
                return;
            }
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                                   window.JirMail?.getCsrfToken() || '';
                const res = await fetch('/api/management/create-account', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify(this.newAccount)
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showAddModal = false;
                    this.newAccount = { username: '', domain: '', password: '' };
                    this.fetchAccounts();
                    this.showToast('Account created successfully', 'success');
                } else {
                    this.showToast(data.message || 'Failed to create account', 'error');
                }
            } catch (e) {
                console.error('Create account error:', e);
                this.showToast('Failed to create account', 'error');
            }
        },

        async toggleAccount(email) {
            try {
                const res = await fetch('/api/core/toggle-account/' + encodeURIComponent(email) + '?key=' + this.JIR_KEY, { method: 'PATCH' });
                const data = await res.json();
                if (data.status === 'success') {
                    this.fetchAccounts();
                }
            } catch (e) {
                console.error('Toggle account error:', e);
            }
        },

        async toggleDomain(domain) {
            try {
                const res = await fetch('/api/core/toggle-domain/' + domain.name + '?key=' + this.JIR_KEY, { method: 'PATCH' });
                const data = await res.json();
                if (data.status === 'success') {
                    domain.is_active = data.is_active;
                }
            } catch (e) {
                console.error('Toggle domain error:', e);
            }
        },

        showDNSModal(domain) {
            this.selectedDomain = domain;
            this.showDNSModalFlag = true;
        },

        copyToClipboard(text) {
            if (!text) return;
            if (window.JirMail?.copyToClipboard(text)) {
                this.showToast('Copied to clipboard!', 'success');
            } else {
                this.showToast('Failed to copy', 'error');
            }
        },

        deleteAccount(account) {
            this.selectedAccount = account;
            this.showDeleteConfirm = true;
        },

        async confirmDelete() {
            if (!this.selectedAccount) return;
            try {
                const res = await fetch('/api/core/delete-account/' + encodeURIComponent(this.selectedAccount.email) + '?key=' + this.JIR_KEY, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showDeleteConfirm = false;
                    this.selectedAccount = null;
                    this.fetchAccounts();
                } else {
                    this.showToast(data.message || 'Failed to delete', 'error');
                }
            } catch (e) {
                console.error('Delete account error:', e);
            }
        },

        async createBackup() {
            if (!confirm('Create a full backup now?')) return;
            try {
                const res = await fetch('/api/backup/create-backup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        backup_type: 'full',
                        include_emails: false,
                        include_configs: true,
                        include_database: true
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.fetchBackups();
                    this.showToast('Backup created successfully', 'success');
                } else {
                    this.showToast(data.message || 'Failed to create backup', 'error');
                }
            } catch (e) {
                console.error('Create backup error:', e);
            }
        },

        async restoreBackup(backup) {
            if (!confirm('Restore from this backup?')) return;
            try {
                const res = await fetch('/api/backup/restore-backup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        backup_id: backup.id,
                        restore_emails: true,
                        restore_configs: true,
                        restore_database: true
                    })
                });
                const data = await res.json();
                this.showToast(data.message || 'Restore completed', 'info');
            } catch (e) {
                console.error('Restore backup error:', e);
            }
        },

        async createDomain() {
            if (!this.newDomain.name) {
                this.showToast('Domain name is required', 'error');
                return;
            }
            try {
                const res = await fetch('/api/core/add-domain?key=' + this.JIR_KEY, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: this.newDomain.name, is_active: true })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showAddDomainModal = false;
                    this.newDomain = { name: '' };
                    this.fetchDomains();
                    this.showToast('Domain added successfully', 'success');
                } else {
                    this.showToast(data.message || 'Failed to add domain', 'error');
                }
            } catch (e) {
                console.error('Create domain error:', e);
            }
        },

        async generateDNS(domain) {
            try {
                const res = await fetch('/api/core/generate-dns-records/' + domain.name + '?key=' + this.JIR_KEY, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    this.fetchDomains();
                    this.showToast('DNS records generated', 'success');
                } else {
                    this.showToast(data.message || 'Failed to generate DNS', 'error');
                }
            } catch (e) {
                console.error('Generate DNS error:', e);
            }
        },

        getRoleLabel(role) {
            const labels = {
                'FULL': 'Full Access',
                'SEND': 'Send Only',
                'RECV': 'Receive Only',
                'BLOCK': 'Internal'
            };
            return labels[role] || role;
        }
    };
}

function mailPanel() {
    return {
        email: '',
        currentFolder: 'inbox',
        selectedMail: null,
        showCompose: false,
        composeType: 'new',
        searchQuery: '',
        unreadCount: 3,

        composeTo: '',
        composeSubject: '',
        composeBody: '',

        toastMessage: '',
        toastType: 'success',
        showToast: false,
        sendingMail: false,

        mails: [],

        filteredMails: [],

        init() {
            this.filterMails();
        },

        showToast(message, type = 'success') {
            this.toastMessage = message;
            this.toastType = type;
            this.showToast = true;
            setTimeout(() => {
                this.showToast = false;
            }, 3000);
        },

        filterMails() {
            let folderMails = this.mails.filter(m => m.folder === this.currentFolder);
            if (this.searchQuery) {
                const query = this.searchQuery.toLowerCase();
                folderMails = folderMails.filter(m =>
                    m.subject.toLowerCase().includes(query) ||
                    m.from.toLowerCase().includes(query) ||
                    m.preview.toLowerCase().includes(query)
                );
            }
            this.filteredMails = folderMails.sort((a, b) => b.date - a.date);
        },

        selectMail(mail) {
            this.selectedMail = mail;
            if (mail.unread) {
                mail.unread = false;
                this.updateUnreadCount();
            }
        },

        formatDate(date) {
            if (window.JirMail?.formatDate) {
                return window.JirMail.formatDate(date);
            }
            const now = new Date();
            const diff = now - date;
            const days = Math.floor(diff / 86400000);
            if (days === 0) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (days === 1) return 'Yesterday';
            if (days < 7) return date.toLocaleDateString([], { weekday: 'short' });
            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        },

        formatDateTime(date) {
            if (window.JirMail?.formatDateTime) {
                return window.JirMail.formatDateTime(date);
            }
            return date.toLocaleString([], {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        },

        updateUnreadCount() {
            this.unreadCount = this.mails.filter(m => m.unread && m.folder === 'inbox').length;
        },

        toggleStar(mail) {
            mail.starred = !mail.starred;
        },

        deleteMail(mail) {
            if (confirm('Move this mail to trash?')) {
                mail.folder = 'trash';
                if (this.selectedMail === mail) {
                    this.selectedMail = null;
                }
                this.filterMails();
            }
        },

        replyTo(mail) {
            this.composeType = 'reply';
            this.composeTo = mail.email;
            this.composeSubject = 'Re: ' + mail.subject;
            this.composeBody = '\n\n--- Original Message ---\nFrom: ' + mail.from + '\nDate: ' + this.formatDateTime(mail.date) + '\nSubject: ' + mail.subject + '\n\n' + mail.body;
            this.showCompose = true;
        },

        forwardMail(mail) {
            this.composeType = 'forward';
            this.composeTo = '';
            this.composeSubject = 'Fwd: ' + mail.subject;
            this.composeBody = '\n\n--- Forwarded Message ---\nFrom: ' + mail.from + '\nDate: ' + this.formatDateTime(mail.date) + '\nSubject: ' + mail.subject + '\n\n' + mail.body;
            this.showCompose = true;
        },

        closeCompose() {
            this.showCompose = false;
            this.composeType = 'new';
            this.composeTo = '';
            this.composeSubject = '';
            this.composeBody = '';
        },

        saveDraft() {
            const draftMail = {
                id: Date.now(),
                from: this.email,
                email: this.email,
                subject: this.composeSubject || '(No Subject)',
                preview: this.composeBody.substring(0, 50),
                date: new Date(),
                body: this.composeBody,
                unread: false,
                starred: false,
                folder: 'drafts',
                status: null
            };
            this.mails.push(draftMail);
            this.closeCompose();
            this.filterMails();
            this.showToast('Draft saved', 'info');
        },

        sendMail() {
            if (!this.composeTo) {
                this.showToast('Please enter a recipient', 'error');
                return;
            }
            this.sendingMail = true;

            const newMail = {
                id: Date.now(),
                from: this.email,
                email: this.composeTo,
                subject: this.composeSubject || '(No Subject)',
                preview: this.composeBody.substring(0, 50),
                date: new Date(),
                body: this.composeBody,
                unread: false,
                starred: false,
                folder: 'inbox',
                status: 'sending'
            };
            this.mails.push(newMail);
            this.filterMails();

            this.showToast('Gidiyor...', 'info');

            setTimeout(() => {
                const mailIndex = this.mails.findIndex(m => m.id === newMail.id);
                if (mailIndex !== -1) {
                    this.mails[mailIndex].status = 'sent';
                    this.mails[mailIndex].folder = 'sent';
                }
                this.filterMails();
                this.sendingMail = false;
                this.closeCompose();
                this.currentFolder = 'sent';
                this.showToast('Gönderildi!', 'success');
            }, 2000);
        }
    };
}