const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '../..');

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

function requireText(content, needle, label) {
  if (!content.includes(needle)) {
    throw new Error(`${label} 缺少冻结内容：${needle}`);
  }
}

function main() {
  const apiSpec = read('docs/API_SPEC.md');
  const appSpec = read('docs/APP_SPEC.md');
  const designSpec = read('docs/RAG子系统详细设计及执行规范.md');
  const kbRoutes = read('backend-app/src/routes/rag_kb.js');
  const taskRoutes = read('backend-app/src/routes/rag_tasks.js');
  const taskService = read('backend-app/src/services/ragTaskService.js');
  const documentService = read('backend-app/src/services/ragDocumentService.js');
  const knowledgeBaseService = read('backend-app/src/services/ragKnowledgeBaseService.js');
  const versionService = read('backend-app/src/services/ragVersionService.js');
  const aiSchemas = read('backend-ai/modules/kb_rag/schemas.py');
  const aiIngestion = read('backend-ai/modules/kb_rag/ingest/ingestion.py');
  const aiVectorStore = read('backend-ai/modules/kb_rag/ingest/vector_store.py');

  for (const [content, label] of [
    [apiSpec, 'API_SPEC'],
    [appSpec, 'APP_SPEC'],
    [designSpec, 'RAG SDD'],
  ]) {
    requireText(content, 'document_mappings', label);
    requireText(content, 'task_code', label);
    requireText(content, 'derma_knowledge', label);
  }

  requireText(kbRoutes, "router.delete('/:kbId', requireAdmin", '知识库删除路由');
  requireText(taskRoutes, "router.get('/', requireAdmin", '任务列表路由');
  requireText(taskService, 'TASK_CODE_MISMATCH', '任务回调');
  requireText(taskService, 'body.chunk_count', '任务回调');
  requireText(taskService, "payload.embedding_model || 'BAAI/bge-small-zh-v1.5'", 'Embedding 模型透传');
  requireText(documentService, 'kb_id 为必填正整数', '文档列表');
  requireText(documentService, 'sv.cleaned_text LIKE ?', '文档内容搜索');
  requireText(knowledgeBaseService, 'reviewResult.affectedRows !== 1', '升级申请审批幂等');
  requireText(knowledgeBaseService, "sourceKb.scope_type !== 'personal'", '升级申请来源校验');
  requireText(versionService, 'createReindexTextTask', '版本回滚');
  requireText(aiSchemas, 'document_mappings: List[CloneDocumentMapping]', 'AI 克隆请求');
  requireText(aiSchemas, 'task_id: int', '纯文本重索引请求');
  requireText(aiIngestion, 'replace_document_vectors_async', '重索引安全替换');
  requireText(aiVectorStore, 'old_point_ids - new_point_ids', '旧向量清理');

  if (versionService.includes('not implemented')) {
    throw new Error('版本服务仍包含占位实现');
  }

  console.log('[verify] RAG V1 contract passed');
}

try {
  main();
} catch (error) {
  console.error('[verify] RAG V1 contract failed');
  console.error(error.message || error);
  process.exitCode = 1;
}
