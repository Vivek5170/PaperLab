<script>
	import { page } from '$app/stores';
	import QuestionReader from '$lib/components/QuestionReader.svelte';

	const paper = $derived($page.params.paper);
	const qn = $derived($page.params.qn);
</script>

<QuestionReader
	paperId={paper}
	initialQ={qn}
	backHref="/cart"
	backLabel="Back to Cart"
/>
