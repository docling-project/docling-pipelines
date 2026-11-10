import React, { lazy, Suspense, useState, useMemo, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { Theme } from '@carbon/react';
import { useTheme } from '@/hooks';
import { AppHeader, ErrorBoundary, Breadcrumb } from '@/components';
import { ToastContainer, ProtectedRoute } from '@/components/common';
import { BreadcrumbActionsContext, ThemeElementContext } from '@/contexts';
import { ROUTES, routeConfig } from '@/config';
import type { RouteConfig } from '@/config';
import styles from './App.module.scss';

/**
 * Wraps a lazy-loaded component in a Suspense boundary with a null fallback.
 * Defined outside App so the JSX element is created once and never recreated
 * on re-renders.
 */
function lazyPage(
  factory: () => Promise<{ default: React.ComponentType<unknown> }>
): React.ReactElement {
  const Component = lazy(factory);
  return (
    <Suspense fallback={null}>
      <Component />
    </Suspense>
  );
}

/**
 * Recursively builds stable <Route> elements from a RouteConfig tree.
 *
 * Called once at module load — never inside a component render.  Calling
 * `lazy()` inside a render creates a new component reference on every
 * re-render, which makes React Router unmount and remount the matched route
 * (resetting all child state, including fetch guards like `fetchedRef`).
 */
function buildRoutes(routes: RouteConfig[]): React.ReactNode {
  return routes.map((route) => {
    const element = lazyPage(route.component);
    if (route.children?.length) {
      return (
        <Route key={route.path} path={route.path} element={<Outlet />}>
          <Route index element={element} />
          {buildRoutes(route.children)}
        </Route>
      );
    }
    return <Route key={route.path} path={route.path} element={element} />;
  });
}

// Evaluated once at module load — the resulting JSX tree is permanently stable.
const shellRouteConfig = routeConfig.filter((route) => route.path !== '/login' && route.path !== '/error');
const appShellRoutes = buildRoutes(shellRouteConfig);

const loginPage = lazyPage(() =>
  import('@/pages/Login').then((m) => ({ default: m.Login }))
);
const errorPage = lazyPage(() =>
  import('@/pages/Error').then((m) => ({ default: m.Error }))
);
const notFoundPage = lazyPage(() =>
  import('@/pages/NotFound').then((m) => ({ default: m.NotFound }))
);

function App(): React.JSX.Element {
  const { theme } = useTheme();
  // Callback ref stored in state: firing setThemeElement once after mount gives
  // ThemeElementContext a non-null value and triggers the single re-render needed
  // to propagate it to all consumers.  useRef alone won't work here because
  // mutating ref.current does not cause a re-render.
  const [themeElement, setThemeElement] = useState<HTMLDivElement | null>(null);
  const themeRefCallback = useCallback((node: HTMLDivElement | null) => {
    if (node !== null) { setThemeElement(node); }
  }, []);
  const [breadcrumbActions, setBreadcrumbActions] = useState<React.ReactNode>(null);

  // useCallback gives setActions a stable reference — it never changes between renders.
  // Without this, useMemo recreates the context object (and thus a new setActions ref)
  // on every breadcrumbActions state change, causing any useEffect that lists setActions
  // as a dependency (e.g. FlowDetail) to re-fire infinitely.
  const setActions = useCallback(
    (actions: React.ReactNode) => { setBreadcrumbActions(actions); },
    [] // setBreadcrumbActions is a useState setter — permanently stable
  );

  const breadcrumbContextValue = useMemo(
  () => ({ actions: breadcrumbActions, setActions }),
  [breadcrumbActions, setActions]
);

  return (
    <ErrorBoundary>
      <BrowserRouter basename="/ui">
        <Theme theme={theme}>
          <ThemeElementContext.Provider value={themeElement}>
          <BreadcrumbActionsContext.Provider value={breadcrumbContextValue}>
            <Routes>
              {/* Public pages outside the shell */}
              <Route path="/login" element={loginPage} />
              <Route path="/error" element={errorPage} />

              {/* Root redirect */}
              <Route path="/" element={<Navigate to={ROUTES.HOME} replace />} />

              {/* Protected shell routes */}
              <Route
                element={
                  <ProtectedRoute>
                    <div ref={themeRefCallback} className={styles.appContainer}>
                      <AppHeader />
                      {/* Breadcrumb sits in normal flow, offset below the fixed header */}
                      <div className={styles.breadcrumbRow}>
                        <Breadcrumb />
                      </div>
                      {/* Only this div scrolls — height fills remaining space */}
                      <div className={styles.pageContent}>
                        <Outlet />
                      </div>
                    </div>
                  </ProtectedRoute>
                }
              >
                {/* Data-driven shell routes */}
                {appShellRoutes}

                {/* 404 catch-all inside shell */}
                <Route path="*" element={notFoundPage} />
              </Route>
            </Routes>
          </BreadcrumbActionsContext.Provider>
          </ThemeElementContext.Provider>
          {/* Global toast container — mounted once, reads from Redux notifications slice */}
          <ToastContainer />
        </Theme>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
