/**
 * Bidirectional text reordering and Arabic shaping for terminal rendering.
 *
 * Terminals on Windows and browser terminal emulators such as xterm.js do not
 * implement the Unicode Bidi Algorithm or contextual Arabic shaping. Without
 * software handling, RTL text is reversed and Arabic letters are displayed as
 * disconnected isolated glyphs.
 *
 * This module first converts Arabic letters to their contextual presentation
 * forms while preserving one grapheme per rendered cell, then applies bidi
 * reordering before Ink's LTR cell-placement loop.
 */
import bidiFactory from 'bidi-js'

type ClusteredChar = {
  value: string
  width: number
  styleId: number
  hyperlink: string | undefined
}

type ArabicForms = {
  isolated: string
  final?: string
  initial?: string
  medial?: string
}

let bidiInstance: ReturnType<typeof bidiFactory> | undefined
let needsSoftwareBidi: boolean | undefined

/**
 * Arabic contextual forms. Values are Unicode Arabic Presentation Forms.
 *
 * Lam + Alef is deliberately not collapsed into a ligature: Hermes stores
 * styling and width per grapheme, so merging two graphemes would shift colours
 * and terminal cells. Rendering Lam in initial/medial form followed by Alef in
 * final form keeps the word visually connected and preserves cell metadata.
 */
const ARABIC_FORMS = new Map<number, ArabicForms>([
  [0x0621, { isolated: '\ufe80' }],
  [0x0622, { isolated: '\ufe81', final: '\ufe82' }],
  [0x0623, { isolated: '\ufe83', final: '\ufe84' }],
  [0x0624, { isolated: '\ufe85', final: '\ufe86' }],
  [0x0625, { isolated: '\ufe87', final: '\ufe88' }],
  [0x0626, { isolated: '\ufe89', final: '\ufe8a', initial: '\ufe8b', medial: '\ufe8c' }],
  [0x0627, { isolated: '\ufe8d', final: '\ufe8e' }],
  [0x0628, { isolated: '\ufe8f', final: '\ufe90', initial: '\ufe91', medial: '\ufe92' }],
  [0x0629, { isolated: '\ufe93', final: '\ufe94' }],
  [0x062a, { isolated: '\ufe95', final: '\ufe96', initial: '\ufe97', medial: '\ufe98' }],
  [0x062b, { isolated: '\ufe99', final: '\ufe9a', initial: '\ufe9b', medial: '\ufe9c' }],
  [0x062c, { isolated: '\ufe9d', final: '\ufe9e', initial: '\ufe9f', medial: '\ufea0' }],
  [0x062d, { isolated: '\ufea1', final: '\ufea2', initial: '\ufea3', medial: '\ufea4' }],
  [0x062e, { isolated: '\ufea5', final: '\ufea6', initial: '\ufea7', medial: '\ufea8' }],
  [0x062f, { isolated: '\ufea9', final: '\ufeaa' }],
  [0x0630, { isolated: '\ufeab', final: '\ufeac' }],
  [0x0631, { isolated: '\ufead', final: '\ufeae' }],
  [0x0632, { isolated: '\ufeaf', final: '\ufeb0' }],
  [0x0633, { isolated: '\ufeb1', final: '\ufeb2', initial: '\ufeb3', medial: '\ufeb4' }],
  [0x0634, { isolated: '\ufeb5', final: '\ufeb6', initial: '\ufeb7', medial: '\ufeb8' }],
  [0x0635, { isolated: '\ufeb9', final: '\ufeba', initial: '\ufebb', medial: '\ufebc' }],
  [0x0636, { isolated: '\ufebd', final: '\ufebe', initial: '\ufebf', medial: '\ufec0' }],
  [0x0637, { isolated: '\ufec1', final: '\ufec2', initial: '\ufec3', medial: '\ufec4' }],
  [0x0638, { isolated: '\ufec5', final: '\ufec6', initial: '\ufec7', medial: '\ufec8' }],
  [0x0639, { isolated: '\ufec9', final: '\ufeca', initial: '\ufecb', medial: '\ufecc' }],
  [0x063a, { isolated: '\ufecd', final: '\ufece', initial: '\ufecf', medial: '\ufed0' }],
  [0x0640, { isolated: '\u0640', final: '\u0640', initial: '\u0640', medial: '\u0640' }],
  [0x0641, { isolated: '\ufed1', final: '\ufed2', initial: '\ufed3', medial: '\ufed4' }],
  [0x0642, { isolated: '\ufed5', final: '\ufed6', initial: '\ufed7', medial: '\ufed8' }],
  [0x0643, { isolated: '\ufed9', final: '\ufeda', initial: '\ufedb', medial: '\ufedc' }],
  [0x0644, { isolated: '\ufedd', final: '\ufede', initial: '\ufedf', medial: '\ufee0' }],
  [0x0645, { isolated: '\ufee1', final: '\ufee2', initial: '\ufee3', medial: '\ufee4' }],
  [0x0646, { isolated: '\ufee5', final: '\ufee6', initial: '\ufee7', medial: '\ufee8' }],
  [0x0647, { isolated: '\ufee9', final: '\ufeea', initial: '\ufeeb', medial: '\ufeec' }],
  [0x0648, { isolated: '\ufeed', final: '\ufeee' }],
  [0x0649, { isolated: '\ufeef', final: '\ufef0' }],
  [0x064a, { isolated: '\ufef1', final: '\ufef2', initial: '\ufef3', medial: '\ufef4' }],
  [0x0671, { isolated: '\ufb50', final: '\ufb51' }],
  [0x0679, { isolated: '\ufb66', final: '\ufb67', initial: '\ufb68', medial: '\ufb69' }],
  [0x067a, { isolated: '\ufb5e', final: '\ufb5f', initial: '\ufb60', medial: '\ufb61' }],
  [0x067b, { isolated: '\ufb52', final: '\ufb53', initial: '\ufb54', medial: '\ufb55' }],
  [0x067e, { isolated: '\ufb56', final: '\ufb57', initial: '\ufb58', medial: '\ufb59' }],
  [0x067f, { isolated: '\ufb62', final: '\ufb63', initial: '\ufb64', medial: '\ufb65' }],
  [0x0680, { isolated: '\ufb5a', final: '\ufb5b', initial: '\ufb5c', medial: '\ufb5d' }],
  [0x0683, { isolated: '\ufb76', final: '\ufb77', initial: '\ufb78', medial: '\ufb79' }],
  [0x0684, { isolated: '\ufb72', final: '\ufb73', initial: '\ufb74', medial: '\ufb75' }],
  [0x0686, { isolated: '\ufb7a', final: '\ufb7b', initial: '\ufb7c', medial: '\ufb7d' }],
  [0x0687, { isolated: '\ufb7e', final: '\ufb7f', initial: '\ufb80', medial: '\ufb81' }],
  [0x0688, { isolated: '\ufb88', final: '\ufb89' }],
  [0x068c, { isolated: '\ufb84', final: '\ufb85' }],
  [0x068d, { isolated: '\ufb82', final: '\ufb83' }],
  [0x068e, { isolated: '\ufb86', final: '\ufb87' }],
  [0x0691, { isolated: '\ufb8c', final: '\ufb8d' }],
  [0x0698, { isolated: '\ufb8a', final: '\ufb8b' }],
  [0x06a4, { isolated: '\ufb6a', final: '\ufb6b', initial: '\ufb6c', medial: '\ufb6d' }],
  [0x06a6, { isolated: '\ufb6e', final: '\ufb6f', initial: '\ufb70', medial: '\ufb71' }],
  [0x06a9, { isolated: '\ufb8e', final: '\ufb8f', initial: '\ufb90', medial: '\ufb91' }],
  [0x06af, { isolated: '\ufb92', final: '\ufb93', initial: '\ufb94', medial: '\ufb95' }],
  [0x06ba, { isolated: '\ufb9e', final: '\ufb9f' }],
  [0x06bb, { isolated: '\ufba0', final: '\ufba1', initial: '\ufba2', medial: '\ufba3' }],
  [0x06be, { isolated: '\ufbaa', final: '\ufbab', initial: '\ufbac', medial: '\ufbad' }],
  [0x06c0, { isolated: '\ufba4', final: '\ufba5' }],
  [0x06c1, { isolated: '\ufba6', final: '\ufba7', initial: '\ufba8', medial: '\ufba9' }],
  [0x06cc, { isolated: '\ufbfc', final: '\ufbfd', initial: '\ufbfe', medial: '\ufbff' }],
  [0x06d0, { isolated: '\ufbe4', final: '\ufbe5', initial: '\ufbe6', medial: '\ufbe7' }],
  [0x06d2, { isolated: '\ufbae', final: '\ufbaf' }],
  [0x06d3, { isolated: '\ufbb0', final: '\ufbb1' }]
])

function needsBidi(): boolean {
  if (needsSoftwareBidi === undefined) {
    needsSoftwareBidi =
      process.platform === 'win32' ||
      typeof process.env['WT_SESSION'] === 'string' || // WSL in Windows Terminal
      process.env['TERM_PROGRAM'] === 'vscode' // VS Code integrated terminal / dashboard xterm.js
  }

  return needsSoftwareBidi
}

function getBidi() {
  if (!bidiInstance) {
    bidiInstance = bidiFactory()
  }

  return bidiInstance
}

function getArabicBase(value: string): { codePoint: number; start: number; length: number } | undefined {
  let offset = 0

  for (const symbol of value) {
    const codePoint = symbol.codePointAt(0)!

    if (ARABIC_FORMS.has(codePoint)) {
      return { codePoint, start: offset, length: symbol.length }
    }

    offset += symbol.length
  }

  return undefined
}

function canJoinPrevious(forms: ArabicForms): boolean {
  return Boolean(forms.final || forms.medial)
}

function canJoinNext(forms: ArabicForms): boolean {
  return Boolean(forms.initial || forms.medial)
}

function findPreviousArabic(
  characters: ClusteredChar[],
  index: number
): { index: number; forms: ArabicForms } | undefined {
  for (let candidate = index - 1; candidate >= 0; candidate--) {
    const base = getArabicBase(characters[candidate]!.value)

    if (base) {
      return { index: candidate, forms: ARABIC_FORMS.get(base.codePoint)! }
    }

    if (!isTransparentCluster(characters[candidate]!.value)) {
      return undefined
    }
  }

  return undefined
}

function findNextArabic(
  characters: ClusteredChar[],
  index: number
): { index: number; forms: ArabicForms } | undefined {
  for (let candidate = index + 1; candidate < characters.length; candidate++) {
    const base = getArabicBase(characters[candidate]!.value)

    if (base) {
      return { index: candidate, forms: ARABIC_FORMS.get(base.codePoint)! }
    }

    if (!isTransparentCluster(characters[candidate]!.value)) {
      return undefined
    }
  }

  return undefined
}

function isTransparentCluster(value: string): boolean {
  return [...value].every(symbol => /\p{M}/u.test(symbol))
}

/**
 * Convert Arabic base letters to contextual forms without merging graphemes.
 * This preserves terminal width, style IDs, hyperlinks, and cursor positions.
 */
function shapeArabic(characters: ClusteredChar[]): ClusteredChar[] {
  return characters.map((character, index) => {
    const base = getArabicBase(character.value)

    if (!base) {
      return character
    }

    const forms = ARABIC_FORMS.get(base.codePoint)!
    const previous = findPreviousArabic(characters, index)
    const next = findNextArabic(characters, index)
    const joinsPrevious =
      Boolean(previous) &&
      canJoinPrevious(forms) &&
      canJoinNext(previous!.forms)
    const joinsNext =
      Boolean(next) &&
      canJoinNext(forms) &&
      canJoinPrevious(next!.forms)

    const shaped =
      joinsPrevious && joinsNext
        ? forms.medial
        : joinsPrevious
          ? forms.final
          : joinsNext
            ? forms.initial
            : forms.isolated

    if (!shaped) {
      return character
    }

    return {
      ...character,
      value:
        character.value.slice(0, base.start) +
        shaped +
        character.value.slice(base.start + base.length)
    }
  })
}

/**
 * Reorder an array of ClusteredChars from logical order to visual order using
 * the Unicode Bidi Algorithm. On terminals that also lack Arabic shaping, the
 * letters are converted to contextual presentation forms first.
 *
 * Returns the same array on bidi-capable terminals (no-op).
 */
export function reorderBidi(characters: ClusteredChar[]): ClusteredChar[] {
  if (!needsBidi() || characters.length === 0) {
    return characters
  }

  const plainText = characters.map(character => character.value).join('')

  if (!hasRTLCharacters(plainText)) {
    return characters
  }

  const shapedCharacters = shapeArabic(characters)
  const shapedText = shapedCharacters.map(character => character.value).join('')
  const bidi = getBidi()
  const { levels } = bidi.getEmbeddingLevels(shapedText, 'auto')

  // Map bidi levels back to ClusteredChar indices. Each cluster may contain
  // multiple UTF-16 code units (for example a base letter plus diacritics).
  const charLevels: number[] = []
  let offset = 0

  for (let i = 0; i < shapedCharacters.length; i++) {
    charLevels.push(levels[offset]!)
    offset += shapedCharacters[i]!.value.length
  }

  // Standard bidi reordering at grapheme-cluster level: reverse contiguous
  // runs from the maximum embedding level down to level 1.
  const reordered = [...shapedCharacters]
  const maxLevel = Math.max(...charLevels)

  for (let level = maxLevel; level >= 1; level--) {
    let i = 0

    while (i < reordered.length) {
      if (charLevels[i]! >= level) {
        let j = i + 1

        while (j < reordered.length && charLevels[j]! >= level) {
          j++
        }

        reverseRange(reordered, i, j - 1)
        reverseRangeNumbers(charLevels, i, j - 1)
        i = j
      } else {
        i++
      }
    }
  }

  return reordered
}

function reverseRange<T>(arr: T[], start: number, end: number): void {
  while (start < end) {
    const temp = arr[start]!
    arr[start] = arr[end]!
    arr[end] = temp
    start++
    end--
  }
}

function reverseRangeNumbers(arr: number[], start: number, end: number): void {
  while (start < end) {
    const temp = arr[start]!
    arr[start] = arr[end]!
    arr[end] = temp
    start++
    end--
  }
}

/** Quick check for RTL scripts. */
function hasRTLCharacters(text: string): boolean {
  return /[\u0590-\u05FF\uFB1D-\uFB4F\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u0780-\u07BF\u0700-\u074F]/u.test(
    text
  )
}
