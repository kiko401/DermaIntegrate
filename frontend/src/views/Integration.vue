<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFetch } from '@/utils/api'

const sources = ref([])
const loading = ref(false)

const selectedPatientId = ref(null)
const selectedPatientName = ref('')
const clinicalView = ref(null)
const cvLoading = ref(false)

const systemColors = { HIS: '#10B981', LIS: '#F59E0B', PACS: '#2563EB' }

async function fetchSources() {
  loading.value = true
  try {
    const res = await apiFetch('/api/empi/sources')
    if (res.ok) sources.value = await res.json()
  } catch {
    sources.value = []
  } finally {
    loading.value = false
  }
}

async function fetchClinicalView(patientId, patientName) {
  if (selectedPatientId.value === patientId) {
    selectedPatientId.value = null
    clinicalView.value = null
    return
  }
  selectedPatientId.value = patientId
  selectedPatientName.value = patientName || patientId
  cvLoading.value = true
  clinicalView.value = null
  try {
    const res = await apiFetch(`/api/patients/${patientId}/clinical-view`)
    if (res.ok) clinicalView.value = await res.json()
  } catch {
    clinicalView.value = null
  } finally {
    cvLoading.value = false
  }
}

onMounted(fetchSources)

const totalMatched = computed(() => sources.value.filter(r => r.patient_id).length)

const columns = [
  { title: '来源系统', dataIndex: 'source_system', key: 'sys', width: 100 },
  { title: '外部 ID', dataIndex: 'source_id', key: 'sid' },
  { title: '姓名', dataIndex: 'name', key: 'name', width: 80 },
  { title: '身份证', dataIndex: 'id_card', key: 'id_card',
    customRender: ({ text }) => text || '-' },
  { title: '手机', dataIndex: 'phone', key: 'phone',
    customRender: ({ text }) => text || '-' },
  { title: '内部患者', key: 'internal', width: 160 },
]

function tagColor(sys) {
  return sys === 'HIS' ? 'green' : sys === 'LIS' ? 'gold' : 'blue'
}

function formatDate(str) {
  if (!str) return '-'
  return str.slice(0, 10)
}
</script>

<template>
  <div style="padding: 28px 32px; background: #f5f7fa; min-height: 100%">

    <div style="margin-bottom: 20px">
      <div style="font-size:20px;font-weight:700;color:#1e293b;border-left:3px solid #14B8A6;padding-left:12px">
        数据集成
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-top:5px;padding-left:15px">
        EMPI 主索引映射 · 多源患者身份归一
      </div>
    </div>

    <!-- 汇总行 -->
    <div style="background:#fff;border-radius:12px;padding:16px 22px;margin-bottom:14px;display:flex;align-items:center;gap:24px;box-shadow:0 1px 4px rgba(0,0,0,0.07)">
      <div v-for="sys in ['HIS','LIS','PACS']" :key="sys" style="display:flex;align-items:center;gap:8px">
        <span :style="`width:8px;height:8px;border-radius:50%;background:${systemColors[sys]};display:inline-block`"></span>
        <a-tag :color="tagColor(sys)" style="margin:0">{{ sys }}</a-tag>
        <span style="font-size:13px;color:#475569">{{ sources.filter(r => r.source_system === sys).length }} 条</span>
      </div>
      <div style="margin-left:auto;font-size:13px;color:#059669;font-weight:600">
        已归一 {{ totalMatched }} / {{ sources.length }} 条
      </div>
    </div>

    <!-- 明细表 -->
    <div style="background:#fff;border-radius:12px;padding:20px 22px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.07)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <span style="font-size:14px;font-weight:600;color:#1e293b">外部数据源明细</span>
        <a-button size="small" :loading="loading" @click="fetchSources">刷新</a-button>
      </div>
      <a-table
        :columns="columns"
        :data-source="sources"
        :loading="loading"
        row-key="id"
        :pagination="false"
        size="small"
        :row-class-name="record => record.patient_id && record.patient_id === selectedPatientId ? 'ant-table-row-selected' : ''"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'sys'">
            <a-tag :color="tagColor(record.source_system)" style="margin:0">
              {{ record.source_system }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'internal'">
            <span v-if="record.patient_id" style="display:flex;align-items:center;gap:8px">
              <span style="color:#059669;font-weight:500">✓ {{ record.internal_name }}</span>
              <a-button
                size="small"
                type="link"
                style="padding:0;height:auto;font-size:12px"
                @click="fetchClinicalView(record.patient_id, record.internal_name)"
              >
                {{ selectedPatientId === record.patient_id ? '收起' : '查看' }}
              </a-button>
            </span>
            <span v-else style="color:#94a3b8;font-size:12px">未归一</span>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 临床视图面板 -->
    <div v-if="selectedPatientId" style="background:#fff;border-radius:12px;padding:20px 22px;box-shadow:0 1px 4px rgba(0,0,0,0.07)">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <span style="font-size:14px;font-weight:600;color:#1e293b">统一临床视图</span>
        <span style="font-size:13px;color:#475569">{{ selectedPatientName }}</span>
        <a-spin v-if="cvLoading" size="small" />
      </div>

      <template v-if="clinicalView && !cvLoading">
        <!-- 患者基本信息 -->
        <div style="background:#f8fafc;border-radius:8px;padding:12px 16px;margin-bottom:12px;font-size:13px;color:#475569;display:flex;gap:24px;flex-wrap:wrap">
          <span><b>姓名：</b>{{ clinicalView.patient?.name || '-' }}</span>
          <span><b>性别：</b>{{ clinicalView.patient?.gender || '-' }}</span>
          <span><b>出生日期：</b>{{ formatDate(clinicalView.patient?.dob) }}</span>
          <span><b>ID：</b>{{ clinicalView.patient?.id }}</span>
          <span><b>EMPI 来源数：</b>{{ clinicalView.empi_sources?.length || 0 }}</span>
        </div>

        <!-- HIS 就诊记录 -->
        <div style="margin-bottom:12px">
          <div style="font-size:13px;font-weight:600;color:#10B981;margin-bottom:8px">
            HIS 就诊记录（{{ clinicalView.his?.length || 0 }} 条）
          </div>
          <div v-if="!clinicalView.his?.length" style="font-size:12px;color:#94a3b8">无数据</div>
          <div
            v-for="r in clinicalView.his"
            :key="r.id"
            style="background:#f0fdf4;border-radius:6px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#334155"
          >
            <span style="margin-right:16px"><b>日期：</b>{{ formatDate(r.visit_date) }}</span>
            <span style="margin-right:16px"><b>科室：</b>{{ r.department || '-' }}</span>
            <span style="margin-right:16px"><b>主诉：</b>{{ r.chief_complaint || '-' }}</span>
            <span><b>诊断：</b>{{ r.diagnosis || '-' }}</span>
          </div>
        </div>

        <!-- LIS 检验结果 -->
        <div style="margin-bottom:12px">
          <div style="font-size:13px;font-weight:600;color:#F59E0B;margin-bottom:8px">
            LIS 检验结果（{{ clinicalView.lis?.length || 0 }} 条）
          </div>
          <div v-if="!clinicalView.lis?.length" style="font-size:12px;color:#94a3b8">无数据</div>
          <div
            v-for="r in clinicalView.lis"
            :key="r.id"
            style="background:#fffbeb;border-radius:6px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#334155"
          >
            <span style="margin-right:16px"><b>日期：</b>{{ formatDate(r.test_date) }}</span>
            <span style="margin-right:16px"><b>项目：</b>{{ r.test_name || '-' }}</span>
            <span style="margin-right:16px"><b>结果：</b>{{ r.result_value }} {{ r.result_unit }}</span>
            <span><b>参考范围：</b>{{ r.reference_range || '-' }}</span>
          </div>
        </div>

        <!-- PACS 影像记录 -->
        <div style="margin-bottom:12px">
          <div style="font-size:13px;font-weight:600;color:#2563EB;margin-bottom:8px">
            PACS 影像记录（{{ clinicalView.pacs?.length || 0 }} 条）
          </div>
          <div v-if="!clinicalView.pacs?.length" style="font-size:12px;color:#94a3b8">无数据</div>
          <div
            v-for="r in clinicalView.pacs"
            :key="r.id"
            style="background:#eff6ff;border-radius:6px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#334155;display:flex;align-items:flex-start;gap:16px"
          >
            <div style="flex:1">
              <span style="margin-right:16px"><b>日期：</b>{{ formatDate(r.exam_date) }}</span>
              <span style="margin-right:16px"><b>类型：</b>{{ r.modality || '-' }}</span>
              <span style="margin-right:16px"><b>部位：</b>{{ r.body_part || '-' }}</span>
              <span><b>描述：</b>{{ r.description || '-' }}</span>
              <div style="margin-top:4px;color:#64748b">
                <span style="margin-right:12px"><b>image_url：</b>{{ r.image_url || '-' }}</span>
                <span><b>thumbnail_url：</b>{{ r.thumbnail_url || '-' }}</span>
              </div>
            </div>
            <img
              v-if="r.thumbnail_url"
              :src="r.thumbnail_url"
              style="width:64px;height:64px;object-fit:cover;border-radius:4px;border:1px solid #bfdbfe;flex-shrink:0"
              :alt="r.description || 'thumbnail'"
            />
          </div>
        </div>

        <!-- AI 任务 -->
        <div>
          <div style="font-size:13px;font-weight:600;color:#7C3AED;margin-bottom:8px">
            AI 任务（{{ clinicalView.ai_tasks?.length || 0 }} 条）
          </div>
          <div v-if="!clinicalView.ai_tasks?.length" style="font-size:12px;color:#94a3b8">无数据</div>
          <div
            v-for="r in clinicalView.ai_tasks"
            :key="r.id"
            style="background:#faf5ff;border-radius:6px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:#334155"
          >
            <span style="margin-right:16px"><b>任务 ID：</b>{{ r.id }}</span>
            <span style="margin-right:16px"><b>状态：</b>{{ r.status }}</span>
            <span><b>创建时间：</b>{{ formatDate(r.created_at) }}</span>
          </div>
        </div>
      </template>
    </div>

  </div>
</template>
