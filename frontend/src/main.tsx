import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { createIntl, createIntlCache, IntlProvider } from 'react-intl';
import '@carbon/styles/css/styles.css';
import '@carbon/ibm-products/css/index-without-carbon.css';
import '@carbon-labs/react-animated-header/scss/animated-header.scss';
import { ThemeProvider } from './contexts/ThemeProvider';
import { store } from './store';
import { loadMessages, DEFAULT_LOCALE } from './i18n';
import { configureApiClient } from './services/api/client';
import App from './App';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Root element not found');
}

// Locale is resolved from the browser's configured language (navigator.language).
// SUPPORTED_LOCALES must be kept in sync with the locale files present in src/i18n/.
// Any browser language not in the list falls back to DEFAULT_LOCALE.
const SUPPORTED_LOCALES = ['en'];
const browserLocale = navigator.language.split('-')[0] ?? DEFAULT_LOCALE;
const locale = SUPPORTED_LOCALES.includes(browserLocale) ? browserLocale : DEFAULT_LOCALE;

const messages = await loadMessages(locale);

const intl = createIntl({ locale, messages, defaultLocale: DEFAULT_LOCALE }, createIntlCache());
configureApiClient({ store, intl });

createRoot(rootElement).render(
  <StrictMode>
    <Provider store={store}>
      <IntlProvider locale={locale} messages={messages} defaultLocale={DEFAULT_LOCALE}>
        <ThemeProvider>
          <App />
        </ThemeProvider>
      </IntlProvider>
    </Provider>
  </StrictMode>
);
