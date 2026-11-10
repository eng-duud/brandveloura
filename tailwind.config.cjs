module.exports = {
  content: [
    './templates/**/*.html',
    './store/**/*.py',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans Arabic"', 'system-ui', 'sans-serif'],
        ibm: ['"IBM Plex Sans Arabic"', 'sans-serif'],
        num: ['system-ui', '"IBM Plex Sans Arabic"', 'sans-serif'],
        brandlogo: ['Milkshake', 'cursive'],
      },
      colors: {
        brand: {
          50: '#fff0f7',
          100: '#fde4f2',
          200: '#fec2f5',
          300: '#fba7e8',
          400: '#f672d4',
          500: '#e83ab8',
          600: '#d11a9e',
          700: '#b10f81',
          800: '#920f6a',
          900: '#791258',
          950: '#4a0434',
        },
        pearl: '#FFF0F7',
        slate: {
          850: '#151f33',
          950: '#0a0f1d',
        },
      },
      boxShadow: {
        luxury: '0 4px 20px -2px rgba(15, 23, 42, 0.05), 0 2px 6px -1px rgba(15, 23, 42, 0.03)',
        'luxury-lg': '0 12px 30px -4px rgba(15, 23, 42, 0.08), 0 4px 12px -2px rgba(15, 23, 42, 0.04)',
        glass: '0 8px 32px 0 rgba(15, 23, 42, 0.04)',
      },
    },
  },
  plugins: [],
};
