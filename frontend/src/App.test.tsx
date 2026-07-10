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

// The frontend decodes the JWT payload (base64url) purely to branch the UI, so
// tests need real decodable tokens - a signed token isn't required.
function makeToken(claims: Record<string, unknown>): string {
  const payload = btoa(JSON.stringify(claims)).replace(/=+$/, "");
  return `header.${payload}.sig`;
}

const adminToken = makeToken({
  sub: "admin@acme.test",
  org_id: "acme",
  role: "admin",
  employee_id: null,
});

const employeeToken = makeToken({
  sub: "employee@acme.test",
  org_id: "acme",
  role: "employee",
  employee_id: "EMP-001",
});

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
    json: async () =>
      url.includes("/stream-ticket")
        ? { ticket: "short-lived-stream-ticket", expires_in: 60 }
        : byPath(url),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Admin/manager dashboard", () => {
  it("renders the roster and org-wide attendance", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    expect(await screen.findByText("Employees")).toBeInTheDocument();
    // Ada appears both in the roster and the filter dropdown, hence getAllByText.
    expect(screen.getAllByText("Ada Lovelace").length).toBeGreaterThan(0);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Attendance report")).toBeInTheDocument();
    expect(screen.getByText("clock_in")).toBeInTheDocument();
  });

  it("attaches the token as a Bearer header on data fetches", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    const fetchMock = mockFetch((url) =>
      url.includes("/employees") ? employees : events,
    );
    render(<App />);

    await screen.findAllByText("Ada Lovelace");
    for (const call of fetchMock.mock.calls) {
      expect(new Headers(call[1]?.headers).get("Authorization")).toBe(
        `Bearer ${adminToken}`,
      );
    }
  });

  it("shows an error message when the API is unreachable", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
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

describe("Live camera feed", () => {
  it("shows the live feed for admin/manager", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    const feed = (await screen.findByAltText(
      "Live camera feed",
    )) as HTMLImageElement;
    expect(feed).toBeInTheDocument();
    expect(feed.src).toContain("/orgs/acme/stream?ticket=");
    expect(feed.src).toContain("short-lived-stream-ticket");
    expect(feed.src).not.toContain(adminToken);
  });

  it("requests the stream ticket with the access-token header", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    const fetchMock = mockFetch((url) =>
      url.includes("/employees") ? employees : events,
    );
    render(<App />);

    await screen.findByAltText("Live camera feed");
    const ticketCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes("/stream-ticket"),
    );
    expect(ticketCall?.[1]?.method).toBe("POST");
    expect(new Headers(ticketCall?.[1]?.headers).get("Authorization")).toBe(
      `Bearer ${adminToken}`,
    );
  });

  it("does not show the live feed for an employee", async () => {
    localStorage.setItem(TOKEN_KEY, employeeToken);
    mockFetch(() => events);
    render(<App />);

    await screen.findByText("Your attendance history");
    expect(screen.queryByAltText("Live camera feed")).not.toBeInTheDocument();
    expect(screen.queryByText("Live camera")).not.toBeInTheDocument();
  });

  it("shows an unavailable message when the stream errors (503)", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    const feed = await screen.findByAltText("Live camera feed");
    // Simulate the browser firing onError when the stream 503s.
    fireEvent.error(feed);

    expect(
      await screen.findByText("Live camera feed is unavailable."),
    ).toBeInTheDocument();
    expect(screen.queryByAltText("Live camera feed")).not.toBeInTheDocument();
  });
});

describe("Employee self-service dashboard", () => {
  it("never requests the roster and shows only its own attendance", async () => {
    localStorage.setItem(TOKEN_KEY, employeeToken);
    const fetchMock = mockFetch(() => events);
    render(<App />);

    expect(await screen.findByText("Your attendance history")).toBeInTheDocument();
    // No roster section, and no /employees call was ever attempted.
    expect(screen.queryByText("Employees")).not.toBeInTheDocument();
    expect(screen.queryByText("Attendance report")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/employees")),
    ).toBe(false);
    expect(screen.getByText("clock_in")).toBeInTheDocument();
  });

  it("derives days-present from the returned events", async () => {
    localStorage.setItem(TOKEN_KEY, employeeToken);
    mockFetch(() => events);
    render(<App />);

    await screen.findByText("Days present");
    // One event on a single date -> one day present.
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});

describe("Login and logout", () => {
  it("logs in, stores the token, and renders the role-appropriate view", async () => {
    const fetchMock = mockFetch((url) => {
      if (url.includes("/auth/login")) return { access_token: adminToken };
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

    expect((await screen.findAllByText("Ada Lovelace")).length).toBeGreaterThan(
      0,
    );
    expect(localStorage.getItem(TOKEN_KEY)).toBe(adminToken);
    const dataCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/employees"),
    );
    expect(new Headers(dataCall?.[1]?.headers).get("Authorization")).toBe(
      `Bearer ${adminToken}`,
    );
  });

  it("logout clears the token and returns to the login form", async () => {
    localStorage.setItem(TOKEN_KEY, adminToken);
    mockFetch((url) => (url.includes("/employees") ? employees : events));
    render(<App />);

    await screen.findAllByText("Ada Lovelace");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });

  it("shows an error and stays on the form when login fails", async () => {
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
