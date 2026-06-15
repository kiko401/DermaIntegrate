<!-- 原图 / 热力图滑动对比组件
  Props:
    leftUrl  - 原图 URL，null 时显示占位
    rightUrl - 热力图/证据图 URL，null 时显示占位
    leftLabel  - 左侧标签文字
    rightLabel - 右侧标签文字
-->
<script setup>
import { ref } from 'vue'

const props = defineProps({
  leftUrl:    { type: String, default: null },
  rightUrl:   { type: String, default: null },
  leftLabel:  { type: String, default: '原图' },
  rightLabel: { type: String, default: '热力图' },
})

const position = ref(50)       // 0-100 百分比，表示分割线位置
const dragging = ref(false)
const containerRef = ref(null)

function startDrag(e) {
  dragging.value = true
  e.preventDefault()
}

function onMove(e) {
  if (!dragging.value || !containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  const clientX = e.touches ? e.touches[0].clientX : e.clientX
  const pct = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100))
  position.value = pct
}

function stopDrag() {
  dragging.value = false
}
</script>

<style scoped>
.compare-wrap {
  position: relative;
  width: 100%;
  user-select: none;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.compare-img {
  display: block;
  width: 100%;
  max-height: 300px;
  object-fit: contain;
  background: #1e293b;
}

.compare-placeholder {
  width: 100%;
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 6px;
  background: #f1f5f9;
  color: #94a3b8;
  font-size: 13px;
}

.right-layer {
  position: absolute;
  top: 0; left: 0;
  width: 100%;
  height: 100%;
}

.divider {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  background: #fff;
  box-shadow: 0 0 4px rgba(0,0,0,0.4);
  cursor: ew-resize;
  z-index: 10;
}

.handle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 6px rgba(0,0,0,0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #475569;
  cursor: ew-resize;
}

.layer-label {
  position: absolute;
  bottom: 8px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(0,0,0,0.45);
  color: #fff;
  padding: 2px 8px;
  border-radius: 4px;
}
.left-label  { left: 8px; }
.right-label { right: 8px; }
</style>

<template>
  <div
    ref="containerRef"
    class="compare-wrap"
    @mousemove="onMove"
    @mouseup="stopDrag"
    @mouseleave="stopDrag"
    @touchmove.prevent="onMove"
    @touchend="stopDrag"
  >
    <!-- Left layer (原图) -->
    <div style="position:relative;display:block">
      <img v-if="leftUrl" :src="leftUrl" class="compare-img" draggable="false" />
      <div v-else class="compare-placeholder">
        <span style="font-size:22px">🖼</span>
        <span>{{ leftLabel }}未存储</span>
      </div>
      <span class="layer-label left-label">{{ leftLabel }}</span>
    </div>

    <!-- Right layer (热力图) — clipped via CSS clip-path via left offset -->
    <div
      class="right-layer"
      :style="`width:100%;clip-path:inset(0 0 0 ${position}%)`"
    >
      <img v-if="rightUrl" :src="rightUrl" class="compare-img" draggable="false" />
      <div v-else class="compare-placeholder">
        <span style="font-size:22px;opacity:0.4">🔥</span>
        <span>{{ rightLabel }}未生成</span>
      </div>
      <span class="layer-label right-label">{{ rightLabel }}</span>
    </div>

    <!-- Divider -->
    <div
      class="divider"
      :style="`left:calc(${position}% - 1px)`"
      @mousedown="startDrag"
      @touchstart.prevent="startDrag"
    >
      <div class="handle">⇔</div>
    </div>
  </div>
</template>
