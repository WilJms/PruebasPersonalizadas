import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./App";

describe("private application shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects an unauthenticated private route to login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "No authenticated session" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/activities/new"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Entrar al workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Configura el recorrido de verificación" })).not.toBeInTheDocument();
  });
});
