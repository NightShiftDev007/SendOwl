<template>
  <header class="app-header" :class="{ bordered: !flush }">
    <div class="header-left">
      <RouterLink class="brand" to="/" aria-label="SandOwl home">
        <span class="mark" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <rect x="1" y="14" width="20" height="6" rx="1" stroke="currentColor" stroke-width="1.5"/>
            <rect x="4" y="10" width="14" height="4" rx="0.5" stroke="currentColor" stroke-width="1.5"/>
            <rect x="7" y="6" width="8" height="4" rx="0.5" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="11" cy="5" r="2.2" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="10.2" cy="4.8" r="0.5" fill="currentColor"/>
            <circle cx="11.8" cy="4.8" r="0.5" fill="currentColor"/>
          </svg>
        </span>
        <span class="wordmark">
          <span class="name">SandOwl</span>
          <span v-if="showSubtitle" class="sub">{{ subtitle }}</span>
        </span>
      </RouterLink>
      <slot name="left" />
    </div>

    <div v-if="$slots.center" class="header-center">
      <slot name="center" />
    </div>

    <div class="header-right">
      <slot name="right" />
      <LanguageSwitcher v-if="showLang" />
    </div>
  </header>
</template>

<script setup>
import LanguageSwitcher from './LanguageSwitcher.vue'

defineProps({
  showSubtitle: { type: Boolean, default: false },
  subtitle: { type: String, default: 'AI Decision Center' },
  showLang: { type: Boolean, default: true },
  flush: { type: Boolean, default: false },
})
</script>

<style scoped>
.app-header {
  height: var(--header-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  background: var(--bg);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.app-header.bordered {
  border-bottom: 1px solid var(--border-strong);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-width: 0;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--ink-secondary);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--ink);
  min-width: 0;
}

.brand:hover .name {
  color: var(--brand);
}

.mark {
  display: inline-flex;
  color: var(--ink);
  flex-shrink: 0;
}

.wordmark {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
  min-width: 0;
}

.name {
  font-family: var(--font-mono);
  font-weight: 800;
  font-size: 1rem;
  letter-spacing: 0.04em;
  transition: color 0.15s ease-out;
}

.sub {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
  white-space: nowrap;
}
</style>
