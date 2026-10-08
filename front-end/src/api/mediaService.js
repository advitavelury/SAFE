import { mediaOrigin, mediaUrl } from './deploymentConfig.js';

const origin = mediaOrigin(import.meta.env.VITE_MEDIA_API_ORIGIN, import.meta.env.DEV);
export const mediaServiceEnabled = origin !== null;
export const mediaServiceUrl = path => mediaUrl(origin, path);
