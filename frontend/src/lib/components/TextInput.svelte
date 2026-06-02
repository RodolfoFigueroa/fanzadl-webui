<script lang="ts">
import type { HTMLInputAttributes } from 'svelte/elements';

type InputValue = HTMLInputAttributes['value'];

let {
    id,
    type = 'text',
    value = $bindable<InputValue>(),
    error = false,
    disabled = false,
    readonly = false,
    placeholder,
    class: extraClasses = '',
    ...rest
}: {
    id?: string;
    type?: HTMLInputAttributes['type'];
    value?: InputValue;
    error?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    placeholder?: string;
    class?: string;
} & Omit<
    HTMLInputAttributes,
    'class' | 'value' | 'type' | 'disabled' | 'readonly' | 'placeholder' | 'id'
> = $props();
</script>

<input
    {id}
    {type}
    bind:value
    {disabled}
    {readonly}
    {placeholder}
    class="bg-th-input border rounded-lg px-3 py-2 text-sm text-th-text transition-shadow
        focus:outline-none focus:ring-2 focus:border-transparent disabled:opacity-50
        disabled:cursor-not-allowed placeholder:text-th-text-dim
        {error
            ? 'border-red-500 focus:ring-red-500'
            : 'border-th-border-input focus:border-sakura-400 focus:ring-sakura-400/60'} {extraClasses}"
    {...rest}
/>