/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: '#1B3A57',
        gold: '#F4B942',
        primary: '#1B3A57',
        secondary: '#F4B942',
        success: '#27ae60',
        danger: '#e74c3c',
        surface: '#fafaf9',
      },
    },
  },
  plugins: [],
}
