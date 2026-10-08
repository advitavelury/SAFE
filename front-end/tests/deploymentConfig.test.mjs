import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FIREBASE_ENV_KEYS, mediaOrigin, mediaUrl, validateDeploymentEnv } from '../src/api/deploymentConfig.js';

const env = Object.fromEntries(FIREBASE_ENV_KEYS.map(key => [key, 'test-value']));
env.VITE_FIREBASE_PROJECT_ID = 'safe-ddacb';

test('production media is disabled by default; development keeps the local proxy', () => {
  assert.equal(mediaOrigin(), null);
  assert.equal(mediaOrigin('  '), null);
  assert.equal(mediaOrigin('', true), '');
  assert.throws(() => mediaUrl(null, '/api/camera/status'), /not connected/);
  assert.equal(mediaUrl('', '/api/camera/status'), '/api/camera/status');
});

test('explicit media services use an HTTPS origin', () => {
  assert.equal(mediaOrigin(' https://camera.example.com/ '), 'https://camera.example.com');
  assert.equal(mediaUrl(mediaOrigin('https://camera.example.com'), '/api/camera/status'),
    'https://camera.example.com/api/camera/status');
  assert.equal(mediaOrigin('http://127.0.0.1:5001', true), 'http://127.0.0.1:5001');
});

test('reject insecure production media and credentials in URLs', () => {
  for (const value of ['http://camera.example.com', 'https://localhost:8000',
    'https://127.0.0.1', 'https://127.1', 'https://[::1]', 'https://test.localhost',
    'https://user:password@camera.example.com', 'https://camera.example.com/api',
    'https://camera.example.com?token=secret', 'https://camera.example.com#fragment',
    '//camera.example.com', '/api', 'not a url', 'file:///tmp']) {
    assert.throws(() => mediaOrigin(value), /VITE_MEDIA_API_ORIGIN/);
  }
});

test('media paths cannot switch origins or traverse paths', () => {
  for (const path of ['//evil.example', 'https://evil.example', '/api/../private', '/api/\\evil']) {
    assert.throws(() => mediaUrl('https://camera.example.com', path), /Invalid/);
  }
});

test('build validation requires the full Firebase config but no camera service', () => {
  assert.doesNotThrow(() => validateDeploymentEnv(env));
  for (const key of FIREBASE_ENV_KEYS) {
    for (const value of ['', '   ', 'your_placeholder']) {
      assert.throws(() => validateDeploymentEnv({ ...env, [key]: value }), /Missing Firebase/);
    }
  }
});

test('build validation rejects mixed project, unsupported schema and private client credentials', () => {
  assert.throws(() => validateDeploymentEnv({ ...env, VITE_FIREBASE_PROJECT_ID: 'safe-1426e' }), /safe-ddacb/);
  assert.throws(() => validateDeploymentEnv({ ...env, VITE_FIREBASE_INCIDENTS_COLLECTION: 'events' }), /schema/);
  assert.throws(() => validateDeploymentEnv({ ...env, VITE_FIREBASE_SERVICE_ACCOUNT: 'private' }), /private backend/);
  assert.throws(() => validateDeploymentEnv({ ...env, VITE_MEDIA_API_ORIGIN: 'http://localhost:8000' }), /HTTPS/);
});
