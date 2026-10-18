<template>
  <!-- design/loading/, A: the home page's shape until the box has said who this is and what its printers are doing -->
  <div class="shape" aria-busy="true" aria-label="Opening the bench">
    <i class="a-sk say" style="width: min(420px, 80%); height: 40px"></i>
    <div class="tiles">
      <div v-for="n in 3" :key="n" class="tile">
        <i class="a-sk" style="width: 110px; height: 24px"></i>
        <i class="a-sk round pic"></i>
        <i class="a-sk" style="width: 70%; height: 22px"></i>
        <i class="a-sk" style="width: 50%; height: 16px"></i>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shape { display: flex; flex-direction: column; gap: 26px; }
.tiles { display: grid; gap: 22px; grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr)); }
.tile { background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); padding: 24px; display: flex; flex-direction: column; gap: 14px; }
.pic { width: 150px; height: 150px; align-self: center; }
@media (max-width: 599px) {
  .tile:nth-child(n + 3) { display: none; }
  .pic { width: 96px; height: 96px; }
}
</style>
