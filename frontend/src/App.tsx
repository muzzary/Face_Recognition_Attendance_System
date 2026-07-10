import { FormEvent, useEffect, useState } from "react";

// Phase 5 skeleton: a login gate in front of the Phase 4 tables. Still a single
// hardcoded org, no routing, no styling - the real dashboard is Phase 6. The
// org id must exist in the local dev database - seed it with
// `python scripts/seed_dev_data.py`, which creates the "acme" org and the
// admin@acme.test / manager@acme.test / employee@acme.test dev logins.
const ORG_ID = "acme";
const API_BASE = "http://127.0.0.1:8000";
const RECENT_ATTENDANCE_LIMIT = 10;
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

async function fetchJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
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
    <main>
      <h1>Face Attendance — sign in</h1>
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
      {error && <p role="alert">{error}</p>}
    </main>
  );
}

function Dashboard({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [roster, attendance] = await Promise.all([
          fetchJson<EmployeeRecord[]>(`/orgs/${ORG_ID}/employees`, token),
          fetchJson<AttendanceEvent[]>(
            `/orgs/${ORG_ID}/attendance?limit=${RECENT_ATTENDANCE_LIMIT}`,
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

  if (loading) return <p>Loading...</p>;
  if (error) return <p role="alert">{error}</p>;

  return (
    <main>
      <h1>Face Attendance — org: {ORG_ID}</h1>
      <button onClick={onLogout}>Sign out</button>

      <h2>Employees</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {employees.map((e) => (
            <tr key={e.employee_id}>
              <td>{e.employee_id}</td>
              <td>{e.full_name}</td>
              <td>{e.is_active ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Recent attendance</h2>
      <table>
        <thead>
          <tr>
            <th>Employee</th>
            <th>Event</th>
            <th>Time</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev, i) => (
            <tr key={`${ev.employee_id}-${ev.occurred_at}-${i}`}>
              <td>{ev.employee_id}</td>
              <td>{ev.event_type}</td>
              <td>{new Date(ev.occurred_at).toLocaleString()}</td>
              <td>{ev.confidence_score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
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

  if (token === null) {
    return <LoginForm onToken={setToken} />;
  }
  return <Dashboard token={token} onLogout={logout} />;
}
