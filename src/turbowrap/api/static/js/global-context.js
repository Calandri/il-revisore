/**
 * Global Repository/Branch Context Store
 *
 * Provides app-wide repo/branch selection that persists per-tab in sessionStorage,
 * with localStorage as fallback for new tabs (inherits last used).
 * This allows different tabs to use different repos independently.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('globalContext', {
        // State
        repositories: [],
        selectedRepoId: sessionStorage.getItem('globalRepoId') || localStorage.getItem('globalRepoId') || null,
        selectedBranch: sessionStorage.getItem('globalBranch') || localStorage.getItem('globalBranch') || null,
        branches: [],
        loading: false,
        branchesLoading: false,

        // Computed
        get selectedRepo() {
            return this.repositories.find(r => r.id === this.selectedRepoId) || null;
        },

        get hasClonedPath() {
            return this.selectedRepo?.path_exists !== false;
        },

        // Initialize store
        async init() {
            await this.loadRepositories();
            if (this.selectedRepoId && this.hasClonedPath) {
                await this.loadBranches();
            }
        },

        // Load all repositories
        async loadRepositories() {
            this.loading = true;
            try {
                const res = await fetch('/api/git/repositories');
                if (res.ok) {
                    this.repositories = await res.json();
                    // Validate stored repo still exists
                    if (this.selectedRepoId && !this.repositories.find(r => r.id === this.selectedRepoId)) {
                        this.clear();
                    }
                }
            } catch (e) {
                console.error('[globalContext] Failed to load repositories:', e);
            } finally {
                this.loading = false;
            }
        },

        // Load branches for selected repo
        async loadBranches() {
            if (!this.selectedRepoId || !this.hasClonedPath) {
                this.branches = [];
                return;
            }

            this.branchesLoading = true;
            try {
                const res = await fetch(`/api/git/repositories/${this.selectedRepoId}/branches`);
                if (res.ok) {
                    const data = await res.json();
                    this.branches = data.branches || [];
                    // Set current branch if not already set or if stored branch doesn't exist
                    if (!this.selectedBranch || !this.branches.includes(this.selectedBranch)) {
                        const currentBranch = data.current || this.branches[0] || null;
                        this.selectedBranch = currentBranch;
                        if (currentBranch) {
                            sessionStorage.setItem('globalBranch', currentBranch);
                            localStorage.setItem('globalBranch', currentBranch);
                        }
                    }
                }
            } catch (e) {
                console.error('[globalContext] Failed to load branches:', e);
                this.branches = [];
            } finally {
                this.branchesLoading = false;
            }
        },

        // Select repository
        async selectRepo(repoId) {
            const oldRepoId = this.selectedRepoId;
            this.selectedRepoId = repoId || null;

            if (repoId) {
                sessionStorage.setItem('globalRepoId', repoId);
                localStorage.setItem('globalRepoId', repoId);
            } else {
                sessionStorage.removeItem('globalRepoId');
                localStorage.removeItem('globalRepoId');
            }

            // Reset branch when repo changes
            if (oldRepoId !== repoId) {
                this.selectedBranch = null;
                sessionStorage.removeItem('globalBranch');
                localStorage.removeItem('globalBranch');
                this.branches = [];

                if (repoId && this.hasClonedPath) {
                    await this.loadBranches();
                }
            }

            // Emit event for other components
            this._emitChange();
        },

        // Select branch (performs git checkout)
        async selectBranch(branch) {
            if (!branch || branch === this.selectedBranch) return;

            // Perform git checkout
            if (this.selectedRepoId) {
                try {
                    const res = await fetch(`/api/git/repositories/${this.selectedRepoId}/checkout`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ branch })
                    });

                    const result = await res.json();

                    if (!result.success) {
                        TurboWrapError.handle('Git Checkout Branch', new Error(result.message || 'Checkout failed'), { repoId: this.selectedRepoId, branch });
                        return;
                    }

                    // Show success toast
                    window.dispatchEvent(new CustomEvent('show-toast', {
                        detail: { message: `Switched to ${branch}`, type: 'success' }
                    }));
                } catch (e) {
                    TurboWrapError.handle('Git Checkout Branch', e, { repoId: this.selectedRepoId, branch });
                    return;
                }
            }

            // Update state after successful checkout
            this.selectedBranch = branch;
            sessionStorage.setItem('globalBranch', branch);
            localStorage.setItem('globalBranch', branch);

            // Emit event
            this._emitChange();
        },

        // Clear selection
        clear() {
            this.selectedRepoId = null;
            this.selectedBranch = null;
            this.branches = [];
            sessionStorage.removeItem('globalRepoId');
            sessionStorage.removeItem('globalBranch');
            localStorage.removeItem('globalRepoId');
            localStorage.removeItem('globalBranch');
            this._emitChange();
        },

        // Emit change event
        _emitChange() {
            window.dispatchEvent(new CustomEvent('global-context-changed', {
                detail: {
                    repoId: this.selectedRepoId,
                    branch: this.selectedBranch,
                    repo: this.selectedRepo
                }
            }));
        },

        // Refresh repositories list
        async refresh() {
            await this.loadRepositories();
            if (this.selectedRepoId && this.hasClonedPath) {
                await this.loadBranches();
            }
        }
    });
});
