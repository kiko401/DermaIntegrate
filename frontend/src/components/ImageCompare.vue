<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  leftUrl: { type: String, default: null },
  rightUrl: { type: String, default: null },
  leftLabel: { type: String, default: '原图' },
  rightLabel: { type: String, default: '热力图' },
  forceMode: { type: String, default: null },
  disableCompare: { type: Boolean, default: false },
  disableOverlay: { type: Boolean, default: false },
  hintText: { type: String, default: 'AI 热区辅助展示' },
})

const position = ref(50)
const dragging = ref(false)
const containerRef = ref(null)
const viewMode = ref('compare') // compare | overlay | original

const hasLeft = computed(() => !!props.leftUrl)
const hasRight = computed(() => !!props.rightUrl)

function startDrag(e) {
  if (viewMode.value !== 'compare') return
  dragging.value = true
  e.preventDefault()
}

function onMove(e) {
  if (!dragging.value || !containerRef.value || viewMode.value !== 'compare') return
  const rect = containerRef.value.getBoundingClientRect()
  const clientX = e.touches ? e.touches[0].clientX : e.clientX
  const pct = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100))
  position.value = pct
}

function stopDrag() {
  dragging.value = false
}

function setMode(mode) {
  if (mode === 'compare' && props.disableCompare) return
  if (mode === 'overlay' && (props.disableOverlay || !hasRight.value)) return
  viewMode.value = mode
}

watch(
    () => props.forceMode,
    (mode) => {
      if (mode && ['compare', 'overlay', 'original'].includes(mode)) {
        viewMode.value = mode
      }
    },
    { immediate: true }
)
</script>

<template>
  <div class="compare-shell">
    <div class="compare-toolbar">
      <div class="compare-modes">
        <button
            class="mode-btn"
            :class="{ active: viewMode === 'compare' }"
            :disabled="props.disableCompare"
            @click="setMode('compare')"
        >
          对比模式
        </button>
        <button
            class="mode-btn"
            :class="{ active: viewMode === 'overlay' }"
            :disabled="props.disableOverlay || !hasRight"
            @click="setMode('overlay')"
        >
          叠加模式
        </button>
        <button
            class="mode-btn"
            :class="{ active: viewMode === 'original' }"
            @click="setMode('original')"
        >
          仅原图
        </button>
      </div>

      <div class="compare-hint">
        <span class="hint-dot"></span>
        {{ props.hintText }}
      </div>
    </div>

    <div
        ref="containerRef"
        class="compare-stage"
        @mousemove="onMove"
        @mouseup="stopDrag"
        @mouseleave="stopDrag"
        @touchmove.prevent="onMove"
        @touchend="stopDrag"
    >
      <div class="compare-canvas">
        <template v-if="viewMode === 'original'">
          <img v-if="leftUrl" :src="leftUrl" class="compare-img" draggable="false" />
          <div v-else class="compare-placeholder">
            <span class="placeholder-icon">🖼</span>
            <span>{{ leftLabel }}未加载</span>
          </div>
        </template>

        <template v-else-if="viewMode === 'overlay'">
          <img v-if="leftUrl" :src="leftUrl" class="compare-img" draggable="false" />
          <div v-else class="compare-placeholder">
            <span class="placeholder-icon">🖼</span>
            <span>{{ leftLabel }}未加载</span>
          </div>

          <img
              v-if="rightUrl"
              :src="rightUrl"
              class="compare-img overlay-img"
              draggable="false"
          />
          <div v-else class="overlay-empty">
            暂无热力图
          </div>
        </template>

        <template v-else>
          <div class="layer-base">
            <img v-if="leftUrl" :src="leftUrl" class="compare-img" draggable="false" />
            <div v-else class="compare-placeholder">
              <span class="placeholder-icon">🖼</span>
              <span>{{ leftLabel }}未加载</span>
            </div>
          </div>

          <div class="right-layer" :style="`clip-path: inset(0 0 0 ${position}%);`">
            <img v-if="rightUrl" :src="rightUrl" class="compare-img" draggable="false" />
            <div v-else class="compare-placeholder">
              <span class="placeholder-icon">🌡</span>
              <span>{{ rightLabel }}未生成</span>
            </div>
          </div>

          <div
              class="divider"
              :style="`left: calc(${position}% - 1px);`"
              @mousedown="startDrag"
              @touchstart.prevent="startDrag"
          >
            <div class="handle">⟷</div>
          </div>
        </template>

        <span class="layer-label left-label">{{ leftLabel }}</span>
        <span v-if="viewMode !== 'original'" class="layer-label right-label">{{ rightLabel }}</span>
      </div>
    </div>

    <div class="compare-footer">
      <div class="legend">
        <span class="legend-pill legend-blue">原始影像</span>
        <span class="legend-pill legend-orange">AI 热区</span>
      </div>
      <div class="compare-note">
        仅作辅助参考，不替代临床判断
      </div>
    </div>
  </div>
</template>

<style scoped>
.compare-shell {
  border-radius: 18px;
  border: 1px solid rgba(116, 152, 193, 0.14);
  background: linear-gradient(180deg, #fafdff 0%, #f3fbfb 100%);
  box-shadow: 0 14px 30px rgba(95, 130, 171, 0.08);
  overflow: hidden;
}

.compare-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(116, 152, 193, 0.1);
  background: rgba(255, 255, 255, 0.72);
}

.compare-modes {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-btn {
  border: 1px solid rgba(116, 152, 193, 0.16);
  background: #ffffff;
  color: #5f7894;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}

.mode-btn:hover {
  border-color: rgba(47, 111, 237, 0.24);
  color: #2f6fed;
}

.mode-btn.active {
  background: linear-gradient(90deg, #eaf2ff 0%, #e8fbfb 100%);
  color: #2f6fed;
  border-color: rgba(47, 111, 237, 0.18);
}

.mode-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.compare-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #7b91a8;
  white-space: nowrap;
}

.hint-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(180deg, #f59e0b 0%, #fb7185 100%);
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);
}

.compare-stage {
  padding: 16px;
}

.compare-canvas {
  position: relative;
  min-height: 420px;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(116, 152, 193, 0.12);
  background:
      radial-gradient(circle at 16% 18%, rgba(47,111,237,0.08) 0%, transparent 28%),
      radial-gradient(circle at 85% 20%, rgba(25,198,208,0.1) 0%, transparent 24%),
      linear-gradient(180deg, #edf6ff 0%, #f5fcfc 100%);
}

.layer-base,
.right-layer {
  position: absolute;
  inset: 0;
}

.compare-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.overlay-img {
  opacity: 0.48;
  mix-blend-mode: multiply;
}

.overlay-empty {
  position: absolute;
  right: 16px;
  top: 16px;
  font-size: 12px;
  color: #8aa0b8;
  background: rgba(255,255,255,0.82);
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(116,152,193,0.12);
}

.compare-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  color: #8aa0b8;
  font-size: 13px;
  background:
      radial-gradient(circle at 20% 20%, rgba(47,111,237,0.06) 0%, transparent 28%),
      linear-gradient(180deg, #f6fbff 0%, #f2fbfb 100%);
}

.placeholder-icon {
  font-size: 24px;
}

.divider {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  background: rgba(255,255,255,0.9);
  box-shadow: 0 0 0 1px rgba(47,111,237,0.08), 0 0 12px rgba(47,111,237,0.16);
  cursor: ew-resize;
  z-index: 10;
}

.handle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: #ffffff;
  border: 1px solid rgba(116, 152, 193, 0.12);
  box-shadow: 0 8px 18px rgba(95,130,171,0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #4f6c88;
}

.layer-label {
  position: absolute;
  top: 14px;
  font-size: 11px;
  font-weight: 700;
  color: #35506f;
  background: rgba(255,255,255,0.84);
  border: 1px solid rgba(116,152,193,0.12);
  padding: 5px 10px;
  border-radius: 999px;
  backdrop-filter: blur(6px);
  z-index: 11;
}

.left-label {
  left: 14px;
}

.right-label {
  right: 14px;
}

.compare-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px 14px;
  border-top: 1px solid rgba(116, 152, 193, 0.08);
  background: rgba(255,255,255,0.68);
}

.legend {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.legend-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 999px;
}

.legend-blue {
  background: rgba(47,111,237,0.1);
  color: #2f6fed;
}

.legend-orange {
  background: rgba(245,158,11,0.14);
  color: #b45309;
}

.compare-note {
  font-size: 11px;
  color: #8aa0b8;
}

@media (max-width: 768px) {
  .compare-toolbar,
  .compare-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .compare-canvas {
    min-height: 300px;
  }
}
</style>
