<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">AI <span>决策中心</span></div>
      <nav class="nav">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/ontology">本体管理</RouterLink>
        <RouterLink to="/decision/new">创建决策</RouterLink>
      </nav>
    </header>
    <RouterView />
  </div>
</template>

<script setup>
</script>
