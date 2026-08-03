import type { SVGProps } from 'react'

type Props = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 16, children, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

/** The Cubicle mark. */
export const Bolt = ({ size = 16, ...rest }: Props) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    {...rest}
  >
    <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
  </svg>
)

export const Sun = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M6 6l1.4 1.4M16.6 16.6L18 18M18 6l-1.4 1.4M7.4 16.6L6 18" />
  </Svg>
)

export const Moon = (p: Props) => (
  <Svg {...p}>
    <path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" />
  </Svg>
)

export const Grid = (p: Props) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </Svg>
)

export const Terminal = (p: Props) => (
  <Svg {...p}>
    <path d="M4 5.5h16v13H4z" />
    <path d="M7.5 10l2.5 2-2.5 2M12.5 14h4" />
  </Svg>
)

export const Globe = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17M12 3.5c4 4.5 4 12.5 0 17M12 3.5c-4 4.5-4 12.5 0 17" />
  </Svg>
)

export const Lines = (p: Props) => (
  <Svg {...p}>
    <path d="M4 6h16M4 12h16M4 18h10" />
  </Svg>
)

export const Bars = (p: Props) => (
  <Svg {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </Svg>
)

export const Sliders = (p: Props) => (
  <Svg {...p}>
    <path d="M4 8h10M18 8h2M4 16h2M10 16h10" />
    <circle cx="15" cy="8" r="2.3" />
    <circle cx="7" cy="16" r="2.3" />
  </Svg>
)

export const Book = (p: Props) => (
  <Svg {...p}>
    <path d="M4 5.5A2.5 2.5 0 016.5 3H19v15H6.5A2.5 2.5 0 004 20.5z" />
    <path d="M8 7.5h7M8 11h5" />
  </Svg>
)

export const Search = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3-3" />
  </Svg>
)

export const Plus = (p: Props) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

export const ChevronRight = (p: Props) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
)

export const ChevronLeft = (p: Props) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Svg>
)

export const ChevronDown = (p: Props) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M8 9l4 4 4-4" />
  </Svg>
)

export const ArrowRight = (p: Props) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
)

export const Download = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <path d="M12 3v13M7 11l5 5 5-5M4 21h16" />
  </Svg>
)

export const Pencil = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <path d="M4 20l4-1 10-10-3-3L5 16z" />
  </Svg>
)

export const Play = ({ size = 16, ...rest }: Props) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    {...rest}
  >
    <path d="M8 5v14l11-7z" />
  </svg>
)

export const Lock = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <rect x="4" y="10" width="16" height="10" rx="2" />
    <path d="M8 10V7a4 4 0 018 0v3" />
  </Svg>
)

export const Meter = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
  </Svg>
)

export const Folder = (p: Props) => (
  <Svg {...p}>
    <path d="M3 7.5A1.5 1.5 0 014.5 6h4l2 2.5h9A1.5 1.5 0 0121 10v8a1.5 1.5 0 01-1.5 1.5h-15A1.5 1.5 0 013 18z" />
  </Svg>
)

export const Database = (p: Props) => (
  <Svg {...p}>
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
    <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </Svg>
)

export const Layers = (p: Props) => (
  <Svg {...p}>
    <path d="M4 7l8-4 8 4-8 4-8-4z" />
    <path d="M4 12l8 4 8-4M4 17l8 4 8-4" />
  </Svg>
)

export const Table = (p: Props) => (
  <Svg strokeWidth={1.7} {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9.5h18M9 9.5V20" />
  </Svg>
)

export const File = (p: Props) => (
  <Svg strokeWidth={1.6} {...p}>
    <path d="M6 2h8l4 4v16H6z" />
    <path d="M14 2v4h4" />
  </Svg>
)

export const Info = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8h.01M11 12h1v4h1" />
  </Svg>
)

export const Help = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 113.2 2.4c-.5.2-.7.6-.7 1.1v.5M12 16.5h.01" />
  </Svg>
)

export const Store = (p: Props) => (
  <Svg {...p}>
    <path d="M4 9h16v10a1 1 0 01-1 1H5a1 1 0 01-1-1V9z" />
    <path d="M3 9l1.4-4.2A1 1 0 015.35 4h13.3a1 1 0 01.95.8L21 9" />
    <path d="M9.5 13h5v7h-5z" />
  </Svg>
)

export const Copy = (p: Props) => (
  <Svg strokeWidth={1.7} {...p}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15V5a2 2 0 012-2h8" />
  </Svg>
)

export const Check = (p: Props) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M4 12.5l5 5L20 6.5" />
  </Svg>
)

export const X = (p: Props) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)

export const Trash = (p: Props) => (
  <Svg strokeWidth={1.7} {...p}>
    <path d="M4 7h16M9 7V5h6v2M6 7l1 14h10l1-14" />
  </Svg>
)

export const Refresh = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <path d="M20 12a8 8 0 10-2.6 5.9M20 6v5h-5" />
  </Svg>
)

export const Power = (p: Props) => (
  <Svg strokeWidth={1.8} {...p}>
    <path d="M12 3v9" />
    <path d="M7.5 6.5a7 7 0 109 0" />
  </Svg>
)

export const Server = (p: Props) => (
  <Svg strokeWidth={1.7} {...p}>
    <rect x="3" y="4" width="18" height="7" rx="2" />
    <rect x="3" y="13" width="18" height="7" rx="2" />
    <path d="M7 7.5h.01M7 16.5h.01" />
  </Svg>
)

export const Github = ({ size = 16, ...rest }: Props) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    {...rest}
  >
    <path d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.36 1.09 2.94.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 015 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0012 2z" />
  </svg>
)
