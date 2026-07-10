<template>
  <router-view />
</template>

<script setup>
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  min-height: 100%;
}

#app {
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--ink);
  background-color: var(--bg);
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--bg-muted);
}

::-webkit-scrollbar-thumb {
  background: var(--ink);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--ink-secondary);
}

button,
input,
select,
textarea {
  font-family: inherit;
}

.mono {
  font-family: var(--font-mono);
}
</style>
