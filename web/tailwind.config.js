/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      screens: {
        'xs': '375px',
      },
      /* ── 颜色：全部通过 CSS 变量接入，实现主题切换 ── */
      colors: {
        // 背景
        'bg-primary': 'var(--bg-primary)',
        'bg-secondary': 'var(--bg-secondary)',
        'bg-card': 'var(--bg-card)',
        'bg-sidebar': 'var(--bg-sidebar)',
        'bg-input': 'var(--bg-input)',
        'bg-hover': 'var(--bg-hover)',
        'bg-active': 'var(--bg-active)',

        // 文字
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-muted': 'var(--text-muted)',
        'text-disabled': 'var(--text-disabled)',
        'text-tertiary': 'var(--text-tertiary)',
        'text-on-accent': 'var(--text-on-accent)',
        'text-inverse': 'var(--text-inverse)',

        // 强调色
        'accent': 'var(--accent-primary)',
        'accent-primary': 'var(--accent-primary)',
        'accent-hover': 'var(--accent-hover)',
        'accent-dim': 'var(--accent-dim)',
        'accent-cyan': 'var(--accent-cyan)',
        'accent-purple': 'var(--accent-purple)',
        'accent-pink': 'var(--accent-pink)',
        'accent-green': 'var(--accent-green)',
        'accent-yellow': 'var(--accent-yellow)',
        'accent-orange': 'var(--accent-orange)',
        'accent-red': 'var(--accent-red)',
        'accent-gold': 'var(--accent-gold)',
        'accent-blue': 'var(--accent-blue)',

        // 强调色变体 (dim)
        'accent-cyan-dim': 'var(--accent-cyan-dim)',
        'accent-purple-dim': 'var(--accent-purple-dim)',
        'accent-pink-dim': 'var(--accent-pink-dim)',
        'accent-green-dim': 'var(--accent-green-dim)',
        'accent-yellow-dim': 'var(--accent-yellow-dim)',
        'accent-orange-dim': 'var(--accent-orange-dim)',
        'accent-red-dim': 'var(--accent-red-dim)',
        'accent-gold-dim': 'var(--accent-gold-dim)',
        'accent-blue-dim': 'var(--accent-blue-dim)',
        'accent-amber-dim': 'var(--accent-amber-dim)',

        // 边框
        'border-default': 'var(--border-default)',
        'border-light': 'var(--border-light)',
        'border-hover': 'var(--border-hover)',
        'border-active': 'var(--border-active)',
        'border-strong': 'var(--border-strong)',

        // 状态色
        'color-safe': 'var(--color-safe)',
        'color-danger': 'var(--color-danger)',
        'color-danger-soft': 'var(--color-danger-soft)',
        'color-warning': 'var(--color-warning)',
        'color-info': 'var(--color-info)',
        'success': 'var(--success)',
        'error': 'var(--error)',

        // 玻璃质感
        'glass-bg': 'var(--glass-bg)',
        'glass-border': 'var(--glass-border)',
      },
      /* ── 圆角：Apple HIG 标准 ── */
      borderRadius: {
        'apple-sm': 'var(--radius-sm)',
        'apple-md': 'var(--radius-md)',
        'apple-lg': 'var(--radius-lg)',
        'apple-xl': 'var(--radius-xl)',
        'apple-pill': 'var(--radius-pill)',
      },
      /* ── 阴影：Apple Soft Ambient ── */
      boxShadow: {
        'apple-sm': 'var(--shadow-sm)',
        'apple-md': 'var(--shadow-md)',
        'apple-lg': 'var(--shadow-lg)',
        'apple-hero': 'var(--shadow-hero)',
        'liquid-glass': 'var(--glass-shadow)',
      },
      /* ── 间距：Apple 8pt Grid ── */
      spacing: {
        'apple-xs': 'var(--spacing-xs)',
        'apple-sm': 'var(--spacing-sm)',
        'apple-md': 'var(--spacing-md)',
        'apple-lg': 'var(--spacing-lg)',
        'apple-xl': 'var(--spacing-xl)',
        'apple-2xl': 'var(--spacing-2xl)',
        'apple-3xl': 'var(--spacing-3xl)',
      },
      /* ── 字号：Apple HIG Typography ── */
      fontSize: {
        'apple-caption2': 'var(--font-caption2)',
        'apple-xs': 'var(--font-xs)',
        'apple-footnote': 'var(--font-footnote)',
        'apple-sm': 'var(--font-sm)',
        'apple-base': 'var(--font-base)',
        'apple-lg': 'var(--font-lg)',
        'apple-xl': 'var(--font-xl)',
        'apple-2xl': 'var(--font-2xl)',
        'apple-3xl': 'var(--font-3xl)',
        'apple-4xl': 'var(--font-4xl)',
      },
      /* ── 过渡：Apple HIG 动效 ── */
      transitionDuration: {
        'apple-fast': '180ms',
        'apple-normal': '280ms',
        'apple-slow': '420ms',
      },
      /* ── 字体族 ── */
      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
        display: 'var(--font-display)',
      },
      /* ── 行高 ── */
      lineHeight: {
        'apple-tight': 'var(--leading-tight)',
        'apple-snug': 'var(--leading-snug)',
        'apple-normal': 'var(--leading-normal)',
      },
      /* ── 模糊 ── */
      backdropBlur: {
        glass: '20px',
      },
    },
  },
  plugins: [],
}
