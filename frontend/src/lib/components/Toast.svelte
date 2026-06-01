<script lang="ts">
let {
    message,
    level = 'ERROR',
    onDismiss,
}: { message: string; level?: string; onDismiss: () => void } = $props();

const isError = level === 'ERROR' || level === 'CRITICAL';

$effect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
});
</script>

<div
    class="flex items-start gap-3 bg-th-surface text-th-text text-sm px-4 py-3 rounded-lg shadow-lg max-w-sm w-full
        {isError ? 'border border-th-border-strong' : 'border border-th-border'}"
    role="alert"
>
    <span class="flex-1 break-words">{message}</span>
    <button
        onclick={onDismiss}
        class="flex-shrink-0 text-th-text-dim hover:text-th-text transition-colors leading-none"
        aria-label="Dismiss"
    >✕</button>
</div>
