import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

export function ArrowRightIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M5 12h14M13 6l6 6-6 6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ArrowLeftIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M19 12H5M11 6l-6 6 6 6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function GitHubIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M12 2.75A9.25 9.25 0 0 0 2.75 12a9.25 9.25 0 0 0 6.32 8.79c.46.08.62-.19.62-.44v-1.53c-2.57.56-3.11-1.08-3.11-1.08-.42-1.05-1.03-1.33-1.03-1.33-.84-.57.06-.56.06-.56.93.06 1.42.96 1.42.96.82 1.41 2.16 1 2.69.77.08-.6.32-1 .58-1.23-2.05-.24-4.2-1.02-4.2-4.57 0-1.01.36-1.84.95-2.49-.1-.23-.42-1.17.09-2.43 0 0 .77-.25 2.53.95A8.7 8.7 0 0 1 12 7.2c.77 0 1.55.1 2.27.3 1.76-1.2 2.53-.95 2.53-.95.52 1.26.2 2.2.1 2.43.6.65.94 1.48.94 2.49 0 3.56-2.16 4.32-4.22 4.56.33.28.62.85.62 1.72v2.55c0 .25.16.53.63.43A9.25 9.25 0 0 0 21.25 12 9.25 9.25 0 0 0 12 2.75Z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function BoltIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M13.2 2.75 6.75 13.1h4.37l-.32 8.15 6.45-10.35h-4.37l.32-8.15Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CodeIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.5 5 10 19" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FlaskIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M10 3h4M11 3v5.5L6.6 16.3a2.8 2.8 0 0 0 2.4 4.2H15a2.8 2.8 0 0 0 2.4-4.2L13 8.5V3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.5 15.5h7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function SaveIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M5 4.5h10.5L19 8v11.5H5V4.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M8 4.5V9h7V4.5M8 19.5v-5h8v5" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

export function ResetIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3L4 9.5M4 4v5.5h5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M4.75 12A7.25 7.25 0 0 0 17.2 17.1M19.25 12A7.25 7.25 0 0 0 6.8 6.9"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <path
        d="M15.75 17.25h1.85v-1.85M8.25 6.75H6.4V8.6"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function TimerIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M12 7v5l3 2M9 2.75h6M12 5.5A8.25 8.25 0 1 1 3.75 13.75 8.25 8.25 0 0 1 12 5.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M4.5 7.5h15M9.5 3.75h5M8 7.5v10.25A1.5 1.5 0 0 0 9.5 19.25h5A1.5 1.5 0 0 0 16 17.75V7.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 11.25v4.5M14 11.25v4.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function CheckCircleIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.7" />
      <path d="m8.75 12.25 2.15 2.15 4.35-4.8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AlertTriangleIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path
        d="M10.73 4.62a1.45 1.45 0 0 1 2.54 0l6.12 10.92a1.45 1.45 0 0 1-1.27 2.16H5.88a1.45 1.45 0 0 1-1.27-2.16l6.12-10.92Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M12 9v3.75" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <circle cx="12" cy="15.75" r="1" fill="currentColor" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="m7 10 5 5 5-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CopyIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M9 9.25h8.25A1.75 1.75 0 0 1 19 11v8.25A1.75 1.75 0 0 1 17.25 21H9A1.75 1.75 0 0 1 7.25 19.25V11A1.75 1.75 0 0 1 9 9.25Z" stroke="currentColor" strokeWidth="1.7" />
      <path d="M5.75 14.75A1.75 1.75 0 0 1 4 13V4.75A1.75 1.75 0 0 1 5.75 3h8.5A1.75 1.75 0 0 1 16 4.75" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}

export function FileCodeIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M7 3.75h7.5L19.25 8.5v11.75H7V3.75Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="m10 11-1.75 1.75L10 14.5M14 11l1.75 1.75L14 14.5M12.75 10 11.25 15.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function GitBranchIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <circle cx="7" cy="6.5" r="1.75" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="17" cy="17.5" r="1.75" stroke="currentColor" strokeWidth="1.7" />
      <path
        d="M7 8.25v6.5a3 3 0 0 0 3 3H15.25M7 18.25a3 3 0 0 0 3-3V12.5a3 3 0 0 1 3-3h4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function BeakerIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M9 3.75h6M10 3.75v5.5l-4.25 7.1a2.1 2.1 0 0 0 1.8 3.15h8.9a2.1 2.1 0 0 0 1.8-3.15L14 9.25v-5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.5 14.75h7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function SendIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M20 4 11 13" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="m20 4-6.5 16-2.9-6.6L4 10.5 20 4Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
