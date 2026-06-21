// ConnectionMonitor: in-memory registry of active SSE sessions (UC-11 / M5)
const registry = new Map(); // task_id → { res, doctorName, patientId, connectedAt, lastHeartbeat }

function register(taskId, { res, doctorName, patientId }) {
  registry.set(taskId, {
    res,
    doctorName: doctorName || '—',
    patientId:  patientId  || '—',
    connectedAt:   new Date(),
    lastHeartbeat: new Date(),
  });
}

function unregister(taskId) {
  registry.delete(taskId);
}

function touch(taskId) {
  const entry = registry.get(taskId);
  if (entry) entry.lastHeartbeat = new Date();
}

function list() {
  const now = Date.now();
  return Array.from(registry.entries()).map(([taskId, e]) => ({
    task_id:          taskId,
    doctor_name:      e.doctorName,
    patient_id:       e.patientId,
    connected_at:     e.connectedAt.toISOString(),
    duration_seconds: Math.floor((now - e.connectedAt.getTime()) / 1000),
    last_heartbeat:   e.lastHeartbeat.toISOString(),
  }));
}

// SessionGovernor: notify frontend then close (UC-11 step 7b-c)
function forceClose(taskIds) {
  const released = [];
  const already_closed = [];
  for (const id of taskIds) {
    const entry = registry.get(id);
    if (!entry) { already_closed.push(id); continue; }
    try {
      entry.res.write(`event: force_close\ndata: ${JSON.stringify({ reason: 'admin_force_release' })}\n\n`);
      entry.res.end();
    } catch (_) { /* connection may already be gone */ }
    registry.delete(id);
    released.push(id);
  }
  return { released, already_closed };
}

module.exports = { register, unregister, touch, list, forceClose };
