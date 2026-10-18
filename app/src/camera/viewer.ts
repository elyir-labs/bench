// Whether the camera is open big: full screen on phones and tablets, the right-hand pane on
// wide screens. One flag for the whole app, so the Now pane's button and the shell agree.

import { ref } from 'vue'

export const cameraOpen = ref(false)
/** On a laptop, the pane view's "Full screen" button: take over the whole screen instead. */
export const cameraFull = ref(false)
