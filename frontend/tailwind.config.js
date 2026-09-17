/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx}',
    './public/index.html',
  ],
  theme: {
    extend: {
      colors: {
        // Healthcare visual identity: calm, trustworthy, restrained.
        primary: '#0F6B72',
        'primary-hover': '#0B565C',
        success: '#2E9E6D',
        warning: '#D9822B',
        danger: '#C0392B',
        background: '#F7F9FA',
        surface: '#FFFFFF',
        border: '#E2E8F0',
        text: '#1F2933',
        muted: '#5B6472',
      },
      fontFamily: {
        // Matches the system font stack already in src/index.css - no
        // external font introduced.
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          'Oxygen',
          'Ubuntu',
          'Cantarell',
          '"Fira Sans"',
          '"Droid Sans"',
          '"Helvetica Neue"',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
};
