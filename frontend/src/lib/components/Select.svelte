<script lang="ts">
import type { Snippet } from 'svelte';
import type { HTMLSelectAttributes } from 'svelte/elements';

type SelectValue = HTMLSelectAttributes['value'];
type Variant = 'default' | 'nested';
type Size = 'md' | 'sm';

let {
    id,
    value = $bindable<SelectValue>(),
    disabled = false,
    variant = 'default',
    size = 'md',
    class: extraClasses = '',
    children,
    ...rest
}: {
    id?: string;
    value?: SelectValue;
    disabled?: boolean;
    variant?: Variant;
    size?: Size;
    class?: string;
    children?: Snippet;
} & Omit<
    HTMLSelectAttributes,
    'class' | 'value' | 'disabled' | 'children' | 'id' | 'size'
> = $props();

const variantClasses: Record<Variant, string> = {
    default: 'bg-th-input',
    nested: 'bg-th-input-nested',
};

const sizeClasses: Record<Size, string> = {
    md: 'px-3 py-2',
    sm: 'px-2 py-1.5',
};
</script>

<select
    {id}
    bind:value
    {disabled}
    class="border border-th-border-input rounded-lg text-sm text-th-text transition-shadow
        focus:outline-none focus:ring-2 focus:border-transparent focus:border-sakura-400
        focus:ring-sakura-400/60 disabled:opacity-50 disabled:cursor-not-allowed
        {variantClasses[variant]} {sizeClasses[size]} {extraClasses}"
    {...rest}
>
    {#if children}
        {@render children()}
    {/if}
</select>