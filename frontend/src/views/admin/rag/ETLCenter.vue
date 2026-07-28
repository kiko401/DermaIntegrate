<template>
  <div class="etl-center rag-admin-page">
    <div class="page-header">
      <h2>ETL 数据处理</h2>
      <div class="header-actions">
        <button class="btn btn-secondary btn-sm" @click="loadJobs" :disabled="loading">
          {{ loading ? '刷新中...' : '刷新列表' }}
        </button>
        <button class="btn btn-primary" @click="showCreateModal = true">新建 ETL 任务</button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filterStatus" @change="loadJobs" class="form-select-sm">
        <option value="">全部状态</option>
        <option value="pending">等待中</option>
        <option value="running">运行中</option>
        <option value="succeeded">已完成</option>
        <option value="failed">已失败</option>
      </select>
      <select v-model="filterKbId" @change="loadJobs" class="form-select-sm">
        <option value="">全部知识库</option>
        <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
      </select>
    </div>

    <!-- 任务列表 -->
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>任务 ID</th>
            <th>任务名称</th>
            <th>来源类型</th>
            <th>知识库</th>
            <th>状态</th>
            <th>进度</th>
            <th>当前阶段</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="9" class="center-cell">加载中...</td>
          </tr>
          <tr v-else-if="jobs.length === 0">
            <td colspan="9" class="center-cell empty-text">暂无 ETL 任务</td>
          </tr>
          <tr v-for="job in jobs" :key="job.job_code || job.id">
            <td class="code-cell">{{ job.job_id || job.job_code }}</td>
            <td>{{ job.job_name || '—' }}</td>
            <td><span class="tag">{{ job.source_type }}</span></td>
            <td>{{ job.kb_name || job.kb_id }}</td>
            <td>
              <span :class="['status-badge', 'status-' + job.status]">
                {{ statusLabel(job.status) }}
              </span>
            </td>
            <td>
              <div class="progress-bar-wrap">
                <div class="progress-bar" :style="{ width: (job.progress || 0) + '%' }"></div>
                <span class="progress-text">{{ job.progress || 0 }}%</span>
              </div>
            </td>
            <td>{{ stageLabel(job.stage) }}</td>
            <td>{{ formatDate(job.created_at) }}</td>
            <td>
              <button
                class="btn btn-xs btn-secondary"
                @click="syncJob(job)"
                :disabled="job.syncing"
                v-if="job.status === 'pending' || job.status === 'running'"
              >
                {{ job.syncing ? '同步中...' : '同步状态' }}
              </button>
              <button
                v-if="job.status === 'failed'"
                class="btn btn-xs btn-danger"
                @click="showError(job)"
              >
                查看错误
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div class="pagination" v-if="total > pageSize">
      <button class="btn btn-xs" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
      <span>第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) }} 页（{{ total }} 条）</span>
      <button class="btn btn-xs" :disabled="page >= Math.ceil(total / pageSize)" @click="changePage(page + 1)">下一页</button>
    </div>

    <!-- 新建任务 Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-box">
        <div class="modal-header">
          <h3>新建 ETL 任务</h3>
          <button class="close-btn" @click="closeCreateModal">×</button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitJob">
            <div class="form-group">
              <label>任务名称</label>
              <input v-model="form.job_name" type="text" class="form-input" placeholder="可选，方便识别" maxlength="200" />
            </div>

            <div class="form-group">
              <label>来源类型 <span class="required">*</span></label>
              <select v-model="form.source_type" class="form-select" required>
                <option value="url">网页 URL</option>
                <option value="database">数据库</option>
                <option value="file">文件（txt/md/pdf/docx）</option>
                <option value="csv">CSV</option>
                <option value="excel">Excel</option>
              </select>
            </div>

            <div class="form-group">
              <label>目标知识库 <span class="required">*</span></label>
              <select v-model="form.kb_id" class="form-select" required>
                <option value="" disabled>请选择知识库</option>
                <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
              </select>
            </div>

            <!-- URL 类型 -->
            <div v-if="form.source_type === 'url'" class="source-config">
              <div class="form-group">
                <label>URL <span class="required">*</span></label>
                <input v-model="form.source_config.url" type="url" class="form-input" placeholder="https://example.com/document.pdf" required />
              </div>
            </div>

            <!-- 数据库类型 -->
            <div v-if="form.source_type === 'database'" class="source-config">
              <div class="form-group">
                <label>数据库类型 <span class="required">*</span></label>
                <select v-model="form.source_config.db_type" class="form-select" required>
                  <option value="mysql">MySQL</option>
                  <option value="postgresql">PostgreSQL</option>
                </select>
              </div>
              <div class="form-row">
                <div class="form-group flex-1">
                  <label>主机 <span class="required">*</span></label>
                  <input v-model="form.source_config.host" type="text" class="form-input" placeholder="localhost" required />
                </div>
                <div class="form-group w-100px">
                  <label>端口 <span class="required">*</span></label>
                  <input v-model.number="form.source_config.port" type="number" class="form-input" placeholder="3306" required />
                </div>
              </div>
              <div class="form-row">
                <div class="form-group flex-1">
                  <label>用户名 <span class="required">*</span></label>
                  <input v-model="form.source_config.user" type="text" class="form-input" required />
                </div>
                <div class="form-group flex-1">
                  <label>密码 <span class="required">*</span></label>
                  <input v-model="form.source_config.password" type="password" class="form-input" />
                </div>
              </div>
              <div class="form-group">
                <label>数据库名 <span class="required">*</span></label>
                <input v-model="form.source_config.database" type="text" class="form-input" required />
              </div>
              <div class="form-group">
                <label>表名</label>
                <input v-model="form.source_config.table_name" type="text" class="form-input" placeholder="与 SQL 查询二选一" />
              </div>
              <div class="form-group">
                <label>SQL 查询（优先）</label>
                <textarea v-model="form.source_config.sql_query" class="form-textarea" placeholder="SELECT * FROM your_table WHERE ..." rows="3"></textarea>
              </div>
              <div class="form-group">
                <label>文本拼接字段（逗号分隔）</label>
                <input v-model="form.source_config.chunk_field" type="text" class="form-input" placeholder="title,content,description" />
              </div>
              <div class="phi-warning">
                <strong>⚠️ PHI 合规提示</strong>：SQL 查询和字段配置中不得包含以下患者标识字段：
                <code>name, patient_name, id_card, phone, mobile, patient_id, source_id, identity, address</code>。
                含有上述字段的请求将被服务端拒绝（错误码 <code>PHI_ETL_BLOCKED</code>）。
              </div>
            </div>

            <!-- 文件类型 -->
            <div v-if="['file', 'csv', 'excel'].includes(form.source_type)" class="source-config">
              <div class="form-group">
                <label>上传文件 <span class="required">*</span></label>
                <input ref="fileInput" type="file" class="form-input" :accept="fileAccept" @change="onFileChange" required />
                <p class="hint">支持 {{ fileAcceptHint }}，最大 50MB</p>
              </div>
            </div>

            <!-- 切分参数 -->
            <div class="form-row">
              <div class="form-group flex-1">
                <label>切分块大小（chunk_size）</label>
                <input v-model.number="form.chunk_size" type="number" class="form-input" min="100" max="4000" />
              </div>
              <div class="form-group flex-1">
                <label>切分重叠（chunk_overlap）</label>
                <input v-model.number="form.chunk_overlap" type="number" class="form-input" min="0" max="2000" />
              </div>
            </div>

            <div v-if="submitError" class="error-msg">{{ submitError }}</div>

            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" @click="closeCreateModal">取消</button>
              <button type="submit" class="btn btn-primary" :disabled="submitting">
                {{ submitting ? '提交中...' : '提交任务' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- 错误详情 Modal -->
    <div v-if="errorModal.show" class="modal-overlay" @click.self="errorModal.show = false">
      <div class="modal-box modal-sm">
        <div class="modal-header">
          <h3>任务错误详情</h3>
          <button class="close-btn" @click="errorModal.show = false">×</button>
        </div>
        <div class="modal-body">
          <p class="code-block">{{ errorModal.message }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const API = '/api/rag'

const jobs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const filterStatus = ref('')
const filterKbId = ref('')
const kbList = ref([])
const showCreateModal = ref(false)
const submitting = ref(false)
const submitError = ref('')
const fileInput = ref(null)
const selectedFile = ref(null)
const errorModal = reactive({ show: false, message: '' })

const form = reactive({
  job_name: '',
  source_type: 'url',
  kb_id: '',
  chunk_size: 800,
  chunk_overlap: 120,
  source_config: {},
})

const fileAccept = computed(() => {
  if (form.source_type === 'csv') return '.csv'
  if (form.source_type === 'excel') return '.xlsx,.xls'
  return '.txt,.md,.pdf,.docx'
})

const fileAcceptHint = computed(() => {
  if (form.source_type === 'csv') return 'CSV'
  if (form.source_type === 'excel') return 'Excel (.xlsx/.xls)'
  return 'txt / md / pdf / docx'
})

function statusLabel(s) {
  const map = { pending: '等待中', running: '运行中', succeeded: '已完成', failed: '已失败' }
  return map[s] || s
}

function stageLabel(s) {
  const map = {
    extracting:  '提取中',
    cleaning:    '清洗中',
    splitting:   '切分中',
    embedding:   '向量化',
    indexing:    '建索引',
    completed:   '已完成',
    failed:      '失败',
  }
  return s ? (map[s] || s) : '—'
}

function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('zh-CN', { hour12: false })
}

async function loadKbs() {
  try {
    const res = await fetch(`${API}/kbs?page=1&pageSize=200`)
    const json = await res.json()
    kbList.value = Array.isArray(json.data) ? json.data : []
  } catch {}
}

async function loadJobs() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      page: page.value,
      pageSize: pageSize.value,
    })
    if (filterStatus.value) params.set('status', filterStatus.value)
    if (filterKbId.value) params.set('kb_id', filterKbId.value)

    const res = await fetch(`${API}/etl/jobs?${params}`)
    const json = await res.json()
    jobs.value = json.data || []
    total.value = json.total || 0
  } catch (err) {
    console.error('loadJobs error', err)
  } finally {
    loading.value = false
  }
}

function changePage(p) {
  page.value = p
  loadJobs()
}

async function syncJob(job) {
  job.syncing = true
  try {
    const res = await fetch(`${API}/etl/jobs/${job.job_id || job.job_code}/sync`, { method: 'POST' })
    const data = await res.json()
    Object.assign(job, data)
    job.job_id = data.job_id
  } catch {}
  job.syncing = false
}

function showError(job) {
  errorModal.message = job.error_message || '无错误信息'
  errorModal.show = true
}

function onFileChange(e) {
  selectedFile.value = e.target.files[0] || null
}

function closeCreateModal() {
  showCreateModal.value = false
  resetForm()
}

function resetForm() {
  form.job_name = ''
  form.source_type = 'url'
  form.kb_id = ''
  form.chunk_size = 800
  form.chunk_overlap = 120
  form.source_config = {}
  selectedFile.value = null
  submitError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function submitJob() {
  submitError.value = ''
  submitting.value = true

  try {
    const isFileType = ['file', 'csv', 'excel'].includes(form.source_type)

    if (isFileType) {
      if (!selectedFile.value) {
        submitError.value = '请选择文件'
        return
      }
      const fd = new FormData()
      fd.append('file', selectedFile.value)
      fd.append('kb_id', form.kb_id)
      fd.append('source_type', form.source_type)
      if (form.job_name) fd.append('job_name', form.job_name)
      fd.append('chunk_size', String(form.chunk_size))
      fd.append('chunk_overlap', String(form.chunk_overlap))

      const res = await fetch(`${API}/etl/jobs`, { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) throw new Error(data.message || '提交失败')
    } else {
      const body = {
        job_name: form.job_name || undefined,
        source_type: form.source_type,
        source_config: { ...form.source_config },
        kb_id: form.kb_id,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
      }
      const res = await fetch(`${API}/etl/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.message || '提交失败')
    }

    closeCreateModal()
    await loadJobs()
  } catch (err) {
    submitError.value = err.message || '提交失败'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadKbs()
  loadJobs()
})
</script>

<style scoped>
.etl-center {
  padding: 20px 24px;
  min-height: 100%;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 10% 14%, rgba(76,128,255,0.08) 0%, transparent 24%),
    radial-gradient(circle at 84% 18%, rgba(0,198,208,0.06) 0%, transparent 22%),
    linear-gradient(180deg, #f7fbff 0%, #eef5fb 52%, #f8fbff 100%);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; font-size: 18px; }
.header-actions { display: flex; gap: 8px; }

.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; }

.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #e9ecef;
  text-align: left;
  white-space: nowrap;
}
.data-table th { background: #f8f9fa; font-weight: 600; color: #495057; }
.center-cell { text-align: center; color: #adb5bd; padding: 32px; }
.empty-text { font-size: 14px; }
.code-cell { font-family: monospace; font-size: 12px; color: #6c757d; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }

.tag { padding: 2px 8px; border-radius: 10px; background: #e9ecef; font-size: 11px; color: #495057; }

.status-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.status-pending  { background: #fff3cd; color: #856404; }
.status-running  { background: #cff4fc; color: #0c5460; }
.status-succeeded { background: #d1e7dd; color: #0f5132; }
.status-failed   { background: #f8d7da; color: #842029; }

.progress-bar-wrap {
  position: relative;
  width: 80px;
  height: 16px;
  background: #e9ecef;
  border-radius: 8px;
  overflow: hidden;
}
.progress-bar {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  background: #0d6efd;
  transition: width .3s;
}
.progress-text {
  position: absolute;
  left: 0; right: 0;
  text-align: center;
  font-size: 10px;
  line-height: 16px;
  color: #333;
  z-index: 1;
}

.pagination { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 13px; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-box {
  background: #fff;
  border-radius: 8px;
  width: 560px;
  max-width: 95vw;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,.2);
}
.modal-box.modal-sm { width: 420px; }
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e9ecef;
}
.modal-header h3 { margin: 0; font-size: 16px; }
.close-btn { background: none; border: none; font-size: 20px; cursor: pointer; color: #adb5bd; }
.modal-body { padding: 20px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 16px; }

.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; }
.required { color: #dc3545; }
.form-input, .form-select, .form-textarea {
  width: 100%; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 4px;
  font-size: 13px; box-sizing: border-box;
}
.form-textarea { resize: vertical; }
.form-row { display: flex; gap: 12px; }
.flex-1 { flex: 1; }
.w-100px { width: 100px; }
.hint { margin: 4px 0 0; font-size: 11px; color: #6c757d; }
.phi-warning {
  margin-top: 10px;
  padding: 8px 12px;
  background: #fff3cd;
  border: 1px solid #ffc107;
  border-radius: 6px;
  font-size: 12px;
  color: #664d03;
  line-height: 1.6;
}
.phi-warning code { background: rgba(0,0,0,0.07); border-radius: 3px; padding: 1px 4px; font-size: 11px; }
.source-config { padding: 12px; background: #f8f9fa; border-radius: 6px; margin-bottom: 14px; }
.error-msg { color: #dc3545; font-size: 13px; margin-bottom: 8px; }
.code-block { font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 12px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; }

/* Buttons */
.btn { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
.btn-primary  { background: #0d6efd; color: #fff; }
.btn-secondary { background: #6c757d; color: #fff; }
.btn-danger   { background: #dc3545; color: #fff; }
.btn-sm  { padding: 4px 10px; font-size: 12px; }
.btn-xs  { padding: 2px 8px; font-size: 11px; }

.form-select-sm { padding: 4px 8px; font-size: 12px; border: 1px solid #ced4da; border-radius: 4px; }
</style>
