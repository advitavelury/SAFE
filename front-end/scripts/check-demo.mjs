import { loadEnv } from 'vite';
import { validateDeploymentEnv } from '../src/api/deploymentConfig.js';

try {
  const env = { ...loadEnv('development', process.cwd(), 'VITE_'), ...process.env };
  // The launcher provides loopback origins; production validation still checks
  // the shared Firebase contract without applying production-only HTTPS rules.
  validateDeploymentEnv({ ...env, VITE_MEDIA_API_ORIGIN: '', VITE_BROWSER_DETECTOR_ORIGIN: '' });
} catch (error) {
  console.log(`${error.message} Copy front-end/.env.example to front-end/.env and fill in the team's public web configuration.`);
  process.exitCode = 1;
}
