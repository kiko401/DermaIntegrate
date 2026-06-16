<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter, useRoute } from 'vue-router'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const route  = useRoute()

// ── Patient list ──────────────────────────────────────────────
const patients = ref([])
const loadingPatients = ref(false)
const selectedPatient = ref(null)
const showNewPatientModal = ref(false)
const submittingPatient = ref(false)
const patientForm = ref({ name: '', id_card: '', phone: '' })
const searchQuery = ref('')

const filteredPatients = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return patients.value
  return patients.value.filter(p =>
    p.name?.toLowerCase().includes(q) ||
    p.phone?.includes(q) ||
    p.id_card?.includes(q)
  )
})

const doctorName = computed(() => {
  try { return JSON.parse(localStorage.getItem('doctor_info') || '{}').name || 'doctor' } catch { return 'doctor' }
})

async function fetchPatients() {
  loadingPatients.value = true
  try {
    const res = await apiFetch('/api/patients')
    patients.value = await res.json()
  } catch {
    message.error('加载患者列表失败')
  } finally {
    loadingPatients.value = false
  }
}

async function createPatient() {
  if (!patientForm.value.name.trim()) { message.warning('姓名不能为空'); return }
  submittingPatient.value = true
  try {
    const res = await apiFetch('/api/patients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patientForm.value),
    })
    if (!res.ok) throw new Error()
    message.success('患者创建成功')
    showNewPatientModal.value = false
    patientForm.value = { name: '', id_card: '', phone: '' }
    await fetchPatients()
  } catch {
    message.error('创建失败')
  } finally {
    submittingPatient.value = false
  }
}

function selectPatient(p) {
  selectedPatient.value = p
  visits.value = []
  visitTaskMap.value = {}
  fetchVisits(p.id)
}

// ── Visits ────────────────────────────────────────────────────
const visits = ref([])
const loadingVisits = ref(false)
const showVisitModal = ref(false)
const submittingVisit = ref(false)
const visitForm = ref({ chief_complaint: '' })
const visitTaskMap = ref({})

const visitColumns = [
  { title: '就诊日期', dataIndex: 'visit_date', key: 'visit_date', width: 110,
    customRender: ({ text }) => text ? text.slice(0, 10) : '-' },
  { title: '主诉', dataIndex: 'chief_complaint', key: 'chief_complaint' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150,
    customRender: ({ text }) => text ? text.replace('T', ' ').slice(0, 16) : '-' },
  { title: '状态', key: 'status', width: 90 },
  { title: '操作', key: 'action', width: 160 },
]

async function fetchVisits(patientId) {
  loadingVisits.value = true
  try {
    const res = await apiFetch(`/api/patients/${patientId}/visits`)
    visits.value = await res.json()
  } catch {
    message.error('加载就诊记录失败')
  } finally {
    loadingVisits.value = false
  }
}

async function createVisit() {
  submittingVisit.value = true
  try {
    const res = await apiFetch(`/api/patients/${selectedPatient.value.id}/visits`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(visitForm.value),
    })
    if (!res.ok) throw new Error()
    message.success('就诊记录创建成功')
    showVisitModal.value = false
    visitForm.value = { chief_complaint: '' }
    await fetchVisits(selectedPatient.value.id)
  } catch {
    message.error('创建失败')
  } finally {
    submittingVisit.value = false
  }
}

// ── AI analysis ───────────────────────────────────────────────
const uploading = ref(false)
const selectedVisitId = ref(null)
const showAnalysisModal = ref(false)
const pendingVisitId = ref(null)
const analysisForm = ref({ clinical_text: '' })
const imageFile = ref(null)
const imagePreviewUrl = ref(null)
const clinicalForm = ref({ age: null, gender: '', region: '', itch: false, grew: false })
const labForm = ref({ breslow_thickness_mm: null, ulceration: false, braf_mutation: '' })

function onFileChange(e) {
  const file = e.target.files[0] || null
  imageFile.value = file
  imagePreviewUrl.value = file ? URL.createObjectURL(file) : null
}

function openAnalysis(visitId) {
  pendingVisitId.value = visitId
  analysisForm.value = { clinical_text: '' }
  imageFile.value = null
  imagePreviewUrl.value = null
  clinicalForm.value = { age: null, gender: '', region: '', itch: false, grew: false }
  labForm.value = { breslow_thickness_mm: null, ulceration: false, braf_mutation: '' }
  showAnalysisModal.value = true
}

function viewAnalysis(visitId) {
  const taskId = visitTaskMap.value[visitId]
  if (taskId) router.push('/tasks/' + taskId)
}

async function launchAnalysis() {
  const visitId = pendingVisitId.value
  selectedVisitId.value = visitId
  uploading.value = true
  showAnalysisModal.value = false
  try {
    const formData = new FormData()
    formData.append('visit_id', visitId)
    if (imageFile.value) formData.append('file', imageFile.value)
    const hasClinical = clinicalForm.value.age != null || clinicalForm.value.gender ||
      clinicalForm.value.region || clinicalForm.value.itch || clinicalForm.value.grew
    if (hasClinical) {
      formData.append('clinical_json', JSON.stringify({
        patient_info: { age: clinicalForm.value.age, gender: clinicalForm.value.gender || null },
        lesion_clinical: { region: clinicalForm.value.region || null },
        lesion_symptoms: { itch: clinicalForm.value.itch, grew: clinicalForm.value.grew },
      }))
    } else if (analysisForm.value.clinical_text.trim()) {
      formData.append('clinical_text', analysisForm.value.clinical_text)
    }
    const hasLab = labForm.value.breslow_thickness_mm != null || labForm.value.braf_mutation || labForm.value.ulceration
    if (hasLab) {
      formData.append('lab_json', JSON.stringify({
        breslow_thickness_mm: labForm.value.breslow_thickness_mm,
        ulceration: labForm.value.ulceration,
        braf_mutation: labForm.value.braf_mutation || null,
      }))
    }
    const res = await apiFetch('/api/tasks/upload', { method: 'POST', body: formData })
    const data = await res.json()
    if (data.task_id) {
      visitTaskMap.value[visitId] = data.task_id
      message.success('AI 分析已发起')
      router.push('/tasks/' + data.task_id)
    } else {
      message.error(data.error || '发起失败')
    }
  } catch {
    message.error('请求失败')
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  await fetchPatients()
  const pid = route.query.patient_id
  if (pid) {
    const target = patients.value.find(p => String(p.id) === String(pid))
    if (target) selectPatient(target)
  }
})
</script>

<template>
  <div class="page">

    <!-- Header -->
    <div class="page-header">
      <div>
        <div class="section-title">患者管理</div>
        <div class="page-sub">患者档案与就诊工作台</div>
      </div>
      <a-button type="primary" @click="showNewPatientModal = true">+ 新建患者</a-button>
    </div>

    <!-- Search -->
    <div class="search-row">
      <a-input
        v-model:value="searchQuery"
        placeholder="搜索患者 · 姓名 / 手机 / 身份证"
        allow-clear
        style="max-width: 360px"
      />
    </div>

    <!-- Patient strip -->
    <div class="card strip-card">
      <div class="strip-label">患者切换</div>
      <div v-if="loadingPatients" style="padding:12px 0;color:#94a3b8;font-size:13px">加载中…</div>
      <div v-else-if="filteredPatients.length === 0" style="padding:12px 0;color:#94a3b8;font-size:13px">
        {{ patients.length === 0 ? '暂无患者，点击右上角「新建患者」' : '无匹配结果' }}
      </div>
      <div v-else class="patient-strip">
        <div
          v-for="p in filteredPatients"
          :key="p.id"
          class="p-card"
          :class="{ active: selectedPatient?.id === p.id }"
          @click="selectPatient(p)"
        >
          <div class="pc-avatar">{{ p.name[0] }}</div>
          <div class="pc-name">{{ p.name }}</div>
          <div class="pc-sub">{{ p.phone || p.id_card || '—' }}</div>
          <a-tag v-if="visitTaskMap[p.id] !== undefined" color="success" style="margin:4px 0 0;font-size:11px;line-height:1.6">已分析</a-tag>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!selectedPatient" class="empty-work">
      <div style="font-size:13px;color:#94a3b8">从上方选择患者，查看就诊记录</div>
    </div>

    <template v-else>
      <!-- Overview card -->
      <div class="card overview-card">
        <div class="ov-header">
          <div class="ov-main">
            <div class="ov-avatar">{{ selectedPatient.name[0] }}</div>
            <div>
              <div class="ov-name">{{ selectedPatient.name }}</div>
              <div class="ov-meta-row">
                <span class="ov-meta-item"><span class="meta-label">手机</span>{{ selectedPatient.phone || '—' }}</span>
                <span class="ov-sep">·</span>
                <span class="ov-meta-item"><span class="meta-label">身份证</span>{{ selectedPatient.id_card || '—' }}</span>
                <span class="ov-sep">·</span>
                <span class="ov-meta-item"><span class="meta-label">主治医生</span>{{ doctorName }}</span>
                <span class="ov-sep">·</span>
                <span class="ov-meta-item">
                  <span class="meta-label">最近更新</span>
                  {{ selectedPatient.created_at ? selectedPatient.created_at.replace('T', ' ').slice(0, 10) : '—' }}
                </span>
              </div>
            </div>
          </div>
          <a-button type="primary" size="small" @click="showVisitModal = true">+ 新建就诊</a-button>
        </div>
      </div>

      <!-- Visits table -->
      <div class="card">
        <div class="card-head">
          <div class="card-title">就诊记录</div>
          <div class="card-sub">{{ visits.length ? `共 ${visits.length} 条` : '暂无记录' }}</div>
        </div>
        <a-table
          :columns="visitColumns"
          :data-source="visits"
          :loading="loadingVisits"
          row-key="id"
          :pagination="{ pageSize: 8, showSizeChanger: false }"
          :locale="{ emptyText: '暂无就诊记录，点击右上角「新建就诊」' }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag
                :color="visitTaskMap[record.id] ? 'success' : 'default'"
                style="margin:0;font-size:12px"
              >{{ visitTaskMap[record.id] ? '已分析' : '未分析' }}</a-tag>
            </template>
            <template v-if="column.key === 'action'">
              <a-space>
                <a-button
                  v-if="visitTaskMap[record.id]"
                  type="link" size="small"
                  @click="viewAnalysis(record.id)"
                >查看分析</a-button>
                <a-button
                  type="link" size="small"
                  :loading="uploading && selectedVisitId === record.id"
                  @click="openAnalysis(record.id)"
                >{{ visitTaskMap[record.id] ? '重新分析' : '发起 AI 分析' }}</a-button>
              </a-space>
            </template>
          </template>
        </a-table>
      </div>
    </template>

  </div>

  <!-- New patient -->
  <a-modal v-model:open="showNewPatientModal" title="新建患者" @ok="createPatient" :confirm-loading="submittingPatient">
    <a-form layout="vertical" style="margin-top:8px">
      <a-form-item label="姓名" required>
        <a-input v-model:value="patientForm.name" placeholder="请输入姓名" />
      </a-form-item>
      <a-form-item label="身份证号">
        <a-input v-model:value="patientForm.id_card" placeholder="可选" />
      </a-form-item>
      <a-form-item label="手机号">
        <a-input v-model:value="patientForm.phone" placeholder="可选" />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- New visit -->
  <a-modal v-model:open="showVisitModal" title="新建就诊" @ok="createVisit" :confirm-loading="submittingVisit">
    <a-form layout="vertical" style="margin-top:8px">
      <a-form-item label="主诉">
        <a-textarea v-model:value="visitForm.chief_complaint" placeholder="请描述主要症状" :rows="3" />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- Analysis -->
  <a-modal v-model:open="showAnalysisModal" title="发起 AI 分析" @ok="launchAnalysis" ok-text="发起" width="540px">
    <a-form layout="vertical" style="margin-top:8px">
      <a-form-item label="皮肤镜图像">
        <input type="file" accept="image/*" :key="String(showAnalysisModal)" @change="onFileChange" style="width:100%" />
        <a-image v-if="imagePreviewUrl" :src="imagePreviewUrl" :width="120" style="margin-top:8px;border-radius:4px;display:block" />
      </a-form-item>
      <a-divider orientation="left" style="font-size:13px;color:#8c8c8c">临床信息</a-divider>
      <a-row :gutter="12">
        <a-col :span="12">
          <a-form-item label="年龄">
            <a-input-number v-model:value="clinicalForm.age" :min="0" :max="120" style="width:100%" placeholder="岁" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="性别">
            <a-select v-model:value="clinicalForm.gender" allow-clear placeholder="请选择">
              <a-select-option value="男">男</a-select-option>
              <a-select-option value="女">女</a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>
      <a-form-item label="病灶部位">
        <a-input v-model:value="clinicalForm.region" placeholder="如：左足底" />
      </a-form-item>
      <a-form-item label="症状">
        <a-space>
          <a-checkbox v-model:checked="clinicalForm.itch">瘙痒</a-checkbox>
          <a-checkbox v-model:checked="clinicalForm.grew">增大</a-checkbox>
        </a-space>
      </a-form-item>
      <a-divider orientation="left" style="font-size:13px;color:#8c8c8c">病理数据</a-divider>
      <a-row :gutter="12">
        <a-col :span="12">
          <a-form-item label="Breslow 厚度(mm)">
            <a-input-number v-model:value="labForm.breslow_thickness_mm" :min="0" :step="0.1" style="width:100%" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item label="BRAF 突变">
            <a-select v-model:value="labForm.braf_mutation" allow-clear placeholder="请选择">
              <a-select-option value="突变型">突变型</a-select-option>
              <a-select-option value="野生型">野生型</a-select-option>
              <a-select-option value="未知">未知</a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
      </a-row>
      <a-form-item>
        <a-checkbox v-model:checked="labForm.ulceration">存在溃疡</a-checkbox>
      </a-form-item>
      <a-divider orientation="left" style="font-size:13px;color:#8c8c8c">补充主诉（可选）</a-divider>
      <a-form-item>
        <a-textarea v-model:value="analysisForm.clinical_text" placeholder="若未填临床信息则作为 clinical_text 发送" :rows="2" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<style scoped>
.page { padding: 28px 32px; background: #f5f7fa; min-height: 100%; }

.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 18px;
}
.section-title {
  font-size: 20px; font-weight: 700; color: #1e293b;
  border-left: 3px solid #14B8A6; padding-left: 12px; line-height: 1.3;
}
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 5px; padding-left: 15px; }

.search-row { margin-bottom: 14px; }

.card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.03);
  padding: 20px 22px;
  margin-bottom: 14px;
}

/* Patient strip */
.strip-card { padding: 16px 20px; }
.strip-label { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }
.patient-strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }
.patient-strip::-webkit-scrollbar { height: 4px; }
.patient-strip::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 2px; }

.p-card {
  flex-shrink: 0;
  width: 130px;
  padding: 12px 12px 10px;
  border-radius: 10px;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  background: #f8fafc;
  text-align: center;
}
.p-card:hover { background: #f1f5f9; border-color: #e2e8f0; }
.p-card.active { background: #eff6ff; border-color: #2563EB; }

.pc-avatar {
  width: 34px; height: 34px; border-radius: 50%;
  background: #e2e8f0; color: #475569;
  font-size: 14px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 7px;
}
.p-card.active .pc-avatar { background: #dbeafe; color: #2563EB; }
.pc-name { font-size: 13px; font-weight: 600; color: #1e293b; }
.pc-sub { font-size: 11px; color: #94a3b8; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Empty work state */
.empty-work {
  display: flex; align-items: center; justify-content: center;
  padding: 60px 0;
}

/* Overview card */
.overview-card { padding: 18px 22px; }
.ov-header { display: flex; align-items: center; justify-content: space-between; }
.ov-main { display: flex; align-items: center; gap: 14px; }
.ov-avatar {
  width: 44px; height: 44px; border-radius: 50%;
  background: #eff6ff; color: #2563EB;
  font-size: 18px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.ov-name { font-size: 17px; font-weight: 700; color: #1e293b; margin-bottom: 5px; }
.ov-meta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 0; }
.ov-meta-item { font-size: 12px; color: #475569; }
.meta-label { color: #94a3b8; margin-right: 4px; }
.ov-sep { color: #cbd5e1; margin: 0 10px; font-size: 12px; }

/* Visits card */
.card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.card-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.card-sub { font-size: 11px; color: #94a3b8; }
</style>
