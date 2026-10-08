export function buildSetup(provider, mode) {
  const extras = { openai: '[openai]', openrouter: '[openai]', anthropic: '[anthropic]', mock: '' };
  if (!(provider in extras) || !['plan', 'local', 'pr'].includes(mode)) throw new Error('Unsupported setup option');
  const install = `python -m pip install "github-issue-agent${extras[provider]}"`;
  const flags = mode === 'plan' ? ' --dry-run --no-pr' : mode === 'local' ? ' --no-pr' : '';
  const run = `github-issue-agent run work-issue \\\n  --prompt "Add a regression test for empty input" \\\n  --provider ${provider} --path ./target-repo${flags}`;
  return { install, run };
}
