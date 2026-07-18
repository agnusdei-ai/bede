// Mirror of homeschool-tutor/src/utils/audioUtils.ts for the demo app.
/**
 * Pure PCM → WAV helpers used by useVoiceRecorder's raw-capture pipeline.
 *
 * These used to also be reached via a MediaRecorder-blob → decodeAudioData
 * conversion step (convertToWav), but decodeAudioData proved unreliable
 * specifically for decoding a browser's OWN MediaRecorder output on iOS
 * Safari (fragmented MP4/AAC container quirks; the promise can reject or —
 * worse — the surrounding onstop handler's rejection went unhandled,
 * leaving the recorder stuck "listening" forever with nothing ever shown to
 * the user and no visible error). useVoiceRecorder now taps raw PCM
 * directly off the live audio graph (the same tap point the level-meter
 * AnalyserNode already used) and only ever calls the pure functions below —
 * no encode/decode round trip, so no codec/container compatibility surface
 * remains to fail on any browser.
 */

export function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array<ArrayBuffer> {
  const ratio = fromRate / toRate
  const outputLength = Math.floor(input.length / ratio)
  const output = new Float32Array(outputLength) as Float32Array<ArrayBuffer>
  for (let i = 0; i < outputLength; i++) {
    const srcIdx = i * ratio
    const lo = Math.floor(srcIdx)
    const hi = Math.min(lo + 1, input.length - 1)
    const frac = srcIdx - lo
    output[i] = input[lo] * (1 - frac) + input[hi] * frac
  }
  return output
}

export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  function writeStr(offset: number, str: string) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }

  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true)       // chunk size
  view.setUint16(20, 1, true)        // PCM
  view.setUint16(22, 1, true)        // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)  // byte rate (16-bit mono)
  view.setUint16(32, 2, true)        // block align
  view.setUint16(34, 16, true)       // bits per sample
  writeStr(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped * 0x7fff, true)
    offset += 2
  }

  return buffer
}
