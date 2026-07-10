import { useEffect, useState } from "react";

// Phase 4 walking skeleton: a single hardcoded org, no auth, no routing.
// The org id must exist in the local dev database - seed it with
// `python scripts/seed_dev_data.py`, which creates the "acme" org.
const ORG_ID = "acme";
const API_BASE = "http://127.0.0.1:8000";
const RECENT_ATTENDANCE_LIMIT = 10;

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

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API responded ${response.status}`);
  }
  return (await response.json()) as T;
}

export function App() {
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [roster, attendance] = await Promise.all([
          fetchJson<EmployeeRecord[]>(`/orgs/${ORG_ID}/employees`),
          fetchJson<AttendanceEvent[]>(
            `/orgs/${ORG_ID}/attendance?limit=${RECENT_ATTENDANCE_LIMIT}`,
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
  }, []);

  if (loading) return <p>Loading...</p>;
  if (error) return <p role="alert">{error}</p>;

  return (
    <main>
      <h1>Face Attendance — org: {ORG_ID}</h1>

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
