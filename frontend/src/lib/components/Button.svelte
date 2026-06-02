<script lang="ts">
import type { Snippet } from 'svelte';
import type { HTMLButtonAttributes } from 'svelte/elements';

type Variant = 'primary' | 'secondary' | 'ghost-destructive' | 'destructive';
type Size = 'md' | 'sm';

let {
    variant = 'primary',
    size = 'md',
    loading = false,
    loadingText = '',
    success = false,
    successText = 'Saved',
    disabled = false,
    class: extraClasses = '',
    children,
    ...rest
}: {
    variant?: Variant;
    size?: Size;
    loading?: boolean;
    loadingText?: string;
    success?: boolean;
    successText?: string;
    disabled?: boolean;
    class?: string;
    children?: Snippet;
} & Omit<HTMLButtonAttributes, 'disabled' | 'class' | 'children'> = $props();

const variantClasses: Record<Variant, string> = {
    primary: 'border-th-border-strong text-th-text hover:bg-th-border/20',
    secondary:
        'border-th-border text-th-text-muted hover:border-th-border-strong hover:text-th-text',
    'ghost-destructive':
        'border-th-border text-th-text-dim hover:border-red-800 hover:text-red-400',
    destructive: 'border-red-800 text-red-400 hover:bg-red-900/20',
};

const sizeClasses: Record<Size, string> = {
    md: 'px-4 py-2 text-sm',
    sm: 'px-3 py-1.5 text-xs',
};
</script>

<button
    class="rounded-lg border transition-colors disabled:opacity-40 whitespace-nowrap {variantClasses[variant]} {sizeClasses[size]} {extraClasses}"
    disabled={disabled || loading || success}
    {...rest}
>
    {#if success}
        <span class="text-sakura-400">{successText}</span>
    {:else if loading && loadingText}
        {loadingText}
    {:else if children}
        {@render children()}
    {/if}
</button>
