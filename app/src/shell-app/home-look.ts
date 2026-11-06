// "Away" while at home (design/printers-away/, A + B): one sheet and one note for the whole app. The list's chip and the
// bar's AWAY open the sheet (A); a printer's own "I'm home: look on this Wi-Fi" looks first and opens it only when the
// printer isn't found (B).

import { reactive, ref } from 'vue'
import { lookOnWifi, printerById } from './printers'
import { foundWords } from './reach'

export const awaySheet = reactive({
  open: false,
  ids: [] as string[],
  state: 'ask' as 'ask' | 'looking' | 'notfound',
})
export const foundNote = ref('')

export function askAboutAway(ids: string[]): void {
  Object.assign(awaySheet, { open: true, ids, state: 'ask' })
}

/** Look for these printers on this Wi-Fi. inSheet: the sheet is open and shows Looking; otherwise it opens only if none is found. */
export async function lookFor(ids: string[], inSheet = false): Promise<boolean> {
  awaySheet.ids = ids
  if (inSheet) awaySheet.state = 'looking'
  const results = await Promise.all(ids.map(lookOnWifi))
  const found = ids.filter((_, i) => results[i]).map((id) => printerById(id)?.name).filter((n): n is string => !!n)
  if (found.length) {
    awaySheet.open = false
    foundNote.value = foundWords(found)
  } else {
    Object.assign(awaySheet, { open: true, state: 'notfound' })
  }
  return found.length > 0
}
