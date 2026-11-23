/**
 * Route configuration — single source of truth for all routing.
 *
 * Defines route paths, lazy-loaded components, metadata (title, breadcrumbs),
 * URL generators, and the ROUTES constant. App.tsx renders from this config;
 * consumers import { ROUTES, generateRoute } from '@/config'.
 *
 * To add a route: add one entry here. Nothing else needs touching.
 */

import type { ComponentType } from 'react';

export interface RouteMetadata {
  title: string;
  description?: string;
  breadcrumbLabel?: string | ((params: Record<string, string>) => string);
  requiresAuth?: boolean;
  preload?: boolean;
  icon?: string;
}

export interface RouteConfig {
  path: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- dynamic lazy import; component props are unknown at config definition time
  component: () => Promise<{ default: ComponentType<any> }>;
  meta: RouteMetadata;
  children?: RouteConfig[];
}

// ---------------------------------------------------------------------------
// Route path constants
// ---------------------------------------------------------------------------

/**
 * Static route pattern strings used in <Route path=…> and for navigation.
 *
 * Parameterised entries use React Router placeholder segments
 * (`:project_id`, `:flow_id`, `:run_id`). Use {@link generateRoute} to build
 * concrete URLs with real IDs substituted in.
 *
 * Design rule: if the page is *about* that resource, its ID goes in the path.
 * If the ID is only needed for back-navigation context, it goes as a query
 * param (e.g. `?project_id=…` on flow-scoped routes).
 */
export const ROUTES = {
  /** `/home` — Home page. */
  HOME: '/home',
  /** `/projects` — Projects list page. */
  PROJECTS: '/projects',
  /** `/projects/:project_id` — Project detail page (parameterised). */
  PROJECT_DETAIL: '/projects/:project_id',
  /** `/flows/:flow_id` — Flow detail page; `?project_id=…` carries back-nav context. */
  FLOW_DETAIL: '/flows/:flow_id',
  /** `/flows/:flow_id/canvas` — Flow editor canvas; `?project_id=…` carries back-nav context. */
  CANVAS: '/flows/:flow_id/canvas',
  /** `/flows/:flow_id/runs/:run_id` — Run details; `?project_id=…` carries back-nav context. */
  FLOW_RUN_DETAILS: '/flows/:flow_id/runs/:run_id',
  /** `/error` — Generic error page. */
  ERROR: '/error',
  /** `/login` — Login page. */
  LOGIN: '/login',
} as const;

/**
 * Helpers that produce concrete URL strings from route parameters.
 *
 * Flow-scoped routes (`flowDetail`, `canvas`, `runDetails`) accept a `projectId`
 * that is appended as `?project_id=…` for back-navigation context only.
 */
export const generateRoute = {
  /** `/projects/${projectId}` */
  projectDetail: (projectId: string) => `/projects/${projectId}`,
  /** `/flows/${flowId}?project_id=${projectId}` */
  flowDetail: (flowId: string, projectId: string) =>
    `/flows/${flowId}?project_id=${projectId}`,
  /** `/flows/${flowId}/canvas?project_id=${projectId}` */
  canvas: (flowId: string, projectId: string) =>
    `/flows/${flowId}/canvas?project_id=${projectId}`,
  /** `/flows/${flowId}/runs/${runId}?project_id=${projectId}` */
  runDetails: (flowId: string, runId: string, projectId: string) =>
    `/flows/${flowId}/runs/${runId}?project_id=${projectId}`,
} as const;

// ---------------------------------------------------------------------------
// Route configuration array
// ---------------------------------------------------------------------------

/**
 * All application routes with their lazy-loaded components and metadata.
 * App.tsx renders this tree directly — no manual <Route> duplication needed.
 */
export const routeConfig: RouteConfig[] = [
  {
    path: '/home',
    component: () => import('@/pages/Home').then((m) => ({ default: m.Home })),
    meta: {
      title: 'Home',
      description: 'Docling Pipelines home page',
      breadcrumbLabel: 'Home',
      preload: true,
    },
  },
  {
    path: '/projects',
    component: () => import('@/pages/Projects').then((m) => ({ default: m.Projects })),
    meta: {
      title: 'Projects',
      description: 'Manage your data processing projects',
      breadcrumbLabel: 'Projects',
    },
    children: [
      {
        path: ':project_id',
        component: () => import('@/pages/ProjectDetail').then((m) => ({ default: m.ProjectDetail })),
        meta: {
          title: 'Project',
          description: 'Project details and flows',
          breadcrumbLabel: (params) => params.project_id ?? 'Project',
        },
      },
    ],
  },
  {
    path: '/flows',
    component: () => import('@/pages/Projects').then((m) => ({ default: m.Projects })),
    meta: {
      title: 'Flows',
      description: 'Flow pages',
      breadcrumbLabel: 'Flows',
    },
    children: [
      {
        path: ':flow_id',
        component: () => import('@/pages/FlowDetail').then((m) => ({ default: m.FlowDetail })),
        meta: {
          title: 'Flow',
          description: 'Flow runs and details',
          breadcrumbLabel: (params) => params.flow_id ?? 'Flow',
        },
      },
      {
        path: ':flow_id/canvas',
        component: () => import('@/pages/Canvas').then((m) => ({ default: m.Canvas })),
        meta: {
          title: 'Canvas',
          description: 'Flow editor canvas for building data pipelines',
          breadcrumbLabel: 'Canvas',
        },
      },
      {
        path: ':flow_id/runs/:run_id',
        component: () => import('@/pages/RunDetails').then((m) => ({ default: m.RunDetails })),
        meta: {
          title: 'Run Details',
          description: 'Detailed information about a specific job run',
          breadcrumbLabel: (params) => `Run ${params.run_id ?? ''}`,
        },
      },
    ],
  },
  {
    path: '/error',
    component: () => import('@/pages/Error').then((m) => ({ default: m.Error })),
    meta: {
      title: 'Error',
      description: 'An error occurred',
      breadcrumbLabel: 'Error',
    },
  },
  {
    path: '/login',
    component: () => import('@/pages/Login').then((m) => ({ default: m.Login })),
    meta: {
      title: 'Sign in',
      description: 'Sign in to Docling Pipelines',
      breadcrumbLabel: 'Sign in',
    },
  },
];

/**
 * Flatten route config for easier lookup
 */
export function flattenRoutes(routes: RouteConfig[], parentPath = ''): RouteConfig[] {
  const flattened: RouteConfig[] = [];

  routes.forEach((route) => {
    const fullPath = parentPath + route.path;
    flattened.push({ ...route, path: fullPath });

    if (route.children) {
      flattened.push(...flattenRoutes(route.children, fullPath));
    }
  });

  return flattened;
}

/**
 * Cached flat route list — computed once at module load time.
 */
const flatRoutesCache: RouteConfig[] = flattenRoutes(routeConfig);

/**
 * Find route config by path
 */
export function findRouteByPath(path: string): RouteConfig | undefined {
  return flatRoutesCache.find((route) => {
    const pattern = route.path.replace(/:[^/]+/g, '[^/]+');
    const regex = new RegExp(`^${pattern}$`);
    return regex.test(path);
  });
}

/**
 * Get route metadata by path
 */
export function getRouteMetadata(path: string): RouteMetadata | undefined {
  return findRouteByPath(path)?.meta;
}

/**
 * Extract route parameters from path
 */
function extractParams(pathname: string, pattern: string): Record<string, string> {
  const params: Record<string, string> = {};
  const patternParts = pattern.split('/').filter(Boolean);
  const pathParts = pathname.split('/').filter(Boolean);

  patternParts.forEach((part, index) => {
    if (part.startsWith(':')) {
      const paramName = part.slice(1);
      params[paramName] = pathParts[index] ?? '';
    }
  });

  return params;
}

/**
 * Build breadcrumb trail from current path.
 *
 * Rules:
 * - No "Home" is ever prepended — the trail starts from the first route segment.
 * - /home and /projects are top-level pages that suppress the breadcrumb bar entirely
 *   (handled in Breadcrumb.tsx, not here).
 * - Every other path builds its crumbs from route segments, e.g.:
 *     /projects/proj-1           → Projects / proj-1
 *     /projects/proj-1/runs/r-5  → Projects / proj-1 / Runs / Run r-5
 */
export function buildBreadcrumbs(pathname: string): Array<{ label: string; path: string }> {
  const breadcrumbs: Array<{ label: string; path: string }> = [];
  const segments = pathname.split('/').filter(Boolean);

  let currentPath = '';
  segments.forEach((segment) => {
    currentPath += `/${segment}`;

    const enhancedRoute = findRouteByPath(currentPath);
    if (enhancedRoute) {
      const params = extractParams(currentPath, enhancedRoute.path);
      const label = typeof enhancedRoute.meta.breadcrumbLabel === 'function'
        ? enhancedRoute.meta.breadcrumbLabel(params)
        : enhancedRoute.meta.breadcrumbLabel ?? enhancedRoute.meta.title;

      breadcrumbs.push({ label, path: currentPath });
    } else {
      breadcrumbs.push({ label: segment, path: currentPath });
    }
  });

  return breadcrumbs;
}
