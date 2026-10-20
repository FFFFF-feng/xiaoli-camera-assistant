<script setup lang="ts">
import { computed } from 'vue';
import { fieldActionCard } from '../field-actions.mjs';
const props=defineProps<{card:NonNullable<ReturnType<typeof fieldActionCard>>}>();
const primary=computed(()=>props.card.actions.slice(0,3));
const remaining=computed(()=>props.card.actions.slice(3));
</script>
<template>
  <aside class="field-action-card" aria-labelledby="field-action-title">
    <h3 id="field-action-title">现场操作卡</h3>
    <dl>
      <div><dt>当前问题</dt><dd>{{ card.problem }}</dd></div>
      <div class="field-action-primary"><dt>推荐动作</dt><dd>
        <ol v-if="primary.length"><li v-for="action in primary" :key="action">{{ action }}</li></ol>
        <p v-else>本次未获得具体动作，先按原图核对主体与边缘。</p>
        <details v-if="remaining.length" class="more-actions"><summary>其余 {{ remaining.length }} 条动作</summary><ol start="4"><li v-for="action in remaining" :key="action">{{ action }}</li></ol></details>
      </dd></div>
      <div><dt>预期改善</dt><dd>{{ card.benefit }}</dd></div>
      <div><dt>拍完检查</dt><dd><template v-if="card.checks.length"><p v-for="check in card.checks" :key="check">{{ check }}</p></template><p v-else>检查主体关键部位、四边余量与背景干扰，再拍一张对照。</p></dd></div>
    </dl>
  </aside>
</template>
<style scoped>
.field-action-card { margin:20px 0 24px; padding:22px 24px; border:1px solid var(--border,#dedbd2); border-radius:14px; background:#f5f6ef; min-width:0; word-break:normal; overflow-wrap:break-word; }
.field-action-card h3 { margin:0 0 14px; font-size:18px; font-weight:700; color:var(--green,#3b604f); }
.field-action-card dl { margin:0; }
.field-action-card dl>div { display:grid; grid-template-columns:80px minmax(0,1fr); gap:18px; padding:15px 0; border-bottom:1px solid #e1e4d9; }
.field-action-card dl>div:last-child { border:0; padding-bottom:0; }
.field-action-card dt { font-size:13px; color:var(--muted,#786f62); padding-top:3px; }
.field-action-card dd { min-width:0; margin:0; font-size:14px; font-weight:400; line-height:1.9; color:var(--ink,#39332d); }
.field-action-card p { margin:0; }
.field-action-card p+p { margin-top:6px; }
.field-action-card ol { margin:0; padding-left:22px; }
.field-action-card li+li { margin-top:8px; }
.field-action-primary dd { font-weight:600; color:#365441; }
.more-actions { margin-top:10px; font-weight:400; }
.more-actions summary { cursor:pointer; width:fit-content; font-size:13px; padding:4px 0; }
.more-actions summary:focus-visible { outline:2px solid var(--green); outline-offset:3px; }
.more-actions ol { margin-top:8px; }
@media(max-width:540px) { .field-action-card { padding:18px 16px; } .field-action-card dl>div { grid-template-columns:64px minmax(0,1fr); gap:12px; } }
@media(max-width:360px) { .field-action-card dl>div { grid-template-columns:minmax(0,1fr); gap:5px; } }
</style>
