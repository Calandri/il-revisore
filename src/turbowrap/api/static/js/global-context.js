/**
 * Global Repository/Branch Context Store
 *
 * Provides app-wide repo/branch selection that persists in localStorage
 * and syncs with active CLI chat sessions.
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('globalContext', {
        // State
        repositories: [],
        selectedRepoId: localStorage.getItem('globalRepoId') || null,
        selectedBranch: localStorage.getItem('globalBranch') || null,
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
                localStorage.setItem('globalRepoId', repoId);
            } else {
                localStorage.removeItem('globalRepoId');
            }

            // Reset branch when repo changes
            if (oldRepoId !== repoId) {
                this.selectedBranch = null;
                localStorage.removeItem('globalBranch');
                this.branches = [];

                if (repoId && this.hasClonedPath) {
                    await this.loadBranches();
                }
            }

            // Emit event for other components
            this._emitChange();
        },

        // Select branch
        async selectBranch(branch) {
            this.selectedBranch = branch || null;

            if (branch) {
                localStorage.setItem('globalBranch', branch);
            } else {
                localStorage.removeItem('globalBranch');
            }

            // Emit event
            this._emitChange();
        },

        // Clear selection
        clear() {
            this.selectedRepoId = null;
            this.selectedBranch = null;
            this.branches = [];
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
