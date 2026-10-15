<script setup lang="ts">
import { computed } from 'vue';
const props = withDefaults(defineProps<{ kind: string; label?: string; appearance?: string; facing?: string; aspectRatio?: number }>(), { label: '', appearance: 'default', facing: 'front', aspectRatio: 1 });
const shape = computed(() => props.appearance !== 'default' ? props.appearance : /相机/.test(props.label) ? 'camera' : /小熊猫/.test(props.label) ? 'red_panda' : 'default');
</script>

<template>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round" class="sketch-glyph">
    <g v-if="shape === 'camera'"><path d="M12 31H30L38 20H65L73 31H89V81H12ZM21 42H29M75 42H81M18 82Q20 99 39 97M14 33Q3 20 7 7M87 33Q98 19 94 7"/><circle cx="52" cy="55" r="19"/><circle cx="52" cy="55" r="12"/></g>
    <g v-else-if="shape === 'bird'"><path d="M15 63Q13 35 40 32Q52 8 68 23L84 28L70 36Q75 64 51 74L30 83L35 69M28 47Q43 51 52 64M45 74L43 91M58 72L60 90M36 93H49M54 92H68"/><circle cx="61" cy="25" r="1.8"/></g>
    <g v-else-if="shape === 'dog'"><path d="M27 34L12 22Q5 54 24 57M72 34L88 22Q98 53 76 57M26 35Q31 15 51 18Q70 17 75 37L72 60Q65 73 50 73Q32 73 26 59ZM33 72L28 94H72L68 72M28 80Q6 81 10 60"/><circle cx="39" cy="44" r="2"/><circle cx="62" cy="44" r="2"/><path d="M46 54L55 54L50 59ZM50 60V65"/></g>
    <g v-else-if="shape === 'red_panda'"><path d="M26 32L21 11L40 23Q52 17 63 24L80 12L76 35Q85 56 69 67L74 91H29L32 68Q15 60 26 32ZM29 77Q2 66 7 94Q8 99 34 94M11 80L27 85M8 89L28 94M36 70L35 91M64 70L65 91"/><path d="M29 39Q39 30 45 43L37 54ZM72 39Q61 31 56 44L64 55Z" fill="currentColor" fill-opacity=".12"/><circle cx="38" cy="42" r="2"/><circle cx="63" cy="42" r="2"/><path d="M46 53L54 53L50 58ZM50 59Q43 64 39 59M50 59Q57 64 61 59"/></g>
    <g v-else-if="shape === 'pine'"><path d="M50 5L24 36H36L13 62H32L7 85H93L68 62H87L64 36H76ZM46 85V97M55 85V97"/></g>
    <g v-else-if="shape === 'cup'"><path d="M19 39H72L67 82Q48 93 25 82ZM73 44Q97 43 87 64Q81 72 71 66M12 94H83M34 25Q27 17 35 7M51 25Q44 17 52 7"/></g>
    <g v-else-if="shape === 'bottle'"><path d="M39 6H61V28Q61 36 75 45V92Q49 99 25 92V45Q39 36 39 28ZM37 6V1H63V6M26 61H74M26 82H74"/></g>
    <g v-else-if="shape === 'book'"><path d="M5 17Q27 10 49 24Q70 9 94 17V84Q71 76 49 91Q27 77 5 84ZM49 24V91M15 30L36 37M15 44L36 51M61 37L83 29M61 51L83 43"/></g>
    <g v-else-if="shape === 'seated'"><ellipse cx="48" cy="17" rx="13" :ry="Math.min(13,13*aspectRatio)"/><path d="M48 29L45 58L75 61L71 91M45 58L20 73L34 94M47 36L65 48L78 43M44 37L27 57M15 63H84M22 63V94M81 63V94"/></g>
    <g v-else-if="shape === 'walking'"><ellipse cx="54" cy="16" rx="13" :ry="Math.min(13,13*aspectRatio)"/><path d="M52 29L43 60L64 75L74 94M43 60L29 91L14 94M48 37L26 45L14 35M48 37L67 49L83 43"/></g>
    <g v-else-if="kind === 'person'"><ellipse cx="50" cy="12" rx="17" :ry="Math.min(12,17*aspectRatio)"/><path :d="`M45 ${12+Math.min(12,17*aspectRatio)}V26M55 ${12+Math.min(12,17*aspectRatio)}V26`"/><path d="M40 27Q50 25 60 27L76 44L68 49L61 39L60 61L66 92L55 94L48 67L44 94L33 92L40 60L38 39L29 51L21 47ZM40 60Q50 64 60 61M33 93L28 97H44M55 94L56 98H73" fill="currentColor" fill-opacity=".045"/></g>
    <g v-else-if="kind === 'tree'"><path d="M44 93L46 57M57 93L54 56M47 70L34 55M54 73L70 54M24 44C10 36 18 17 33 19C35 3 58 2 64 17C81 8 94 29 82 41C95 56 73 68 60 59C48 71 31 63 28 55C13 60 9 45 24 44ZM34 95Q52 91 69 96" /></g>
    <g v-else-if="kind === 'pet'"><path d="M29 37L24 12L43 24Q51 20 60 25L79 12L76 42Q84 61 67 68L70 91M33 68L30 91M34 64Q19 72 26 92H72Q78 74 68 65M26 82Q6 86 12 63" /><circle cx="40" cy="43" r="2" /><circle cx="64" cy="43" r="2" /><path d="M49 52L54 52L51 56ZM51 56Q45 62 41 57M51 56Q56 62 61 57M22 50L9 46M24 56L10 59M77 50L91 45M76 57L92 60" /></g>
    <g v-else-if="kind === 'building'"><path d="M16 94V27L49 7L83 27V94ZM12 28L49 4L88 28M43 94V69H58V94M29 40H39V52H29ZM61 40H71V52H61ZM6 95H95" /></g>
    <g v-else-if="kind === 'mountain'"><path d="M3 93L36 24L58 63L75 39L98 93ZM25 47L36 53L45 42M66 55L75 63L83 56" /></g>
    <g v-else-if="kind === 'flower'"><path d="M50 93V53M48 76Q18 76 23 60Q45 58 49 79M51 86Q77 86 81 68Q57 65 51 86" /><circle cx="50" cy="34" r="9" /><path d="M43 26C21 21 31 3 44 12C47 -2 65 3 61 19C83 9 86 32 65 35C87 49 64 64 57 45C52 68 29 57 37 42C14 44 19 21 39 28" /></g>
    <g v-else><path d="M24 23Q49 10 76 23L82 83Q50 97 18 83ZM24 23Q50 38 76 23M20 78Q48 91 80 78" /><path d="M38 42Q33 58 36 70" /></g>
  </g>
</template>

<style scoped>
.sketch-glyph :deep(*) { vector-effect: non-scaling-stroke; }
</style>
