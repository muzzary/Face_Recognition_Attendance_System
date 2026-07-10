import { FormEvent, useEffect, useMemo, useState } from "react";
import "./App.css";

// Phase 6: role-appropriate dashboards on top of the Phase 5 auth gate. The org
// id is still a single hardcoded tenant (seed it with
// `python scripts/seed_dev_data.py`, which creates the "acme" org and the
// admin@acme.test / manager@acme.test / employee@acme.test dev logins).
const ORG_ID = "acme";
const API_BASE = "http://127.0.0.1:8000";
const ATTENDANCE_LIMIT = 100;
const TOKEN_KEY = "fa_access_token";

interface EmployeeRecord {
  employee_id: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  org_id: string;
}

interface AttendanceEvent {
  employee_id: string;
  occurred_at: string;
  event_type: string;
  confidence_score: number;
  match_distance: number;
  org_id: string;
}

// Only the claims the UI branches on. The token is already trusted (the API
// enforces the real authorization); this decode is purely for UX branching, so
// no signature check and no JWT library are needed on the frontend.
interface TokenClaims {
  sub: string;
  org_id: string;
  role: "admin" | "manager" | "employee";
  employee_id: string | null;
}

function decodeToken(token: string): TokenClaims | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    let b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    b64 += "=".repeat((4 - (b64.length % 4)) % 4); // restore base64url padding
    return JSON.parse(atob(b64)) as TokenClaims;
  } catch {
    return null;
  }
}

async function fetchJson<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    throw new Error(`API responded ${response.status}`);
  }
  return (await response.json()) as T;
}

async function login(email: string, password: string): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error("Login failed");
  }
  const data = (await response.json()) as { access_token: string };
  return data.access_token;
}

function LoginForm({ onToken }: { onToken: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const token = await login(email, password);
      localStorage.setItem(TOKEN_KEY, token);
      onToken(token);
    } catch {
      setError("Invalid email or password");
    }
  }

  return (
    <main className="login">
      <h1>Face Attendance</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit">Sign in</button>
      </form>
      {error && (
        <p className="state error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}

function Header({
  claims,
  onLogout,
}: {
  claims: TokenClaims;
  onLogout: () => void;
}) {
  return (
    <header className="app-header">
      <div className="brand">
        Face Attendance <span className="org">{claims.org_id}</span>
      </div>
      <div className="header-user">
        <span className="email">{claims.sub}</span>
        <span className="role-pill">{claims.role}</span>
        <button className="ghost" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </header>
  );
}

function AttendanceTable({
  events,
  showEmployee,
}: {
  events: AttendanceEvent[];
  showEmployee: boolean;
}) {
  if (events.length === 0) {
    return <p className="empty">No attendance events yet.</p>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {showEmployee && <th>Employee</th>}
            <th>Event</th>
            <th>Time</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev, i) => (
            <tr key={`${ev.employee_id}-${ev.occurred_at}-${i}`}>
              {showEmployee && <td>{ev.employee_id}</td>}
              <td>{ev.event_type}</td>
              <td>{new Date(ev.occurred_at).toLocaleString()}</td>
              <td>{ev.confidence_score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// MJPEG renders natively in a plain <img>, which cannot set an Authorization
// header. Fetch a one-minute, stream-only ticket with the access-token header;
// only that restricted credential enters the image URL.
function LiveFeed({ token }: { token: string }) {
  const [ticket, setTicket] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadTicket() {
      try {
        const result = await fetchJson<{ ticket: string }>(
          `/orgs/${ORG_ID}/stream-ticket`,
          token,
          { method: "POST" },
        );
        if (!cancelled) setTicket(result.ticket);
      } catch {
        if (!cancelled) setFailed(true);
      }
    }
    loadTicket();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const src = ticket
    ? `${API_BASE}/orgs/${ORG_ID}/stream?ticket=${encodeURIComponent(ticket)}`
    : null;
  return (
    <section className="card">
      <h2>Live camera</h2>
      {failed ? (
        <p className="state error" role="alert">
          Live camera feed is unavailable.
        </p>
      ) : src ? (
        <img
          className="live-feed"
          src={src}
          alt="Live camera feed"
          onError={() => setFailed(true)}
        />
      ) : (
        <p className="state">Connecting to live camera...</p>
      )}
    </section>
  );
}

// admin and manager share the same full-org scope (a documented Phase 5
// simplification - no team hierarchy is modeled yet).
function AdminDashboard({ token }: { token: string }) {
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [roster, attendance] = await Promise.all([
          fetchJson<EmployeeRecord[]>(`/orgs/${ORG_ID}/employees`, token),
          fetchJson<AttendanceEvent[]>(
            `/orgs/${ORG_ID}/attendance?limit=${ATTENDANCE_LIMIT}`,
            token,
          ),
        ]);
        if (cancelled) return;
        setEmployees(roster);
        setEvents(attendance);
      } catch {
        if (!cancelled) setError("Failed to reach API");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const visibleEvents = useMemo(
    () => (filter ? events.filter((e) => e.employee_id === filter) : events),
    [events, filter],
  );

  if (loading) return <p className="state">Loading dashboard...</p>;
  if (error)
    return (
      <p className="state error" role="alert">
        {error}
      </p>
    );

  return (
    <>
      <LiveFeed token={token} />

      <section className="card">
        <h2>Employees</h2>
        {employees.length === 0 ? (
          <p className="empty">No employees enrolled yet.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((e) => (
                  <tr key={e.employee_id}>
                    <td>{e.employee_id}</td>
                    <td>{e.full_name}</td>
                    <td>
                      <span
                        className={`badge ${e.is_active ? "active" : "inactive"}`}
                      >
                        {e.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Attendance report</h2>
          <label className="filter">
            Employee
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All employees</option>
              {employees.map((e) => (
                <option key={e.employee_id} value={e.employee_id}>
                  {e.full_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <AttendanceTable events={visibleEvents} showEmployee />
      </section>
    </>
  );
}

function lastEventTime(events: AttendanceEvent[], type: string): string | null {
  const match = events
    .filter((e) => e.event_type === type)
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))[0];
  return match ? new Date(match.occurred_at).toLocaleString() : null;
}

// Self-service view: the employee never touches the roster route (the API 403s
// it), and all stats are derived client-side from the events the API already
// scopes to them - no new backend endpoints.
function EmployeeDashboard({ token }: { token: string }) {
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        // No employee_id param needed: the API forces the filter to the
        // caller's own id for employee-role tokens.
        const attendance = await fetchJson<AttendanceEvent[]>(
          `/orgs/${ORG_ID}/attendance?limit=${ATTENDANCE_LIMIT}`,
          token,
        );
        if (!cancelled) setEvents(attendance);
      } catch {
        if (!cancelled) setError("Failed to reach API");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const daysPresent = useMemo(
    () => new Set(events.map((e) => e.occurred_at.slice(0, 10))).size,
    [events],
  );

  if (loading) return <p className="state">Loading your attendance...</p>;
  if (error)
    return (
      <p className="state error" role="alert">
        {error}
      </p>
    );

  return (
    <>
      <section className="card">
        <h2>Your summary</h2>
        <div className="stats">
          <div className="stat">
            <div className="label">Days present</div>
            <div className="value">{daysPresent}</div>
          </div>
          <div className="stat">
            <div className="label">Last clock-in</div>
            <div className="value">
              {lastEventTime(events, "clock_in") ?? "--"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Last clock-out</div>
            <div className="value">
              {lastEventTime(events, "clock_out") ?? "--"}
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Your attendance history</h2>
        <AttendanceTable events={events} showEmployee={false} />
      </section>
    </>
  );
}

function Dashboard({
  token,
  claims,
  onLogout,
}: {
  token: string;
  claims: TokenClaims;
  onLogout: () => void;
}) {
  return (
    <>
      <Header claims={claims} onLogout={onLogout} />
      <main className="content">
        {claims.role === "employee" ? (
          <EmployeeDashboard token={token} />
        ) : (
          <AdminDashboard token={token} />
        )}
      </main>
    </>
  );
}

export function App() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY),
  );

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }

  const claims = token ? decodeToken(token) : null;
  if (!token || !claims) {
    // Drop an unreadable/stale token so we land cleanly on the login form
    // instead of looping on a broken session.
    if (token && !claims) localStorage.removeItem(TOKEN_KEY);
    return <LoginForm onToken={setToken} />;
  }
  return <Dashboard token={token} claims={claims} onLogout={logout} />;
}
