import { describe, expect, it } from "vitest";
import { ApiError, errorFromResponse, friendlyMessage, notFoundMessage } from "./errors";

describe("notFoundMessage", () => {
  it("uses matter copy only for matter-shaped errors", () => {
    const matter = new ApiError("not_found", 404, "Matter gone", "matter_not_found");
    expect(notFoundMessage(matter)).toMatch(/matter/);
    expect(friendlyMessage(matter)).toMatch(/matter/);
  });

  it("keeps the server message for generic 404s", () => {
    const missing = new ApiError("not_found", 404, "Prompt not found.", "not_found");
    expect(notFoundMessage(missing)).toBe("Prompt not found.");
    expect(friendlyMessage(missing)).toBe("Prompt not found.");
  });

  it("falls back when the message is the generic status line", () => {
    const bare = new ApiError("not_found", 404, "Request failed (404)");
    expect(notFoundMessage(bare)).toBe("That resource was not found.");
  });
});

describe("errorFromResponse", () => {
  it("reads detail.error_code and message", async () => {
    const res = new Response(
      JSON.stringify({ detail: { error_code: "not_found", message: "Prompt not found." } }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
    const err = await errorFromResponse(res);
    expect(err.kind).toBe("not_found");
    expect(err.code).toBe("not_found");
    expect(friendlyMessage(err)).toBe("Prompt not found.");
  });

  it("maps matter 404s to the access sentence", async () => {
    const res = new Response(
      JSON.stringify({
        detail: { error_code: "matter_not_found", message: "You do not have access to that matter." },
      }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
    const err = await errorFromResponse(res);
    expect(friendlyMessage(err)).toMatch(/matter/);
  });
});
