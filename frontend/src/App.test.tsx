import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const employees = [
  {
    employee_id: "EMP-001",
    full_name: "Ada Lovelace",
    is_active: true,
    created_at: "2026-06-10T00:00:00Z",
    org_id: "acme",
  },
];

const events = [
  {
    employee_id: "EMP-001",
    occurred_at: "2026-07-10T09:00:00Z",
    event_type: "clock_in",
    confidence_score: 0.98,
    match_distance: 0.21,
    org_id: "acme",
  },
];

function mockFetch(byPath: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => byPath(url),
    })),
  );
}

describe("App", () => {
  it("renders employee and attendance rows from the API", async () => {
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    // EMP-001 appears in both the roster and the attendance row.
    expect(screen.getAllByText("EMP-001")).toHaveLength(2);
    expect(screen.getByText("clock_in")).toBeInTheDocument();
  });

  it("shows an error message when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    render(<App />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Failed to reach API"),
    );
  });
});
