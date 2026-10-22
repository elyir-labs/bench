<template>
  <section ref="root" class="model" :class="{ stage, collapsed: stage && collapsed }">
    <!-- Print a model, C "Ready first" (design/print-a-model/, picked 2 October 2026). What's on the plate
         is sliced as soon as it's picked; each row is a choice, and the purpose sheet shows what each costs.
         The plate is a list (design/plate/, A, picked 3 October 2026): a line per part with its own count,
         "Add a model" last, a sheet per part; spool, purpose and supports are the whole plate's.
         ?view=settings is "Every setting": each change, what it replaced and why.
         On a wide pane (design/ready-wide/, A + C, picked 3 October 2026) the plate is the stage, filling the
         pane, and the page is a card over its right that collapses to a bar with the time and Print.
         Several colors (design/multi-color/, B, picked 21 October 2026): a Colors card between the parts and the
         plate's rows, one row per color with where it comes from, the cost of the changes and where the old color goes. -->
    <div v-if="stage && session.stage !== 'error'" class="stagepic">
      <ModelPicture ref="big" :tris="plate" :color="colour" :runs="runs" :alt="label" plate :bed="printer?.bed" turnable zoomable
                    :shift="collapsed ? 0 : -cardRoom / 2" class="fill" @moved="m => (moved = m)" />
      <div class="zoom" role="group" aria-label="Zoom">
        <button type="button" aria-label="Closer" @click="big?.zoomBy(1.25)">+</button>
        <button type="button" aria-label="Further" @click="big?.zoomBy(0.8)">−</button>
        <button v-if="moved" type="button" class="fit" @click="big?.fit()">Fit</button>
      </div>
      <span class="hint">{{ picNote || 'Drag to turn' }} · scroll to zoom</span>
    </div>
    <div class="card">
    <header class="bar">
      <button class="back" :aria-label="view === 'settings' ? 'Back to the model' : session.picking && !session.picking.first ? 'Back to the plate' : 'Back to Print'" @click="back">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <b v-if="view === 'settings'" class="bar-title">Every setting</b>
      <span v-else class="file">{{ fileLine }}</span>
      <button v-if="stage" class="hide" type="button" aria-label="Hide, to see the whole plate" @click="collapsed = true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
      </button>
    </header>

    <!-- Which parts of a file to print (design/remove-parts/, C, picked 4 October 2026): before anything is sliced,
         every part ticked; "Change" opens it again from Ready -->
    <div v-if="session.picking && view !== 'settings'" class="picker">
      <h1 class="a-display head">{{ session.picking.from }} has {{ pickParts.length }} parts.</h1>
      <p class="pick-sub">Untick the ones you don't want to print now.</p>
      <div class="pgrid">
        <button v-for="p in pickParts" :key="p.key" type="button" class="ptile" :class="{ on: picked.has(p.key) }" role="checkbox"
                :aria-checked="picked.has(p.key)" @click="togglePick(p.key)">
          <ModelPicture :tris="p.tris" :color="colour" alt="" plate class="ptile-pic" />
          <span class="ck" aria-hidden="true"><svg v-if="picked.has(p.key)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
          <span class="n">{{ partName(p) }}</span>
        </button>
      </div>
      <div class="pickbar">
        <span class="t"><b>{{ picked.size === pickParts.length ? `All ${pickParts.length}` : `${picked.size} of ${pickParts.length}` }}</b>
          <button class="every" @click="tickAll">{{ picked.size === pickParts.length ? 'Untick all' : 'Tick all' }}</button></span>
        <button class="a-btn accent" :disabled="!picked.size" @click="confirmPick">{{ pickLabel }}</button>
      </div>
    </div>

    <!-- Every setting -->
    <div v-else-if="view === 'settings'" class="settings">
      <p class="lead" v-if="job?.state === 'done'">
        <b>{{ keptHere ? `Your ${purposeLabel}` : purposeLabel }}</b> in <b>{{ spool?.name }}</b>, from <b>{{ printer?.base }}</b>,
        {{ printerName }}'s everyday settings. Tap one you can change.
      </p>
      <p class="lead" v-else-if="job?.state === 'failed'">{{ job.error }}<br><span class="detail">{{ job.error_detail }}</span></p>
      <p class="lead" v-else>Working it out…</p>
      <!-- design/edit-settings/, C: what the person kept for this purpose, set for this print, and the rest they can change -->
      <template v-for="g in editGroups" :key="g.title">
        <h3 class="grp">{{ g.title }}<button v-if="g.reset" class="grp-reset" @click="resetPurpose()">Back to Elyir Bench's</button></h3>
        <div class="chg">
          <button v-for="r in g.rows" :key="r.key" class="chg-row ed" :class="{ you: g.mine }" :disabled="job?.state !== 'done'" @click="openEdit(r.key)">
            <div class="l">
              <span>{{ r.label }}</span>
              <span class="v a-num"><template v-if="r.was"><s>{{ r.was }} → </s></template>{{ r.now }}</span>
            </div>
            <div class="w">{{ r.why }}<template v-if="orcaNames"> · <code>{{ r.key }}</code></template></div>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
        </div>
      </template>
      <template v-for="g in groups" :key="g.title">
        <h3 class="grp">{{ g.title }}</h3>
        <div class="chg">
          <div v-for="r in g.rows" :key="r.key + r.label" class="chg-row">
            <div class="l">
              <span>{{ r.label }}</span>
              <span class="v a-num">
                <template v-if="r.was"><s>{{ r.was }} → </s></template>
                <i v-if="r.color" class="dot" :style="{ '--c': r.color }"></i>{{ r.color ? colourWord(r.color) : r.now }}
              </span>
            </div>
            <div class="w">{{ r.why }}<template v-if="orcaNames"> · <code>{{ r.key }}</code></template></div>
          </div>
        </div>
      </template>
      <p v-for="w in job?.warnings ?? []" :key="w" class="warnline">{{ w }}</p>
      <!-- Orca's own names, for finding a setting in Orca. Hidden by default: in grey monospace they read as
           unfilled placeholders (3 October 2026). -->
      <button v-if="groups.length" class="every names" @click="orcaNames = !orcaNames">{{ orcaNames ? "Hide Orca's names" : "Show Orca's names" }}</button>
    </div>

    <!-- Ready -->
    <template v-else>
      <div v-if="session.stage === 'error'" class="problem">
        <h1 class="a-display head">{{ offTitle(session.errorInfo) ?? "That didn't work." }}</h1>
        <p class="sub">{{ session.error }}</p>
        <div class="problem-acts">
          <button v-if="offTitle(session.errorInfo)" class="a-btn accent" @click="retry">Try again</button>
          <button class="a-btn ghost" @click="back">Back to Print</button>
        </div>
      </div>
      <template v-else>
        <!-- The plate where Orca put things; drag to look round it -->
        <ModelPicture v-if="!stage" :tris="plate" :color="colour" :runs="runs" :alt="label" plate :bed="printer?.bed" turnable class="pic">
          <span v-if="picNote" class="picnote">{{ picNote }}</span>
          <button v-if="only && paintable(only)" type="button" class="pictool" @click="openPaint(0)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19.5 3.5l-9 9M9 13.5c-2 0-3.5 1.5-3.5 3.5 0 1.2-.8 2.3-2 2.5 1 .7 2.3 1 3.5 1 2.8 0 5-2.2 5-5z" /></svg>Paint
          </button>
        </ModelPicture>
        <h1 class="a-display head">{{ headline }}</h1>

        <!-- What doesn't fit goes on a second plate, said out loud -->
        <div v-if="spill.rest" class="warn">
          <b>{{ spill.fit }} fit on the plate.</b>
          <span>The other {{ spill.rest }} go on a second plate. When this one's done and the bed is clear, {{ printerName }} asks to print them.</span>
          <button class="inline" @click="onlyWhatFits">Make it {{ spill.fit }}</button>
        </div>
        <div v-else-if="only && tooBig(only) && only.size && printer?.bed" class="warn">
          <b>Too big for {{ printerName }}'s bed.</b>
          <span v-if="only.scale === only.fit">{{ tooBigText(only) }}, so I made it {{ pct(only.scale) }}. Change the size if that's wrong for it.</span>
          <span v-else>{{ tooBigText(only) }}. It's printing at {{ pct(only.scale) }}.</span>
        </div>

        <div class="plist">
          <div v-for="(p, i) in session.parts" :key="p.key" class="pl">
            <button class="pl-open" :aria-label="`${partName(p)}: size, which way down`" @click="openPart(i)">
              <ModelPicture :tris="p.tris" :color="partColor(p)" :runs="p.project || p.paint || session.heights.length ? ownRuns(p) : null" alt="" class="thumb" />
              <span class="t"><b>{{ partName(p) }}</b>
                <span v-if="p.project" class="pcol"><span class="dots"><i v-for="(c, k) in fileDots(p)" :key="k" :style="{ '--c': c }"></i></span>{{ fileDots(p).length }} colors from the file</span>
                <span v-else :class="{ you: subOf(p, i).amber, pcol: multi }"><i v-if="multi" class="dot sm" :style="{ '--c': partColor(p) }"></i>{{ multi ? `${plateSpools[p.spool]?.color ? colorWord(plateSpools[p.spool]?.color) : plateSpools[p.spool]?.material ?? ''} · ` : '' }}{{ subOf(p, i).text }}</span></span>
            </button>
            <Stepper v-if="!p.project" :value="p.copies" :label="`How many of ${partName(p)}`" :bin="session.parts.length > 1" @change="n => setCopies(i, n)" @remove="removePart(i)" />
          </div>
          <label v-if="!hasProject" class="addl" :class="{ busy: session.adding > 0 }">
            <input type="file" multiple accept=".stl,.obj,.step,.stp,.3mf" class="file-input" :disabled="session.adding > 0" @change="add" />
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            {{ session.adding ? 'Adding…' : 'Add a model' }}
          </label>
        </div>
        <p v-for="f in fromFiles" :key="f.from" class="fromrow">
          {{ f.on === f.of ? `All ${f.of}` : `${f.on} of ${f.of}` }} from {{ f.from }}
          <button class="every" @click="openPicker(f.from)">Change</button>
        </p>
        <p v-if="addError" class="bad small">{{ addError }}</p>

        <!-- Bench spots it (design/paint-and-height/, C): a flat top with something on it, one tap to color what's above -->
        <div v-if="spotted && offerSpools.length" class="offer">
          <b class="h">{{ spotted.raised ? 'Raised parts on top' : 'A base, then the rest' }}</b>
          <p>{{ spotted.raised ? `They start at ${mm(spotted.z)}, on top of a flat area.` : `The base is ${mm(spotted.z)} tall.` }}
            Print {{ spotted.raised ? 'them' : "what's above it" }} in another color? One change{{ unitHere ? ', about 2 minutes' : ', swapped by hand' }}.</p>
          <div class="choices">
            <button v-for="s in offerSpools" :key="`${s.slot}${s.color}`" type="button" class="choice" @click="takeOffer(s)">
              <i class="dot" :style="{ '--c': s.color || 'transparent' }"></i>{{ colorWord(s.color) }}</button>
            <button type="button" class="choice plain" @click="openHeight(-1, spotted.z)">Another</button>
          </div>
          <div class="offer-foot">
            <button type="button" class="every" @click="openHeight(-1, spotted.z)">Somewhere else…</button>
            <button type="button" class="every quiet" @click="dismissOffer()">Not this time</button>
          </div>
        </div>
        <button v-else-if="canHeight && !multi" type="button" class="every" @click="openHeight(-1)">Change color at a height</button>

        <!-- Colors (design/multi-color/, B): one row per color, where it comes from, then the cost and the purge -->
        <template v-if="multi">
          <h3 class="grp">Colors<span class="grp-n">{{ plateSpools.length }} spools</span></h3>
          <div class="ccard">
            <button v-for="(s, k) in plateSpools" :key="k" class="cr" @click="openColor(k)">
              <i class="dot big" :class="{ hand: handOf(s, k), miss: unsortedColors.includes(k) }" :style="{ '--c': s.color || 'transparent' }"></i>
              <span class="t"><b>{{ colorName(s, k) }}<i v-if="handOf(s, k) && !unsortedColors.includes(k)" class="tag">By hand</i></b>
                <span :class="{ you: lineOf(s, k).amber }">{{ lineOf(s, k).text }}</span></span>
              <span class="g a-num">{{ gramsFor(k) }}</span>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
            </button>
            <!-- a new change at a height (design/paint-and-height/, A); one already made is moved from its color's sheet -->
            <button v-if="canHeight" type="button" class="addrow" @click="openHeight(-1)"><i aria-hidden="true">+</i>Change color at a height</button>
            <div class="cost">
              <div v-if="many" class="toomany">
                <p><b>{{ many.count }} swaps by hand,</b> {{ tooManyWords(many) }}. That's too many to stand by.</p>
                <div class="acts">
                  <button v-if="session.parts.length > 1 && !session.oneAfterOther" class="a-btn accent" @click="setOneAfterOther(true)">Print one after the other</button>
                  <button v-if="!hasProject" class="a-btn ghost" @click="oneColor()">One color</button>
                </div>
              </div>
              <p v-if="colorsNow"><b>{{ cost!.strong }}</b> {{ cost!.rest }}</p>
              <p v-else>Working out the changes…</p>
              <p v-if="session.oneAfterOther" class="aside">One part after the other, so the color changes once per part.
                <button class="every" @click="setOneAfterOther(false)">Print them together</button></p>
              <div v-if="purgeChoices.length > 1" class="seg" role="radiogroup" aria-label="Between colors">
                <button v-for="pg in purgeChoices" :key="pg" role="radio" :aria-checked="pg === purgeNow" :class="{ on: pg === purgeNow }" @click="setPurge(pg)">{{ PURGE_WORDS[pg].label }}</button>
              </div>
            </div>
          </div>
        </template>

        <h3 class="grp">For the whole plate</h3>
        <div class="rows">
          <button class="row" @click="open = 'purpose'">
            <span class="k">It's for</span>
            <span class="v">{{ purposeLabel }}<small>{{ keptHere ? `Yours: ${keptWords}` : purposeSummary }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button v-if="!multi" class="row" @click="open = 'spool'">
            <span class="k">Spool</span>
            <span class="v"><span class="one"><i class="dot" :style="{ '--c': spool?.color || 'transparent' }"></i>{{ spool?.name }}</span><small>{{ spoolNote }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <!-- design/first-layer-sheets/, C: only when the sheets' first layers differ -->
          <button v-if="sheetPick" class="row" :disabled="!allowedHere('first_layer_sheet')" @click="open = 'sheet'">
            <span class="k">Sheet on</span>
            <span class="v">{{ sheetChoice(sheetPick.on) }}<small>{{ sheetNote(sheetNow, sheetOthers) }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button v-if="changedWords" class="row" @click="router.push({ query: { view: 'settings' } })">
            <span class="k">Changed</span>
            <span class="v">{{ changedWords }}<small>You set this · for this print</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button class="row" @click="open = 'supports'">
            <span class="k">Supports</span>
            <span class="v">{{ sup.value }}<small>{{ sup.note }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
        </div>
        <!-- design/supports/, A: a kind picked for this print can become the usual -->
        <p v-if="session.supports !== session.usual && session.supports !== 'off'" class="usual">
          Your usual is {{ KIND_WORDS[session.usual].label }}.
          <button class="every" @click="makeUsual()">Make {{ KIND_WORDS[session.supports].label }} my usual</button>
        </p>
        <button class="every" @click="router.push({ query: { view: 'settings' } })">Every setting</button>

        <!-- The time and Print stay in view while the page scrolls under them -->
        <div class="dock">
          <div v-if="heightToast" class="toast" role="status">
            <span>{{ heightToast }}</span>
            <button type="button" @click="undoHeight">Undo</button>
          </div>
          <div v-else-if="session.undo" class="toast" role="status">
            <span>Took {{ partName(session.undo.part) }} off</span>
            <button type="button" @click="undoRemove">Undo</button>
          </div>
          <div v-if="session.sent" class="foot sent">
            <div class="t"><b>Sent to {{ printerName }}.</b><span>{{ sentNote }}</span></div>
            <button class="a-btn accent" @click="back">Done</button>
          </div>
          <template v-else>
            <div class="foot">
              <div class="t">
                <b v-if="job?.state === 'done'" class="a-num">{{ time }} · {{ grams }}</b>
                <b v-else-if="job?.state === 'failed'" class="bad">{{ job.error }}</b>
                <b v-else-if="waiting"><span class="spin" aria-hidden="true"></span>{{ waiting.title }}</b>
                <b v-else><span class="spin" aria-hidden="true"></span>Slicing…</b>
                <span>{{ waiting ? waiting.note : footNote }}</span>
              </div>
              <button v-if="!door.away" class="a-btn accent" :disabled="!canPrint" @click="open = 'bed'">Print</button>
              <button v-else class="a-btn accent" :disabled="job?.state !== 'done' || working" @click="sendOnly">Send to {{ printerName }}</button>
            </div>
            <button v-if="!door.away" class="send" :disabled="job?.state !== 'done' || working" @click="sendOnly">Send to {{ printerName }} for later</button>
            <p v-if="actionError" class="bad small">{{ actionError }}</p>
          </template>
        </div>
      </template>
    </template>

    </div>
    <!-- the card, collapsed: the time and Print stay -->
    <div v-if="stage && collapsed" class="minibar">
      <span class="t"><b v-if="job?.state === 'done'" class="a-num">{{ time }} · {{ grams }}</b><b v-else>Slicing…</b><span>{{ label }}</span></span>
      <button v-if="!door.away && !session.sent" class="a-btn accent" :disabled="!canPrint" @click="open = 'bed'">Print</button>
      <button class="a-btn ghost show" @click="collapsed = false">Show</button>
    </div>

    <!-- One part: how many, its size, which way down, off the plate -->
    <SliceSheet :open="open === 'part' && !!editing" :title="editing ? partName(editing) : ''" :sub="editing?.name" @close="open = null">
      <template v-if="editing">
        <div class="howmany">
          <span class="t"><b>How many</b><span class="a-num">{{ copiesNote }}</span></span>
          <Stepper big :value="editing.copies" :label="`How many of ${partName(editing)}`" @change="n => setCopies(editAt, n)" />
        </div>
        <div class="chips qty">
          <button v-for="n in QUICK" :key="n" class="chip" :class="{ on: editing.copies === n }" @click="setCopies(editAt, n)">{{ n }}</button>
          <button v-if="!editing.fill || editing.fill.others_fit" class="chip" :class="{ on: !!editing.fill && editing.copies === editing.fill.fits }"
                  :disabled="!editing.fill" @click="editing.fill && setCopies(editAt, editing.fill.fits)">
            Fill the plate<template v-if="editing.fill"> · {{ editing.fill.fits }}{{ editing.fill.at_least ? '+' : '' }}</template><template v-else>…</template>
          </button>
        </div>
        <div class="rows">
          <button v-if="!editing.project" class="row" @click="open = 'partColor'">
            <span class="k">Color</span>
            <span class="v"><span class="one"><i class="dot" :style="{ '--c': partColor(editing) }"></i>{{ colorName(plateSpools[editing.spool], editing.spool) }}</span>
              <small>{{ multi ? lineOf(plateSpools[editing.spool], editing.spool).text : spoolNote }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button v-if="paintable(editing)" class="row" @click="openPaint(editAt)">
            <span class="k">Paint</span>
            <span class="v">{{ editing.paint ? `${paintUses(editing.paint).size} ${paintUses(editing.paint).size === 1 ? 'color' : 'colors'} painted on` : 'Not painted' }}
              <small>{{ editing.paint ? 'Tap areas in another color, or Undo there' : 'Tap areas of it in another color' }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button class="row" @click="open = 'size'">
            <span class="k">Size</span>
            <span class="v a-num">{{ pct(editing.scale) }}<small>{{ sizeAt(editing, editing.scale) }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <button v-if="sideOptions.length > 1" class="row" @click="open = 'lay'">
            <span class="k">Lying</span>
            <span class="v">{{ lyingWords(editing).value }}<small>{{ lyingWords(editing).note }}</small></span>
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
          <div v-else class="row still">
            <span class="k">Lying</span>
            <span class="v">As in the file<small>{{ editing.lying ? 'It only sits one way' : 'Printed the way the file has it' }}</small></span>
          </div>
          <!-- design/brim/, A: picked for it from how it stands, said, changed from pictures of its own footprint -->
          <button class="row" @click="open = 'brim'">
            <span class="k">Brim</span>
            <span class="v">{{ brimRow.value }}<small>{{ brimRow.note }}</small></span>
            <FootprintPicture v-if="editPrint && brimRow.kind" :print="editPrint" :color="colour" :kind="brimRow.kind" :area="editArea" alt="" class="mini" />
            <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
          </button>
        </div>
        <button v-if="session.parts.length > 1" class="takeoff" @click="takeOff">Take it off the plate</button>
      </template>
    </SliceSheet>

    <HeightSheet :open="heightOpen" :tris="session.parts[0]?.tris ?? null" :scale="session.parts[0]?.scale ?? 1" :own="session.parts[0]?.spool ?? 0"
                 :heights="session.heights" :choices="trayChoices" :layer="layer" :start="heightStart" :at="heightAt"
                 :start-spool="heightAt >= 0 ? session.heights[heightAt]?.spool : undefined"
                 @close="heightOpen = false" @add="addHeight" @remove="dropHeight" />
    <PaintScreen :open="paintAt >= 0" :name="painting ? partName(painting) : ''" :tris="painting?.tris ?? null" :paint="painting?.paint ?? null"
                 :own="painting?.spool ?? 0" :choices="trayChoices" @close="paintAt = -1" @done="paintDone" />

    <!-- What it's for: all four sliced, so the real times -->
    <SliceSheet :open="open === 'purpose'" title="What's it for?" sub="All four are sliced, so these are the real times." @close="open = null">
      <div class="opts">
        <button v-for="p in purposes" :key="p.id" class="opt" :class="{ on: p.id === session.purpose }" @click="pickPurpose(p.id)">
          <span class="ic" v-html="ICONS[p.id]"></span>
          <span class="t"><b>{{ p.label }}<i v-if="hasKept(p.id)" class="tag mine">Yours</i></b><span>{{ hasKept(p.id) ? `Yours: ${keptOf(p.id)}` : p.summary }}</span></span>
          <span class="tm a-num"><b>{{ timeOf(p.id) }}</b><span>{{ gramsOf(p.id) }}</span></span>
        </button>
      </div>
      <p v-if="keptHere" class="usual">Your {{ purposeLabel }}: {{ keptWords }}. <button class="every" @click="resetPurpose(); open = null">Back to Elyir Bench's {{ purposeLabel }}</button></p>
    </SliceSheet>

    <!-- Which side down: every side it can rest on, as it would lie (design/orientation/, then any side).
         Each is measured, not sliced: slicing every side would take minutes on the printer's Pi. -->
    <SliceSheet :open="open === 'lay' && !!editing" title="Which side down?" sub="Tap the side that goes on the plate. It's sliced once you pick." @close="open = null">
      <SidePicks v-if="editing?.trisFile" :options="sideOptions" :file="editing.trisFile" :color="colour" :time="job?.state === 'done' ? time : ''" @pick="pickSide" />
    </SliceSheet>

    <!-- Brim (design/brim/, A, picked 4 October 2026): the part's own first layer with each brim, drawn from its
         footprint so the sheet opens at once; sliced once one is picked. The rule's pick is tagged; picking it
         again hands the part back to the rule. -->
    <SliceSheet :open="open === 'brim' && !!editing" title="Brim" :sub="brimSub" @close="open = null">
      <div class="opts">
        <button v-for="k in BRIM_KINDS" :key="k" class="opt lay" :class="{ on: k === brimRow.kind }" @click="pickBrim(k)">
          <FootprintPicture v-if="editPrint" :print="editPrint" :color="colour" :kind="k" :area="editArea" :alt="BRIM_WORDS[k].label" class="tile fpt" />
          <span class="t"><b>{{ BRIM_WORDS[k].label }}<i v-if="k === brimRule" class="tag">Picked for it</i></b><span>{{ cardLine(k) }}</span></span>
          <span v-if="k === brimRow.kind && job?.state === 'done'" class="tm a-num"><b>{{ time }}</b><span>the plate</span></span>
        </button>
      </div>
      <p v-if="brimRow.note" class="usual">{{ brimRow.note }}.</p>
    </SliceSheet>
    <!-- Which spool -->
    <SliceSheet :open="open === 'spool'" title="Which spool?" :sub="`What's loaded in ${printerName} and has settings here.`" @close="open = null">
      <div class="opts">
        <button v-for="s in usable" :key="s.slot" class="opt" :class="{ on: spool?.slot === (s.direct ? null : s.slot) && spool?.material === s.material?.toUpperCase() }" @click="pickSpool(s)">
          <i class="dot big" :style="{ '--c': s.color || 'transparent' }"></i>
          <span class="t"><b>{{ s.name || s.material }}</b><span>{{ s.direct ? 'Loaded' : `Slot ${s.slot + 1}` }}<template v-if="s.grams"> · {{ s.grams }} g left</template></span></span>
        </button>
      </div>
      <p class="sub2">Not loaded yet? Pick the material and load it before you print.</p>
      <div class="chips">
        <button v-for="m in printer?.materials ?? []" :key="m" class="chip" :class="{ on: spool?.slot == null && !spool?.color && spool?.material === m }" @click="pickMaterial(m)">{{ m }}</button>
      </div>
    </SliceSheet>

    <!-- A part's color (design/multi-color/, B): the plate's colors, a loaded spool, or one swapped in by hand -->
    <SliceSheet :open="open === 'partColor' && !!editing" :title="editing ? `${partName(editing)} prints in` : ''"
                sub="A color another part uses is shared, with no extra change." @close="open = null">
      <div v-if="editing" class="opts">
        <button v-for="(s, k) in plateSpools" :key="'p' + k" class="opt" :class="{ on: editing.spool === k }" @click="pickPartSpool(s)">
          <i class="dot big" :class="{ hand: handOf(s, k) }" :style="{ '--c': s.color || 'transparent' }"></i>
          <span class="t"><b>{{ colorName(s, k) }}</b><span>{{ lineOf(s, k).text }}</span></span>
        </button>
        <button v-for="s in offPlate" :key="'s' + s.slot" class="opt" @click="pickLoaded(s, 'part')">
          <i class="dot big" :style="{ '--c': s.color || 'transparent' }"></i>
          <span class="t"><b>{{ s.name || s.material }}</b><span>Slot {{ s.slot + 1 }}<template v-if="s.grams"> · {{ s.grams }} g left</template></span></span>
        </button>
      </div>
      <p class="sub2">Or a color you'll swap in by hand: the print waits for it.</p>
      <div class="chips swatches">
        <button v-for="c in COLORS" :key="c.hex" class="sw" :style="{ '--c': c.hex }" :aria-label="c.name" @click="pickHand(c.hex, 'part')"></button>
      </div>
    </SliceSheet>

    <!-- One of the plate's colors: which spool, or by hand -->
    <SliceSheet :open="open === 'color' && !!colorAt" :title="colorAt ? colorTitle : ''" :sub="colorSub" @close="open = null">
      <div v-if="colorAt" class="opts">
        <button v-if="loadSlot != null" class="opt" @click="pickLoad()">
          <i class="dot big" :style="{ '--c': colorAt.s.color || 'transparent' }"></i>
          <span class="t"><b>Load it in slot {{ loadSlot + 1 }}</b><span>Slot {{ loadSlot + 1 }} is empty. Then the unit does it, and nobody needs to be here.</span></span>
        </button>
        <button v-if="colorAt.k > 0" class="opt" :class="{ on: handOf(colorAt.s, colorAt.k) && !unsortedColors.includes(colorAt.k) }" @click="pickHand(colorAt.s.color, 'color')">
          <i class="dot big hand" :style="{ '--c': colorAt.s.color || 'transparent' }"></i>
          <span class="t"><b>Swap it by hand</b><span>{{ handLine }}</span></span>
        </button>
        <button v-for="s in usable" :key="s.slot" class="opt" :class="{ on: !colorAt.s.hand && colorAt.s.slot === (s.direct ? null : s.slot) && colorAt.s.color === s.color }" @click="pickLoaded(s, 'color')">
          <i class="dot big" :style="{ '--c': s.color || 'transparent' }"></i>
          <span class="t"><b>{{ s.name || s.material }}</b><span>{{ s.direct ? 'Loaded' : `Slot ${s.slot + 1}` }}<template v-if="otherMaterial(s)"> · another material, may not stick</template><template v-else-if="s.grams"> · {{ s.grams }} g left</template></span></span>
        </button>
      </div>
      <template v-for="(h, i) in session.heights" :key="'h' + i">
        <div v-if="colorAt && h.spool === colorAt.k" class="hacts">
          <span>From {{ mm(h.z) }} up, a change at a height</span>
          <button type="button" class="every" @click="open = null; openHeight(i, h.z)">Move it</button>
          <button type="button" class="every" @click="open = null; dropHeight(i)">Remove it</button>
        </div>
      </template>
      <template v-if="colorAt && colorAt.k > 0 && !unitHere">
        <p class="sub2">Which color will you swap in?</p>
        <div class="chips swatches">
          <button v-for="c in COLORS" :key="c.hex" class="sw" :class="{ on: colorAt.s.color === c.hex }" :style="{ '--c': c.hex }" :aria-label="c.name" @click="pickHand(c.hex, 'color')"></button>
        </div>
      </template>
    </SliceSheet>

    <SliceSheet :open="open === 'sheet' && !!sheetPick" title="Which sheet is on the bed?" sub="Each keeps its own first layer. It's used from this print on." @close="open = null">
      <div class="opts">
        <button v-for="o in sheetPick?.options ?? []" :key="o.name" class="opt" :class="{ on: o.name === sheetPick?.on }" @click="pickSheet(o.name)">
          <span class="t"><b>{{ sheetChoice(o.name) }}</b><span>{{ o.words }} ({{ o.mm }})</span></span>
        </button>
      </div>
    </SliceSheet>

    <!-- Supports -->
    <!-- Normal or tree (design/supports/, A, picked 4 October 2026): each kind sliced for the chosen purpose, its
         real supports drawn solid under a see-through plate, with its real time. -->
    <SliceSheet :open="open === 'supports'" title="Supports" sub="Each is sliced, so these are the real supports and times." @close="open = null">
      <div class="opts">
        <button v-for="k in SUPPORT_KINDS" :key="k" class="opt lay" :class="{ on: k === session.supports }" @click="pickSupports(k)">
          <ModelPicture :tris="kindPlates[k]" :color="colour" :alt="`${KIND_WORDS[k].label} supports`" plate :bed="printer?.bed"
                        :supports="kindLines(k)" class="tile" />
          <span class="t"><b>{{ KIND_WORDS[k].label }}<i v-if="k === session.usual" class="tag">Your usual</i></b><span>{{ kindLine(k) }}</span></span>
          <span class="tm a-num"><b>{{ kindTime(k) }}</b><span>{{ kindGrams(k) }}</span></span>
        </button>
      </div>
    </SliceSheet>

    <!-- One setting (design/edit-settings/, C): its control, its real price, and whether it's kept -->
    <SliceSheet :open="open === 'edit' && !!edited" :title="edited?.label ?? ''" :sub="edited?.help ?? ''" @close="open = null">
      <template v-if="edited">
        <div v-if="edited.kind === 'number'" class="edit-step">
          <Stepper big :value="editSteps!.at" :min="0" :max="editSteps!.last" :shown="editWords(edited, wanted(edited.key))"
                   :label="edited.label" @change="i => setSetting(edited!.key, editSteps!.value(i), editScope)" />
        </div>
        <div v-else class="opts">
          <button v-for="c in edited.choices" :key="c[0]" class="opt" :class="{ on: c[0] === wanted(edited.key) }"
                  @click="setSetting(edited!.key, c[0], editScope)">
            <span class="t"><b>{{ c[1] }}</b></span>
          </button>
        </div>
        <p class="edit-price a-num"><b>{{ job?.state === 'done' ? `${time} · ${grams}` : 'Working it out…' }}</b>
          <span v-if="priceDelta" class="d">{{ priceDelta }}</span></p>
        <p v-if="purposeGives != null && wanted(edited.key) !== purposeGives" class="edit-was">
          {{ purposeLabel }} uses {{ editWords(edited, purposeGives) }}.
          <button class="every" @click="setSetting(edited!.key, purposeGives!, editScope)">Back to {{ editWords(edited, purposeGives) }}</button>
        </p>
        <div class="scope" role="radiogroup" aria-label="How long">
          <button role="radio" :aria-checked="editScope === 'print'" :class="{ on: editScope === 'print' }" @click="pickScope('print')">
            <span class="rd"></span><span class="t"><b>Just this print</b><span>The next plate starts as {{ purposeLabel }} is.</span></span>
          </button>
          <button role="radio" :aria-checked="editScope === 'keep'" :class="{ on: editScope === 'keep' }" @click="pickScope('keep')">
            <span class="rd"></span><span class="t"><b>Every {{ purposeLabel }} print on {{ printerName }}</b><span>Your {{ purposeLabel }} keeps it from now on.</span></span>
          </button>
        </div>
        <button class="a-btn accent edit-done" @click="open = null">Done</button>
      </template>
    </SliceSheet>

    <!-- Size of one part -->
    <SliceSheet :open="open === 'size' && !!editing" title="Size" :sub="editing && tooBig(editing) ? `${tooBigText(editing)}.` : 'Every copy of it, the same size.'" @close="open = null">
      <div v-if="editing" class="opts">
        <button v-for="k in sizesOf(editing)" :key="k" class="opt" :class="{ on: k === editing.scale }" @click="pickScale(k)">
          <span class="t"><b>{{ pct(k) }}</b><span class="a-num">{{ sizeAt(editing, k) }}</span></span>
        </button>
      </div>
    </SliceSheet>

    <BedClearSheet :open="open === 'bed'" :printer="printerName" :working="working" @close="open = null" @confirm="printNow" />
    <PrintCheckSheet :check="refusal" @close="refusal = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { IntentSpool, PrintCheck } from '@/intent/types'
import { allowedHere, door } from '@/door'
import { sheetChoice, sheetNote } from '@/intent/firstLayer'
import { layout } from '@/shell/useLayout'
import { humanDuration, prettyName } from '@/intent/jobs'
import { COLORS } from '@/components/materials/palette'
import ModelPicture from '@/components/slice/ModelPicture.vue'
import SidePicks from '@/components/slice/SidePicks.vue'
import { area, sameSide, sideOptions as sideOptions_ } from '@/slice/sides'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import FootprintPicture from '@/components/slice/FootprintPicture.vue'
import Stepper from '@/components/slice/Stepper.vue'
import BedClearSheet from '@/components/slice/BedClearSheet.vue'
import PrintCheckSheet from '@/components/print/PrintCheckSheet.vue'
import HeightSheet from '@/components/slice/HeightSheet.vue'
import PaintScreen from '@/components/slice/PaintScreen.vue'
import { mm, paintUses } from '@/slice/paint'
import { needsSheet } from '@/intent/colour'
import {
  session, current, only, plate, tooBig, addFiles, askFill, downOf, followSpools, onlyWhatFits, removePart, reset, send,
  setCopies, setPurpose, setScale, setSide, setSpool, setSupports, askKinds, kindJob, loadLines, makeUsual, plateOf, type Part,
  setSetting, setScope, resetPurpose, wanted, isKept, undoRemove, openPicker, pick, closePicker, setBrim, retry,
  multi, plateSpools, runs, partRuns, unsortedColors, setPartSpool, setPlateSpool, setPurge, setOneAfterOther, oneColor,
  paintable, canHeight, spotted, setHeight, removeHeight, restoreHeights, setPaint, dismissOffer,
} from '@/slice/session'
import { colorWord, costLine, footColors, PURGE_WORDS, spoolLine, tooMany, tooManyWords, type PlateSpool, type Purge } from '@/slice/colors'
import { offTitle, readyNote, waitWords } from '@/slice/elsewhere'
import { footprint, roomFor, type BrimKind } from '@/slice/footprint'
import { fileCounts } from '@/slice/plate'
import { BRIM_WORDS, editRows, editSummary, editWords, steps, groupChanges, KIND_WORDS, modelName, overflow, plateHeadline, plateLabel, SUPPORT_KINDS, supportsWords, tooBigWords, usableSpools, type Purpose, type SupportKind } from '@/slice/plan'

const store = useIntentStore()
// The plate as the stage on a wide pane (design/ready-wide/): measured, so a narrow window or a tablet's
// pane keeps the column; never on a phone
const root = ref<HTMLElement | null>(null)
const big = ref<{ zoomBy: (k: number) => void; fit: () => void } | null>(null)
const stage = ref(false)
const collapsed = ref(false)
const moved = ref(false)
const cardRoom = 440                      // the card's width and its margin: the plate centres left of it
let paneRO: ResizeObserver | null = null
onMounted(() => {
  paneRO = new ResizeObserver(([e]) => { stage.value = e.contentRect.width >= 880 && layout.value !== 'compact' })
  const pane = root.value?.parentElement      // the pane, not the page: the page itself is held to a column
  if (pane) paneRO.observe(pane)
})
onBeforeUnmount(() => paneRO?.disconnect())
const route = useRoute()
const router = useRouter()

const view = computed(() => (route.query.view === 'settings' ? 'settings' : 'ready'))
const orcaNames = ref(false)
const open = ref<null | 'sheet' | 'purpose' | 'spool' | 'supports' | 'size' | 'bed' | 'lay' | 'part' | 'edit' | 'brim' | 'color' | 'partColor'>(null)
const editAt = ref(0)
const working = ref(false)
const actionError = ref('')
const addError = ref('')
const refusal = ref<PrintCheck | null>(null)
const QUICK = [1, 2, 4, 6, 10]

// while a change waits to be sliced, the last slice's time and price are old: show it as slicing
const job = computed(() => (session.pending ? null : current.value))
const printer = computed(() => session.printer)
const printerName = computed(() => store.intent?.printer?.name || printer.value?.name || 'the printer')
const spool = computed(() => session.spool)
const colour = computed(() => spool.value?.color || '#8A8D91')
const editing = computed<Part | null>(() => session.parts[editAt.value] ?? null)
const label = computed(() => (session.parts.length ? plateLabel(session.parts) : ''))
const fileLine = computed(() => (session.files.length > 1 ? `${session.files.length} files` : session.files[0] ?? session.parts[0]?.name ?? ''))
const purposes = computed(() => session.options?.purposes ?? [])
const purpose = computed(() => purposes.value.find(p => p.id === session.purpose))
const purposeLabel = computed(() => purpose.value?.label ?? 'Everyday')
const purposeSummary = computed(() => purpose.value?.summary ?? '')
const usable = computed(() => usableSpools((store.intent?.spools ?? []) as IntentSpool[], printer.value?.materials ?? []))
const plates = computed(() => (job.value?.state === 'done' ? job.value.plates ?? [] : []))
const spill = computed(() => (plates.value.length > 1 ? overflow(session.parts, plates.value[0].counts) : { fit: 0, rest: 0 }))

const headline = computed(() => {
  if (!session.parts.length) return 'Reading it…'
  const state = job.value?.state === 'done' ? 'done' : job.value?.state === 'failed' ? 'failed' : 'working'
  const o = only.value
  return plateHeadline(session.parts, state, plates.value.length || 1, o && o.copies === 1 && tooBig(o) ? pct(o.scale) : undefined)
})
const picNote = computed(() => {
  const o = only.value
  if (o && o.copies === 1) return o.lay === 'flat' && o.layAuto ? 'Laid flat for you' : ''
  return 'Drag to look around'
})
const total = (j: { estimate?: { seconds: number | null; changes_seconds?: number } } | null | undefined) =>
  j?.estimate?.seconds == null ? null : j.estimate.seconds + (j.estimate.changes_seconds ?? 0)
const time = computed(() => humanDuration(total(job.value)))
const grams = computed(() => (job.value?.estimate?.grams != null ? `${Math.round(job.value.estimate.grams)} g` : ''))
const sup = computed(() => supportsWords(session.supports, job.value?.state === 'done' ? job.value.supports_added : null, session.usual))
// the Supports sheet: each kind's plate as its slice placed it, its supports, time and weight
const kindPlates = computed(() => Object.fromEntries(SUPPORT_KINDS.map(k => [k, plateOf(kindJob(k))])) as Record<SupportKind, Float32Array>)
function kindLines(k: SupportKind) { const j = kindJob(k); return j?.id ? session.lines[j.id] ?? null : null }
function kindLine(k: SupportKind) {
  const j = kindJob(k)
  return k !== 'off' && j?.state === 'done' && j.supports_added === false ? 'None needed: nothing overhangs too far.' : KIND_WORDS[k].line
}
function kindTime(k: SupportKind) { const j = kindJob(k); return j?.state === 'done' ? humanDuration(j.estimate?.seconds) : j?.state === 'failed' ? '—' : '…' }
function kindGrams(k: SupportKind) { const j = kindJob(k); return j?.state === 'done' && j.estimate?.grams != null ? `${Math.round(j.estimate.grams)} g` : '' }
watch(() => open.value === 'supports', o => { if (o) void askKinds() })
watch(() => (open.value === 'supports' ? SUPPORT_KINDS.map(k => { const j = kindJob(k); return j ? `${j.id}:${j.state}` : '' }).join() : ''),
  key => { if (key) for (const k of SUPPORT_KINDS) void loadLines(kindJob(k)) })
const spoolNote = computed(() => {
  const s = spool.value
  if (!s) return ''
  if (s.slot == null && !s.color) return 'Not loaded yet'
  const live = usable.value.find(u => u.slot === s.slot)
  return [s.slot != null ? `Slot ${s.slot + 1}` : 'Loaded', live?.grams ? `${live.grams} g left` : ''].filter(Boolean).join(' · ')
})
const ready = computed(() => store.intent?.state === 'ready')
const sheetPick = computed(() => store.intent?.first_layer?.sheet ?? null)
const sheetNow = computed(() => sheetPick.value?.options.find((o) => o.name === sheetPick.value?.on))
const sheetOthers = computed(() => (sheetPick.value?.options ?? []).map((o) => o.name).filter(Boolean))
async function pickSheet(name: string) {
  open.value = null
  await store.act('first_layer_sheet', { name })
}
// Whether the spool is really loaded is the printer's own check (check_print), after the bed question.
const canPrint = computed(() => job.value?.state === 'done' && ready.value && !working.value && !unsortedColors.value.length)
const copies = computed(() => session.parts.reduce((a, p) => a + p.copies, 0))
// sliced on another machine (design/slicing-elsewhere/, A): who, and what a slice waits behind there
const slicer = computed(() => session.options?.slicer ?? null)
const waiting = computed(() => waitWords(job.value, slicer.value))
const footNote = computed(() => readyNote(baseNote.value, job.value?.state === 'done' ? slicer.value : null))
const baseNote = computed(() => {
  if (job.value?.state === 'failed') return 'Every setting says more'
  if (door.away) return 'Start it at the printer, where you can check the bed is clear.'
  if (!ready.value && store.intent) return `${printerName.value} is busy. Send it now and start it when it's free.`
  if (job.value?.state !== 'done') return 'Tap a row to change it'
  const first = unsortedColors.value[0]
  if (first != null) return `Pick a spool for ${colorWord(plateSpools.value[first]?.color)} first`
  if (colorsNow.value) return footColors(colorsNow.value, plateSpools.value.length)
  if (plates.value.length > 1) {
    const rest = plates.value.slice(1).reduce((a, p) => a + (p.seconds ?? 0), 0)
    return `Plate 1 of ${plates.value.length} · then about ${humanDuration(rest)}`
  }
  const secs = job.value.estimate?.seconds
  if (only.value && only.value.copies > 1 && secs) return `About ${humanDuration(secs / only.value.copies)} each`
  if (session.parts.length > 1) return `${copies.value} parts, one start`
  return 'Tap a row to change it'
})
const copiesNote = computed(() => {
  if (job.value?.state !== 'done') return 'Slicing…'
  const secs = job.value.estimate?.seconds
  if (only.value && only.value.copies > 1 && secs) return `${humanDuration(secs)} · about ${humanDuration(secs / only.value.copies)} each`
  return `${humanDuration(secs)} for the plate`
})
const sentNote = computed(() => {
  if (door.away) return `Start it at ${printerName.value}, where you can check the bed is clear.`
  const later = session.sentLater.length
  const as = prettyName(session.sent ?? '')
  return later ? `It's on ${printerName.value} as ${as}, with the ${later === 1 ? 'second plate' : `other ${later} plates`} for after.`
    : `It's on ${printerName.value} as ${as}.`
})
// the editable settings get their own groups above (design/edit-settings/, C), so they're never listed twice
const editable = computed(() => session.options?.editable ?? [])
const editKeys = computed(() => new Set(editable.value.map(e => e.key)))
const groups = computed(() => groupChanges((job.value?.changes ?? []).filter(c => !editKeys.value.has(c.key) && c.source !== 'you' && c.source !== 'kept'),
  purposeLabel.value, printerName.value))
const editGroups = computed(() => {
  const j = job.value
  if (!j?.values || !editable.value.length) return []
  const r = editRows(editable.value, j.values, j.before, j.changes ?? [], printerName.value)
  return [
    { title: `Your ${purposeLabel.value}`, rows: r.kept, mine: true, reset: true },
    { title: 'This print', rows: r.you, mine: true, reset: false },
    { title: 'You can change', rows: r.rest, mine: false, reset: false },
  ].filter(g => g.rows.length)
})
const hasKept = (p: string) => Object.keys(session.kept[p as Purpose] ?? {}).length > 0
const keptOf = (p: string) => editSummary(editable.value, session.kept[p as Purpose])
const keptHere = computed(() => hasKept(session.purpose))
const keptWords = computed(() => keptOf(session.purpose))
const changedWords = computed(() => editSummary(editable.value, session.settings))
// the sheet for one setting
const editKey = ref('')
const editScope = ref<'print' | 'keep'>('print')
const edited = computed(() => editable.value.find(e => e.key === editKey.value) ?? null)
const editSteps = computed(() => (edited.value?.kind === 'number' ? steps(edited.value, wanted(edited.value.key)) : null))
const purposeGives = computed(() => (edited.value ? job.value?.before?.[edited.value.key] ?? null : null))
let openedAt: number | null = null
function openEdit(key: string) {
  editKey.value = key
  editScope.value = isKept(key) ? 'keep' : 'print'
  openedAt = job.value?.estimate?.seconds ?? null
  open.value = 'edit'
}
function pickScope(s: 'print' | 'keep') {
  if (s === editScope.value) return
  editScope.value = s
  if (edited.value && wanted(edited.value.key) !== purposeGives.value) setScope(edited.value.key, s)
}
// what the change costs, against the plate as it was when the sheet opened
const priceDelta = computed(() => {
  const now = job.value?.state === 'done' ? job.value.estimate?.seconds : null
  if (now == null || openedAt == null) return ''
  const d = Math.round((now - openedAt) / 60)
  return d ? `${d > 0 ? '+' : '−'}${Math.abs(d)} min` : ''
})

function partName(p: Part) { return modelName(p.name) }

// ── several colors (design/multi-color/, B) ──
const hasProject = computed(() => session.parts.some(p => p.project))
const unitHere = computed(() => printer.value?.unit ?? (printer.value?.slots ?? 1) > 1)
const colorsNow = computed(() => (job.value?.state === 'done' ? job.value.colors ?? null : null))
const purgeChoices = computed<Purge[]>(() => printer.value?.purges ?? [])
const purgeNow = computed<Purge>(() => session.purge ?? purgeChoices.value[0] ?? 'tower')
const cost = computed(() => (colorsNow.value ? costLine(colorsNow.value, purgeNow.value, unitHere.value) : null))
const many = computed(() => tooMany(colorsNow.value))
function partColor(p: Part) { return plateSpools.value[p.spool]?.color || colour.value }
function ownRuns(p: Part) { let end = 0; return partRuns(p).map(r => ({ end: (end += r.count), color: r.color })) }
function fileDots(p: Part) { return (p.project?.colors ?? []).filter(c => c.used).map((c, k) => plateSpools.value[k]?.color || c.color || '#8A8D91') }
const handOf = (s: PlateSpool | undefined, k: number) => !!s && k > 0 && (s.hand || !unitHere.value || s.slot == null)
function colorName(s: PlateSpool | undefined, k: number) {
  if (!s) return ''
  if (unsortedColors.value.includes(k)) return `${colorWord(s.color)} isn't loaded`
  return s.hand || !unitHere.value && k > 0 ? `${colorWord(s.color)} ${s.material}` : s.name
}
function usesOf(k: number) {
  if (hasProject.value) return ''
  const names = session.parts.filter(p => p.spool === k).map(partName)
  const hs = session.heights
  const bits: string[] = []
  if (names.length) bits.push(hs.length && session.parts.length === 1 ? `up to ${mm(hs[0].z)}` : names.length > 2 ? `${names.length} parts` : names.join(', '))
  for (const h of hs) if (h.spool === k) bits.push(`from ${mm(h.z)} up`)
  const painted = session.parts.filter(p => paintUses(p.paint).has(k)).map(partName)
  if (painted.length) bits.push(`painted on ${painted.length > 2 ? `${painted.length} parts` : painted.join(', ')}`)
  return bits.join(', ')
}

// ── painting and a change at a height (design/paint-and-height/, height C with A, painting A) ──
/** What a height or a paint can use: the plate's colors, then the spools loaded in the unit that aren't one yet. */
const trayChoices = computed<PlateSpool[]>(() => [...plateSpools.value, ...offPlate.value.map(loaded)])
const layer = computed(() => {
  const v = current.value?.values ?? {}
  const first = parseFloat(v.initial_layer_print_height ?? ''), height = parseFloat(v.layer_height ?? '')
  return { first: first > 0 ? first : 0.2, height: height > 0 ? height : 0.2 }
})
// the spotted flat top's one-tap answers: loaded spools other than the part's own, two at most
const offerSpools = computed(() => {
  const own = plateSpools.value[session.parts[0]?.spool ?? 0]
  return usable.value.map(loaded).filter(s => !own || s.color !== own.color || s.material !== own.material).slice(0, 2)
})
const heightOpen = ref(false)
const heightAt = ref(-1)
const heightStart = ref<number | null>(null)
const heightToast = ref('')
let heightBefore: { heights: typeof session.heights; more: PlateSpool[] } | null = null
let toastTimer = 0
function openHeight(at: number, z?: number) { heightAt.value = at; heightStart.value = z ?? null; heightOpen.value = true }
function remember() { heightBefore = { heights: [...session.heights], more: [...session.more] } }
function addHeight(z: number, s: PlateSpool, at: number) { remember(); setHeight(z, s, at); heightOpen.value = false }
function dropHeight(at: number) { remember(); removeHeight(at); heightOpen.value = false }
function takeOffer(s: PlateSpool) {
  if (!spotted.value) return
  const raised = spotted.value.raised
  remember()
  setHeight(spotted.value.z, s)
  heightToast.value = `${raised ? 'The raised parts' : "What's above the base"} print${raised ? '' : 's'} in ${colorWord(s.color).toLowerCase()}.`
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { heightToast.value = '' }, 6000)
}
function undoHeight() {
  if (heightBefore) { restoreHeights(heightBefore.heights, heightBefore.more); heightBefore = null }
  heightToast.value = ''
}
const paintAt = ref(-1)
const painting = computed(() => session.parts[paintAt.value] ?? null)
function openPaint(i: number) { open.value = null; paintAt.value = i }
function paintDone(states: Uint8Array, palette: PlateSpool[]) { setPaint(paintAt.value, states, palette); paintAt.value = -1 }
function lineOf(s: PlateSpool | undefined, k: number) {
  return s ? spoolLine(s, k, colorsNow.value, unitHere.value, usesOf(k)) : { text: '', amber: false }
}
function gramsFor(k: number) {
  const g = colorsNow.value?.grams?.[k]
  return g == null ? '' : `${g < 1 ? g.toFixed(1) : Math.round(g)} g`
}
// a spool loaded in the unit, not one of the plate's colors yet: a part can take it
const offPlate = computed(() => (unitHere.value ? usable.value.filter(u => !u.direct && !plateSpools.value.some(s => !s.hand && s.slot === u.slot)) : []))
const colorK = ref(0)
const colorAt = computed(() => (plateSpools.value[colorK.value] ? { k: colorK.value, s: plateSpools.value[colorK.value] } : null))
const colorTitle = computed(() => {
  const c = colorAt.value
  if (!c) return ''
  const uses = usesOf(c.k)
  return `${colorWord(c.s.color)}${uses ? `, for ${uses}` : ''}`
})
const colorSub = computed(() => {
  const c = colorAt.value
  if (!c) return ''
  const g = gramsFor(c.k)
  if (unsortedColors.value.includes(c.k)) return `${printerName.value} has no ${colorWord(c.s.color).toLowerCase()} spool.${g ? ` ${g}.` : ''}`
  return 'Where this color comes from. Every part in it follows.'
})
const emptySlots = computed(() => ((store.intent?.spools ?? []) as IntentSpool[]).filter(s => s.status === 'empty' && !s.direct).map(s => s.slot))
const loadSlot = computed(() => (unitHere.value && colorAt.value && unsortedColors.value.includes(colorAt.value.k) ? emptySlots.value[0] ?? null : null))
const handLine = computed(() => {
  const at = colorAt.value ? colorsNow.value?.spools[colorAt.value.k]?.swaps ?? [] : []
  return at.length ? `The print waits at about ${at.length > 1 ? `${Math.round(at[0] / 60)} min, ${at.length} times` : `${Math.round(at[0] / 60)} min`} and asks for it. Resume carries on.`
    : 'The print waits and asks for it. Resume carries on.'
})
function otherMaterial(s: IntentSpool) { const c = colorAt.value; return !!c && !!s.material && s.material.toUpperCase() !== c.s.material }
function openColor(k: number) { colorK.value = k; open.value = 'color' }
function loaded(s: IntentSpool): PlateSpool {
  return { slot: s.direct ? null : s.slot, material: (s.material ?? 'PLA').toUpperCase(), color: s.color, name: s.name || s.material || '', hand: false }
}
function pickPartSpool(s: PlateSpool) { setPartSpool(editAt.value, s); open.value = null }
function pickLoaded(s: IntentSpool, to: 'part' | 'color') {
  if (to === 'part') setPartSpool(editAt.value, loaded(s))
  else setPlateSpool(colorK.value, loaded(s))
  open.value = null
}
function pickHand(hex: string | null, to: 'part' | 'color') {
  const material = (to === 'color' ? colorAt.value?.s.material : plateSpools.value[0]?.material) ?? 'PLA'
  const s: PlateSpool = { slot: null, material, color: hex, name: `${colorWord(hex)} ${material}`, hand: true }
  if (to === 'part') setPartSpool(editAt.value, s)
  else setPlateSpool(colorK.value, s)
  open.value = null
}
function pickLoad() {
  const c = colorAt.value, n = loadSlot.value
  if (!c || n == null) return
  setPlateSpool(c.k, { slot: n, material: c.s.material, color: c.s.color, name: `${colorWord(c.s.color)} ${c.s.material}`, hand: false })
  open.value = null
}
function pct(k: number) { return `${Math.round(k * 100)}%` }
function sizeAt(p: Part, k: number) {
  const s = p.size
  return s ? s.map(v => Math.round(v * k)).join(' × ') + ' mm' : ''
}
function sizesOf(p: Part) { return [...new Set([p.fit, 0.75, 0.5].filter(k => k <= p.fit))] }
function tooBigText(p: Part) { return p.size && printer.value?.bed ? tooBigWords(p.size, printer.value.bed, printerName.value) : '' }
/** The line under a part's name: what's worth knowing about it, most important first. */
function subOf(p: Part, i: number): { text: string; amber?: boolean } {
  const first = plates.value.length > 1 ? plates.value[0].counts[i] : undefined
  if (first != null && first < p.copies) return { text: first ? `${first} now, ${p.copies - first} after` : 'On the second plate', amber: true }
  const brim = brimOf(i)
  const and = (t: string, short: string) => ({ text: brim ? `${short} · ${BRIM_WORDS[brim.kind].short}` : t })
  if (p.lay === 'flat' && p.layAuto) return and('Laid flat for you', 'Laid flat')
  if (p.lay === 'side') return and('On the side you picked', 'On the side you picked')
  if (p.scale < 1) return and(`At ${pct(p.scale)} to fit`, `At ${pct(p.scale)}`)
  const plain = sizeAt(p, p.scale) || 'As in the file'
  return and(plain, plain)
}
// Brims (design/brim/, A): the slicer picks one per part and says why; the slice for this plate carries them
const BRIM_KINDS: BrimKind[] = ['all', 'ears', 'none']
function brimOf(i: number) {
  const j = job.value, parts = j?.state === 'done' ? j.parts : null
  if (!parts || parts.length !== session.parts.length) return null
  return parts[i]?.brim_pick ?? null
}
const editPrint = computed(() => {
  const f = editing.value?.tris ? footprint(editing.value.tris, editing.value.scale) : null
  return f ? markRaw(f) : null
})
const editArea = computed(() => (editPrint.value ? roomFor(editPrint.value) : undefined))
const brimRule = computed(() => brimOf(editAt.value)?.rule ?? null)
const brimRow = computed<{ value: string; note: string; kind: BrimKind | null }>(() => {
  const p = editing.value, pick = brimOf(editAt.value)
  if (!p) return { value: '', note: '', kind: null }
  if (pick) return { value: BRIM_WORDS[pick.kind].label, note: pick.why, kind: pick.kind === 'auto' ? null : pick.kind }
  if (p.brim !== 'auto') return { value: BRIM_WORDS[p.brim].label, note: 'Slicing…', kind: p.brim }
  return { value: 'Working it out…', note: '', kind: null }
})
const brimSub = computed(() => {
  const p = editing.value
  if (!p) return ''
  return `${p.copies > 1 ? 'Every copy of it gets the same. ' : ''}Drawn from what touches the plate; sliced once you pick.`
})
// a rounded part has no corners sharp enough for a pad: say so rather than show a picture the same as None
function cardLine(k: BrimKind) {
  return k === 'ears' && editPrint.value && !editPrint.value.corners.length ? 'It has no sharp corners, so this is close to none.' : BRIM_WORDS[k].line
}
function pickBrim(k: BrimKind) {
  // the rule's own pick hands the part back to the rule, so it follows a change of side or size
  setBrim(editAt.value, k === brimRule.value ? 'auto' : k)
  open.value = null
}
function timeOf(p: string) {
  const j = session.jobs[p as Purpose]
  return j?.state === 'done' ? humanDuration(total(j)) : j?.state === 'failed' ? '—' : '…'
}
function gramsOf(p: string) {
  const j = session.jobs[p as Purpose]
  return j?.state === 'done' && j.estimate?.grams != null ? `${Math.round(j.estimate.grams)} g` : ''
}
const colourWord = colorWord

function openPart(i: number) {
  editAt.value = i
  open.value = 'part'
  void askFill(i)
}
function takeOff() { open.value = null; removePart(editAt.value); editAt.value = 0 }
function pickPurpose(p: string) { setPurpose(p as Purpose); open.value = null }
function pickSide(n: number[] | null) { setSide(editAt.value, n); open.value = null }

/** The Lying row: which side is down, and why. */
function lyingWords(p: Part): { value: string; note: string } {
  const l = p.lying
  if (p.lay === 'side') {
    const s = l?.sides?.find(x => sameSide(x.normal, p.down))
    return { value: 'The side you picked', note: s ? `Touches ${area(s.contact)} · ${Math.round(s.size[2])} mm tall` : '' }
  }
  if (p.lay === 'flat') return { value: 'Its flattest side', note: p.layAuto ? `Laid flat for you: it touched ${area(l?.down_area ?? 0)} in the file` : `Touches ${area(l?.flat_area ?? 0)}` }
  return { value: 'As in the file', note: l?.flat_better ? 'A flatter side faces away' : 'It sits on its flattest side' }
}
// Every side it can rest on, flattest first, each drawn lying that way (slice/sides.ts, SidePicks)
const sideOptions = computed(() => {
  const p = editing.value
  return p?.trisFile ? sideOptions_(p.lying, downOf(p)) : []
})
function pickSupports(k: SupportKind) { if (k !== session.supports) setSupports(k); open.value = null }
function pickScale(k: number) { setScale(editAt.value, k); open.value = null }
function pickSpool(s: IntentSpool) {
  setSpool({ slot: s.direct ? null : s.slot, material: (s.material ?? 'PLA').toUpperCase(), color: s.color, name: s.name || s.material || '' })
  open.value = null
}
function pickMaterial(m: string) { setSpool({ slot: null, material: m, color: null, name: m }); open.value = null }

async function add(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  addError.value = ''
  try { await addFiles(files) } catch (err) { addError.value = err instanceof Error ? err.message : String(err) }
}

async function sendOnly() {
  working.value = true
  actionError.value = ''
  try { await send() } catch (e) { actionError.value = e instanceof Error ? e.message : String(e) } finally { working.value = false }
}

async function printNow() {
  working.value = true
  actionError.value = ''
  try {
    const filename = await send()
    const check = await store.requestPrint(filename)
    open.value = null
    if (!needsSheet(check)) router.push('/')
    else refusal.value = check
  } catch (e) {
    open.value = null
    actionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    working.value = false
  }
}

// the picker (design/remove-parts/, C): one file's parts, on the plate or waiting beside it, in the file's order
const pickParts = computed(() => {
  const from = session.picking?.from
  return from ? [...session.parts, ...session.left].filter(p => p.from === from).sort((a, b) => a.order - b.order) : []
})
const picked = ref(new Set<number>())
watch(() => session.picking, pk => { if (pk) picked.value = new Set(session.parts.filter(p => p.from === pk.from).map(p => p.key)) }, { immediate: true })
function togglePick(key: number) { const s = new Set(picked.value); if (s.has(key)) s.delete(key); else s.add(key); picked.value = s }
function tickAll() { picked.value = picked.value.size === pickParts.value.length ? new Set() : new Set(pickParts.value.map(p => p.key)) }
const pickLabel = computed(() => {
  const all = picked.value.size === pickParts.value.length, n = all ? `all ${pickParts.value.length}` : `these ${picked.value.size}`
  return session.picking?.first ? `Print ${n}` : `Use ${n}`
})
function confirmPick() { if (session.picking) pick(session.picking.from, picked.value) }
const fromFiles = computed(() => fileCounts(session.parts, session.left))
// a part taken off can come back for a few seconds
let undoTimer = 0
watch(() => session.undo, u => { clearTimeout(undoTimer); if (u) undoTimer = window.setTimeout(() => { if (session.undo === u) session.undo = null }, 6000) })

function back() {
  if (view.value === 'settings') return router.back()
  if (session.picking && !session.picking.first) return closePicker()
  if (!session.sent) reset()          // nothing kept: stop the slicer working on it
  router.push('/print')
}

// The printer's spools can arrive after the model was picked (a slow connection): follow them until
// the person picks one.
watch(() => [JSON.stringify(store.intent?.spools ?? []), session.stage], () => followSpools((store.intent?.spools ?? []) as IntentSpool[]), { immediate: true })

// Opened without a model (a reload, a shared link): nothing to show here.
onMounted(() => { if (session.stage === 'idle') router.replace('/print') })

const ICONS: Record<string, string> = {
  draft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/></svg>',
  everyday: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/></svg>',
  display: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  strong: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9v6M6 6.5v11M18 6.5v11M21 9v6M6 12h12"/></svg>',
}
</script>

<style scoped>
.model { flex: 1; overflow: auto; padding: 8px 20px 24px; max-width: 560px; width: 100%; margin: 0 auto; }
.bar { display: flex; align-items: center; gap: 10px; height: 44px; margin-bottom: 10px; }
.back { appearance: none; border: 0; cursor: pointer; width: 36px; height: 36px; border-radius: 50%; background: var(--a-surface); color: var(--a-ink); display: grid; place-items: center; box-shadow: var(--a-card-shadow); flex: none; }
.back svg { width: 18px; height: 18px; }
.back:focus-visible, .row:focus-visible, .every:focus-visible, .send:focus-visible, .opt:focus-visible, .chip:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.file { font-size: 13.5px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-title { font-size: 17px; }

.pic { width: 100%; aspect-ratio: 16 / 9; }
.picnote { position: absolute; left: 10px; bottom: 10px; background: color-mix(in srgb, var(--a-surface) 92%, transparent); border-radius: 99px; padding: 6px 12px; font-size: 13px; font-weight: 600; color: var(--a-ink-2); box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12); }
.opt.lay { padding: 10px 12px 10px 10px; }
.opt .tile { width: 104px; height: 78px; border-radius: 12px; flex: none; }
.opt .tile.fpt { width: 84px; height: 84px; }
.row .mini { width: 44px; height: 44px; border-radius: 10px; flex: none; }
.head { font-size: 28px; letter-spacing: -0.025em; line-height: 1.1; margin: 16px 0 12px; text-wrap: balance; }
.sub { color: var(--a-ink-2); font-size: 16px; margin: 0 0 16px; }

.warn { background: color-mix(in srgb, var(--a-amber) 30%, var(--a-surface)); border-radius: 16px; padding: 13px 15px; display: grid; gap: 3px; margin-bottom: 12px; }
.warn b { font-size: 17px; }
.warn span { font-size: 14.5px; color: var(--a-ink-2); line-height: 1.35; }

.rows { display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); }
.row { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px; background: var(--a-surface); padding: 13px 14px 13px 16px; min-height: 60px; }
.row:active { filter: brightness(0.97); }
.row .k { width: 74px; flex: none; font-size: 14px; color: var(--a-ink-3); font-weight: 600; }
.row .v { flex: 1; min-width: 0; display: grid; gap: 2px; font-size: 17px; font-weight: 600; }
.row .v small { font-size: 13px; font-weight: 500; color: var(--a-ink-3); line-height: 1.3; }
.one { display: flex; align-items: center; gap: 8px; }
.dot { display: inline-block; width: 18px; height: 18px; border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); flex: none; box-sizing: border-box; vertical-align: -3px; }
.dot.big { width: 34px; height: 34px; border-width: 3px; }
.chev { width: 22px; height: 22px; color: var(--a-ink-3); flex: none; }
.every { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; padding: 10px 2px 0; font-size: 14.5px; color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; }

.foot { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.foot .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.foot .t b { font-size: 21px; letter-spacing: -0.02em; }
.foot .t span { font-size: 13.5px; color: var(--a-ink-3); line-height: 1.3; overflow-wrap: anywhere; }
.foot .a-btn { height: 54px; font-size: 19px; border-radius: 18px; padding: 0 26px; flex: none; }
.foot.sent .t b { color: var(--a-green-text); }
.send { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; display: block; width: 100%; text-align: center; margin-top: 12px; padding: 8px; font-size: 15px; font-weight: 600; color: var(--a-ink-2); }
.send[disabled] { opacity: 0.4; cursor: default; }
.bad { color: var(--a-red-text); }
.bad.small { font-size: 14px; margin: 8px 0 0; }
.spin { width: 18px; height: 18px; border-radius: 50%; border: 3px solid var(--a-surface-2); border-top-color: var(--a-accent); display: inline-block; vertical-align: -3px; margin-right: 8px; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.problem { padding-top: 20px; }
.problem-acts { display: flex; flex-wrap: wrap; gap: 12px; }

/* sheets */
.opts { display: grid; gap: 9px; }
.opt { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 14px; background: var(--a-surface); border-radius: 18px; padding: 13px 14px; border: 2px solid transparent; box-shadow: var(--a-card-shadow); }
.opt.on { border-color: var(--a-accent); }
.opt .ic { width: 42px; height: 42px; border-radius: 13px; background: var(--a-surface-2); display: grid; place-items: center; flex: none; color: var(--a-ink-2); }
.opt .ic :deep(svg) { width: 24px; height: 24px; }
.opt .t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.opt .t b { font-size: 18px; }
.opt .t span { font-size: 13.5px; color: var(--a-ink-3); line-height: 1.3; }
.opt .tm { text-align: right; display: grid; gap: 1px; flex: none; }
.opt .tm b { font-size: 17px; }
.opt .tm span { font-size: 13px; color: var(--a-ink-3); }
.sub2 { color: var(--a-ink-3); font-size: 13.5px; margin: 16px 0 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { appearance: none; font: inherit; font-weight: 700; cursor: pointer; font-size: 15px; letter-spacing: 0.03em; padding: 0 16px; height: 42px; border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2); }
.chip.on { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }

/* every setting */
.settings .lead { font-size: 15px; color: var(--a-ink-2); margin: 2px 0 0; line-height: 1.4; }
.settings .detail { font-size: 13px; color: var(--a-ink-3); }
.grp { font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--a-ink-3); margin: 16px 0 7px; }
.chg { display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; }
.chg-row { background: var(--a-surface); padding: 11px 16px; display: grid; gap: 2px; }
.chg-row .l { display: flex; align-items: baseline; gap: 8px; font-size: 16px; font-weight: 600; }
.chg-row .l .v { margin-left: auto; white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
.chg-row .l .v s { color: var(--a-ink-3); font-weight: 500; text-decoration: none; }
.chg-row .w { font-size: 13.5px; color: var(--a-ink-3); line-height: 1.3; }
.chg-row code { font: 600 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--a-ink-3); background: none; padding: 0; }
.every.names { margin-top: 14px; color: var(--a-ink-3); }
.fromrow { display: flex; align-items: baseline; gap: 8px; margin: 9px 2px 0; font-size: 14px; color: var(--a-ink-3); }
.fromrow .every { padding: 0; margin-left: auto; font-size: 14px; }
.toast { display: flex; align-items: center; gap: 12px; background: #1f2430; color: #fff; border-radius: 14px; padding: 12px 16px; margin-bottom: 10px; font-size: 14.5px; box-shadow: 0 10px 30px rgba(0,0,0,.25); }
.toast span { flex: 1; min-width: 0; }
.toast button { appearance: none; border: 0; background: none; font: inherit; font-weight: 700; color: #8cc4ff; cursor: pointer; padding: 4px 2px; }
.toast button:focus-visible { outline: 2px solid #8cc4ff; outline-offset: 2px; border-radius: 6px; }
.picker { padding-bottom: 96px; }
.picker .head { margin-top: 4px; }
.pick-sub { color: var(--a-ink-3); font-size: 15px; margin: 4px 0 14px; }
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 9px; }
.ptile { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; position: relative; padding: 0; background: var(--a-surface); border-radius: 14px; overflow: hidden; border: 2px solid transparent; box-shadow: var(--a-card-shadow); display: grid; }
.ptile.on { border-color: var(--a-accent); }
.ptile:not(.on) { opacity: 0.55; }
.ptile:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.ptile-pic { width: 100%; aspect-ratio: 4 / 3; height: auto; border-radius: 0; }
.ptile .ck { position: absolute; top: 6px; right: 6px; width: 22px; height: 22px; border-radius: 7px; border: 2px solid var(--a-ink-3); background: var(--a-surface); display: grid; place-items: center; }
.ptile.on .ck { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }
.ptile .ck svg { width: 13px; height: 13px; }
.ptile .n { padding: 5px 8px 8px; font-size: 12.5px; font-weight: 600; line-height: 1.2; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; min-height: 52px; }
.pickbar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px; margin-top: 14px; padding: 12px 0 calc(12px + env(safe-area-inset-bottom, 0px)); background: var(--a-bg); }
.pickbar .t { flex: 1; display: grid; gap: 1px; font-size: 14px; }
.pickbar .t b { font-size: 17px; }
.pickbar .every { padding: 0; text-align: left; font-size: 14px; }
.pickbar .a-btn { height: 52px; padding: 0 22px; font-size: 17px; border-radius: 16px; }
.usual { margin: 10px 2px 0; font-size: 14.5px; color: var(--a-ink-3); }
.usual .every { padding: 0; }
.chg-row.ed { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; grid-template-columns: minmax(0, 1fr) auto; column-gap: 8px; align-items: center; }
.chg-row.ed > .l, .chg-row.ed > .w { grid-column: 1; }
.chg-row.ed .chev { grid-column: 2; grid-row: 1 / span 2; width: 18px; height: 18px; color: var(--a-ink-3); }
.chg-row.ed:disabled { cursor: default; }
.chg-row.ed:focus-visible { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.chg-row.you { background: color-mix(in srgb, var(--a-amber) 14%, var(--a-surface)); }
.chg-row.you .l .v { color: var(--a-amber-text); }
.grp-reset { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; float: right; letter-spacing: 0; text-transform: none; font-size: 12.5px; font-weight: 600; color: var(--a-accent-text); padding: 0; }
.opt .t b .tag.mine { color: var(--a-amber-text); }
.edit-step { display: flex; justify-content: center; margin: 4px 0 2px; }
.edit-price { display: flex; justify-content: center; gap: 8px; font-size: 15px; color: var(--a-ink-2); margin: 10px 0 0; }
.edit-price b { color: var(--a-ink); }
.edit-price .d { color: var(--a-amber-text); font-weight: 700; }
.edit-was { text-align: center; font-size: 13.5px; color: var(--a-ink-3); margin: 4px 0 0; }
.edit-was .every { padding: 0; font-size: 13.5px; }
.scope { display: grid; gap: 8px; margin-top: 16px; }
.scope button { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px; background: var(--a-surface); border-radius: 16px; padding: 12px 14px; border: 2px solid transparent; box-shadow: var(--a-card-shadow); }
.scope button.on { border-color: var(--a-accent); }
.scope button:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.scope .rd { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--a-ink-3); flex: none; display: grid; place-items: center; }
.scope .on .rd { border-color: var(--a-accent); }
.scope .on .rd::after { content: ''; width: 11px; height: 11px; border-radius: 50%; background: var(--a-accent); }
.scope .t { display: grid; gap: 1px; }
.scope .t b { font-size: 16px; }
.scope .t span { font-size: 13px; color: var(--a-ink-3); }
.edit-done { margin-top: 14px; height: 52px; padding: 0 28px; font-size: 18px; border-radius: 16px; }
.warnline { font-size: 14px; color: var(--a-amber-text); margin: 12px 2px 0; }

/* the plate as the stage on a wide pane (design/ready-wide/, A + C) */
.model.stage { max-width: none; padding: 0; position: relative; overflow: hidden; height: 100%; }
.stagepic { position: absolute; inset: 0; }
.stagepic .fill { position: absolute; inset: 0; border-radius: 0; width: auto; height: auto; aspect-ratio: auto; }
.zoom { position: absolute; left: 20px; top: 16px; display: grid; gap: 6px; }
.zoom button { appearance: none; border: 0; font: inherit; cursor: pointer; width: 40px; height: 40px; border-radius: 12px; background: color-mix(in srgb, var(--a-surface) 92%, transparent); color: var(--a-ink-2); font-size: 20px; font-weight: 600; box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12); }
.zoom button.fit { width: auto; padding: 0 12px; font-size: 13.5px; }
.zoom button:focus-visible, .hide:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.hint { position: absolute; left: 20px; bottom: 18px; background: color-mix(in srgb, var(--a-surface) 92%, transparent); border-radius: 99px; padding: 6px 12px; font-size: 13px; font-weight: 600; color: var(--a-ink-2); box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12); }
.stage .card { position: absolute; right: 20px; top: 12px; bottom: 20px; width: 400px; overflow: auto; padding: 14px 18px 18px;
  background: color-mix(in srgb, var(--a-bg) 88%, transparent); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-radius: 24px; box-shadow: 0 12px 40px rgba(16, 24, 40, 0.18); }
.stage.collapsed .card { display: none; }
.stage .card .dock { bottom: -18px; margin: 0 -18px -18px; padding: 14px 18px 18px; background: linear-gradient(transparent, var(--a-bg) 16px); }
.hide { appearance: none; border: 0; cursor: pointer; margin-left: auto; width: 34px; height: 34px; border-radius: 50%; background: var(--a-surface); color: var(--a-ink-2); display: grid; place-items: center; box-shadow: var(--a-card-shadow); flex: none; }
.hide svg { width: 18px; height: 18px; }
.minibar { position: absolute; right: 20px; bottom: 20px; display: flex; align-items: center; gap: 12px; padding: 10px 10px 10px 18px;
  background: color-mix(in srgb, var(--a-bg) 88%, transparent); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-radius: 20px; box-shadow: 0 12px 40px rgba(16, 24, 40, 0.18); max-width: calc(100% - 40px); }
.minibar .t { display: grid; gap: 1px; min-width: 0; }
.minibar .t b { font-size: 19px; letter-spacing: -0.02em; }
.minibar .t span { font-size: 13px; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.minibar .a-btn { height: 46px; border-radius: 14px; font-size: 16px; padding: 0 20px; flex: none; }

/* the plate as a list (design/plate/, A) */
.plist { display: grid; gap: 1px; background: var(--a-line); border-radius: 18px; overflow: hidden; box-shadow: var(--a-card-shadow); margin-top: 2px; }
.pl { display: flex; align-items: center; gap: 10px; background: var(--a-surface); padding: 8px 10px 8px 8px; min-height: 62px; }
.pl-open { appearance: none; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 0; }
.pl-open:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; border-radius: 12px; }
.thumb { width: 46px; height: 46px; border-radius: 12px; flex: none; }
.pl .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.pl .t b { font-size: 16.5px; line-height: 1.2; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.pl .t span { font-size: 13px; color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pl .t span.you { color: var(--a-amber-text); font-weight: 600; }
.addl { position: relative; display: flex; align-items: center; gap: 12px; background: var(--a-surface); padding: 12px 14px 12px 18px; color: var(--a-accent-text); font-weight: 600; font-size: 16px; cursor: pointer; }
.addl svg { width: 22px; height: 22px; }
.addl.busy { color: var(--a-ink-3); cursor: default; }
.addl:focus-within { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.warn .inline { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; padding: 4px 0 0; justify-self: start; font-size: 14.5px; font-weight: 600; color: var(--a-ink); text-decoration: underline; text-underline-offset: 3px; }
.dock { position: sticky; bottom: -24px; margin: 0 -20px -24px; padding: 14px 20px 18px; background: linear-gradient(transparent, var(--a-bg) 18px); z-index: 2; }
.dock .foot { margin-top: 0; }
.dock .send { margin-top: 6px; padding: 4px; }
.row.still { cursor: default; }
.howmany { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 4px 0 12px; }
.howmany .t { display: grid; gap: 2px; }
.howmany .t b { font-size: 18px; }
.howmany .t span { font-size: 13.5px; color: var(--a-ink-3); }
.chips.qty { margin-bottom: 16px; }
.chips.qty .chip { height: 38px; padding: 0 14px; }
.chip[disabled] { opacity: 0.5; cursor: default; }
.opt .t b .tag { white-space: nowrap; display: inline-block; font-style: normal; font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-accent-text); margin-left: 8px; vertical-align: 2px; }
/* several colors (design/multi-color/, B) */
.grp-n { float: right; letter-spacing: 0; text-transform: none; font-size: 13.5px; font-weight: 600; color: var(--a-accent-text); }
.ccard { background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); overflow: hidden; }
.cr { appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; width: 100%; display: flex; align-items: center; gap: 11px; padding: 10px 12px; }
.cr:first-child { border-top: 0; }
.cr:focus-visible { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.cr .t { flex: 1; min-width: 0; display: grid; gap: 1px; }
.cr .t b { font-size: 16px; }
.cr .t span { font-size: 13px; color: var(--a-ink-3); line-height: 1.3; }
.cr .t span.you { color: var(--a-amber-text); font-weight: 600; }
.cr .g { font-size: 13px; color: var(--a-ink-3); flex: none; }
.hacts { display: flex; align-items: baseline; gap: 14px; margin-top: 14px; font-size: 14px; color: var(--a-ink-3); }
.hacts span { flex: 1; }
.hacts .every { padding: 0; font-size: 14px; }
.addrow { appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; font: inherit; cursor: pointer; width: 100%; display: flex; align-items: center; gap: 11px; padding: 12px 12px; color: var(--a-accent-text); font-size: 15px; font-weight: 600; text-align: left; }
.addrow i { width: 34px; height: 34px; border-radius: 50%; border: 2px dashed currentColor; display: grid; place-items: center; font-style: normal; font-size: 18px; flex: none; box-sizing: border-box; }
.addrow:focus-visible { outline: 2px solid var(--a-accent); outline-offset: -2px; }
/* Bench spots it (design/paint-and-height/, C) */
.offer { margin-top: 12px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); border-left: 5px solid var(--a-accent); padding: 13px 14px 12px; display: grid; gap: 9px; }
.offer .h { font-size: 16.5px; }
.offer p { margin: 0; font-size: 13.5px; color: var(--a-ink-2); line-height: 1.35; }
.offer .choices { display: flex; flex-wrap: wrap; gap: 7px; }
.offer .choice { appearance: none; font: inherit; cursor: pointer; display: inline-flex; align-items: center; gap: 7px; height: 38px; padding: 0 13px 0 7px; border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-surface); font-weight: 600; font-size: 15px; color: var(--a-ink); }
.offer .choice .dot { width: 22px; height: 22px; }
.offer .choice.plain { padding: 0 13px; }
.offer .choice:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.offer-foot { display: flex; justify-content: space-between; }
.offer-foot .every { padding: 2px 0 0; font-size: 14px; }
.every.quiet { color: var(--a-ink-3); }
.pictool { position: absolute; top: 10px; right: 10px; appearance: none; border: 0; font: inherit; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 13px 0 10px; border-radius: 99px; background: var(--a-surface); box-shadow: var(--a-card-shadow); font-size: 14px; font-weight: 600; color: var(--a-ink); }
.pictool svg { width: 18px; height: 18px; }
.pictool:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.cr .tag, .opt .t b .tag { white-space: nowrap; display: inline-block; font-style: normal; font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-accent-text); margin-left: 8px; vertical-align: 2px; }
.dot.big.hand { border: 3px dashed var(--a-ink-2); }
.dot.big.miss { border: 3px dashed var(--a-amber); }
.dot.sm { width: 12px; height: 12px; border-width: 1.5px; vertical-align: -1px; margin-right: 5px; }
.pl .t .pcol { display: flex; align-items: center; gap: 0; }
.dots { display: inline-flex; padding-left: 5px; margin-right: 6px; }
.dots i { width: 14px; height: 14px; border-radius: 50%; background: var(--c); margin-left: -5px; border: 2px solid var(--a-surface); box-shadow: 0 0 0 1px var(--a-swatch-edge); }
.cost { border-top: 1px solid var(--a-line); padding: 11px 14px 13px; display: grid; gap: 9px; background: color-mix(in srgb, var(--a-surface-2) 35%, var(--a-surface)); }
.cost p { margin: 0; font-size: 14px; color: var(--a-ink-2); line-height: 1.35; }
.cost p b { color: var(--a-ink); }
.cost .aside { font-size: 13px; color: var(--a-ink-3); }
.cost .aside .every { padding: 0; font-size: 13px; }
.seg { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; background: var(--a-surface-2); border-radius: 12px; padding: 3px; gap: 3px; }
.seg button { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 4px; border-radius: 9px; color: var(--a-ink-2); }
.seg button.on { background: var(--a-surface); color: var(--a-ink); box-shadow: 0 1px 3px rgba(16, 24, 40, 0.14); }
.seg button:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 1px; }
.toomany { background: color-mix(in srgb, var(--a-amber) 22%, var(--a-surface)); border-radius: 12px; padding: 10px 12px; display: grid; gap: 8px; }
.toomany p { color: var(--a-amber-text); }
.toomany .acts { display: flex; flex-wrap: wrap; gap: 8px; }
.toomany .a-btn { height: 38px; font-size: 14.5px; padding: 0 14px; border-radius: 12px; }
.swatches { gap: 10px; }
.sw { appearance: none; cursor: pointer; width: 38px; height: 38px; border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); padding: 0; }
.sw.on { box-shadow: 0 0 0 3px var(--a-accent); }
.sw:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.takeoff { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; padding: 16px 2px 2px; font-size: 16px; font-weight: 600; color: var(--a-red-text); }
</style>
