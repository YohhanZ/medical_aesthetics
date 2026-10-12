<script setup lang="ts">
defineProps<{ compact?: boolean; motif?: string }>()
</script>

<template>
  <svg class="botanical-art" :class="{ compact }" viewBox="0 0 600 600" role="img" :aria-label="compact ? '服务方向抽象插画' : '绿色植物与水滴的原创抽象插画'">
    <defs>
      <linearGradient id="leaf" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#acc4a5"/><stop offset=".48" stop-color="#47735a"/><stop offset="1" stop-color="#173c30"/></linearGradient>
      <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff" stop-opacity=".86"/><stop offset=".5" stop-color="#c8d9ce" stop-opacity=".24"/><stop offset="1" stop-color="#719080" stop-opacity=".7"/></linearGradient>
      <radialGradient id="orb"><stop stop-color="#fff" stop-opacity=".95"/><stop offset=".75" stop-color="#dae5da" stop-opacity=".6"/><stop offset="1" stop-color="#91ac9a" stop-opacity=".2"/></radialGradient>
      <filter id="shadow"><feGaussianBlur stdDeviation="14"/></filter>
    </defs>
    <ellipse cx="308" cy="493" rx="145" ry="22" fill="#345c43" opacity=".12" filter="url(#shadow)"/>
    <g v-if="!compact">
      <circle cx="327" cy="300" r="188" fill="none" stroke="#c3d0bd" stroke-width="1"/>
      <circle cx="327" cy="300" r="153" fill="none" stroke="#c3d0bd" stroke-width=".7" opacity=".6"/>
      <path d="M294 449C131 421 117 243 207 115C341 128 400 314 294 449Z" fill="url(#leaf)"/>
      <path d="M212 126C240 245 278 333 294 449" fill="none" stroke="#d2e0c7" opacity=".48"/>
      <path d="M292 451C297 290 371 181 493 190C520 329 447 445 292 451Z" fill="url(#leaf)"/>
      <path d="M488 196C388 287 329 372 292 451" fill="none" stroke="#d6e6d0" opacity=".45"/>
      <path d="M322 484C225 484 186 430 216 363C240 311 277 266 315 215C355 269 402 317 424 367C452 434 412 484 322 484Z" fill="url(#glass)" stroke="#fff" stroke-opacity=".65"/>
      <path d="M250 391C242 414 248 438 262 450" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".7"/>
      <circle cx="465" cy="397" r="33" fill="url(#orb)" stroke="#fff" stroke-opacity=".75"/>
      <circle cx="130" cy="291" r="12" fill="url(#orb)"/>
    </g>
    <g v-else>
      <circle cx="300" cy="300" r="160" fill="none" stroke="currentColor" opacity=".16"/>
      <template v-if="motif === 'droplet'">
        <path d="M300 130C278 178 196 273 196 343C196 418 244 454 300 454C356 454 404 418 404 343C404 273 322 178 300 130Z" fill="url(#glass)" stroke="#fff" stroke-width="2"/>
        <path d="M226 338C217 380 239 405 260 413" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round"/>
      </template>
      <template v-else-if="motif === 'sun'">
        <circle cx="300" cy="300" r="102" fill="#dac7a8" opacity=".45"/><circle cx="280" cy="273" r="93" fill="url(#orb)" stroke="#fff" stroke-width="2"/>
        <circle cx="300" cy="300" r="133" fill="none" stroke="#b0a085" opacity=".35"/>
      </template>
      <template v-else-if="motif === 'ripple'">
        <ellipse v-for="i in 5" :key="i" cx="300" cy="310" :rx="i*30" :ry="i*19" fill="none" stroke="#91aaaa" :stroke-width="6-i" opacity=".55"/>
        <circle cx="300" cy="235" r="55" fill="url(#glass)" stroke="#fff" stroke-width="2"/>
      </template>
      <template v-else>
        <path d="M184 393C185 144 416 144 416 393" fill="none" stroke="#b3a59c" stroke-width="24" opacity=".3"/>
        <path d="M215 393C215 206 385 206 385 393" fill="none" stroke="#fff" stroke-width="20" opacity=".85"/>
        <circle cx="300" cy="356" r="61" fill="url(#glass)" stroke="#fff"/>
      </template>
    </g>
  </svg>
</template>
