// Mirror of homeschool-tutor/src/utils/audioUtils.ts for the demo app.
/**
 * Convert a MediaRecorder blob (WebM/Opus) to a WAV Blob via the AudioContext
 * pipeline. The server's soundfile/librosa expect standard PCM WAV.
 *
 * Flow: MediaRecorder chunks → Blob → ArrayBuffer → AudioContext.decodeAudioData
 *       → Float32Array (mono, 16 kHz) → WAV header + PCM bytes → Blob
 */

export async function convertToWav(
  chunks: Blob[],
  targetSampleRate = 16000
): Promise<Blob> {
  const rawBlob = new Blob(chunks, { type: 'audio/webm' })
  const arrayBuffer = await rawBlob.arrayBuffer()

  const offlineCtx = new OfflineAudioContext(1, 1, targetSampleRate)
  let audioBuffer: AudioBuffer

  try {
    audioBuffer = await offlineCtx.decodeAudioData(arrayBuffer)
  } catch {
    // Some browsers can't decode WebM in OfflineAudioContext — use regular AudioContext
    const tmpCtx = new AudioContext()
    audioBuffer = await tmpCtx.decodeAudioData(arrayBuffer.slice(0))
    await tmpCtx.close()
  }

  // Mix to mono
  const numChannels = audioBuffer.numberOfChannels
  const length = audioBuffer.length
  const mono = new Float32Array(length)
  for (let c = 0; c < numChannels; c++) {
    const ch = audioBuffer.getChannelData(c)
    for (let i = 0; i < length; i++) mono[i] += ch[i]
  }
  for (let i = 0; i < length; i++) mono[i] /= numChannels

  // Resample to targetSampleRate if needed
  let samples: Float32Array = mono
  if (audioBuffer.sampleRate !== targetSampleRate) {
    samples = resample(mono, audioBuffer.sampleRate, targetSampleRate)
  }

  const wavBuffer = encodeWav(samples, targetSampleRate)
  return new Blob([wavBuffer], { type: 'audio/wav' })
}

function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array<ArrayBuffer> {
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

function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
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

/** Get the best available MediaRecorder mimeType */
export function getBestMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}
