<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFetch } from '@/utils/api'

const sources = ref([])
const loading = ref(false)

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
  { title: '内部患者', key: 'internal', width: 130 },
]

function tagColor(sys) {
  return sys === 'HIS' ? 'green' : sys === 'LIS' ? 'gold' : 'blue'
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
    <div style="background:#fff;border-radius:12px;padding:20px 22px;box-shadow:0 1px 4px rgba(0,0,0,0.07)">
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
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'sys'">
            <a-tag :color="tagColor(record.source_system)" style="margin:0">
              {{ record.source_system }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'internal'">
            <span v-if="record.patient_id" style="color:#059669;font-weight:500">
              ✓ {{ record.internal_name }}
            </span>
            <span v-else style="color:#94a3b8;font-size:12px">未归一</span>
          </template>
        </template>
      </a-table>
    </div>

  </div>
</template>
