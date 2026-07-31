const db = require('../db');

const VALID_ACTIONS = ['generate_context', 'phi_check', 'block'];

/**
 * Fire-and-forget PHI audit log writer.
 * Never throws — audit failures must not block the main flow.
 * Never writes actual PHI values — only field names and action types.
 *
 * @param {object} opts
 * @param {number}   opts.doctorId
 * @param {number|null} opts.patientId
 * @param {number|null} opts.conversationId
 * @param {string}   opts.action  — one of VALID_ACTIONS
 * @param {string[]} opts.phiFields — list of field names detected (not values)
 */
function writePhiAuditLog({ doctorId, patientId = null, conversationId = null, action, phiFields = [] }) {
  if (!VALID_ACTIONS.includes(action)) return;

  db.query(
    `INSERT INTO rag_phi_audit_logs
       (doctor_id, patient_id, conversation_id, action, phi_fields_json)
     VALUES (?, ?, ?, ?, ?)`,
    [
      doctorId || null,
      patientId || null,
      conversationId || null,
      action,
      JSON.stringify(phiFields),
    ]
  ).catch(err => {
    console.error('[ragPhiAuditService] write failed (non-blocking):', err.message);
  });
}

module.exports = { writePhiAuditLog };
