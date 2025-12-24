/**
 * TurboWrap Frontend JavaScript
 * Alpine.js utilities and HTMX handlers
 */

// Toast notification manager for Alpine.js
function toastManager() {
    return {
        toasts: [],

        show(detail) {
            const id = Date.now();
            this.toasts.push({
                id,
                message: detail.message,
                type: detail.type || 'success',
                visible: true
            });

            // Auto-hide after 4 seconds
            setTimeout(() => {
                const toast = this.toasts.find(t => t.id === id);
                if (toast) toast.visible = false;

                // Remove from array after animation
                setTimeout(() => {
                    this.toasts = this.toasts.filter(t => t.id !== id);
                }, 300);
            }, 4000);
        }
    }
}

// HTMX configuration
document.body.addEventListener('htmx:configRequest', function(evt) {
    // Add any custom headers here if needed
});

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', function(evt) {
    window.dispatchEvent(new CustomEvent('show-toast', {
        detail: {
            message: 'Errore di connessione. Riprova.',
            type: 'error'
        }
    }));
});

// SSE event handling helper
function createSSEConnection(url, onToken, onDone, onError) {
    const eventSource = new EventSource(url);

    eventSource.addEventListener('token', function(e) {
        const data = JSON.parse(e.data);
        onToken(data.content);
    });

    eventSource.addEventListener('done', function(e) {
        const data = JSON.parse(e.data);
        eventSource.close();
        onDone(data);
    });

    eventSource.addEventListener('error', function(e) {
        eventSource.close();
        if (onError) onError(e);
    });

    return eventSource;
}

// Basic markdown rendering (for chat messages)
function renderMarkdown(content) {
    return content
        // Code blocks
        .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">$1</code>')
        // Bold
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        // Line breaks
        .replace(/\n/g, '<br>');
}

// Debounce utility
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Format date utility
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;

    // Less than a minute
    if (diff < 60000) {
        return 'Adesso';
    }

    // Less than an hour
    if (diff < 3600000) {
        const minutes = Math.floor(diff / 60000);
        return `${minutes} min fa`;
    }

    // Less than a day
    if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours} ore fa`;
    }

    // More than a day
    return date.toLocaleDateString('it-IT', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit'
    });
}
