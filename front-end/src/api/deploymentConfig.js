export const FIREBASE_ENV_KEYS = [
  'VITE_FIREBASE_API_KEY', 'VITE_FIREBASE_AUTH_DOMAIN',
  'VITE_FIREBASE_PROJECT_ID', 'VITE_FIREBASE_STORAGE_BUCKET',
  'VITE_FIREBASE_MESSAGING_SENDER_ID', 'VITE_FIREBASE_APP_ID',
];

export function mediaOrigin(value = '', development = false) {
  const raw = value.trim();
  if (!raw) return development ? '' : null;
  let url;
  try { url = new URL(raw); }
  catch { throw new Error('VITE_MEDIA_API_ORIGIN must be an absolute HTTPS origin.'); }
  const loopback = url.hostname === 'localhost' || url.hostname.endsWith('.localhost')
    || url.hostname.startsWith('127.') || url.hostname === '[::1]';
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/'
    || !['https:', 'http:'].includes(url.protocol)
    || (!development && (url.protocol !== 'https:' || loopback))) {
    throw new Error('VITE_MEDIA_API_ORIGIN must be an HTTPS origin without credentials, path or query; production cannot use localhost.');
  }
  return url.origin;
}

export function mediaUrl(origin, path) {
  if (origin === null) throw new Error('Media service is not connected to this deployment.');
  if (!path.startsWith('/api/') || path.includes('\\') || path.includes('..')) {
    throw new Error('Invalid media API path.');
  }
  return `${origin}${path}`;
}

export function validateDeploymentEnv(env) {
  const missing = FIREBASE_ENV_KEYS.filter(key => !env[key]?.trim() || env[key].startsWith('your_'));
  if (missing.length) throw new Error(`Missing Firebase web configuration: ${missing.join(', ')}. See DEPLOYMENT.md.`);
  if (env.VITE_FIREBASE_PROJECT_ID !== 'safe-ddacb') {
    throw new Error('This deployment must use the team Firebase project safe-ddacb.');
  }
  if ((env.VITE_FIREBASE_INCIDENTS_COLLECTION || 'incidents') !== 'incidents') {
    throw new Error('The dashboard currently supports the incidents schema, not backend events. See DEPLOYMENT.md.');
  }
  const privateKeys = Object.keys(env).filter(key => key.startsWith('VITE_')
    && /PRIVATE_KEY|SERVICE_ACCOUNT/.test(key));
  if (privateKeys.length) throw new Error('Remove private backend credentials from VITE_ variables.');
  mediaOrigin(env.VITE_MEDIA_API_ORIGIN);
}
