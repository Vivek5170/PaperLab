<script>
	let { paper, questions = 0, types = '' } = $props();
</script>

<article class="paper">
	<div class="paper-main">
		<h3 class="paper-title">
			<a href={`/archive/${paper.id}`}>{paper.title || `Paper ${paper.id}`}</a>
		</h3>
		<p class="paper-meta pl-mono">
			{paper.exam || 'Unknown exam'} - {paper.date || 'undated'} - {questions} questions - #{paper.id}
		</p>
		{#if types}
			<p class="paper-types">
				{#each types.split(' - ') as chip (chip)}
					<span class="pl-chip">{chip}</span>
				{/each}
			</p>
		{/if}
		{#if paper.institute}
			<p class="paper-meta">Institute: {paper.institute}</p>
		{/if}
	</div>
	<div class="paper-actions">
		<a class="pl-btn pl-btn-primary" href={`/archive/${paper.id}`}>Open</a>
	</div>
</article>

<style>
	.paper {
		display: flex;
		gap: 16px;
		justify-content: space-between;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 16px 18px;
	}
	.paper:hover {
		box-shadow: var(--pl-shadow-sm);
	}
	.paper-title {
		font-size: 1.15rem;
		margin-bottom: 4px;
	}
	.paper-title a {
		text-decoration: none;
	}
	.paper-title a:hover {
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.paper-meta {
		margin: 2px 0;
		color: var(--pl-ink-soft);
	}
	.paper-types {
		margin: 6px 0 0;
	}
	.paper-actions {
		display: flex;
		flex-direction: column;
		justify-content: center;
		flex-shrink: 0;
	}
</style>
