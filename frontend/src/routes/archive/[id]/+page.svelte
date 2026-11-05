<script>
	import { page } from '$app/stores';
	import QuestionReader from '$lib/components/QuestionReader.svelte';

	const id = $derived($page.params.id);
	const fromSearch = $derived($page.url.searchParams.get('from') === 'search');
	const initialQ = $derived($page.url.searchParams.get('q'));
</script>

<QuestionReader
	paperId={id}
	initialQ={initialQ}
	backHref={fromSearch ? '/search' : '/archive'}
	backLabel={fromSearch ? 'Back to Search Results' : 'Back to Archive'}
/>
