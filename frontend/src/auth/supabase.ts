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
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: true,
          persistSession: true,
        },
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
  onSession: (session: SupabaseSession | null) => void,
  client: SupabaseClient = getSupabaseClient(),
): () => void {
  const { data } = client.auth.onAuthStateChange((_event, session) => onSession(session));
  return () => data.subscription.unsubscribe();
}

export async function signOutCloud(
  client: SupabaseClient = getSupabaseClient(),
): Promise<void> {
  const { error } = await client.auth.signOut();
  if (error) throw error;
}
