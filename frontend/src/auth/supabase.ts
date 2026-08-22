import {
  createClient,
  type Session as SupabaseSession,
  type SupabaseClient,
} from "@supabase/supabase-js";

export interface PublicAuthConfig {
  supabaseUrl?: string;
  supabasePublishableKey?: string;
}

const configuredAuth: PublicAuthConfig = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL?.trim(),
  supabasePublishableKey: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim(),
};

let browserClient: SupabaseClient | null = null;

export const EPHEMERAL_BROWSER_AUTH = {
  autoRefreshToken: false,
  detectSessionInUrl: true,
  persistSession: false,
} as const;

export function resolveAuthMode(
  config: PublicAuthConfig = configuredAuth,
): "cloud" | "local" {
  return config.supabaseUrl && config.supabasePublishableKey ? "cloud" : "local";
}

export function getSupabaseClient(
  config: PublicAuthConfig = configuredAuth,
): SupabaseClient {
  if (resolveAuthMode(config) !== "cloud") {
    throw new Error("Supabase Auth no está configurado para este entorno.");
  }
  if (!browserClient) {
    browserClient = createClient(
      config.supabaseUrl!,
      config.supabasePublishableKey!,
      {
        auth: EPHEMERAL_BROWSER_AUTH,
      },
    );
  }
  return browserClient;
}

export async function beginCloudLogin(
  email: string,
  client: SupabaseClient = getSupabaseClient(),
  redirectOrigin = window.location.origin,
): Promise<string | null> {
  const redirectUrl = new URL("/login", redirectOrigin).toString();

  const { error } = await client.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: redirectUrl,
      shouldCreateUser: false,
    },
  });
  if (error) throw error;
  // Email OTP/magic-link initiation never establishes a session in this
  // response. The browser receives the authenticated session through
  // onAuthStateChange after the invited user follows the link.
  return null;
}

export async function currentCloudAccessToken(
  client: SupabaseClient = getSupabaseClient(),
): Promise<string | null> {
  const { data, error } = await client.auth.getSession();
  if (error) throw error;
  return data.session?.access_token ?? null;
}

export function subscribeToCloudSession(
  onAccessToken: (accessToken: string) => void,
  client: SupabaseClient = getSupabaseClient(),
): () => void {
  const { data } = client.auth.onAuthStateChange((_event, session: SupabaseSession | null) => {
    // A null INITIAL_SESSION is expected because Supabase tokens are never
    // persisted. It must not override the backend's HTTP-only session cookie.
    if (session?.access_token) onAccessToken(session.access_token);
  });
  return () => data.subscription.unsubscribe();
}

export async function signOutCloud(
  client: SupabaseClient = getSupabaseClient(),
): Promise<void> {
  const { error } = await client.auth.signOut();
  if (error) throw error;
}
