<script lang="ts">
import type { HTMLInputAttributes } from 'svelte/elements';

type Size = 'sm' | 'md';

let inputElement = $state<HTMLInputElement | null>(null);

let {
    checked = $bindable(false),
    indeterminate = false,
    disabled = false,
    size = 'md',
    class: extraClasses = '',
    ariaLabel,
    ...rest
}: {
    checked?: boolean;
    indeterminate?: boolean;
    disabled?: boolean;
    size?: Size;
    class?: string;
    ariaLabel?: string;
} & Omit<
    HTMLInputAttributes,
    'type' | 'checked' | 'disabled' | 'class' | 'size'
> = $props();

const sizeClasses: Record<Size, string> = {
    sm: 'w-3.5 h-3.5',
    md: 'w-4 h-4',
};

$effect(() => {
    if (inputElement !== null) {
        inputElement.indeterminate = indeterminate;
    }
});
</script>

<input
    bind:this={inputElement}
    type="checkbox"
    bind:checked
    {disabled}
    aria-label={ariaLabel}
    class="rounded border border-sakura-400/40 bg-th-input accent-sakura-400 cursor-pointer
        disabled:opacity-50 disabled:cursor-not-allowed {sizeClasses[size]} {extraClasses}"
    {...rest}
/>