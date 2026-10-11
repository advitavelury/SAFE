import { auth } from './firebase.js';
import { createRecordingRequest, recordingOrigin } from './recordingClient.js';

const origin = recordingOrigin(import.meta.env);
export const recordingServiceEnabled = origin !== null;
export const recordingRequest = createRecordingRequest({ getUser: () => auth?.currentUser, origin });
