# Contributing to Docling Pipelines Frontend

This document outlines the coding standards, best practices, and conventions for contributing to the Docling Pipelines frontend application.

## Table of Contents

1. [Technology Stack](#technology-stack)
2. [Project Structure](#project-structure)
3. [TypeScript Standards](#typescript-standards)
4. [React Standards](#react-standards)
5. [Styling Standards](#styling-standards)
6. [ESLint Configuration](#eslint-configuration)
7. [Import Standards](#import-standards)
8. [Naming Conventions](#naming-conventions)
9. [Component Patterns](#component-patterns)
10. [State Management](#state-management)
11. [Error Handling](#error-handling)
12. [Logging Standards](#logging-standards)
13. [API Integration](#api-integration)
14. [Testing Standards](#testing-standards)
15. [Accessibility](#accessibility)
16. [Performance](#performance)
17. [Git Workflow](#git-workflow)

---

## Technology Stack

### Core Technologies
- **React** 18.3.1 - UI library with hooks and functional components
- **TypeScript** 5.7.2 - Type-safe JavaScript with strict mode enabled
- **Vite** 6.0.1 - Build tool and dev server
- **React Router** 6.30.4 - Client-side routing
- **Carbon Design System** 1.68.2 - IBM's design system
- **SCSS** - CSS preprocessing with modules

### Development Tools
- **ESLint** 9.39.0 - Code linting with TypeScript support
- **Node.js** 22.15.1 - Runtime (specified in `.nvmrc`)
- **npm** - Package manager

---

## Project Structure

### Directory Organization

```
frontend/
├── src/
│   ├── components/          # Reusable React components
│   │   ├── common/          # Generic components (ErrorBoundary, Loading, etc.)
│   │   ├── layout/          # Layout components (AppHeader, PageLayout)
│   │   └── index.ts         # Barrel exports
│   ├── config/              # Configuration files
│   │   ├── constants.ts     # App-wide constants
│   │   ├── routes.config.ts # Route configuration
│   │   ├── env.ts           # Environment variables
│   │   └── theme.ts         # Theme configuration
│   ├── contexts/            # React Context providers
│   ├── hooks/               # Custom React hooks
│   ├── lib/                 # Utility libraries
│   │   ├── helpers/         # Helper functions
│   │   └── validation/      # Validation schemas
│   ├── pages/               # Page components (route targets)
│   ├── services/            # External service integrations
│   │   ├── api/             # API client and endpoints
│   │   └── storage/         # Browser storage utilities
│   ├── types/               # TypeScript type definitions
│   ├── utils/               # Utility functions
│   ├── App.tsx              # Root application component
│   └── main.tsx             # Application entry point
├── public/                  # Static assets
├── .env.example             # Environment variable template
├── eslint.config.js         # ESLint configuration
├── tsconfig.json            # TypeScript configuration
├── vite.config.ts           # Vite configuration
└── package.json             # Dependencies and scripts
```

### Component Organization Rules

To ensure a clear separation between routing views and UI components:

1. **`pages/` (Route Containers Only)**:
   - Contains only top-level route components (`Canvas.tsx`, `Projects.tsx`, `Home.tsx`), their SCSS modules, and page-scoped hooks.
   - Does not hold component subtrees.

2. **`components/<PageOrFeatureName>/` (Domain & Feature Components)**:
   - UI components grouped by the feature or page domain that owns them.
   - Addressable from anywhere via the `@/components/<FeatureName>` path alias.
   - Examples:
     - `components/Canvas/` (`FlowRunHistoryTearsheet`, `FlowRunPropertiesTearsheet`, `NodeSuggestion`, `NotificationPanel`)
     - `components/ProjectDetail/` (`FlowsTable`, `CreateFlowTearsheet`)
     - `components/Projects/` (`ProjectsTable`)
     - `components/Home/` (`SampleProjectModal`)
     - `components/PropertiesPanel/`, `components/ElyraCanvas/`, `components/ReadOnlyCanvas/`

3. **`components/common/` (Shared Primitives)**:
   - Reusable primitives consumed across 2+ independent, unrelated feature/domain contexts.
   - Examples: `DeleteModal`, `SharedDataTable`, `RequiredParamTooltip`, `TagInput`, `VaultInput`, `ToastContainer`, `CreateProjectTearsheet`.

### File Organization Rules

1. **One component per file** - Each component should have its own file
2. **Co-locate related files** - Keep component, styles, and tests together
3. **Use barrel exports** - Export from `index.ts` files for cleaner imports
4. **Separate concerns** - Keep business logic separate from UI components

---

## TypeScript Standards

### Configuration

TypeScript is configured with **strict mode** enabled in `tsconfig.json`:

```typescript
{
  "compilerOptions": {
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true
  }
}
```

### Type Safety Rules

#### 1. Explicit Return Types

**Required** for exported functions and public APIs:

```typescript
// ✅ Good - Explicit return type
export function calculateTotal(items: Item[]): number {
  return items.reduce((sum, item) => sum + item.price, 0);
}

// ❌ Bad - Missing return type
export function calculateTotal(items: Item[]) {
  return items.reduce((sum, item) => sum + item.price, 0);
}
```

**Optional** for internal functions and arrow functions where type is obvious:

```typescript
// ✅ Good - Type is inferred and obvious
const handleClick = () => {
  navigate('/home');
};
```

#### 2. Type Imports

Use **inline type imports** for type-only imports:

```typescript
// ✅ Good - Inline type import
import { useState, type ReactNode } from 'react';
import { Button, type ButtonProps } from '@carbon/react';

// ❌ Bad - Separate type import
import type { ReactNode } from 'react';
import { useState } from 'react';
```

#### 3. Avoid `any`

Use `unknown` or proper types instead of `any`:

```typescript
// ✅ Good - Use unknown and type guard
function processData(data: unknown): void {
  if (typeof data === 'string') {
    // data is now typed as string
  }
}

// ❌ Bad - Using any
function processData(data: any): void {
  // No type safety
}
```

#### 4. Array Types

Use **array-simple** syntax:

```typescript
// ✅ Good - Simple array syntax
const items: string[] = [];
const matrix: number[][] = [];

// ✅ Good - Complex types use Array<T>
const callbacks: Array<(value: string) => void> = [];

// ❌ Bad - Inconsistent
const items: Array<string> = [];
```

#### 5. Null Safety

Use **optional chaining** and **nullish coalescing**:

```typescript
// ✅ Good - Safe property access
const userName = user?.profile?.name ?? 'Anonymous';

// ❌ Bad - Unsafe access
const userName = user.profile.name || 'Anonymous';
```

#### 6. Type Definitions

Define types in `src/types/` directory:

```typescript
// src/types/models.ts
export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

export type UserRole = 'admin' | 'user' | 'guest';
```

---

## React Standards

### Component Structure

#### 1. Functional Components Only

Use **functional components** with hooks:

```typescript
// ✅ Good - Functional component
export function UserProfile({ userId }: UserProfileProps): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null);

  return <div>{user?.name}</div>;
}

// ❌ Bad - Class component (except ErrorBoundary)
class UserProfile extends React.Component {
  // ...
}
```

**Exception**: `ErrorBoundary` uses class component (required by React).

#### 2. Component File Structure

```typescript
// 1. Imports
import React, { useState, useEffect } from 'react';
import { Button } from '@carbon/react';
import { Add } from '@carbon/icons-react';
import type { User } from '@/types';
import styles from './MyComponent.module.scss';

// 2. Type definitions
interface MyComponentProps {
  title: string;
  onAction: () => void;
}

// 3. Component
export function MyComponent({ title, onAction }: MyComponentProps): React.JSX.Element {
  // Hooks
  const [count, setCount] = useState(0);

  // Event handlers
  const handleClick = (): void => {
    setCount((prev) => prev + 1);
    onAction();
  };

  // Effects
  useEffect(() => {
    // Effect logic
  }, []);

  // Render
  return (
    <div className={styles.container}>
      <h1>{title}</h1>
      <Button onClick={handleClick}>Click me</Button>
    </div>
  );
}
```

#### 3. Props Interface

Always define props interface:

```typescript
// ✅ Good - Explicit props interface
interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

export function Button({ label, onClick, disabled = false }: ButtonProps): React.JSX.Element {
  return <button onClick={onClick} disabled={disabled}>{label}</button>;
}

// ❌ Bad - Inline props
export function Button({ label, onClick }: { label: string; onClick: () => void }) {
  return <button onClick={onClick}>{label}</button>;
}
```

#### 4. Return Type

Always specify `React.JSX.Element` return type:

```typescript
// ✅ Good
export function MyComponent(): React.JSX.Element {
  return <div>Content</div>;
}

// ❌ Bad
export function MyComponent() {
  return <div>Content</div>;
}
```

### React Hooks Rules

#### 1. Hook Order

Follow the **Rules of Hooks**:

```typescript
export function MyComponent(): React.JSX.Element {
  // 1. State hooks
  const [count, setCount] = useState(0);
  const [user, setUser] = useState<User | null>(null);

  // 2. Context hooks
  const { theme } = useTheme();

  // 3. Ref hooks
  const inputRef = useRef<HTMLInputElement>(null);

  // 4. Custom hooks
  const { data, loading } = useApi('/users');

  // 5. Effects
  useEffect(() => {
    // Effect logic
  }, []);

  return <div>{count}</div>;
}
```

#### 2. Dependencies

Always specify **complete dependencies** for hooks:

```typescript
// ✅ Good - All dependencies listed
useEffect(() => {
  fetchData(userId, filter);
}, [userId, filter]);

// ❌ Bad - Missing dependencies
useEffect(() => {
  fetchData(userId, filter);
}, [userId]); // Missing 'filter'
```

#### 3. Custom Hooks

Custom hooks must start with `use`:

```typescript
// ✅ Good - Custom hook
export function useLocalStorage<T>(key: string, initialValue: T): [T, (value: T) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    const item = window.localStorage.getItem(key);
    return item ? JSON.parse(item) : initialValue;
  });

  const setValue = (value: T): void => {
    setStoredValue(value);
    window.localStorage.setItem(key, JSON.stringify(value));
  };

  return [storedValue, setValue];
}
```

### JSX Standards

#### 1. Self-Closing Tags

Use self-closing tags for components without children:

```typescript
// ✅ Good
<Button />
<Input value={text} />

// ❌ Bad
<Button></Button>
<Input value={text}></Input>
```

#### 2. Boolean Props

Omit `={true}` for boolean props:

```typescript
// ✅ Good
<Button disabled />

// ❌ Bad
<Button disabled={true} />
```

#### 3. Conditional Rendering

Use **ternary** or **logical AND** for conditional rendering:

```typescript
// ✅ Good - Ternary
{isLoading ? <Loading /> : <Content />}

// ✅ Good - Logical AND
{error && <ErrorMessage error={error} />}

// ❌ Bad - If statement
{if (isLoading) { return <Loading />; }}
```

#### 4. Fragments

Avoid unnecessary fragments:

```typescript
// ✅ Good - No fragment needed
return <div>Content</div>;

// ✅ Good - Fragment needed for multiple elements
return (
  <>
    <Header />
    <Content />
  </>
);

// ❌ Bad - Unnecessary fragment
return <>{<div>Content</div>}</>;
```

#### 5. Key Props

Always provide **unique keys** for list items:

```typescript
// ✅ Good - Unique ID as key
{users.map((user) => (
  <UserCard key={user.id} user={user} />
))}

// ❌ Bad - Index as key (avoid unless list is static)
{users.map((user, index) => (
  <UserCard key={index} user={user} />
))}
```

---

## Styling Standards

### SCSS Modules

Use **CSS Modules** for component styles:

```scss
// MyComponent.module.scss
.container {
  padding: 1rem;
  background-color: var(--cds-background);
}

.title {
  font-size: 1.5rem;
  color: var(--cds-text-primary);
}
```

```typescript
// MyComponent.tsx
import styles from './MyComponent.module.scss';

export function MyComponent(): React.JSX.Element {
  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Title</h1>
    </div>
  );
}
```

### Carbon Design Tokens

Use **Carbon design tokens** for consistency:

```scss
// ✅ Good - Carbon tokens
.container {
  padding: var(--cds-spacing-05);
  background-color: var(--cds-background);
  color: var(--cds-text-primary);
}

// ❌ Bad - Hard-coded values
.container {
  padding: 16px;
  background-color: #ffffff;
  color: #000000;
}
```

### Class Naming

Use **camelCase** for CSS module classes:

```scss
// ✅ Good
.headerContainer { }
.primaryButton { }
.errorMessage { }

// ❌ Bad
.header-container { }
.primary_button { }
.ErrorMessage { }
```

---

## ESLint Configuration

### Key Rules

The project enforces strict linting rules via `eslint.config.js`:

#### TypeScript Rules

- **`@typescript-eslint/no-unused-vars`**: Error - No unused variables (prefix with `_` to ignore)
- **`@typescript-eslint/explicit-function-return-type`**: Warn - Explicit return types for functions
- **`@typescript-eslint/no-explicit-any`**: Warn - Avoid `any` type
- **`@typescript-eslint/consistent-type-imports`**: Error - Use inline type imports
- **`@typescript-eslint/prefer-nullish-coalescing`**: Error - Use `??` instead of `||`
- **`@typescript-eslint/prefer-optional-chain`**: Error - Use `?.` for safe access

#### React Rules

- **`react/react-in-jsx-scope`**: Off - Not needed with React 18
- **`react/prop-types`**: Off - Using TypeScript instead
- **`react/jsx-key`**: Error - Keys required in lists
- **`react/self-closing-comp`**: Error - Self-close components without children
- **`react-hooks/rules-of-hooks`**: Error - Follow hooks rules
- **`react-hooks/exhaustive-deps`**: Warn - Complete dependency arrays

#### Code Quality Rules

- **`no-console`**: Error - Use logger utility instead
- **`no-debugger`**: Error - Remove debugger statements
- **`no-var`**: Error - Use `const` or `let`
- **`prefer-const`**: Error - Use `const` when possible
- **`eqeqeq`**: Error - Always use `===` and `!==`
- **`max-len`**: Error - Max 150 characters per line

#### Style Rules

- **`quotes`**: Error - Use single quotes
- **`semi`**: Error - Always use semicolons
- **`comma-dangle`**: Error - Trailing commas in multiline
- **`arrow-parens`**: Error - Always use parentheses in arrow functions

### Running ESLint

```bash
# Check for issues
npm run lint

# Auto-fix issues
npm run lint:fix
```

### Disabling Rules

Only disable rules when absolutely necessary:

```typescript
// ✅ Good - Specific line disable with reason
// eslint-disable-next-line no-console -- Debug logging in development
console.log('Debug info');

// ❌ Bad - Disabling entire file
/* eslint-disable */
```

---

## Import Standards

### Import Order

Organize imports in this order:

```typescript
// 1. React and external libraries
import React, { useState, useEffect } from 'react';
import { Button, Header } from '@carbon/react';
import { Add } from '@carbon/icons-react';

// 2. Internal modules (using path aliases)
import { useTheme } from '@/hooks';
import { ROUTES } from '@/config';
import type { User } from '@/types';

// 3. Relative imports
import { helper } from './utils';

// 4. Styles (always last)
import styles from './MyComponent.module.scss';
```

### Path Aliases

Use configured path aliases from `tsconfig.json`:

```typescript
// ✅ Good - Path aliases
import { Button } from '@/components';
import { useTheme } from '@/hooks';
import { ROUTES } from '@/config';
import type { User } from '@/types';

// ❌ Bad - Relative paths
import { Button } from '../../../components';
import { useTheme } from '../../hooks';
```

### Barrel Exports

Use barrel exports (`index.ts`) for cleaner imports:

```typescript
// components/index.ts
export { AppHeader } from './layout/AppHeader';
export { ErrorBoundary } from './common/ErrorBoundary';
export { Loading } from './common/Loading';

// Usage
import { AppHeader, ErrorBoundary, Loading } from '@/components';
```

---

## Naming Conventions

### Files and Directories

- **Components**: PascalCase - `UserProfile.tsx`, `AppHeader.tsx`
- **Utilities**: camelCase - `formatters.ts`, `validators.ts`
- **Types**: camelCase - `models.ts`, `api.ts`
- **Styles**: Match component - `UserProfile.module.scss`
- **Directories**: camelCase - `components/`, `hooks/`, `utils/`

### Code Elements

- **Components**: PascalCase - `UserProfile`, `AppHeader`
- **Functions**: camelCase - `fetchUser`, `handleClick`
- **Variables**: camelCase - `userName`, `isLoading`
- **Constants**: UPPER_SNAKE_CASE - `API_BASE_URL`, `MAX_RETRIES`
- **Types/Interfaces**: PascalCase - `User`, `ApiResponse`
- **Enums**: PascalCase - `UserRole`, `ThemeType`

### Event Handlers

Prefix with `handle`:

```typescript
// ✅ Good
const handleClick = (): void => { };
const handleSubmit = (): void => { };
const handleChange = (value: string): void => { };

// ❌ Bad
const onClick = (): void => { };
const submit = (): void => { };
```

### Boolean Variables

Use `is`, `has`, `should` prefixes:

```typescript
// ✅ Good
const isLoading = true;
const hasError = false;
const shouldRender = true;

// ❌ Bad
const loading = true;
const error = false;
```

---

## Component Patterns

### Container/Presentational Pattern

Separate logic from presentation:

```typescript
// UserProfileContainer.tsx (logic)
export function UserProfileContainer(): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchUser().then(setUser).finally(() => { setLoading(false); });
  }, []);

  if (loading) {
    return <Loading />;
  }

  return <UserProfileView user={user} />;
}

// UserProfileView.tsx (presentation)
interface UserProfileViewProps {
  user: User | null;
}

export function UserProfileView({ user }: UserProfileViewProps): React.JSX.Element {
  return (
    <div>
      <h1>{user?.name}</h1>
      <p>{user?.email}</p>
    </div>
  );
}
```

### Compound Components

Use for related components:

```typescript
// Card.tsx
export function Card({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className={styles.card}>{children}</div>;
}

Card.Header = function CardHeader({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className={styles.header}>{children}</div>;
};

Card.Body = function CardBody({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className={styles.body}>{children}</div>;
};

// Usage
<Card>
  <Card.Header>Title</Card.Header>
  <Card.Body>Content</Card.Body>
</Card>
```

### Higher-Order Components (HOCs)

Use sparingly, prefer hooks:

```typescript
// ✅ Good - Custom hook
export function useAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null);
  return { user, setUser };
}

// ❌ Avoid - HOC (unless necessary)
export function withAuth<P>(Component: React.ComponentType<P>) {
  return (props: P) => {
    const auth = useAuth();
    return <Component {...props} auth={auth} />;
  };
}
```

---

## State Management

### Local State

Use `useState` for component-local state:

```typescript
export function Counter(): React.JSX.Element {
  const [count, setCount] = useState(0);

  const increment = (): void => {
    setCount((prev) => prev + 1);
  };

  return <button onClick={increment}>{count}</button>;
}
```

### Context API

Use Context for shared state:

```typescript
// ThemeContext.tsx
interface ThemeContextType {
  theme: string;
  toggleTheme: () => void;
}

export const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [theme, setTheme] = useState('light');

  const toggleTheme = (): void => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

// useTheme.ts
export function useTheme(): ThemeContextType {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
}
```

### State Updates

Use functional updates for state that depends on previous value:

```typescript
// ✅ Good - Functional update
setCount((prev) => prev + 1);

// ❌ Bad - Direct update (can cause stale state)
setCount(count + 1);
```

---

## Error Handling

### Error Boundary

Wrap application in `ErrorBoundary`:

```typescript
// App.tsx
export function App(): React.JSX.Element {
  return (
    <ErrorBoundary>
      <Router>
        <Routes />
      </Router>
    </ErrorBoundary>
  );
}
```

### Try-Catch

Use try-catch for async operations:

```typescript
async function fetchData(): Promise<void> {
  try {
    const response = await fetch('/api/data');
    const data = await response.json();
    setData(data);
  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to fetch data',
      data: { error }
    });
    setError(error instanceof Error ? error.message : 'Unknown error');
  }
}
```

### Error States

Always handle error states in UI:

```typescript
export function DataView(): React.JSX.Element {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  if (loading) {
    return <Loading />;
  }

  if (error) {
    return <ErrorMessage message={error} />;
  }

  return <div>{data?.content}</div>;
}
```

---

## Logging Standards

### Logger Utility

Use the custom logger utility instead of `console.*`:

```typescript
import { log4js, logUtil } from '@/utils/logger';

const logger = log4js.getLogger('MyComponent');

// Debug (development only)
logUtil.debug({ logger, message: 'Debug info', data: { value } });

// Info
logUtil.info({ logger, message: 'Operation completed', data: { result } });

// Warning
logUtil.warn({ logger, message: 'Deprecated API used', data: { api } });

// Error
logUtil.error({ logger, message: 'Operation failed', data: { error } });
```

### Logging Rules

1. **Never use `console.*` directly** - Use logger utility
2. **Use appropriate log levels** - Debug, Info, Warn, Error
3. **Include context** - Pass relevant data in `data` parameter
4. **Structured logging** - Use named parameters
5. **Category naming** - Use component/module name as category

### ESLint Exception

When `console.*` is absolutely necessary (rare cases):

```typescript
// eslint-disable-next-line no-console -- Required for [specific reason]
console.log('Special case');
```

---

## API Integration

> **TODO**: The API client implementation is currently under development and may change. This section provides a basic structure that should be adapted as the API integration evolves.

### API Client Structure

```typescript
// services/api/client.ts
const API_BASE_URL = import.meta.env.APP_API_BASE_URL;

export async function apiRequest<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return response.json();
}
```

### API Hooks

Create custom hooks for API calls:

```typescript
// hooks/useUsers.ts
export function useUsers(): {
  users: User[];
  loading: boolean;
  error: string | null;
} {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<User[]>('/users')
      .then(setUsers)
      .catch((err) => { setError(err.message); })
      .finally(() => { setLoading(false); });
  }, []);

  return { users, loading, error };
}
```

---

## Testing Standards

### Test File Structure

```typescript
// MyComponent.test.tsx
import { render, screen } from '@testing-library/react';
import { MyComponent } from './MyComponent';

describe('MyComponent', () => {
  it('renders correctly', () => {
    render(<MyComponent title="Test" />);
    expect(screen.getByText('Test')).toBeInTheDocument();
  });

  it('handles click events', () => {
    const handleClick = jest.fn();
    render(<MyComponent onClick={handleClick} />);
    screen.getByRole('button').click();
    expect(handleClick).toHaveBeenCalled();
  });
});
```

### Testing Best Practices

1. **Test behavior, not implementation**
2. **Use semantic queries** - `getByRole`, `getByLabelText`
3. **Avoid testing internal state**
4. **Mock external dependencies**
5. **Write descriptive test names**

### Testing Role-Gated Components

Components that gate actions by role read `useAuth()`, which reads the `auth` slice of the store. Render them with `renderWithProviders` and set the slice with `authStateFixture` from `tests/mocks/fixtures/store.fixture.ts`:

```typescript
// tests/unit/components/MyGatedButton.test.tsx
import { screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { renderWithProviders } from '../../utils/renderWithProviders';
import { authStateFixture } from '../../mocks/fixtures/store.fixture';
import { MyGatedButton } from '@/components/MyGatedButton';

describe('MyGatedButton', () => {
  it('is disabled for a viewer', () => {
    renderWithProviders(<MyGatedButton createdBy="eve" />, {
      preloadedState: { auth: authStateFixture({ role: 'viewer' }) },
    });
    expect(screen.getByRole('button', { name: /create/i })).toBeDisabled();
  });

  it('is disabled for an editor on another user\'s asset', () => {
    renderWithProviders(<MyGatedButton createdBy="eve" />, {
      preloadedState: { auth: authStateFixture({ role: 'editor', username: 'sam' }) },
    });
    expect(screen.getByRole('button', { name: /create/i })).toBeDisabled();
  });

  it('is enabled for the owner and for an admin', () => {
    renderWithProviders(<MyGatedButton createdBy="eve" />, {
      preloadedState: { auth: authStateFixture({ role: 'editor', username: 'eve' }) },
    });
    expect(screen.getByRole('button', { name: /create/i })).toBeEnabled();
  });
});
```

- `authStateFixture({ role, username, overrides })` defaults to an authenticated `admin` named `test-user`.
- The default test store is authenticated with auth disabled (administrator rights), so existing tests need no change.
- Cover a viewer, an editor on their own asset, an editor on another user's asset, an admin and an asset without an owner for every gated action.
- Gated controls are disabled, not hidden, and carry a tooltip. Assert on the disabled state and on the tooltip text.

---

## Accessibility

### WCAG 2.1 AA Compliance

Follow accessibility standards:

1. **Semantic HTML** - Use proper HTML elements
2. **ARIA labels** - Add `aria-label` for screen readers
3. **Keyboard navigation** - Ensure all interactive elements are keyboard accessible
4. **Color contrast** - Use Carbon tokens for proper contrast
5. **Focus management** - Visible focus indicators

### Example

```typescript
<button
  aria-label="Close dialog"
  onClick={handleClose}
>
  <Close />
</button>
```

---

## Performance

### Optimization Techniques

1. **Lazy loading** - Use `React.lazy()` for code splitting
2. **Memoization** - Use `useMemo` and `useCallback` for expensive operations
3. **Virtualization** - Use virtual lists for large datasets
4. **Image optimization** - Use appropriate formats and sizes

### Example

```typescript
// Lazy loading
const HeavyComponent = React.lazy(() => import('./HeavyComponent'));

// Memoization
const expensiveValue = useMemo(() => computeExpensiveValue(data), [data]);

const handleClick = useCallback(() => {
  // Handler logic
}, [dependency]);
```

---

## Git Workflow

### Commit Messages

Follow conventional commits:

```
feat: Add user profile page
fix: Resolve navigation bug
docs: Update coding standards
style: Format code with prettier
refactor: Simplify authentication logic
test: Add tests for UserProfile
chore: Update dependencies
```

### Branch Naming

```
feature/user-profile
fix/navigation-bug
docs/coding-standards
refactor/auth-logic
```

### Pre-commit Hooks

The project uses `lint-staged` to run ESLint on staged files:

```json
{
  "lint-staged": {
    "*.{ts,tsx,js,jsx}": "eslint --cache --fix"
  }
}
```

---

## Environment Variables

### Configuration

There is a single `frontend/.env` file, read only by the BFF Node process at startup. **No env vars are bundled into the browser JS.**

The frontend makes all API calls to relative `/api/*` paths. The BFF proxies them to the Python backend using `BACKEND_API_URL` from `.env`. The browser never sees backend addresses.

```bash
# frontend/.env
BACKEND_API_URL=http://localhost:8000
BFF_PORT=3001
# BFF_HOST=127.0.0.1
```

`BFF_HOST` is the BFF bind address. It defaults to `127.0.0.1`; the BFF container image sets it to `0.0.0.0`. `BACKEND_API_URL` is also read by `vite.config.ts` as the target of the `/auth` dev proxy.

### Request Flow and Authentication

```text
Browser -> Vite (:3000) -- /api/* --> BFF (:3001) --> REST API /api/v1/*
                        -- /auth/* --> REST API /auth/*   (never through the BFF)
```

- The axios client in `src/services/api/client.ts` sends cookies (`withCredentials`) and adds `X-Requested-With` on POST, PUT, PATCH and DELETE. It never reads or stores a token.
- The BFF forwards only `Cookie`, `Authorization`, `X-Requested-With` and `X-Transaction-ID` to the REST API (`server/controllers/http-headers.ts`). New BFF controllers must build their upstream headers with `buildForwardHeaders` so the session reaches the backend.
- `/auth/*` is served by the REST API only. A custom ingress must never route `/auth` to the BFF.
- In development, register `http://localhost:3000/auth/oauth2/callback` as the OIDC redirect URI; the `/auth` Vite proxy forwards it to the REST API.
- Gate UI actions with `useAuth()` (`canEdit`, `canAdmin`, `canModifyAsset(createdBy)`): disable the control and explain why in a tooltip. The backend enforces permissions.

### Usage in BFF controllers

```typescript
// server/controllers/operator-controller.ts
const url = `${process.env.BACKEND_API_URL}/api/v1/operators/metadata`;
```

### Usage in frontend

The frontend does not read env vars. Use relative paths:

```typescript
// services/api/client.ts
const response = await fetch('/api/fetchOperatorMetadata');
```

---

## Carbon Design System

### Component Usage

Always use Carbon components when available:

```typescript
// ✅ Good - Carbon component
import { Button } from '@carbon/react';
<Button>Click me</Button>

// ❌ Bad - Custom button
<button className="custom-button">Click me</button>
```

### Theme Integration

Use Carbon themes via Context:

```typescript
import { Theme } from '@carbon/react';

<Theme theme="g100">
  <App />
</Theme>
```

### Resources

- [Carbon Design System](https://carbondesignsystem.com/)
- [Carbon React Components](https://react.carbondesignsystem.com/)
- [Carbon Icons](https://www.carbondesignsystem.com/guidelines/icons/library/)

---

## Summary Checklist

Before submitting code, ensure:

- [ ] TypeScript strict mode passes with no errors
- [ ] ESLint passes with no errors (`npm run lint`)
- [ ] All functions have explicit return types
- [ ] No `console.*` statements (use logger utility)
- [ ] No `any` types (use `unknown` or proper types)
- [ ] All imports use path aliases
- [ ] Components follow naming conventions
- [ ] SCSS uses Carbon design tokens
- [ ] Error handling is implemented
- [ ] Accessibility standards are met
- [ ] Code is properly formatted
- [ ] Commit messages follow conventions

---

## Additional Resources

- [React Documentation](https://react.dev/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
- [Carbon Design System](https://carbondesignsystem.com/)
- [ESLint Rules](https://eslint.org/docs/rules/)
- [Vite Documentation](https://vitejs.dev/)

---

**Last Updated**: 2026-06-08
