/** How a provider's id is shown to a person: "openai" reads as a typo. */
const NAMES: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic (Claude)',
  mistral: 'Mistral AI',
  local: 'this computer',
}

export function providerName(id: string | null | undefined): string {
  if (!id) return ''
  return NAMES[id.toLowerCase()] ?? id
}
