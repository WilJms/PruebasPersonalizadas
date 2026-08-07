import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it, vi } from "vitest";
import { beginCloudLogin, resolveAuthMode } from "./supabase";

describe("Supabase invite-only browser authentication", () => {
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
});
