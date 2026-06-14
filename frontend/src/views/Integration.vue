<template>
  <div style="padding:28px">
    <div style="font-size:20px;font-weight:600;color:#1e293b;margin-bottom:6px">数据集成</div>
    <div style="font-size:13px;color:#64748b;margin-bottom:40px">
      EMPI 主索引映射 + FHIR R4 适配器（Phase 3/4，建设中）
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px">
      <div v-for="src in sources" :key="src.name" style="background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.07)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <span :style="`width:8px;height:8px;border-radius:50%;background:${src.color};display:inline-block`"></span>
          <span style="font-size:14px;font-weight:600;color:#1e293b">{{ src.name }}</span>
        </div>
        <div style="font-size:13px;color:#64748b">{{ src.desc }}</div>
        <a-tag :color="src.status === '连通' ? 'green' : src.status === '正常' ? 'blue' : 'default'" style="margin-top:12px">
          {{ src.status }}
        </a-tag>
      </div>
    </div>

    <a-result
      title="多源数据集成功能开发中"
      sub-title="Phase 3（EMPI 主索引映射）和 Phase 4（FHIR R4 适配器）完成后，此页将展示患者跨系统身份归一和异构数据摘要。"
    />
  </div>
</template>

<script setup>
const sources = [
  { name: 'HIS 内部数据库', desc: 'MySQL 3306，患者 / 就诊 / 任务', color: '#10B981', status: '连通' },
  { name: 'AI 推理服务', desc: 'FastAPI，多模态诊断推理', color: '#2563EB', status: '正常' },
  { name: 'FHIR Mock Server', desc: 'Patient / Observation / Report', color: '#cbd5e1', status: '未启用' },
]
</script>
