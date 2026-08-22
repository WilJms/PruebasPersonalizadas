import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it, vi } from "vitest";
import {
  beginCloudLogin,
  EPHEMERAL_BROWSER_AUTH,
  resolveAuthMode,
  subscribeToCloudSession,
} from "./supabase";

describe("Supabase invite-only browser authentication", () => {
  it("never persists or refreshes the exchange token in browser storage", () => {
    expect(EPHEMERAL_BROWSER_AUTH).toEqual({
      autoRefreshToken: false,
      detectSessionInUrl: true,
      persistSession: false,
    });
  });

  it("keeps local auth when public cloud variables are absent", () => {
    expect(resolveAuthMode({})).toBe("local");
    expect(
      resolveAuthMode({
        supabaseUrl: "https://project.supabase.co",
        supabasePublishableKey: "publishable-key",
      }),
    ).toBe("cloud");
  });

  it("requests an OTP only for an existing invited user and uses the app origin", async () => {
    const signInWithOtp = vi.fn().mockResolvedValue({
      data: { user: null, session: null },
      error: null,
    });
    const client = { auth: { signInWithOtp } } as unknown as SupabaseClient;

    await expect(
      beginCloudLogin("docente@example.test", client, "https://app.example.test"),
    ).resolves.toBeNull();

    expect(signInWithOtp).toHaveBeenCalledWith({
      email: "docente@example.test",
      options: {
        emailRedirectTo: "https://app.example.test/login",
        shouldCreateUser: false,
      },
    });
  });

  it("waits for the auth state callback instead of trusting a noncanonical immediate session", async () => {
    const signInWithOtp = vi.fn().mockResolvedValue({
      data: { user: null, session: { access_token: "access-token-01" } },
      error: null,
    });
    const client = { auth: { signInWithOtp } } as unknown as SupabaseClient;

    await expect(
      beginCloudLogin("docente@example.test", client, "https://app.example.test"),
    ).resolves.toBeNull();
  });

  it("ignores an empty ephemeral Supabase session and forwards only access tokens", () => {
    let callback: ((event: string, session: unknown) => void) | undefined;
    const unsubscribe = vi.fn();
    const onAuthStateChange = vi.fn((handler) => {
      callback = handler;
      return { data: { subscription: { unsubscribe } } };
    });
    const client = { auth: { onAuthStateChange } } as unknown as SupabaseClient;
    const onAccessToken = vi.fn();

    const stop = subscribeToCloudSession(onAccessToken, client);
    callback?.("INITIAL_SESSION", null);
    expect(onAccessToken).not.toHaveBeenCalled();
    callback?.("SIGNED_IN", { access_token: "access-token-01" });
    expect(onAccessToken).toHaveBeenCalledWith("access-token-01");
    stop();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
