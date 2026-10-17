<template>
  <svg class="aperture-mark" viewBox="0 0 100 100" fill="none" aria-hidden="true">
    <circle class="aperture-ring" cx="50" cy="50" r="43" />
    <g class="aperture-blades"><path v-for="n in 6" :key="n" :transform="`rotate(${n * 60} 50 50)`" d="M50 13 81 31 65 59 50 33Z" /></g>
    <circle class="aperture-core" cx="50" cy="50" r="10" />
  </svg>
</template>
