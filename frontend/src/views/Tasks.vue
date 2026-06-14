<template>
  <div style="padding:28px">
    <div style="font-size:20px;font-weight:600;color:#1e293b;margin-bottom:6px">AI 分析记录</div>
    <div style="font-size:13px;color:#64748b;margin-bottom:40px">全部 AI 诊断任务汇总</div>

    <div style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.07)">
      <a-table :columns="columns" :data-source="tasks" :pagination="false" row-key="taskId" />
    </div>
  </div>
</template>

<script setup>
const columns = [
  { title: 'Task ID', dataIndex: 'taskId', key: 'taskId', ellipsis: true },
  { title: '患者', dataIndex: 'patient', key: 'patient' },
  { title: '主诉', dataIndex: 'complaint', key: 'complaint' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '创建时间', dataIndex: 'createdAt', key: 'createdAt' },
]

const tasks = [
  { taskId: 'task-abc123', patient: '张三', complaint: '面部红斑', status: '完成', createdAt: '2026-06-14 01:30' },
  { taskId: 'task-def456', patient: '王五', complaint: '色素沉着', status: '分析中', createdAt: '2026-06-13 22:10' },
  { taskId: 'task-ghi789', patient: '李四', complaint: '荨麻疹', status: '失败', createdAt: '2026-06-13 20:05' },
]
</script>
