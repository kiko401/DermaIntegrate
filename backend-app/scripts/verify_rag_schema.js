const db = require('../src/db');

const requiredTables = [
  'rag_knowledge_bases',
  'rag_knowledge_base_members',
  'rag_kb_upgrade_requests',
  'rag_documents',
  'rag_document_versions',
  'rag_tasks',
  'rag_task_events',
  'rag_conversations',
  'rag_messages',
  'rag_message_sources',
  'rag_logs',
  'rag_logs_archive',
  'rag_feedback',
  'rag_api_keys',
  'rag_system_configs',
  'rag_etl_jobs',
  'rag_tool_registry',
  'rag_agent_runs',
  'rag_phi_audit_logs',
];

const requiredColumns = {
  rag_kb_upgrade_requests: [
    'id', 'source_kb_id', 'target_kb_id', 'doc_ids', 'reason', 'status',
    'applicant_doctor_id', 'reviewer_admin_id', 'review_comment',
    'created_at', 'reviewed_at',
  ],
  rag_documents: [
    'id', 'doc_code', 'kb_id', 'title', 'file_name', 'file_ext',
    'storage_path', 'source_type', 'mime_type', 'status',
    'active_version_id', 'uploaded_by', 'deleted_at',
    'created_at', 'updated_at',
  ],
  rag_document_versions: [
    'id', 'doc_id', 'version_no', 'raw_text', 'cleaned_text',
    'parser_meta', 'chunk_meta', 'embedding_model', 'status',
    'created_by', 'created_at',
  ],
  rag_tasks: [
    'id', 'task_code', 'task_type', 'kb_id', 'doc_id', 'doc_version_id',
    'status', 'progress_percent', 'error_message', 'retry_count',
    'payload_json', 'result_json', 'created_by', 'created_at',
    'updated_at', 'completed_at',
  ],
};

async function main() {
  try {
    const [tableRows] = await db.query(`SHOW TABLES LIKE 'rag_%'`);
    const actualTables = new Set(tableRows.map((row) => Object.values(row)[0]));
    const missingTables = requiredTables.filter((table) => !actualTables.has(table));
    if (actualTables.has('rag_chunks')) {
      throw new Error('应用域禁止存在 rag_chunks 表');
    }
    if (missingTables.length) {
      throw new Error(`缺少 RAG 表：${missingTables.join(', ')}`);
    }

    for (const [table, columns] of Object.entries(requiredColumns)) {
      const [rows] = await db.query(`SHOW COLUMNS FROM ${table}`);
      const actualColumns = new Set(rows.map((row) => row.Field));
      const missing = columns.filter((column) => !actualColumns.has(column));
      if (missing.length) {
        throw new Error(`${table} 缺少字段：${missing.join(', ')}`);
      }
    }

    console.log('[verify] RAG V1 schema passed');
    console.log(`[verify] required tables: ${requiredTables.length}`);
  } finally {
    await db.end();
  }
}

main().catch((error) => {
  console.error('[verify] RAG V1 schema failed');
  console.error(error.message || error);
  process.exitCode = 1;
});
