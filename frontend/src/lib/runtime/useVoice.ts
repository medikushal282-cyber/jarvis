"use client";

/**
 * Microphone capture, energy VAD, playback and barge-in.
 *
 * Push-to-talk is the reliable path and the default. Hands-free listening is
 * available but off unless asked for -- wake-word detection in a noisy demo
 * room is a trap.
 *
 * Every failure here degrades to text rather than blocking the app. See
 * docs/runtime/VOICE.md section 6.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { voice as voiceApi } from "./client";
import type { Transcript, VoiceConfig } from "./types";

export type MicState =
  | "unsupported"
  | "denied"
  | "idle"
  | "listening"
  | "transcribing"
  | "speaking"
  | "error";

/** Energy threshold above which we treat the signal as speech. */
const SPEECH_THRESHOLD = 0.018;
/** Silence after speech that ends an utterance. */
const SILENCE_MS = 800;
/** Anything shorter than this is a cough, not an instruction. */
const MIN_UTTERANCE_MS = 300;
/** Stop listening if nobody says anything for this long. */
const NO_SPEECH_TIMEOUT_MS = 8000;

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const type of [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ]) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

export interface UseVoiceOptions {
  sessionId?: string | null;
  workspaceId?: string | null;
  /** Fired with the final transcript of an utterance. */
  onTranscript?: (transcript: Transcript) => void;
  onError?: (message: string) => void;
  /** Stop playback the moment the user speaks over JARVIS. */
  bargeIn?: boolean;
}

export interface VoiceHandle {
  state: MicState;
  config: VoiceConfig | null;
  level: number;
  error: string | null;
  transcript: Transcript | null;
  supported: boolean;
  start: () => Promise<void>;
  stop: () => void;
  speak: (text: string) => Promise<void>;
  stopSpeaking: () => void;
  clearError: () => void;
}

export function useVoice(options: UseVoiceOptions = {}): VoiceHandle {
  const { sessionId, workspaceId, onTranscript, onError, bargeIn = true } = options;

  const [state, setState] = useState<MicState>("idle");
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);
  const lastSpeechRef = useRef(0);
  const sawSpeechRef = useRef(false);
  const playerRef = useRef<HTMLAudioElement | null>(null);
  const speakingRef = useRef(false);
  /** True between start() and the recorder actually running (mic prompt). */
  const startingRef = useRef(false);
  /** Whether the analyser came up, i.e. whether "no speech heard" is knowable. */
  const vadRef = useRef(false);

  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onTranscriptRef.current = onTranscript;
    onErrorRef.current = onError;
  }, [onTranscript, onError]);

  // Decided after mount, never during render: the server has no microphone
  // API, and React does not patch attribute mismatches when hydrating, so a
  // render-time check left the button stuck as disabled in the browser.
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    const ok =
      typeof navigator !== "undefined" &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== "undefined";
    setSupported(ok);
    if (!ok) setState("unsupported");
  }, []);

  useEffect(() => {
    voiceApi
      .config()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const fail = useCallback((message: string) => {
    setError(message);
    setState("error");
    onErrorRef.current?.(message);
  }, []);

  const stopSpeaking = useCallback(() => {
    speakingRef.current = false;
    if (playerRef.current) {
      playerRef.current.pause();
      playerRef.current.currentTime = 0;
      playerRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setState((s) => (s === "speaking" ? "idle" : s));
  }, []);

  const teardownCapture = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    analyserRef.current = null;
    if (audioCtxRef.current?.state !== "closed") {
      audioCtxRef.current?.close().catch(() => undefined);
    }
    audioCtxRef.current = null;
    setLevel(0);
  }, []);

  const finish = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
  }, []);

  const stop = useCallback(() => {
    void finish();
  }, [finish]);

  /** Per-frame RMS: drives the waveform, the VAD and barge-in. */
  const monitor = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const buffer = new Float32Array(analyser.fftSize);
    const tick = () => {
      if (!analyserRef.current) return;
      analyser.getFloatTimeDomainData(buffer);

      let sum = 0;
      for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
      const rms = Math.sqrt(sum / buffer.length);
      setLevel(rms);

      const now = performance.now();
      if (rms > SPEECH_THRESHOLD) {
        if (bargeIn && speakingRef.current) stopSpeaking();
        sawSpeechRef.current = true;
        lastSpeechRef.current = now;
      } else if (
        sawSpeechRef.current &&
        now - lastSpeechRef.current > SILENCE_MS &&
        now - startedAtRef.current > MIN_UTTERANCE_MS
      ) {
        void finish();
        return;
      } else if (
        !sawSpeechRef.current &&
        now - startedAtRef.current > NO_SPEECH_TIMEOUT_MS
      ) {
        void finish();
        return;
      }

      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [bargeIn, finish, stopSpeaking]);

  const start = useCallback(async () => {
    if (!supported) {
      fail("This browser cannot record audio. Use the text box instead.");
      return;
    }
    if (config && !config.stt_enabled) {
      fail("Speech-to-text is switched off on the server.");
      return;
    }
    if (recorderRef.current?.state === "recording" || startingRef.current) return;

    // Pressing talk while JARVIS is speaking interrupts it.
    stopSpeaking();
    startingRef.current = true;
    setError(null);
    setTranscript(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (cause: any) {
      const denied = cause?.name === "NotAllowedError" || cause?.name === "SecurityError";
      startingRef.current = false;
      setState(denied ? "denied" : "error");
      const message = denied
        ? "Microphone access denied. You can still type."
        : "No microphone available. You can still type.";
      setError(message);
      onErrorRef.current?.(message);
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];
    sawSpeechRef.current = false;
    startedAtRef.current = performance.now();
    lastSpeechRef.current = startedAtRef.current;

    try {
      const AudioCtx =
        window.AudioContext ?? (window as any).webkitAudioContext;
      const ctx = new AudioCtx();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      analyserRef.current = analyser;
      vadRef.current = true;
      monitor();
    } catch {
      // Without an analyser there is no VAD; push-to-talk still works.
      analyserRef.current = null;
      vadRef.current = false;
    }

    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = async () => {
      const elapsed = performance.now() - startedAtRef.current;
      teardownCapture();
      recorderRef.current = null;

      const blob = new Blob(chunksRef.current, {
        type: mimeType || "audio/webm",
      });
      chunksRef.current = [];

      if (elapsed < MIN_UTTERANCE_MS || blob.size < 1024) {
        setState("idle");
        return;
      }
      if (vadRef.current && !sawSpeechRef.current) {
        // Nothing but room noise: don't spend a transcription on it.
        setState("idle");
        setError("I didn't hear anything.");
        return;
      }
      if (config && blob.size > config.max_audio_bytes) {
        fail("That was too long. Try a shorter instruction.");
        return;
      }

      setState("transcribing");
      try {
        const result = await voiceApi.transcribe(blob, {
          sessionId: sessionId ?? undefined,
          workspaceId: workspaceId ?? undefined,
        });
        setTranscript(result);
        setState("idle");
        if (result.empty) {
          setError("I did not catch that.");
          return;
        }
        onTranscriptRef.current?.(result);
      } catch (cause: any) {
        fail(cause?.message ?? "Could not transcribe that. You can still type.");
      }
    };

    // A hard cap so a stuck recorder cannot run forever.
    const maxMs = (config?.max_utterance_s ?? 60) * 1000;
    window.setTimeout(() => {
      if (recorderRef.current?.state === "recording") void finish();
    }, maxMs);

    recorder.start(250);
    startingRef.current = false;
    setState("listening");
  }, [supported, config, monitor, teardownCapture, fail, finish, stopSpeaking, sessionId, workspaceId]);

  const speak = useCallback(
    async (text: string) => {
      if (!text.trim() || (config && !config.tts_enabled)) return;

      stopSpeaking();
      speakingRef.current = true;
      setState("speaking");

      try {
        const result = await voiceApi.synthesize(text);

        if (result instanceof Blob) {
          const url = URL.createObjectURL(result);
          const player = new Audio(url);
          playerRef.current = player;
          player.onended = () => {
            URL.revokeObjectURL(url);
            speakingRef.current = false;
            playerRef.current = null;
            setState("idle");
          };
          await player.play();
          return;
        }

        // Browser backend: speak the server-shortened text locally with a British Butler voice if available.
        if (typeof window !== "undefined" && window.speechSynthesis) {
          const utterance = new SpeechSynthesisUtterance(result.text);
          utterance.rate = 1.0;
          
          const voices = window.speechSynthesis.getVoices();
          const britishVoice = voices.find(
            (v) =>
              v.lang === "en-GB" ||
              v.lang.startsWith("en-GB") ||
              v.name.includes("UK") ||
              v.name.includes("British") ||
              v.name.includes("George") ||
              v.name.includes("Daniel") ||
              v.name.includes("Oliver") ||
              v.name.includes("Ryan")
          );
          if (britishVoice) {
            utterance.voice = britishVoice;
          }

          utterance.onend = () => {
            speakingRef.current = false;
            setState("idle");
          };
          window.speechSynthesis.speak(utterance);
        } else {
          speakingRef.current = false;
          setState("idle");
        }
      } catch {
        // A silent JARVIS is fine; the reply is on screen.
        speakingRef.current = false;
        setState("idle");
      }
    },
    [config, stopSpeaking],
  );

  useEffect(
    () => () => {
      teardownCapture();
      stopSpeaking();
    },
    [teardownCapture, stopSpeaking],
  );

  return {
    state,
    config,
    level,
    error,
    transcript,
    supported,
    start,
    stop,
    speak,
    stopSpeaking,
    clearError: () => setError(null),
  };
}

export default useVoice;
