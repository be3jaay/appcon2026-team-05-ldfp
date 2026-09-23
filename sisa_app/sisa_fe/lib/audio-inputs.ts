"use client"

export interface AudioInput {
  context: AudioContext
  node: AudioNode
  now?: () => number
  onEnded?: (callback: () => void) => void
  release: () => void | Promise<void>
}

export type AudioInputFactory = () => Promise<AudioInput>

function createAudioContext(): AudioContext {
  const AudioContextCtor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext
  return new AudioContextCtor()
}

async function closeContext(context: AudioContext) {
  try {
    await context.close()
  } catch {
    // already closed
  }
}

export const micInput: AudioInputFactory = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const context = createAudioContext()
  return {
    context,
    node: context.createMediaStreamSource(stream),
    release: async () => {
      stream.getTracks().forEach((track) => track.stop())
      await closeContext(context)
    },
  }
}

interface ElementGraph {
  context: AudioContext
  source: MediaElementAudioSourceNode
}

const elementGraphs = new WeakMap<HTMLMediaElement, ElementGraph>()

function getElementGraph(element: HTMLMediaElement): ElementGraph {
  let graph = elementGraphs.get(element)
  if (!graph) {
    const context = createAudioContext()
    const source = context.createMediaElementSource(element)
    source.connect(context.destination)
    graph = { context, source }
    elementGraphs.set(element, graph)
  }
  return graph
}

export async function resumeMediaElementAudio(element: HTMLMediaElement) {
  const graph = elementGraphs.get(element)
  if (graph?.context.state === "suspended") await graph.context.resume()
}

export async function disposeMediaElementAudio(element: HTMLMediaElement) {
  const graph = elementGraphs.get(element)
  if (!graph) return
  elementGraphs.delete(element)
  await closeContext(graph.context)
}

export function mediaElementInput(
  element: HTMLMediaElement
): AudioInputFactory {
  return async () => {
    const { context, source } = getElementGraph(element)
    if (context.state === "suspended") await context.resume()
    return {
      context,
      node: source,
      now: () => element.currentTime,
      onEnded: (callback) =>
        element.addEventListener("ended", callback, { once: true }),
      release: () => {},
    }
  }
}

export const tabAudioInput: AudioInputFactory = async () => {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: true,
    preferCurrentTab: true,
    selfBrowserSurface: "include",
  } as DisplayMediaStreamOptions)

  const [audioTrack] = stream.getAudioTracks()
  if (!audioTrack) {
    stream.getTracks().forEach((track) => track.stop())
    throw new Error(
      'No tab audio was shared. Pick this tab and turn on "Share tab audio".'
    )
  }

  const context = createAudioContext()
  return {
    context,
    node: context.createMediaStreamSource(new MediaStream([audioTrack])),
    onEnded: (callback) =>
      audioTrack.addEventListener("ended", callback, { once: true }),
    release: async () => {
      stream.getTracks().forEach((track) => track.stop())
      await closeContext(context)
    },
  }
}
