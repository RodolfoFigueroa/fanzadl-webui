<script lang="ts">
import type { Snippet } from 'svelte';

let {
    class: extraClasses = '',
    children,
}: {
    class?: string;
    children?: Snippet;
} = $props();
</script>

<span
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-sakura-800/70 text-sakura-200 {extraClasses}"
>
    {#if children}
        {@render children()}
    {/if}
</span>