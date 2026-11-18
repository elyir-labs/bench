// What the head-switch drawing shows (design/filament-units/, A): each switch lit, dark or red, and how far down
// the filament reaches.
import type { IntentHeadSwitches } from '../../intent/types.ts'

export type SwitchLook = 'lit' | 'dark' | 'bad'

export interface HeadSwitchesLook {
  extruder: SwitchLook
  /** null: the printer has no hotend switch, so none is drawn */
  hotend: SwitchLook | null
  reach: 'none' | 'extruder' | 'hotend'
  gears: 'in' | 'out' | null
  label: string
}

export function headSwitchesLook(h: IntentHeadSwitches): HeadSwitchesLook {
  const look = (on: boolean | null, which: 'extruder' | 'hotend'): SwitchLook =>
    h.failed === which ? 'bad' : on ? 'lit' : 'dark'
  const two = h.hotend_switch !== false
  const reach = two && h.hotend ? 'hotend' : h.extruder ? 'extruder' : 'none'
  const said = { none: 'No filament in the head', extruder: 'Filament at the extruder', hotend: 'Filament through the extruder' }[reach]
  const stopped = h.failed === 'hotend' ? '; it stopped at the gears' : h.failed === 'extruder' ? "; it didn't reach the extruder" : ''
  const turning = h.gears === 'in' ? '; the gears are pulling it in' : h.gears === 'out' ? '; the gears are backing it out' : ''
  return {
    extruder: look(h.extruder, 'extruder'), hotend: two ? look(h.hotend, 'hotend') : null, reach, gears: h.gears ?? null,
    label: said + stopped + turning,
  }
}
