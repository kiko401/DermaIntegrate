<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import DiagnosisDialog from '@/components/DiagnosisDialog.vue'
import { apiFetch } from '@/utils/api'

const route = useRoute()
const router = useRouter()
const patientId = route.params.id

const patient = ref(null)
const visits = ref([])
const loadingVisits = ref(false)
const showVisitModal = ref(false)
const submittingVisit = ref(false)
const visitForm = ref({ chief_complaint: '' })

const visitTaskMap = ref({})   // visitId → taskId，session 内持久
const uploading = ref(false)
const selectedVisitId = ref(null)
const showAnalysisModal = ref(false)
const analysisForm = ref({ clinical_text: '' })
const pendingVisitId = ref(null)
const imageFile = ref(null)
const imagePreviewUrl = ref(null)

function onFileChange(e) {
  const file = e.target.files[0] || null
  imageFile.value = file
  imagePreviewUrl.value = file ? URL.createObjectURL(file) : null
}
const clinicalForm = ref({ age: null, gender: '', region: '', itch: false, grew: false })
const labForm = ref({ breslow_thickness_mm: null, ulceration: false, braf_mutation: '' })

// Phase 6: diagnosis dialog
const diagnosisVisible = ref(false)
const diagnosisTaskId = ref(null)

function openAnalysis(visitId) {
  pendingVisitId.value = visitId
  analysisForm.value = { clinical_text: '' }
  imageFile.value = null
  imagePreviewUrl.value = null
  clinicalForm.value = { age: null, gender: '', region: '', itch: false, grew: false }
  labForm.value = { breslow_thickness_mm: null, ulceration: false, braf_mutation: '' }
  showAnalysisModal.value = true
}

async function launchAnalysis() {
  const visitId = pendingVisitId.value
  selectedVisitId.value = visitId
  uploading.value = true
  showAnalysisModal.value = false
  try {
    const formData = new FormData()
    formData.append('visit_id', visitId)
    if (imageFile.value) {
      formData.append('file', imageFile.value)
    }
    // clinical_json 优先；若无结构化数据则回退到 clinical_text
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
    // lab_json
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
      diagnosisTaskId.value = data.task_id
      diagnosisVisible.value = true
      message.success('AI 分析已发起')
    } else {
      message.error(data.error || '发起失败')
    }
  } catch {
    message.error('请求失败')
  } finally {
    uploading.value = false
  }
}

const visitColumns = [
  { title: '就诊日期', dataIndex: 'visit_date', key: 'visit_date',
    customRender: ({ text }) => text ? text.slice(0, 10) : '-' },
  { title: '主诉', dataIndex: 'chief_complaint', key: 'chief_complaint' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at',
    customRender: ({ text }) => text ? text.replace('T', ' ').slice(0, 16) : '-' },
  { title: '操作', key: 'action' },
]

async function fetchPatient() {
  try {
    const res = await apiFetch(`/api/patients/${patientId}`)
    if (!res.ok) { router.push('/'); return }
    patient.value = await res.json()
  } catch {
    message.error('加载患者信息失败')
  }
}

async function fetchVisits() {
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
    const res = await apiFetch(`/api/patients/${patientId}/visits`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(visitForm.value),
    })
    if (!res.ok) throw new Error()
    message.success('就诊记录创建成功')
    showVisitModal.value = false
    visitForm.value = { chief_complaint: '' }
    await fetchVisits()
  } catch {
    message.error('创建失败')
  } finally {
    submittingVisit.value = false
  }
}


onMounted(async () => {
  await fetchPatient()
  await fetchVisits()
})
</script>

<template>
  <div style="padding: 24px">
    <a-button @click="router.push('/')" style="margin-bottom:16px">← 返回列表</a-button>

    <a-card v-if="patient" style="margin-bottom:16px">
      <a-descriptions title="患者信息" :column="3">
        <a-descriptions-item label="姓名">{{ patient.name }}</a-descriptions-item>
        <a-descriptions-item label="手机">{{ patient.phone || '-' }}</a-descriptions-item>
        <a-descriptions-item label="身份证">{{ patient.id_card || '-' }}</a-descriptions-item>
      </a-descriptions>
    </a-card>

    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
      <h3 style="margin:0">就诊记录</h3>
      <a-button type="primary" @click="showVisitModal = true">新建就诊</a-button>
    </div>

    <a-table
      :columns="visitColumns"
      :data-source="visits"
      :loading="loadingVisits"
      row-key="id"
      :pagination="false"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'action'">
          <a-space>
            <a-tag v-if="visitTaskMap[record.id]" color="success" style="margin-right:0">已分析</a-tag>
            <a-button
              type="link"
              :loading="uploading && selectedVisitId === record.id"
              @click="openAnalysis(record.id)"
            >
              {{ visitTaskMap[record.id] ? '重新分析' : '发起 AI 分析' }}
            </a-button>
          </a-space>
        </template>
      </template>
    </a-table>

    <DiagnosisDialog
      v-model:open="diagnosisVisible"
      :task-id="diagnosisTaskId"
    />

    <a-modal v-model:open="showAnalysisModal" title="发起 AI 分析" @ok="launchAnalysis" ok-text="发起" width="540px">
      <a-form layout="vertical" style="margin-top:8px">

        <a-form-item label="皮肤镜图像">
          <input type="file" accept="image/*" :key="String(showAnalysisModal)" @change="onFileChange" style="width:100%" />
          <a-image v-if="imagePreviewUrl" :src="imagePreviewUrl" :width="120" style="margin-top:8px; border-radius:4px; display:block" />
        </a-form-item>

        <a-divider orientation="left" style="font-size:13px; color:#8c8c8c">临床信息</a-divider>
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

        <a-divider orientation="left" style="font-size:13px; color:#8c8c8c">病理数据</a-divider>
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

        <a-divider orientation="left" style="font-size:13px; color:#8c8c8c">补充主诉（可选）</a-divider>
        <a-form-item>
          <a-textarea v-model:value="analysisForm.clinical_text" placeholder="填写后，若未填临床信息则作为 clinical_text 发送" :rows="2" />
        </a-form-item>

      </a-form>
    </a-modal>

    <a-modal v-model:open="showVisitModal" title="新建就诊" @ok="createVisit" :confirm-loading="submittingVisit">
      <a-form layout="vertical" style="margin-top:8px">
        <a-form-item label="主诉">
          <a-textarea v-model:value="visitForm.chief_complaint" placeholder="请描述主要症状" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
