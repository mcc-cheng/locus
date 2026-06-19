// Minimal inline stroke-icon set (Heroicons-style), so we depend on no icon lib.

type P = { className?: string };
const base = (className = "h-5 w-5") => ({
  className,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const BookmarkIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M6 4h12v16l-6-4-6 4V4z" />
  </svg>
);
export const PlusCircleIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v8M8 12h8" />
  </svg>
);
export const HomeIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" />
    <path d="M9.5 21v-6h5v6" />
  </svg>
);
export const UploadIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M12 16V4" />
    <path d="m7 9 5-5 5 5" />
    <path d="M5 20h14" />
  </svg>
);
export const DataIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
    <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
  </svg>
);
export const ChartIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <rect x="7" y="12" width="3" height="5" rx="0.5" />
    <rect x="12.5" y="8" width="3" height="9" rx="0.5" />
    <rect x="18" y="14" width="3" height="3" rx="0.5" />
  </svg>
);
export const BeakerIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M9 3h6" />
    <path d="M10 3v6l-5 8.5A2 2 0 0 0 6.7 21h10.6a2 2 0 0 0 1.7-3.5L14 9V3" />
    <path d="M7.5 14h9" />
  </svg>
);
export const ChatIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 21 12Z" />
  </svg>
);
export const SendIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="m4 12 16-8-6 16-3-7-7-1Z" />
  </svg>
);
export const SparkleIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
    <path d="m6.3 6.3 2.1 2.1M15.6 15.6l2.1 2.1M17.7 6.3l-2.1 2.1M8.4 15.6l-2.1 2.1" />
  </svg>
);
export const ChevronRight = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="m9 6 6 6-6 6" />
  </svg>
);
export const CloseIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const ShieldIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M12 3 5 6v6c0 4 3 7 7 9 4-2 7-5 7-9V6l-7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);
export const PlayIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M7 4.5v15l12-7.5-12-7.5Z" />
  </svg>
);
export const MenuIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </svg>
);
export const ChevronLeft = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="m15 6-6 6 6 6" />
  </svg>
);
export const PlusIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const TrashIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M4 7h16" />
    <path d="M10 11v6M14 11v6" />
    <path d="M6 7l1 13h10l1-13" />
    <path d="M9 7V4h6v3" />
  </svg>
);
export const DownloadIcon = ({ className }: P) => (
  <svg {...base(className)}>
    <path d="M12 4v11" />
    <path d="m7 10 5 5 5-5" />
    <path d="M5 20h14" />
  </svg>
);
