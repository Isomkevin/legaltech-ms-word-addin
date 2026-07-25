import type { ProviderId } from "./providers/types";

export type { ProviderId };

/**
 * BYOK key store for the community edition.
 *
 * Keys live in the add-in's own partitioned localStorage: on the user's machine,
 * sent only to the provider they chose. Office gives no encrypted store, so this
 * is the standard, accepted trust model for a bring-your-own-key tool. We never
 * write keys to Office document settings, which would travel inside the .docx.
 */
const PREFIX = "vaquill.byok";

export interface ModelOption {
  id: string;
  label: string;
}

export const PROVIDER_LABELS: Record<ProviderId, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  groq: "Groq",
  ollama: "Ollama",
  azure: "Azure OpenAI",
};

/** Providers that run against a user-supplied endpoint (need the base-URL
 *  field): Ollama's local server and an Azure deployment. */
export const PROVIDERS_NEEDING_BASE_URL: ProviderId[] = ["ollama", "azure"];

/** Providers that do not require an API key (Ollama runs locally). */
export const KEYLESS_PROVIDERS: ProviderId[] = ["ollama"];

const KNOWN_PROVIDERS: ProviderId[] = ["openai", "anthropic", "gemini", "groq", "ollama", "azure"];

/** A small curated list per provider. New models are a one-line add here. Azure
 *  lists nothing because the "model" is the user's own deployment name. */
export const MODEL_OPTIONS: Record<ProviderId, ModelOption[]> = {
  openai: [
    { id: "gpt-5.4-mini", label: "GPT-5.4 mini (fast, low cost)" },
    { id: "gpt-5.5", label: "GPT-5.5 (highest quality)" },
    { id: "gpt-4o-mini", label: "GPT-4o mini" },
  ],
  anthropic: [
    { id: "claude-sonnet-5", label: "Claude Sonnet 5 (recommended)" },
    { id: "claude-opus-4-8", label: "Claude Opus 4.8 (highest quality)" },
    { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 (fast)" },
  ],
  gemini: [
    { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash (fast)" },
    { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro (highest quality)" },
  ],
  groq: [
    { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B" },
    { id: "llama-3.1-8b-instant", label: "Llama 3.1 8B (fast)" },
    { id: "qwen-2.5-32b", label: "Qwen 2.5 32B" },
  ],
  ollama: [
    { id: "llama3.1", label: "Llama 3.1" },
    { id: "qwen2.5", label: "Qwen 2.5" },
    { id: "mistral", label: "Mistral" },
  ],
  azure: [],
};

const DEFAULT_MODEL: Record<ProviderId, string> = {
  openai: "gpt-5.4-mini",
  anthropic: "claude-sonnet-5",
  gemini: "gemini-2.5-flash",
  groq: "llama-3.3-70b-versatile",
  ollama: "llama3.1",
  // Azure's model is the deployment name, which is per-account; no default.
  azure: "",
};

/** Partition the storage key per add-in instance where Office supports it. */
function partition(): string {
  try {
    const ctx = (typeof Office !== "undefined" ? Office.context : undefined) as
      | { partitionKey?: string }
      | undefined;
    return ctx?.partitionKey ? `${ctx.partitionKey}:` : "";
  } catch {
    return "";
  }
}

function keyName(suffix: string): string {
  return `${partition()}${PREFIX}.${suffix}`;
}

/**
 * Session fallback for when localStorage is unavailable (Office storage
 * partitioning, an InPrivate / third-party pane, or an enterprise cookie
 * policy). Without it a swallowed write meant `read` returned null immediately
 * after `setKey` "succeeded", so the key never took: Save looked like a dead
 * button and the user could never get past the BYOK screen. Mirrors the
 * in-memory fallback in lib/prefs.ts and lib/org.ts. Keys still never leave
 * this device.
 */
const memory = new Map<string, string>();

function read(suffix: string): string | null {
  const k = keyName(suffix);
  try {
    const v = localStorage.getItem(k);
    if (v !== null) return v;
  } catch {
    // storage blocked; fall through to the session fallback
  }
  return memory.get(k) ?? null;
}

/** Returns whether the value was PERSISTED (false = held in memory only, so it
 *  works for this session but will not survive a reload). */
function write(suffix: string, value: string | null): boolean {
  const k = keyName(suffix);
  if (value === null) memory.delete(k);
  else memory.set(k, value);
  try {
    if (value === null) localStorage.removeItem(k);
    else localStorage.setItem(k, value);
    return true;
  } catch {
    return false;
  }
}

export function getActiveProvider(): ProviderId {
  const saved = read("provider");
  return saved && (KNOWN_PROVIDERS as string[]).includes(saved) ? (saved as ProviderId) : "openai";
}

export function setActiveProvider(p: ProviderId): void {
  write("provider", p);
}

export function getKey(p: ProviderId): string | null {
  const v = read(`${p}.key`);
  return v && v.trim() ? v : null;
}

/** Returns whether the key was PERSISTED (false = kept for this session only). */
export function setKey(p: ProviderId, key: string): boolean {
  return write(`${p}.key`, key.trim() || null);
}

export function removeKey(p: ProviderId): void {
  write(`${p}.key`, null);
}

/** Clear every provider's key and custom base URL (sign-out / leave BYOK). */
export function clearAllProviderKeys(): void {
  for (const p of KNOWN_PROVIDERS) {
    write(`${p}.key`, null);
    write(`${p}.baseUrl`, null);
  }
}

export function getModel(p: ProviderId): string {
  return read(`${p}.model`) || DEFAULT_MODEL[p];
}

export function setModel(p: ProviderId, model: string): void {
  write(`${p}.model`, model);
}

/** Optional custom endpoint base URL (Ollama server / Azure deployment). Empty
 *  string when unset so callers can fall back to a per-provider default. */
export function getBaseUrl(p: ProviderId): string {
  return read(`${p}.baseUrl`) || "";
}

export function setBaseUrl(p: ProviderId, url: string): void {
  write(`${p}.baseUrl`, url.trim() || null);
}

/** True once the active provider is usable. Unlocks the AI features and the app.
 *  Ollama runs locally with no key, so it counts as configured on its own. */
export function isConfigured(): boolean {
  const p = getActiveProvider();
  if ((KEYLESS_PROVIDERS as string[]).includes(p)) return true;
  return getKey(p) !== null;
}

// --- CourtListener (optional BYO case-law token) ----------------------------
// Separate from the LLM providers: used only to verify that cited cases exist,
// browser-direct against the user's own free CourtListener account.
const CL_TOKEN = "courtlistener.token";

export function getCourtListenerToken(): string | null {
  const v = read(CL_TOKEN);
  return v && v.trim() ? v : null;
}

export function setCourtListenerToken(token: string): void {
  write(CL_TOKEN, token.trim() || null);
}

export function hasCourtListenerToken(): boolean {
  return getCourtListenerToken() !== null;
}
