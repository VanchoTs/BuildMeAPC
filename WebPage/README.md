# BuildMeAPC Front-End

A modern, responsive web application built with **TypeScript** and **Vanilla HTML/CSS**. It provides an intuitive interface for users to configure their ideal PC.

## 🎨 Key Features

- **7-Step Interactive Questionnaire**: A step-by-step wizard that captures user requirements (Budget, Usage, RAM/Storage capacity, Resolution, Brand preferences).
- **Intelligent Comparison Engine**: Side-by-side comparison of three recommended builds (Price-Performance, Upgradeability, Quality).
- **Internationalization (i18n)**: Full support for English and Bulgarian with automatic browser language detection and a dynamic `MutationObserver` based translation engine.
- **Client-Side PDF Export**: Uses `html2pdf.js` to generate professional configuration reports directly in the browser.
- **Dynamic Theme System**: Supports Light, Dark, and an unlockable "Ultra Dark" mode (via an Easter Egg).
- **Role-Based Views**: Specialized views for standard Users, Writers (News management), and Administrators (User & Report management).

## 🚀 Technical Highlights

- **Framework-Free**: Developed using native ES Modules and TypeScript for maximum performance and low bundle size.
- **State Management**: Uses `localStorage` for persisting user requirements and "pending" builds during the authentication flow.
- **Secure Communication**: Built-in support for `credentials: 'include'` to handle HttpOnly JWT cookies across API requests.
- **Responsive Layout**: CSS Flexbox and Grid based design, tested across all major browsers and mobile devices.

## 🛠️ Setup & Development

1. **Prerequisites**: Node.js 18+ (for TypeScript compilation).
2. **Installation**:
   ```bash
   cd WebPage
   npm install
   ```
3. **Compilation**:
   ```bash
   npx tsc -p tsconfig.json --watch
   ```
4. **Hosting**:
   Serve the root of the `WebPage` directory using any static web server (e.g., Live Server, Nginx, or `python -m http.server`).

## 🥚 Easter Egg

To unlock **Ultra Dark Mode**: Quickly toggle the theme switcher 6 times (within 800ms between clicks). This activates a high-contrast black/neon-red cyberpunk theme.
