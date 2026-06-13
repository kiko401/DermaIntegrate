<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { apiFetch } from '@/utils/api'

const router = useRouter()
const patients = ref([])
const loading = ref(false)
const showModal = ref(false)
const submitting = ref(false)
const form = ref({ name: '', id_card: '', phone: '' })

const columns = [
  { title: '姓名', dataIndex: 'name', key: 'name' },
  { title: '身份证号', dataIndex: 'id_card', key: 'id_card' },
  { title: '手机', dataIndex: 'phone', key: 'phone' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at',
    customRender: ({ text }) => text ? text.replace('T', ' ').slice(0, 16) : '-' },
  { title: '操作', key: 'action' },
]

async function fetchPatients() {
  loading.value = true
  try {
    const res = await apiFetch('/api/patients')
    patients.value = await res.json()
  } catch {
    message.error('加载患者列表失败')
  } finally {
    loading.value = false
  }
}

async function createPatient() {
  if (!form.value.name.trim()) {
    message.warning('姓名不能为空')
    return
  }
  submitting.value = true
  try {
    const res = await apiFetch('/api/patients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) throw new Error()
    message.success('患者创建成功')
    showModal.value = false
    form.value = { name: '', id_card: '', phone: '' }
    await fetchPatients()
  } catch {
    message.error('创建失败')
  } finally {
    submitting.value = false
  }
}

onMounted(fetchPatients)
</script>

<template>
  <div style="padding: 24px">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
      <h2 style="margin:0">患者列表<span v-if="patients.length" style="font-size:14px; font-weight:400; color:#8c8c8c; margin-left:8px">共 {{ patients.length }} 位</span></h2>
      <a-button type="primary" @click="showModal = true">新建患者</a-button>
    </div>

    <a-table
      :columns="columns"
      :data-source="patients"
      :loading="loading"
      row-key="id"
      :pagination="{ pageSize: 10 }"
      :locale="{ emptyText: '暂无患者记录，请点击右上角「新建患者」' }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'action'">
          <a-button type="link" @click="router.push(`/patients/${record.id}`)">查看就诊</a-button>
        </template>
      </template>
    </a-table>

    <a-modal v-model:open="showModal" title="新建患者" @ok="createPatient" :confirm-loading="submitting">
      <a-form layout="vertical" style="margin-top:8px">
        <a-form-item label="姓名" required>
          <a-input v-model:value="form.name" placeholder="请输入姓名" />
        </a-form-item>
        <a-form-item label="身份证号">
          <a-input v-model:value="form.id_card" placeholder="可选" />
        </a-form-item>
        <a-form-item label="手机号">
          <a-input v-model:value="form.phone" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
