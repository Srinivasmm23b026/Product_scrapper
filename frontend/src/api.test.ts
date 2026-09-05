import { describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("API client", () => {
  it("sends JSON with same-origin credentials", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ onboarded: true }), { status: 200 }));
    await api.session();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session", expect.objectContaining({ credentials: "same-origin" }));
    fetchMock.mockRestore();
  });

  it("normalizes API errors", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid session" }), { status: 401 }));
    await expect(api.session()).rejects.toMatchObject({ message: "Invalid session", status: 401 });
    fetchMock.mockRestore();
  });
});
