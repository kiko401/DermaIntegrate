/**
 * DebounceManager — 同一 patient_id 30s 窗口内合并推送，到期执行 triggerAnalysis
 *
 * 使用内存 Map，不依赖 Redis。进程重启后定时器丢失，可接受（demo 场景）。
 */

const DEBOUNCE_MS = 30_000;

// patient_id → { timer, count }
const pending = new Map();

let _triggerFn = null;

function init(triggerFn) {
  _triggerFn = triggerFn;
}

function schedule(patientId) {
  const existing = pending.get(patientId);
  if (existing) {
    clearTimeout(existing.timer);
    existing.count += 1;
  }

  const timer = setTimeout(async () => {
    pending.delete(patientId);
    if (_triggerFn) {
      try {
        await _triggerFn(patientId);
      } catch (e) {
        console.error(`[debounce] triggerAnalysis failed for patient ${patientId}:`, e.message);
      }
    }
  }, DEBOUNCE_MS);

  pending.set(patientId, { timer, count: existing ? existing.count : 1 });
  console.log(`[debounce] patient ${patientId} scheduled (${pending.get(patientId).count} push(es) merged)`);
}

function getPending() {
  return [...pending.keys()];
}

module.exports = { init, schedule, getPending };
