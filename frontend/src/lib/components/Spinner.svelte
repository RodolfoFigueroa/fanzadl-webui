<script lang="ts">
type Size = 'sm' | 'md' | 'lg';

let {
    size = 'md',
    class: extraClasses = '',
}: {
    size?: Size;
    class?: string;
} = $props();

const sizeClasses: Record<Size, string> = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
};
</script>

<svg
    class="animate-spin text-sakura-300 {sizeClasses[size]} {extraClasses}"
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
>
    <path
        stroke-linecap="round"
        stroke-linejoin="round"
        stroke-width="2"
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
    />
</svg>