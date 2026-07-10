import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "./App";

const TOKEN_KEY = "fa_access_token";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
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
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => byPath(url),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("App (authenticated dashboard)", () => {
  it("renders employee and attendance rows once a token is present", async () => {
    localStorage.setItem(TOKEN_KEY, "test-token");
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getAllByText("EMP-001")).toHaveLength(2);
    expect(screen.getByText("clock_in")).toBeInTheDocument();
  });

  it("attaches the token as a Bearer header on data fetches", async () => {
    localStorage.setItem(TOKEN_KEY, "test-token");
    const fetchMock = mockFetch((url) =>
      url.includes("/employees") ? employees : events,
    );
    render(<App />);

    await screen.findByText("Ada Lovelace");
    for (const call of fetchMock.mock.calls) {
      expect(call[1]?.headers).toMatchObject({
        Authorization: "Bearer test-token",
      });
    }
  });

  it("shows an error message when the API is unreachable", async () => {
    localStorage.setItem(TOKEN_KEY, "test-token");
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

describe("App (login gate)", () => {
  it("logs in, stores the token, and uses it on the next request", async () => {
    // /auth/login returns a token; the subsequent data fetch must carry it.
    const fetchMock = mockFetch((url) => {
      if (url.includes("/auth/login")) return { access_token: "issued-token" };
      return url.includes("/employees") ? employees : events;
    });
    render(<App />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "admin@acme.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "devpassword123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    // Dashboard renders after login, proving the token flowed through.
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(localStorage.getItem(TOKEN_KEY)).toBe("issued-token");

    const dataCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/employees"),
    );
    expect(dataCall?.[1]?.headers).toMatchObject({
      Authorization: "Bearer issued-token",
    });
  });

  it("shows an error and stays on the form when login fails", async () => {
    mockFetch(() => ({ detail: "invalid" }));
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, json: async () => ({}) })),
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "nobody@acme.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Invalid email or password",
      ),
    );
  });
});
