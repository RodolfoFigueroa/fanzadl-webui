<script lang="ts">
let { message }: { message: string } = $props();
</script>

<div class="text-red-400 bg-red-900/20 border border-red-800 rounded-lg p-4">
    {message}
</div>