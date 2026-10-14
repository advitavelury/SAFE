import { MultipartParser } from '@remix-run/multipart-parser';
import { ContentType } from '@remix-run/headers/content-type';

export async function streamVideoFeed(user, { signal, onFrame, idleMs = 30000 } = {}) {
  if (!user || user.isAnonymous) throw new Error('Staff sign-in required.');
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) abort();
  let timer;
  let reader;
  let cancelTokenWait;
  const resetTimeout = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(new Error(
      'No video frames received. Check the Python backend and its video source.'
    )), idleMs);
  };
  const cancelReader = () => { reader?.cancel().catch(() => {}); };
  controller.signal.addEventListener('abort', cancelReader);
  resetTimeout();
  try {
    controller.signal.throwIfAborted();
    const cancelled = new Promise((_, reject) => {
      cancelTokenWait = () => reject(controller.signal.reason);
      controller.signal.addEventListener('abort', cancelTokenWait, { once: true });
    });
    const token = await Promise.race([user.getIdToken(), cancelled]);
    controller.signal.removeEventListener('abort', cancelTokenWait);
    controller.signal.throwIfAborted();
    const response = await fetch('/api/video-feed', {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store', signal: controller.signal,
    });
    reader = response.body?.getReader();
    if (response.status === 401) throw new Error('Video access expired. Sign in again and reconnect.');
    if (response.status === 403) throw new Error('Video access denied. An active staff account is required.');
    if (!response.ok) throw new Error('Video feed unavailable. Start the Python backend on port 8000.');
    const type = ContentType.from(response.headers.get('content-type'));
    if (type.mediaType?.toLowerCase() !== 'multipart/x-mixed-replace' || !type.boundary || !reader) {
      throw new Error('Unexpected video response. Check the Python backend on port 8000.');
    }
    const parser = new MultipartParser(type.boundary, {
      maxHeaderSize: 8192, maxFileSize: 4 * 1024 * 1024,
      // This is a continuous feed, not a finite multipart upload.
      maxParts: Infinity, maxTotalSize: Infinity,
    });
    while (true) {
      const { value, done } = await reader.read();
      controller.signal.throwIfAborted();
      if (done) throw new Error('Video feed ended. Check the Python backend and reconnect.');
      let latest;
      for (const part of parser.write(value)) {
        if (part.mediaType !== 'image/jpeg') throw new Error('Unexpected video frame format.');
        latest = new Blob([part.bytes], { type: 'image/jpeg' });
      }
      // Drop superseded frames in a coalesced network chunk rather than queueing playback.
      if (latest) {
        resetTimeout();
        controller.signal.throwIfAborted();
        await onFrame(latest);
      }
    }
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    if (error instanceof TypeError) throw new Error('Video feed unavailable. Start the Python backend on port 8000.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
    if (cancelTokenWait) controller.signal.removeEventListener('abort', cancelTokenWait);
    controller.signal.removeEventListener('abort', cancelReader);
    try { await reader?.cancel(); } catch { /* The network may already be closed. */ }
    reader?.releaseLock();
    controller.abort();
  }
}
