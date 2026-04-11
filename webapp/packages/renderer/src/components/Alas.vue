<template>
  <iframe class="alas" :src="url"></iframe>
</template>

<script lang="ts">
  import {defineComponent} from 'vue';

  // 不能在渲染进程中导入 main 进程的 Node.js 模块（含 require）
  // 从 Vite 注入的环境变量中读取，或者 fallback 到默认端口
  const WEBUI_URL = (import.meta.env.VITE_WEBUI_URL as string | undefined)
    ?? `http://127.0.0.1:22267`;

  export default defineComponent({
    name: 'Alas',
    computed: {
      url: function () {
        return WEBUI_URL;
      },
    },
  });
</script>

<style scoped>
  .alas {
    border-width: 0;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
  }
</style>
