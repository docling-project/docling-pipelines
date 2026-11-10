import express from 'express';
import dotenv from 'dotenv';
import { routes as operatorRoutes } from './controllers/operator-controller';
import { routes as flowRoutes } from './controllers/flow-controller';
import { routes as jobRunRoutes } from './controllers/job-run-controller';
import { routes as projectsRoutes } from './controllers/projects-controller';
import { routes as documentClassRoutes } from './controllers/document-class-controller';
import { routes as validationRoutes } from './controllers/validation-controller';
import { log4js, logUtil } from '../src/utils/logger';
import { resolveBffHost } from './bind-host';

const logger = log4js.getLogger('bff.server');

// Load environment variables — path relative to CWD (dev/standalone mode).
// In wheel mode env vars are injected directly by main.py so this is a no-op.
dotenv.config();

// Fail fast when the upstream URL is missing — misconfiguration should surface
// immediately at startup rather than silently proxying to an undefined host.
if (!process.env.BACKEND_API_URL) {
  logger.fatal('BACKEND_API_URL is not set — BFF cannot proxy requests to the backend. Exiting.');
  process.exit(1);
}

const app = express();
const PORT = Number(process.env.BFF_PORT) || 3001;
const HOST = resolveBffHost();

// Middleware
app.use(express.json());

// API Routes
const router = express.Router();
operatorRoutes(router);
flowRoutes(router);
jobRunRoutes(router);
projectsRoutes(router);
documentClassRoutes(router);
validationRoutes(router);
app.use('/api', router);

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'docling-pipelines-bff' });
});

// Error handling middleware
app.use((err: Error & { status?: number }, req: express.Request, res: express.Response, _next: express.NextFunction) => {
  logUtil.error({ logger, message: 'BFF Error', data: err.message });
  res.status((err as { status?: number }).status || 500).json({
    error: err.message || 'Internal server error',
  });
});

// Start server
app.listen(PORT, HOST, () => {
  logUtil.info({ logger, message: 'Server running', data: { url: `http://${HOST}:${PORT}`, host: HOST } });
  logUtil.info({ logger, message: 'Ready to proxy API requests to backend' });
});
